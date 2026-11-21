import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, writeFile} from "./drive.mjs";
import {assembleLibrary} from "./offline.mjs";

export const PART_BYTES = 2 ** 30;
export const MANIFEST = "LIBRARY/.owl/browser-build.json";
const FAT32_MAX = 2 ** 32 - 1;
const DIGEST = /^[0-9a-f]{64}$/;
const tier = ["CRITICAL", "USEFUL", "NONESSENTIAL"];
const NETWORK_IDLE_MS = 60_000;

class SourceError extends Error {
  constructor(message, whole = false) {
    super(message);
    this.whole = whole;
  }
}

export function buildOrder(assets) {
  const priority = asset => asset.destination.startsWith("SOFTWARE/") ? 0 : (tier.indexOf(asset.utility_tier) + 1 || tier.length + 1);
  return [...assets].sort((a, b) => priority(a) - priority(b) ||
    (a.selection?.level ?? Infinity) - (b.selection?.level ?? Infinity) ||
    (a.selection?.rank ?? Infinity) - (b.selection?.rank ?? Infinity) ||
    a.id.localeCompare(b.id));
}

function assetPin(asset) {
  return {id: asset.id, sha256: asset.sha256, bytes: asset.size_bytes, path: asset.destination, format: asset.format};
}

export function partLayout(asset, partBytes = PART_BYTES) {
  if (!Number.isSafeInteger(partBytes) || partBytes < 1 || partBytes > FAT32_MAX ||
      !Number.isSafeInteger(asset.size_bytes) || asset.size_bytes < 1 || !DIGEST.test(asset.sha256)) {
    throw Error("Invalid size or SHA-256 pin for " + asset.id);
  }
  const count = asset.format === "zim" ? Math.ceil(asset.size_bytes / partBytes) : 1;
  if (count > 26 ** 2 || (count === 1 && asset.size_bytes > FAT32_MAX)) {
    throw Error("File cannot be stored in FAT32-compatible parts: " + asset.title);
  }
  return Array.from({length: count}, (_, i) => {
    const suffix = count === 1 ? "" : String.fromCharCode(97 + Math.floor(i / 26), 97 + i % 26);
    const start = i * partBytes;
    const bytes = count === 1 ? asset.size_bytes : Math.min(partBytes, asset.size_bytes - start);
    return {path: "LIBRARY/" + asset.destination + suffix, start, bytes};
  });
}

export async function readBuild(drive) {
  const file = await optional(async () => (await fileHandle(drive, MANIFEST)).getFile());
  if (!file) return null;
  const state = JSON.parse(await file.text());
  if (state.version !== 1 || !state.buildId || !Array.isArray(state.plan) || !Array.isArray(state.excluded) ||
      !state.parts || !state.verified || !state.dropped || !state.failures) {
    throw Error("The browser build record is unreadable. Choose a different library folder.");
  }
  return state;
}

async function assertDrive(drive, state) {
  if ((await readBuild(drive))?.buildId !== state.buildId) {
    throw Error("The saved build is missing from this drive. Reconnect the original drive and choose Resume.");
  }
}

async function save(drive, state) {
  await assertDrive(drive, state);
  await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n");
}

async function start(drive, {assets, excluded, partBytes}) {
  if (await optional(() => drive.getFileHandle("START_HERE.html"))) {
    throw Error("This drive folder already has a library. Choose an empty folder on the drive.");
  }
  const library = await optional(() => drive.getDirectoryHandle("LIBRARY"));
  if (library) {
    for await (const entry of library.values()) {
      if (entry.name !== ".owl" || entry.kind !== "directory") {
        throw Error("This drive folder already contains library files. Choose an empty folder on the drive.");
      }
      for await (const unused of entry.values()) {
        throw Error("This drive folder already contains build files. Choose an empty folder on the drive.");
      }
    }
  }
  const state = {version: 1, buildId: globalThis.crypto.randomUUID(), partBytes,
    plan: buildOrder(assets).map(assetPin), excluded, parts: {}, verified: {}, dropped: {}, failures: {}, finished: false};
  await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n");
  return state;
}

function partPins(asset, layout, published, partBytes) {
  if (layout.length === 1) return [asset.sha256];
  const record = published.chunks?.[asset.id];
  if (!record) return [];
  if (record.sha256 !== asset.sha256 || record.part_bytes !== partBytes ||
      record.hashes.length !== layout.length || !record.hashes.every(hash => DIGEST.test(hash))) {
    throw Error("Published chunk manifest does not match " + asset.title);
  }
  return record.hashes;
}

async function readCheckpoint(drive, part, hash, whole) {
  const file = await optional(async () => (await fileHandle(drive, part.path)).getFile());
  if (!file || file.size !== part.bytes) return null;
  const next = whole.clone(), current = sha256.create();
  for await (const chunk of file.stream()) {
    next.update(chunk);
    current.update(chunk);
  }
  return bytesToHex(current.digest()) === hash ? next : null;
}

async function streamRequest(url, range, expected, fetchFile, signal, onChunk) {
  const controller = new AbortController();
  const requestSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  async function receive(operation) {
    const timer = setTimeout(() => controller.abort(), NETWORK_IDLE_MS);
    try { return await operation(); }
    catch (_) {
      signal?.throwIfAborted();
      throw new SourceError(controller.signal.aborted ? "Source stopped sending data" : "Connection or browser access failed");
    } finally { clearTimeout(timer); }
  }
  const headers = range ? {Range: "bytes=" + range.start + "-" + range.end} : {};
  const response = await receive(() => fetchFile(url, {
    headers, signal: requestSignal, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer"
  }));
  if (!response.body) throw new SourceError("Source returned no data (HTTP " + response.status + ")");
  const reader = response.body.getReader();
  let count = 0;
  try {
    if (range ? response.status !== 206 ||
        response.headers.get("Content-Range") !== "bytes " + range.start + "-" + range.end + "/" + range.total :
        response.status !== 200) {
      throw new SourceError(range && response.ok ? "Source did not return the pinned byte range" : "HTTP " + response.status);
    }
    for (;;) {
      signal?.throwIfAborted();
      const packet = await receive(() => reader.read());
      if (packet.done) break;
      count += packet.value.byteLength;
      if (count > expected) throw new SourceError("Source exceeded the pinned byte count");
      await onChunk(packet.value);
    }
    if (count !== expected) throw new SourceError("Source ended before the pinned byte count");
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

async function writePart(drive, asset, part, source, options) {
  const {fetchFile, signal, whole, expectedHash, last, range, onBytes} = options;
  const writable = await (await fileHandle(drive, part.path, true)).createWritable({mode: "exclusive"});
  const hash = sha256.create(), next = whole.clone();
  try {
    let total = 0;
    for (const piece of source.pieces) {
      const pieceHash = piece.sha256 ? sha256.create() : null;
      await streamRequest(piece.url, range, piece.bytes ?? part.bytes, fetchFile, signal, async chunk => {
        hash.update(chunk);
        next.update(chunk);
        pieceHash?.update(chunk);
        await writable.write(chunk);
        total += chunk.byteLength;
        onBytes(total);
      });
      if (pieceHash && bytesToHex(pieceHash.digest()) !== piece.sha256) throw new SourceError("Published chunk SHA-256 mismatch");
    }
    const digest = bytesToHex(hash.digest());
    if (total !== part.bytes || (expectedHash && digest !== expectedHash)) throw new SourceError("Part SHA-256 or size mismatch");
    if (last && bytesToHex(next.clone().digest()) !== asset.sha256) throw new SourceError("Whole-file SHA-256 mismatch", true);
    signal?.throwIfAborted();
    await writable.close();
    return {digest, next};
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
}

function routesFor(asset, routes, published) {
  const choices = (routes[asset.id] || []).map(url => ({label: new URL(url).hostname, pieces: [{url}]}));
  if (published.files?.[asset.id]) {
    choices.push({label: "library website", pieces: published.files[asset.id]});
  }
  return choices;
}

export function browserSelection(assets, routes, published) {
  const available = [], excluded = [];
  for (const asset of buildOrder(assets)) {
    if (routesFor(asset, routes, published).length) available.push(asset);
    else excluded.push({id: asset.id, title: asset.title,
      reason: asset.redistributable ? "No browser-accessible pinned copy is published." : "Publisher blocks browser downloads and this site cannot host a copy."});
  }
  return {assets: available, excluded};
}

async function forgetParts(drive, state, asset, layout) {
  await assertDrive(drive, state);
  for (const part of layout) await removeFile(drive, part.path);
  delete state.parts[asset.id];
  delete state.verified[asset.id];
}

async function buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const checkpoints = state.parts[asset.id] ||= [];
  let whole = sha256.create(), index = 0;
  for (const [i, part] of layout.entries()) {
    signal?.throwIfAborted();
    const saved = checkpoints[i];
    if (!DIGEST.test(saved?.sha256) || saved.bytes !== part.bytes || (pins[i] && pins[i] !== saved.sha256)) break;
    onProgress({kind: "checking", asset, index: i, count: layout.length});
    const restored = await readCheckpoint(drive, part, saved.sha256, whole);
    if (!restored) break;
    whole = restored;
    index++;
  }
  if (index === layout.length) {
    if (bytesToHex(whole.digest()) === asset.sha256) return;
    throw new SourceError("Saved parts failed whole-file SHA-256", true);
  }
  // Discard only this build's untrusted suffix before rewriting it, so a
  // replacement does not hold both the old bytes and a new swap file.
  for (const part of layout.slice(index)) await removeFile(drive, part.path);
  checkpoints.length = index;
  delete state.verified[asset.id];
  await save(drive, state);

  const choices = routesFor(asset, routes, published);
  let preferred = (state.sourceOffsets?.[asset.id] || 0) % (choices.length || 1);
  for (; index < layout.length; index++) {
    signal?.throwIfAborted();
    await assertDrive(drive, state);
    const part = layout[index];
    const progress = {asset, index, count: layout.length};
    const range = layout.length === 1 ? null : {start: part.start, end: part.start + part.bytes - 1, total: asset.size_bytes};
    const failures = [];
    let downloaded, wholeMismatch = false;
    for (let round = 0; round < 2 && !downloaded; round++) {
      for (let offset = 0; offset < choices.length; offset++) {
        const sourceIndex = (preferred + offset) % choices.length;
        const source = choices[sourceIndex];
        onProgress({kind: "downloading", ...progress, source: source.label, received: 0, bytes: part.bytes});
        try {
          await assertDrive(drive, state);
          downloaded = await writePart(drive, asset, part, source, {fetchFile, signal, whole, range,
            expectedHash: pins[index], last: index === layout.length - 1,
            onBytes: received => onProgress({kind: "downloading", ...progress, source: source.label, received, bytes: part.bytes})});
          preferred = sourceIndex;
          break;
        } catch (error) {
          if (!(error instanceof SourceError)) throw error;
          wholeMismatch ||= error.whole;
          const message = source.label + " — " + error.message;
          if (!failures.includes(message)) failures.push(message);
          onProgress({kind: "retrying", ...progress, message});
        }
      }
    }
    if (!downloaded) {
      if (wholeMismatch && choices.length > 1) (state.sourceOffsets ||= {})[asset.id] = (preferred + 1) % choices.length;
      // Failed swaps leave an empty destination placeholder in Chromium.
      await removeFile(drive, part.path);
      throw new SourceError(failures.join(". ") || "No browser source is available", wholeMismatch);
    }
    checkpoints.push({sha256: downloaded.digest, bytes: part.bytes});
    whole = downloaded.next;
    await save(drive, state);
  }
}

export async function buildLibrary(drive, {assets, excluded = [], catalogAssets = assets, routes,
  published = {}, navigation = {}, partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal,
  onProgress = () => {}, resume = false}) {
  const saved = await readBuild(drive);
  if (saved && !resume) throw Error("This drive has a saved build. Choose Resume.");
  if (!saved && resume) throw Error("No browser build was found on this drive.");
  if (!saved && !assets.length) throw Error("Choose files with browser-accessible sources.");
  const state = saved || await start(drive, {assets, excluded, partBytes});
  const byId = new Map(catalogAssets.map(asset => [asset.id, asset]));
  const ordered = state.plan.map(pin => {
    const asset = byId.get(pin.id);
    if (!asset || Object.entries(assetPin(asset)).some(([key, value]) => value !== pin[key])) {
      throw Error("The pinned selection has changed since this build started: " + pin.id);
    }
    return asset;
  });
  const layouts = new Map(ordered.map(asset => [asset.id, partLayout(asset, state.partBytes)]));
  state.finished = false;
  if (resume) state.dropped = {};
  for (const [position, asset] of ordered.entries()) {
    signal?.throwIfAborted();
    await assertDrive(drive, state);
    const layout = layouts.get(asset.id);
    const report = event => onProgress({...event, position, total: ordered.length});
    try {
      await buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress: report});
      state.verified[asset.id] = true;
      delete state.failures[asset.id];
    } catch (error) {
      signal?.throwIfAborted();
      if (isNoSpace(error)) {
        // Earlier files are higher priority. Reclaim this unfinished file's
        // space and give the remaining, usually smaller files a chance to fit.
        await forgetParts(drive, state, asset, layout);
        state.dropped[asset.id] = "Drive ran out of space";
        delete state.failures[asset.id];
        report({kind: "dropped", asset, message: state.dropped[asset.id]});
      } else if (error instanceof SourceError) {
        if (error.whole) await forgetParts(drive, state, asset, layout);
        state.failures[asset.id] = error.message;
        report({kind: "failed", asset, message: error.message});
      } else throw error;
    }
    await save(drive, state);
  }
  signal?.throwIfAborted();
  await assertDrive(drive, state);
  onProgress({kind: "assembling"});
  const completed = ordered.filter(asset => state.verified[asset.id] === true);
  const missing = [...state.excluded, ...ordered.flatMap(asset => {
    const reason = state.dropped[asset.id] || state.failures[asset.id];
    return reason ? [{id: asset.id, title: asset.title, reason}] : [];
  })];
  await assembleLibrary(drive, {completed, missing, navigation, layouts, parts: state.parts, signal});
  state.finished = Object.keys(state.failures).length === 0 && Object.keys(state.dropped).length === 0;
  await save(drive, state);
  return {state, completed, missing};
}
