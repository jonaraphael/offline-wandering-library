import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, optional, writeFile} from "./drive.mjs";

const root = "LIBRARY/SEARCH/";
const dig = /^[a-f0-9]{64}$/;
const encoder = new TextEncoder();
const charge = row => encoder.encode(JSON.stringify(row)).length;
const wrap = (name, value) => "globalThis." + name + "(" + JSON.stringify(value) + ");\n";
const locator = path => path.split("/").map(encodeURIComponent).join("/");

async function transfer(drive, base, path, pin, fetchFile, signal) {
  if (!dig.test(pin.sha256) || !Number.isInteger(pin.bytes) || pin.bytes < 1 || pin.bytes > 3_000_000) {
    throw Error("Invalid precomputed search file pin");
  }
  const relative = root + path;
  const existing = await optional(async () => (await fileHandle(drive, relative)).getFile());
  if (existing?.size === pin.bytes && bytesToHex(sha256(new Uint8Array(await existing.arrayBuffer()))) === pin.sha256) {
    return pin.sha256 + "  " + relative;
  }
  const response = await fetchFile(base + path, {signal, credentials: "omit", cache: "no-store"});
  if (!response.ok || !response.body) throw Error("HTTP " + response.status + " reading a search file");
  const data = new Uint8Array(pin.bytes);
  const reader = response.body.getReader();
  let offset = 0;
  try {
    for (;;) {
      const packet = await reader.read();
      if (packet.done) break;
      if (offset + packet.value.length > pin.bytes) throw Error("Search file exceeds pinned size");
      data.set(packet.value, offset);
      offset += packet.value.length;
    }
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  if (offset !== pin.bytes || bytesToHex(sha256(data)) !== pin.sha256) throw Error("Search file SHA-256 differs");
  await writeFile(drive, relative, data);
  return pin.sha256 + "  " + relative;
}

export async function assembleSearch(drive, {completed, layouts, navigation, config, fetchFile, signal, budget}) {
  const {manifest, base, records, page, runtime, rankRuntime} = config;
  const warnings = [];
  const modelParts = manifest.model_parts || [];
  const selection = {version: 1, sources: [], model_parts: modelParts.length};
  const checksums = new Map();
  const pages = new Map();
  const selected = new Map(completed.map(asset => [asset.id, asset]));
  const recordsHere = records.flatMap(record => {
    if (record.kind === "topic") return record.source_ids.some(id => selected.has(id)) ? [record] : [];
    if (!selected.has(record.asset_id)) return [];
    const destination = layouts.get(record.asset_id)[0].path.slice("LIBRARY/".length);
    const fragment = record.href.includes("#") ? "#" + record.href.split("#")[1] : "";
    return [{...record, href: locator(destination) + fragment, destination}];
  });
  if (manifest.version !== 1) throw Error("Unsupported precomputed search schema");
  const matches = completed.filter(asset => dig.test(asset.sha256) && Object.hasOwn(manifest.sources, asset.sha256));
  matches.sort((a, b) => Number(Boolean(b.critical)) - Number(Boolean(a.critical)) ||
    manifest.sources[a.sha256].records - manifest.sources[b.sha256].records || a.id.localeCompare(b.id, "en"));
  let remaining = budget - charge(recordsHere) - charge(page) - charge(runtime) - 100_000;
  if (matches.length && manifest.model && manifest.license) {
    const files = [["model.js", manifest.model], ["model-license.txt", manifest.license],
      ...modelParts.map((pin, number) => ["model/" + String(number).padStart(2, "0") + ".js", pin])];
    if (files.reduce((sum, [, pin]) => sum + pin.bytes, 0) > remaining) matches.length = 0;
    try {
      for (const [path, pin] of matches.length ? files : []) {
        const line = await transfer(drive, base, path, pin, fetchFile, signal);
        checksums.set(path, line);
        remaining -= pin.bytes;
      }
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push("Search model — " + error.message);
      matches.length = 0;
    }
  }
  for (const asset of matches) {
    const shard = manifest.sources[asset.sha256];
    const meta = navigation.assets[asset.id] || {};
    const parts = [];
    for (const pool of shard.shared || []) {
      if (!dig.test(pool) || !Object.hasOwn(manifest.shared, pool)) throw Error("Invalid shared search pool");
      for (const [number, pin] of manifest.shared[pool].parts.entries()) parts.push({pool, number, pin});
    }
    for (const [number, pin] of (shard.parts || []).entries()) parts.push({pool: asset.sha256, number, pin});
    const row = {id: asset.id, sha256: asset.sha256, title: asset.title, format: asset.format,
      category: asset.category, critical: Boolean(asset.critical),
      discussion: (asset.source_url || "").includes("/stack_exchange/"),
      destination: layouts.get(asset.id)[0].path.slice("LIBRARY/".length), license: asset.license,
      attribution: meta.attribution, shelves: meta.shelves || [], legacy: Boolean(meta.legacy),
      records: shard.records, main: shard.main, entrypoints: shard.entrypoints, parts: parts.map(
        ({pool, number, pin: {bloom, vectors, passages, lead_vectors, semantic_vectors}}) =>
          ({bloom, vectors, passages, lead_vectors, semantic_vectors, ...(shard.shared && {pool, number})}))};
    const paths = parts.map(({pool, number}) => "sources/" + pool + "/" + String(number).padStart(5, "0") + ".js");
    const cost = charge(row) + parts.reduce((sum, {pin}, index) => sum + (checksums.has(paths[index]) ? 0 : pin.bytes), 0);
    if (cost > remaining) continue;
    const whole = sha256.create();
    try {
      for (const [index, {pin}] of parts.entries()) {
        signal?.throwIfAborted();
        const path = paths[index];
        if (!checksums.has(path)) {
          const line = await transfer(drive, base, path, pin, fetchFile, signal);
          checksums.set(path, line);
          remaining -= pin.bytes;
        }
        const stored = await (await fileHandle(drive, root + path)).getFile();
        whole.update(new Uint8Array(await stored.arrayBuffer()));
      }
      if (bytesToHex(whole.digest()) !== shard.sha256) throw Error("Whole search shard SHA-256 differs");
      selection.sources.push(row);
      remaining -= charge(row);
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push(asset.title + " search — " + error.message);
    }
  }
  const format = "owl-discovery-v1";
  const generation = bytesToHex(sha256(encoder.encode(JSON.stringify(recordsHere))));
  const data = JSON.stringify({format, generation, records: recordsHere}) + "\n";
  const digest = bytesToHex(sha256(encoder.encode(data)));
  const path = "SEARCH/data/" + digest + ".js";
  const composed = selection.sources.length > 0;
  pages.set("LIBRARY/" + path, "globalThis.OWLDiscoveryData(" + data.trimEnd() + ");\n");
  pages.set("LIBRARY/SEARCH.html", page);
  pages.set(root + "search.js", runtime);
  if (composed) {
    pages.set(root + "rank.js", rankRuntime);
    pages.set(root + "shards.js", wrap("OWLShardSelection", selection));
  }
  const coverage = {format, assets: selection.sources.map(({id, sha256, records}) => ({id, sha256, records})), warnings};
  pages.set(root + "coverage.json", JSON.stringify(coverage, null, 2) + "\n");
  pages.set(root + "manifest.js", wrap("OWLDiscoveryManifest", {format, path, sha256: digest,
    generation, records: recordsHere.length, shards: composed}));
  return {pages, checksums: [...checksums.values()], warnings, sources: selection.sources};
}
