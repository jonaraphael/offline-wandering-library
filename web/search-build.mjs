import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, optional, writeFile} from "./drive.mjs";
import {receiveFile, SourceError} from "./network.mjs";

const root = "LIBRARY/SEARCH/";
const dig = /^[a-f0-9]{64}$/;
const encoder = new TextEncoder();
const charge = row => encoder.encode(JSON.stringify(row)).length;
const supportScript = /^(?:model\.js|(?:model|impact|transformer)\/[a-zA-Z0-9.-]+\.js)$/;
export const canonical = value => JSON.stringify(value, (_key, item) => item && !Array.isArray(item) && typeof item === "object"
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item);
const wrap = (name, value) => "globalThis." + name + "(" + canonical(value) + ");\n";
export const locator = path => path.split("/").map(segment => encodeURIComponent(segment)
  .replace(/[!'()*]/g, char => "%" + char.charCodeAt(0).toString(16).toUpperCase())).join("/");

// The fixed names also serve the drive's existing audit and repair tools.
// Readers use pinned copies so a new model or term index cannot change an open generation.
export async function shareSearchSupport(drive, pins, signal) {
  const paths = {}, checksums = [];
  for (const line of pins) {
    const [digest, path] = line.split("  ");
    if (!path.startsWith(root) || !supportScript.test(path.slice(root.length))) continue;
    signal?.throwIfAborted();
    const alias = root + "shared/" + digest + ".js";
    const existing = await optional(async () => (await fileHandle(drive, alias)).getFile());
    if (!existing || bytesToHex(sha256(new Uint8Array(await existing.arrayBuffer()))) !== digest) {
      const stored = await (await fileHandle(drive, path)).getFile();
      const bytes = new Uint8Array(await stored.arrayBuffer());
      if (bytesToHex(sha256(bytes)) !== digest) throw Error("Search support changed during reader assembly");
      await writeFile(drive, alias, bytes);
    }
    paths[path.slice("LIBRARY/".length)] = alias.slice("LIBRARY/".length);
    checksums.push(digest + "  " + alias);
  }
  return {paths, checksums: [...new Set(checksums)]};
}

export async function transfer(drive, base, path, pin, fetchFile, signal, network,
  destination = root + path, maxBytes = 3_000_000) {
  if (!dig.test(pin.sha256) || !Number.isInteger(pin.bytes) || pin.bytes < 1 || pin.bytes > maxBytes) {
    throw Error("Invalid precomputed file pin");
  }
  const relative = destination;
  const existing = await optional(async () => (await fileHandle(drive, relative)).getFile());
  if (existing?.size === pin.bytes && bytesToHex(sha256(new Uint8Array(await existing.arrayBuffer()))) === pin.sha256) {
    return pin.sha256 + "  " + relative;
  }
  const data = new Uint8Array(pin.bytes);
  await network.retry(async () => {
    let offset = 0;
    await receiveFile(base + path, {
      fetchFile, signal,
      check(response) {
        if (!response.ok) throw new SourceError("HTTP " + response.status + " reading a search file");
      },
      onChunk(chunk) {
        if (offset + chunk.length > pin.bytes) throw new SourceError("Search file exceeds pinned size");
        data.set(chunk, offset);
        offset += chunk.length;
      }
    });
    if (offset !== pin.bytes || bytesToHex(sha256(data)) !== pin.sha256)
      throw new SourceError("Search file SHA-256 differs", {connection: offset < pin.bytes});
  });
  await writeFile(drive, relative, data);
  return pin.sha256 + "  " + relative;
}

export async function assembleSearch(drive, {completed, layouts, config, fetchFile, signal, budget, network, versioned = false}) {
  const {plan, base, records, page, runtime, rankRuntime, rerankRuntime} = config;
  const warnings = [];
  const omittedForSpace = [];
  const selection = {version: plan.version, sources: [], model_parts: plan.model_parts};
  const checksums = new Map();
  const pages = new Map();
  const selected = new Map(completed.map(asset => [asset.id, asset]));
  const documents = new Map(records.filter(record => record.kind === "document").map(record => [record.asset_id, record]));
  const recordsHere = records.flatMap(record => {
    if (record.kind === "topic") {
      const source_ids = record.source_ids.filter(id => selected.has(id));
      if (!source_ids.length) return [];
      const shelves = [...new Set(source_ids.flatMap(id => documents.get(id).shelves))].sort();
      const legacy = source_ids.every(id => documents.get(id).legacy);
      return [{...record, source_ids, shelves, legacy}];
    }
    if (!selected.has(record.asset_id)) return [];
    const destination = layouts.get(record.asset_id)[0].path.slice("LIBRARY/".length);
    const fragment = record.href.includes("#") ? "#" + record.href.split("#")[1] : "";
    return [{...record, href: locator(destination) + fragment, destination}];
  });
  if (plan.version !== 1) throw Error("Unsupported precomputed search schema");
  const matches = plan.sources.filter(({row}) => selected.get(row.id)?.sha256 === row.sha256);
  const copies = versioned ? 2 : 1;
  const fileCost = (path, pin) => supportScript.test(path) ? pin.bytes * copies : pin.bytes;
  let remaining = budget - charge(recordsHere) - charge(page) - copies * (charge(runtime) + charge(rankRuntime)) - plan.reserve;
  const files = plan.model;
  if (matches.length && files.length) {
    if (files.reduce((sum, [path, pin]) => sum + fileCost(path, pin), 0) > remaining) {
      omittedForSpace.push(...matches.map(({row}) => row.id));
      matches.length = 0;
    }
    try {
      for (const [path, pin] of matches.length ? files : []) {
        const line = await transfer(drive, base, path, pin, fetchFile, signal, network);
        checksums.set(path, line);
        remaining -= fileCost(path, pin);
      }
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push("Search model — " + error.message);
      matches.length = 0;
    }
  }
  for (const source of matches) {
    const paths = source.parts;
    const row = {...source.row, destination: layouts.get(source.row.id)[0].path.slice("LIBRARY/".length),
      parts: paths.map(path => plan.chunks[path].rank)};
    const newParts = [...new Set(paths)].filter(path => !checksums.has(path));
    const cost = copies * (charge(row) + 1) + newParts.reduce((sum, path) => sum + plan.chunks[path].pin.bytes, 0);
    if (cost > remaining) {
      omittedForSpace.push(row.id);
      continue;
    }
    const whole = sha256.create();
    try {
      for (const path of paths) {
        signal?.throwIfAborted();
        const {pin} = plan.chunks[path];
        if (path !== "chunks/" + pin.sha256 + ".js" && !/^sources\/[a-f0-9]{64}\/\d{5}\.js$/.test(path))
          throw Error("Invalid search chunk path");
        if (!checksums.has(path)) {
          const line = await transfer(drive, base, path, pin, fetchFile, signal, network);
          checksums.set(path, line);
          remaining -= pin.bytes;
        }
        const stored = await (await fileHandle(drive, root + path)).getFile();
        whole.update(new Uint8Array(await stored.arrayBuffer()));
      }
      if (bytesToHex(whole.digest()) !== source.sha256) throw Error("Whole search shard SHA-256 differs");
      selection.sources.push(row);
    remaining -= copies * (charge(row) + 1);
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push(row.title + " search — " + error.message);
    }
  }
  const impact = Object.entries(plan.impact || {});
  const routed = selection.sources.some(source => source.parts.some(part => part.impact));
  if (routed && impact.length &&
      impact.reduce((sum, [name, pin]) => sum + fileCost("impact/" + name, pin) + 20, 0) <= remaining) {
    try {
      for (const [name, pin] of impact) {
        if (!/^[a-f0-9]{2}\.js$/.test(name)) throw Error("Invalid term bucket name");
        const path = "impact/" + name;
        const line = await transfer(drive, base, path, pin, fetchFile, signal, network);
        checksums.set(path, line);
        remaining -= fileCost(path, pin) + 20;
      }
      selection.impact = Object.fromEntries(impact.map(([name, pin]) => [name, pin.bytes]));
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push("Term index — " + error.message);
    }
  }
  const transformer = Object.entries(plan.transformer || {});
  if (selection.sources.length && transformer.length &&
      transformer.reduce((sum, [name, pin]) => sum + fileCost("transformer/" + name, pin),
        copies * charge(rerankRuntime) + 20) <= remaining) {
    try {
      for (const [name, pin] of transformer) {
        if (!/^[a-zA-Z0-9.-]+\.(?:js|txt)$/.test(name)) throw Error("Invalid local transformer asset name");
        const path = "transformer/" + name;
        const line = await transfer(drive, base, path, pin, fetchFile, signal, network);
        checksums.set(path, line);
      }
      pages.set(root + "rerank.js", rerankRuntime);
      selection.reranker = true;
    } catch (error) {
      signal?.throwIfAborted();
      warnings.push("Search reranker — " + error.message);
    }
  }
  const format = "owl-discovery-v1";
  const generation = bytesToHex(sha256(encoder.encode(canonical(recordsHere) + "\n")));
  const data = canonical({format, generation, records: recordsHere}) + "\n";
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
  const coverage = {format, assets: selection.sources.map(({id, sha256, records}) => ({id, sha256, records})), omittedForSpace, warnings};
  pages.set(root + "coverage.json", JSON.stringify(coverage, null, 2) + "\n");
  pages.set(root + "manifest.js", wrap("OWLDiscoveryManifest", {format, path, sha256: digest,
    generation, records: recordsHere.length, ...(composed ? {shards: true} : {})}));
  return {pages, checksums: [...checksums.values()], warnings, sources: selection.sources};
}
