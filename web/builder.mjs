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

export function isKnowledgeFile(asset) {
  return !asset.destination.startsWith("SOFTWARE/") && !asset.supporting_file && asset.archive_member?.document !== false;
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

async function start(drive, {assets, excluded, partBytes, joinArchives}) {
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
  const state = {version: 1, buildId: globalThis.crypto.randomUUID(), partBytes, joinArchives, joined: {},
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

const fileAt = (drive, path) => optional(async () => (await fileHandle(drive, path)).getFile());

function hashCheckpoint(hash) {
  return {words: hash.get().map(word => word >>> 0), tail: Array.from(hash.buffer.subarray(0, hash.pos))};
}

function restoreHash(checkpoint, bytes) {
  const {words, tail} = checkpoint || {};
  if (!Array.isArray(words) || words.length !== 8 ||
      words.some(word => !Number.isInteger(word) || word < 0 || word > 0xffffffff) ||
      !Array.isArray(tail) || tail.length !== bytes % 64 ||
      tail.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255)) return null;
  const hash = sha256.create();
  hash.set(...words);
  hash.length = bytes;
  hash.pos = tail.length;
  hash.buffer.set(tail);
  return hash;
}

async function readCheckpoint(file, digest, whole, signal) {
  const next = whole.clone(), current = sha256.create();
  for await (const chunk of file.stream()) {
    signal?.throwIfAborted();
    next.update(chunk);
    current.update(chunk);
  }
  return bytesToHex(current.digest()) === digest ? next : null;
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

function checkPublisherPieces(published, asset, part) {
  const record = published?.archives?.[asset.id];
  if (!record) return null;
  const size = published.piece_bytes;
  const digests = atob(record.sha1);
  if (record.sha256 !== asset.sha256 || size !== 4 * 2 ** 20 ||
      digests.length !== Math.ceil(asset.size_bytes / size) * 20 ||
      part.start % size || (part.start + part.bytes !== asset.size_bytes && part.bytes % size)) {
    throw Error("Publisher piece manifest does not match " + asset.title);
  }
  const buffer = new Uint8Array(Math.min(size, part.bytes));
  let offset = 0, written = 0, index = part.start / size;
  return async chunk => {
    for (let cursor = 0; cursor < chunk.length;) {
      const length = Math.min(buffer.length - offset, chunk.length - cursor);
      buffer.set(chunk.subarray(cursor, cursor + length), offset);
      offset += length;
      cursor += length;
      written += length;
      if (offset < buffer.length && written < part.bytes) continue;
      const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-1", buffer.subarray(0, offset)));
      const expected = digests.slice(index * 20, (index + 1) * 20);
      if (digest.some((byte, i) => byte !== expected.charCodeAt(i))) {
        throw new SourceError("Publisher piece SHA-1 mismatch");
      }
      offset = 0;
      index++;
    }
  };
}

async function writePart(drive, asset, part, source, options) {
  const {fetchFile, signal, whole, expectedHash, publisherPieces, last, range, onBytes} = options;
  const checkPiece = checkPublisherPieces(publisherPieces, asset, part);
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
        if (checkPiece) await checkPiece(chunk);
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

async function buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, fullVerify}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const checkpoints = state.parts[asset.id] ||= [];
  let whole = sha256.create(), index = 0;
  for (const [i, part] of layout.entries()) {
    signal?.throwIfAborted();
    const saved = checkpoints[i];
    if (!DIGEST.test(saved?.sha256) || saved.bytes !== part.bytes || (pins[i] && pins[i] !== saved.sha256)) break;
    const file = await fileAt(drive, part.path);
    if (file?.size !== part.bytes) break;
    let restored = fullVerify ? null : restoreHash(saved.hashState, part.start + part.bytes);
    if (!restored) {
      onProgress({kind: "checking", asset, index: i, count: layout.length});
      restored = await readCheckpoint(file, saved.sha256, whole, signal);
      if (!restored) break;
      saved.hashState = hashCheckpoint(restored);
    }
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
            expectedHash: pins[index], publisherPieces: published.publisherPieces, last: index === layout.length - 1,
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
    whole = downloaded.next;
    checkpoints.push({sha256: downloaded.digest, bytes: part.bytes, hashState: hashCheckpoint(whole)});
    await save(drive, state);
  }
}

function joinedLayout(asset) {
  return [{path: "LIBRARY/" + asset.destination, start: 0, bytes: asset.size_bytes}];
}

async function removeSplitParts(drive, layout) {
  for (const part of layout) await removeFile(drive, part.path);
}

async function checkJoined(drive, state, asset, layout, {fullVerify, signal}) {
  if (!state.joined[asset.id]) return false;
  const [{path, bytes}] = joinedLayout(asset);
  const file = await fileAt(drive, path);
  if (file?.size === bytes && (!fullVerify || await readCheckpoint(file, asset.sha256, sha256.create(), signal))) {
    await removeSplitParts(drive, layout);
    return true;
  }
  await removeFile(drive, path);
  delete state.joined[asset.id];
  delete state.verified[asset.id];
  await save(drive, state);
  return false;
}

async function joinParts(drive, state, asset, layout, {signal, onProgress}) {
  const [{path}] = joinedLayout(asset);
  // An interrupted copy may have left a placeholder or a complete but unrecorded swap.
  await removeFile(drive, path);
  let writable;
  try {
    writable = await (await fileHandle(drive, path, true)).createWritable({mode: "exclusive"});
    const digest = sha256.create();
    for (const part of layout) {
      onProgress({kind: "joining", asset});
      const file = await fileAt(drive, part.path);
      for await (const chunk of file.stream()) {
        signal?.throwIfAborted();
        digest.update(chunk);
        await writable.write(chunk);
      }
    }
    if (bytesToHex(digest.digest()) !== asset.sha256) throw new SourceError("Saved parts failed whole-file SHA-256", true);
    await writable.close();
  } catch (error) {
    await writable?.abort().catch(() => {});
    await removeFile(drive, path);
    signal?.throwIfAborted();
    if (isNoSpace(error) || error.name === "InvalidStateError" || /EFBIG|file too large/i.test(error.message)) return;
    throw error;
  }
  state.joined[asset.id] = true;
  await save(drive, state);
  await removeSplitParts(drive, layout);
}

export async function buildLibrary(drive, {assets, excluded = [], catalogAssets = assets, routes,
  published = {}, navigation = {}, search, searchBudget = 16 * 2 ** 20, partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal,
  onProgress = () => {}, resume = false, fullVerify = false, joinArchives = false}) {
  const saved = await readBuild(drive);
  if (saved && !resume) throw Error("This drive has a saved build. Choose Resume.");
  if (!saved && resume) throw Error("No browser build was found on this drive.");
  if (!saved && !assets.some(isKnowledgeFile)) throw Error("Choose knowledge files with browser-accessible sources.");
  const state = saved || await start(drive, {assets, excluded, partBytes, joinArchives});
  state.joined ||= {};
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
      if (!await checkJoined(drive, state, asset, layout, {fullVerify, signal})) {
        await buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress: report, fullVerify});
        if (state.joinArchives && layout.length > 1) {
          await joinParts(drive, state, asset, layout, {signal, onProgress: report});
        }
      }
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
  const installedParts = {...state.parts};
  for (const asset of completed) {
    if (state.joined[asset.id]) {
      layouts.set(asset.id, joinedLayout(asset));
      installedParts[asset.id] = [{sha256: asset.sha256}];
    }
  }
  const searchWarnings = await assembleLibrary(drive, {completed, missing, navigation, layouts, parts: installedParts,
    search, searchBudget, fetchFile, signal});
  state.finished = Object.keys(state.failures).length === 0 && Object.keys(state.dropped).length === 0 && !searchWarnings.length;
  await save(drive, state);
  return {state, completed, missing, searchWarnings};
}
