import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, writeFile} from "./drive.mjs";
import {diag} from "./diagnostics.mjs";
import {assembleLibrary} from "./offline.mjs";
import {createNetwork, SourceError} from "./network.mjs";
import {archiveSession, checkAlignment, publisherPin, streamRequest} from "./archive-download.mjs";

export const PART_BYTES = 2 ** 30;
export const MANIFEST = "LIBRARY/.owl/browser-build.json";
const FAT32_MAX = 2 ** 32 - 1;
const DIGEST = /^[0-9a-f]{64}$/;
const tier = ["CRITICAL", "USEFUL", "NONESSENTIAL"];

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

const matches = (asset, pin) => pin && Object.entries(assetPin(asset)).every(([key, value]) => pin[key] === value);
const fileAt = (drive, path) => optional(async () => (await fileHandle(drive, path)).getFile());
const map = () => Object.create(null);

function legacyRecord(record, modified) {
  const installed = map(), working = map(), owned = [];
  for (const pin of record.plan) {
    const asset = fromPin(pin);
    const split = partLayout(asset, record.partBytes);
    const joined = joinedLayout(asset);
    const layout = record.joined?.[pin.id] ? joined : split;
    owned.push(...split.map(part => part.path));
    if (record.joined?.[pin.id] || record.prefixes?.[pin.id] || record.stagedArchives?.[pin.id]) owned.push(joined[0].path);
    working[pin.id] = asset.destination;
    if (record.finished && record.verified[pin.id]) {
      installed[pin.id] = {pin, asset, layout, parts: record.joined?.[pin.id] ? [{sha256: pin.sha256}] : record.parts[pin.id]};
    }
  }
  return {...record, version: 2, migrated: true, installed, working, owned, generated: [],
    choice: {kind: "legacy", files: record.plan.map(pin => pin.id), split: !record.joinArchives && !record.singleArchives},
    syncedAt: record.finished && modified ? new Date(modified).toISOString() : undefined, pending: !record.finished};
}

export async function readBuild(drive) {
  const file = await fileAt(drive, MANIFEST);
  if (!file) return null;
  const state = JSON.parse(await file.text());
  if (![1, 2].includes(state.version) || !state.buildId || !Array.isArray(state.plan) ||
      !Array.isArray(state.excluded) || !state.parts || !state.verified || !state.dropped || !state.failures ||
      (state.version === 2 && (!state.installed || !state.working || !Array.isArray(state.owned) ||
       !Array.isArray(state.generated) || !state.owned.every(path => typeof path === "string" &&
         path.startsWith("LIBRARY/") && path !== MANIFEST) || !state.generated.every(path =>
         typeof path === "string" && (path === "START_HERE.html" || path.startsWith("LIBRARY/")) && path !== MANIFEST)))) {
    throw Error("The saved drive record is unreadable. Choose another drive folder.");
  }
  return state.version === 1 ? legacyRecord(state, file.lastModified) : state;
}

function fromPin(pin) {
  return {id: pin.id, title: pin.id, sha256: pin.sha256, size_bytes: pin.bytes, destination: pin.path, format: pin.format};
}

async function assertDrive(drive, state) {
  const file = await fileAt(drive, MANIFEST);
  if (!file || JSON.parse(await file.text()).buildId !== state.buildId) {
    throw Error("The drive was disconnected. Reconnect the original drive.");
  }
}

async function save(drive, state) {
  await assertDrive(drive, state);
  await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n");
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

function checkPublisherPieces(published, asset, part) {
  const pin = publisherPin(published, asset);
  if (!pin) return null;
  checkAlignment(pin, asset, part);
  const size = pin.size;
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
      if (!await pin.matches(index, buffer.subarray(0, offset))) {
        throw new SourceError("Publisher piece SHA-1 mismatch");
      }
      offset = 0;
      index++;
    }
  };
}

async function transferPart(asset, part, source, writable, options) {
  const {fetchFile, signal, whole, expectedHash, publisherPieces, last, range, onBytes} = options;
  const checkPiece = checkPublisherPieces(publisherPieces, asset, part);
  const hash = sha256.create(), next = whole.clone();
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
  if (last && bytesToHex(next.clone().digest()) !== asset.sha256)
    throw new SourceError("Whole-file SHA-256 mismatch", {whole: true});
  signal?.throwIfAborted();
  return {digest, next};
}

// Persist ownership before opening each batch of journal files. A later sync
// can reclaim only these paths, including after a closed tab.
async function pieceJournal(drive, state, asset, part, pin) {
  const base = "LIBRARY/.owl/download-pieces/" + asset.id + "/" + part.start + "/";
  const first = part.start / pin.size;
  const paths = Array.from({length: Math.ceil(part.bytes / pin.size)}, (_, index) => base + (first + index));
  const owned = new Set(state.owned);
  for (const path of paths) {
    if (owned.has(path)) continue;
    const existing = await fileAt(drive, path);
    const index = Number(path.slice(base.length));
    if (existing && (!state.migrated || !await pin.matches(index, new Uint8Array(await existing.arrayBuffer())))) {
      throw Error("An existing file blocks a download. Choose another library folder.");
    }
    state.owned.push(path);
  }
  await save(drive, state);
  return {
    async restore(index, length) {
      const file = await fileAt(drive, base + index);
      if (file?.size !== length) return null;
      const bytes = new Uint8Array(await file.arrayBuffer());
      return await pin.matches(index, bytes) ? bytes : null;
    },
    persist: (index, bytes) => writeFile(drive, base + index, bytes)
  };
}

async function prunePieceJournal(drive, state, asset, keep) {
  const prefix = "LIBRARY/.owl/download-pieces/" + asset.id + "/";
  const kept = prefix + keep + "/";
  const removed = new Set();
  for (const path of state.owned) {
    if (!path.startsWith(prefix) || path.startsWith(kept)) continue;
    try {
      await removeFile(drive, path);
      removed.add(path);
    } catch (error) {
      diag("cleanup-error", {asset: asset.id, error: error.message});
    }
  }
  if (removed.size) state.owned = state.owned.filter(path => !removed.has(path));
}

async function transferRangedPart(asset, part, writable, options) {
  const {whole, expectedHash, signal, last, onBytes, ranged, journal, writeOffset = 0} = options;
  const hash = sha256.create(), next = whole.clone();
  let total = 0, journalMs = 0, partMs = 0;
  await ranged(part, {
    restore: journal?.restore || (() => null),
    async accept(index, bytes, persist) {
      const began = performance.now();
      if (persist) await journal?.persist(index, bytes);
      const journaled = performance.now();
      await writable.seek(writeOffset + index * options.pieceSize - part.start);
      await writable.write(bytes);
      journalMs += journaled - began;
      partMs += performance.now() - journaled;
      total += bytes.byteLength;
      onBytes(total);
    },
    ordered(bytes) {
      hash.update(bytes);
      next.update(bytes);
    }
  });
  const digest = bytesToHex(hash.digest());
  diag("part-writes", {asset: asset.id, start: part.start, mb: +(part.bytes / 1e6).toFixed(1),
    journalMs: Math.round(journalMs), partMs: Math.round(partMs)});
  if (total !== part.bytes || (expectedHash && digest !== expectedHash)) throw new SourceError("Part SHA-256 or size mismatch");
  if (last && bytesToHex(next.clone().digest()) !== asset.sha256)
    throw new SourceError("Whole-file SHA-256 mismatch", {whole: true});
  signal?.throwIfAborted();
  return {digest, next};
}

async function writePart(drive, asset, part, source, options) {
  const writable = await (await fileHandle(drive, part.path, true)).createWritable({mode: "exclusive"});
  try {
    const result = options.ranged ? await transferRangedPart(asset, part, writable, options) :
      await transferPart(asset, part, source, writable, options);
    const closing = performance.now();
    await writable.close();
    diag("part-close", {asset: asset.id, start: part.start, mb: +(part.bytes / 1e6).toFixed(1),
      ms: Math.round(performance.now() - closing)});
    return result;
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
  await prunePieceJournal(drive, state, asset);
  delete state.parts[asset.id];
  delete state.verified[asset.id];
}

async function buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, fullVerify, network}) {
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
  await prunePieceJournal(drive, state, asset, layout[index]?.start);
  if (index === layout.length) {
    if (bytesToHex(whole.digest()) === asset.sha256) return;
    throw new SourceError("Saved parts failed whole-file SHA-256", {whole: true});
  }
  // Discard only this build's untrusted suffix before rewriting it, so a
  // replacement does not hold both the old bytes and a new swap file.
  for (const part of layout.slice(index)) await removeFile(drive, part.path);
  checkpoints.length = index;
  delete state.verified[asset.id];
  await save(drive, state);

  const download = partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network});
  for (; index < layout.length; index++) {
    const part = layout[index];
    let downloaded;
    try {
      downloaded = await download(index, whole, (source, options) => writePart(drive, asset, part, source, options));
    } catch (error) {
      // Failed swaps leave an empty destination placeholder in Chromium.
      if (error instanceof SourceError) await removeFile(drive, part.path);
      throw error;
    }
    whole = downloaded.next;
    checkpoints.push({sha256: downloaded.digest, bytes: part.bytes, hashState: hashCheckpoint(whole)});
    await save(drive, state);
    // Release the verified part's temporary pieces before reserving the next part.
    await prunePieceJournal(drive, state, asset, layout[index + 1]?.start);
  }
}

function partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const choices = routesFor(asset, routes, published);
  const pin = publisherPin(published.publisherPieces, asset);
  const direct = routes[asset.id] || [];
  const ranged = pin && direct.length && asset.size_bytes > pin.size ?
    archiveSession(asset, pin, {direct, relay: published.archiveRelay?.[asset.id], fetchFile, signal, network}) : null;
  let preferred = (state.sourceOffsets?.[asset.id] || 0) % (choices.length || 1);
  return async (index, whole, write) => {
    signal?.throwIfAborted();
    const part = layout[index];
    const progress = {asset, index, count: layout.length};
    const range = layout.length === 1 ? null : {start: part.start, end: part.start + part.bytes - 1, total: asset.size_bytes};
    const failures = new Set();
    if (ranged) {
      checkAlignment(pin, asset, part);
      const journal = await pieceJournal(drive, state, asset, part, pin);
      const notify = received => onProgress({kind: "downloading", ...progress, received, bytes: part.bytes});
      notify(0);
      await assertDrive(drive, state);
      return write(null, {ranged, journal, pieceSize: pin.size, whole, signal,
        expectedHash: pins[index], last: index === layout.length - 1, onBytes: notify});
    }
    let wholeMismatch = false, round = 0;
    while (choices.length && round < 2) {
      let connection = false;
      for (let offset = 0; offset < choices.length; offset++) {
        const sourceIndex = (preferred + offset) % choices.length;
        const source = choices[sourceIndex];
        const notify = received => onProgress({kind: "downloading", ...progress, received, bytes: part.bytes});
        notify(0);
        try {
          await assertDrive(drive, state);
          const result = await write(source, {fetchFile, signal, whole, range,
            expectedHash: pins[index], publisherPieces: published.publisherPieces, last: index === layout.length - 1,
            onBytes: notify});
          preferred = sourceIndex;
          return result;
        } catch (error) {
          if (!(error instanceof SourceError)) throw error;
          wholeMismatch ||= error.whole;
          connection ||= error.connection;
          const message = source.label + " — " + error.message;
          failures.add(message);
          onProgress({kind: "retrying", ...progress, message});
        }
      }
      if ((connection || network.offline()) && await network.waitForConnection()) continue;
      if (++round < 2) await network.delay();
    }
    if (wholeMismatch && choices.length > 1) (state.sourceOffsets ||= {})[asset.id] = (preferred + 1) % choices.length;
    throw new SourceError([...failures].join(". ") || "No browser source is available", {whole: wholeMismatch});
  };
}

function joinedLayout(asset) {
  return [{path: "LIBRARY/" + asset.destination, start: 0, bytes: asset.size_bytes}];
}

async function removeSplitParts(drive, state, asset, layout) {
  const installed = new Set(state.installed[asset.id]?.layout.map(part => part.path));
  for (const part of layout) {
    if (!installed.has(part.path)) await removeFile(drive, part.path);
  }
}

async function checkJoined(drive, state, asset, layout, {fullVerify, signal}) {
  if (!state.joined[asset.id]) return false;
  const [{path, bytes}] = joinedLayout(asset);
  const file = await fileAt(drive, path);
  if (file?.size === bytes && (!fullVerify || await readCheckpoint(file, asset.sha256, sha256.create(), signal))) {
    await removeSplitParts(drive, state, asset, layout);
    return true;
  }
  await removeFile(drive, path);
  delete state.joined[asset.id];
  delete state.verified[asset.id];
  await save(drive, state);
  return false;
}

async function prepareSingleArchive(drive, state, asset, layout, {signal, onProgress, published}) {
  const [{path}] = joinedLayout(asset);
  const file = await fileAt(drive, path);
  if (file?.size === asset.size_bytes && await readCheckpoint(file, asset.sha256, sha256.create(), signal)) {
    state.joined[asset.id] = true;
  } else {
    const prefix = state.prefixes[asset.id];
    const bytes = prefix && layout[prefix.count]?.start;
    if (bytes > 0 && file?.size >= bytes) {
      // Import the deployed builder's committed prefix without fetching it again.
      const pins = partPins(asset, layout, published, state.partBytes);
      const checkpoints = [];
      const whole = sha256.create();
      onProgress({kind: "checking", asset});
      for (const part of layout.slice(0, prefix.count)) {
        const writer = await (await fileHandle(drive, part.path, true)).createWritable({mode: "exclusive"});
        const digest = sha256.create();
        try {
          for await (const chunk of file.slice(part.start, part.start + part.bytes).stream()) {
            signal?.throwIfAborted();
            digest.update(chunk);
            whole.update(chunk);
            await writer.write(chunk);
          }
          await writer.close();
        } catch (error) {
          await writer.abort().catch(() => {});
          throw error;
        }
        const sha = bytesToHex(digest.digest());
        if (pins[checkpoints.length] && pins[checkpoints.length] !== sha) break;
        checkpoints.push({sha256: sha, bytes: part.bytes, hashState: hashCheckpoint(whole)});
      }
      if (checkpoints.length === prefix.count && bytesToHex(whole.digest()) === prefix.sha256) {
        state.parts[asset.id] = checkpoints;
      }
    }
    state.stagedArchives[asset.id] = true;
  }
  delete state.prefixes[asset.id];
  await save(drive, state);
}

async function joinParts(drive, state, asset, layout, {signal, onProgress}) {
  const [{path}] = joinedLayout(asset);
  // The last close may have committed before the journal write.
  const existing = await fileAt(drive, path);
  if (existing?.size === asset.size_bytes &&
      await readCheckpoint(existing, asset.sha256, sha256.create(), signal)) {
    state.joined[asset.id] = true;
    await save(drive, state);
    await removeSplitParts(drive, state, asset, layout);
    return;
  }
  await removeFile(drive, path);
  let writable;
  const began = performance.now();
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
    if (bytesToHex(digest.digest()) !== asset.sha256) throw new SourceError("Saved parts failed whole-file SHA-256", {whole: true});
    const closing = performance.now();
    await writable.close();
    diag("join", {asset: asset.id, mb: +(asset.size_bytes / 1e6).toFixed(1),
      copyMs: Math.round(closing - began), closeMs: Math.round(performance.now() - closing)});
  } catch (error) {
    await writable?.abort().catch(() => {});
    await removeFile(drive, path);
    signal?.throwIfAborted();
    if (isNoSpace(error) || error.name === "InvalidStateError" || /EFBIG|file too large/i.test(error.message)) return;
    throw error;
  }
  state.joined[asset.id] = true;
  await save(drive, state);
  await removeSplitParts(drive, state, asset, layout);
}

function layoutFor(asset, partBytes) {
  return asset.format === "zim" && partBytes === null ? joinedLayout(asset) : partLayout(asset, partBytes);
}

const diskAsset = (asset, destination) => ({...asset, destination});
const bytesOf = rows => rows.reduce((total, row) => total + row.bytes, 0);

async function candidateFile(drive, path) {
  try { return await fileAt(drive, path); }
  catch (error) {
    if (error.name === "TypeMismatchError") return null;
    throw error;
  }
}

async function layoutExists(drive, layout) {
  return (await Promise.all(layout.map(async part => (await candidateFile(drive, part.path))?.size === part.bytes))).every(Boolean);
}

async function verifyLayout(drive, asset, layout, signal) {
  const whole = sha256.create(), parts = [];
  for (const part of layout) {
    const file = await candidateFile(drive, part.path);
    if (file?.size !== part.bytes) return null;
    const hash = sha256.create();
    for await (const chunk of file.stream()) {
      signal?.throwIfAborted();
      hash.update(chunk);
      whole.update(chunk);
    }
    parts.push({sha256: bytesToHex(hash.digest()), bytes: part.bytes, hashState: hashCheckpoint(whole)});
  }
  return bytesToHex(whole.digest()) === asset.sha256 ? parts : null;
}

export async function inspectDrive(drive) {
  const state = await readBuild(drive);
  const library = await optional(() => drive.getDirectoryHandle("LIBRARY"));
  const adoption = Boolean(state?.adopting || !state && await candidateFile(drive, "START_HERE.html"));
  const installedPaths = Object.values(state?.installed || {}).flatMap(row => row.layout.map(part => part.path));
  const paths = new Set([...(state?.owned || []), ...(state?.generated || []), ...installedPaths]);
  let heldBytes = 0;
  for (const path of paths) heldBytes += (await candidateFile(drive, path))?.size || 0;
  const legacy = adoption || state?.migrated ? await previousReader(drive) : new Map();
  let candidates;
  if (adoption && legacy.size) {
    const inventory = await candidateFile(drive, "LIBRARY/INVENTORY.json");
    if (inventory && inventory.size <= 16 * 2 ** 20) {
      const data = JSON.parse(await inventory.text());
      candidates = new Set();
      for (const asset of data.assets || []) {
        if (typeof asset.id !== "string" || typeof asset.destination !== "string" || !DIGEST.test(asset.sha256)) continue;
        const path = "LIBRARY/" + asset.destination.replace(/^LIBRARY\//, "");
        const file = await candidateFile(drive, path);
        if (legacy.has(path) && file?.size && file.size === (asset.size_bytes ?? asset.bytes)) {
          if (!paths.has(path)) { heldBytes += file.size; paths.add(path); }
          candidates.add(asset.id);
        }
      }
    }
  }
  return {state, hasLibrary: Boolean(library), adoption, heldBytes, candidates, legacy};
}

export async function compareLibrary(drive, {assets, choice, catalogVersion, partBytes = PART_BYTES,
    singleArchives = false, joinArchives = false, fullVerify = false, signal, inspection, freeBytes = Infinity} = {}) {
  const {state, adoption, legacy} = inspection || await inspectDrive(drive);
  const wantsSingle = singleArchives || joinArchives;
  const sameOptions = !state || (partBytes === state.partBytes &&
    wantsSingle === Boolean(state.singleArchives || state.joinArchives));
  const adds = [], drops = [], present = [], held = [];
  const planned = new Map(state?.plan.map(pin => [pin.id, pin]));
  let room = freeBytes;
  for (const asset of buildOrder(assets)) {
    signal?.throwIfAborted();
    const old = state?.installed[asset.id];
    const previous = planned.get(asset.id);
    const split = layoutFor(asset, partBytes).length > 1;
    const compatible = !split || (sameOptions && !wantsSingle) || (wantsSingle && old?.layout.length === 1);
    const working = (sameOptions || !split) && matches(asset, previous) && state?.working[asset.id];
    const staged = working && state.stagedArchives?.[asset.id];
    let installed = compatible && !staged && matches(asset, old?.pin) ? old : null;
    if (!installed && working && state.verified[asset.id] && !state.stagedArchives?.[asset.id]) {
      const file = diskAsset(asset, working);
      const layout = state.joined?.[asset.id] ? joinedLayout(file) : layoutFor(file, partBytes);
      installed = {pin: assetPin(asset), asset, layout, parts: state.joined?.[asset.id] ?
        [{sha256: asset.sha256}] : state.parts[asset.id]};
    }
    if (installed && await layoutExists(drive, installed.layout)) {
      const parts = fullVerify ? await verifyLayout(drive, asset, installed.layout, signal) : installed.parts;
      if (parts?.length) { present.push({asset, ...installed, parts}); continue; }
    }
    if (!old && !working && !state?.owned.includes(joinedLayout(asset)[0].path)) {
      const canonical = joinedLayout(asset);
      const split = layoutFor(asset, partBytes);
      for (const layout of canonical[0].path === split[0].path ? [canonical] : [canonical, split]) {
        if (!await layoutExists(drive, layout)) continue;
        const parts = await verifyLayout(drive, asset, layout, signal);
        if (parts) {
          const owned = layout.every((part, index) => legacy.get(part.path) === parts[index].sha256);
          present.push({asset, pin: assetPin(asset), layout, parts, protected: !owned});
          installed = true;
          break;
        }
      }
      if (installed === true) continue;
    }
    const savedParts = working ? state.parts[asset.id] || [] : [];
    const bytes = Math.max(0, asset.size_bytes - bytesOf(savedParts));
    const row = {asset, old, working, bytes, savedBytes: asset.size_bytes - bytes,
      corrupt: fullVerify && Boolean(installed)};
    adds.push(row);
    if (old && bytes > room) held.push(row);
    else room -= bytes;
  }
  const target = new Set(assets.map(asset => asset.id));
  for (const old of Object.values(state?.installed || {})) {
    if (!target.has(old.pin.id)) drops.push(old);
  }
  const removes = [...drops, ...adds.flatMap(row => row.old && !row.old.protected ? [row.old] : [])];
  const changedChoice = Boolean(state && choice && JSON.stringify(choice) !== JSON.stringify(state.choice));
  const current = Boolean(state?.finished && !adds.length && !drops.length && !changedChoice && !state.migrated &&
    state.catalogVersion === catalogVersion && await candidateFile(drive, "START_HERE.html"));
  return {state, adoption, adds, drops, present, held, changedChoice, current, workCount: adds.length + drops.length,
    addBytes: bytesOf(adds), removeBytes: bytesOf(removes.filter(row => !row.protected).map(row => row.pin)),
    presentBytes: bytesOf(present.map(row => row.pin)) + adds.reduce((sum, row) => sum + row.savedBytes, 0)};
}

async function reservePaths(drive, state, asset, partBytes, joining) {
  const owned = new Set(state.owned);
  const versioned = (destination, suffix) => {
    const dot = destination.lastIndexOf(".");
    const offset = dot > destination.lastIndexOf("/") ? dot : destination.length;
    return destination.slice(0, offset) + "-" + suffix + destination.slice(offset);
  };
  for (let attempt = 0; attempt < 3; attempt++) {
    const suffix = asset.sha256.slice(0, 12) + (attempt === 2 ? "-" + state.buildId.slice(0, 8) : "");
    const destination = attempt ? versioned(asset.destination, suffix) : asset.destination;
    const file = diskAsset(asset, destination);
    const layout = layoutFor(file, partBytes);
    const paths = new Set(layout.map(part => part.path));
    if (joining) paths.add(joinedLayout(file)[0].path);
    let conflict = false;
    for (const path of paths) {
      // An existing directory at a file path is also occupied.
      const exists = await fileAt(drive, path).catch(error => {
        if (error.name === "TypeMismatchError") return true;
        throw error;
      });
      if (owned.has(path) || exists) { conflict = true; break; }
    }
    if (conflict) continue;
    state.owned.push(...paths);
    state.working[asset.id] = destination;
    return file;
  }
  throw Error("An existing file or folder blocks " + asset.title + ". Choose another library folder.");
}

const readerPath = path => path === "START_HERE.html" ||
  /^LIBRARY\/(?:INDEX\/|SEARCH(?:\/|\.html$)|INVENTORY(?:\.|\/)|VERIFY\.py$|README\.txt$|BUILD_INFO\.json$|BUILD_REPORT\.html$|SOURCE_NOTES\.txt$|CRITICAL\/MEDICAL\/WIKIMED-PHONE\/)/.test(path);
const readerChecksums = "LIBRARY/SHA256SUMS.txt";
const generationPath = /^LIBRARY\/INDEX\/([a-f0-9]{8,64})\//;

async function checksumPins(checksums) {
  const pins = new Map();
  for (const line of (await checksums.text()).split("\n")) {
    const match = /^([0-9a-f]{64})  (.+)$/.exec(line);
    if (!match) continue;
    const path = match[2] === "../START_HERE.html" || match[2] === "START_HERE.html" ? "START_HERE.html" :
      match[2].startsWith("LIBRARY/") ? match[2] : "LIBRARY/" + match[2];
    if (!path.split("/").some(piece => !piece || piece === "." || piece === "..")) pins.set(path, match[1]);
  }
  return pins;
}

async function previousReader(drive) {
  const checksums = await fileAt(drive, readerChecksums);
  if (!checksums || checksums.size > 16 * 2 ** 20) return new Map();
  const pins = await checksumPins(checksums);
  const start = await fileAt(drive, "START_HERE.html");
  if (!start || start.size > 16 * 2 ** 20 || !pins.has("START_HERE.html") ||
      !/offline wandering library/i.test(await start.text()) ||
      !await readCheckpoint(start, pins.get("START_HERE.html"), sha256.create())) return new Map();
  pins.set(readerChecksums, null);
  return pins;
}

function guardReader(drive, state, legacy) {
  const known = new Set(state.generated);
  const wrap = (dir, prefix) => ({
    async getDirectoryHandle(name, options) {
      return wrap(await dir.getDirectoryHandle(name, options), prefix + name + "/");
    },
    async getFileHandle(name, options) {
      const path = prefix + name;
      if (options?.create && !known.has(path)) {
        const file = await optional(async () => (await dir.getFileHandle(name)).getFile());
        if (file && (!(readerPath(path) || path === readerChecksums) || !legacy.has(path) || (legacy.get(path) &&
            !await readCheckpoint(file, legacy.get(path), sha256.create())))) {
          throw Error("An existing file blocks the start page or search index. Choose another library folder.");
        }
        known.add(path);
        state.generated.push(path);
        await save(drive, state);
      }
      return dir.getFileHandle(name, options);
    }
  });
  return wrap(drive, "");
}

async function recordAdoptedGeneration(drive, state, legacy, signal) {
  const known = new Set(state.generated);
  for (const path of ["START_HERE.html", readerChecksums]) {
    if (!known.has(path)) state.generated.push(path);
  }
  for (const [path, digest] of legacy) {
    if (!generationPath.test(path) || known.has(path)) continue;
    const file = await candidateFile(drive, path);
    if (file && await readCheckpoint(file, digest, sha256.create(), signal)) state.generated.push(path);
  }
}

async function retireReaderFiles(drive, state, signal) {
  signal?.throwIfAborted();
  const active = await checksumPins(await fileAt(drive, readerChecksums));
  active.set(readerChecksums, null);
  const generations = new Set();
  for (const path of state.generated) {
    if (active.has(path)) continue;
    signal?.throwIfAborted();
    if (await candidateFile(drive, path)) await removeFile(drive, path);
    const id = generationPath.exec(path)?.[1];
    if (id) generations.add(id);
  }
  const index = generations.size && await optional(async () => (await drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle("INDEX"));
  for (const id of generations) {
    signal?.throwIfAborted();
    await optional(async () => {
      const dir = await index?.getDirectoryHandle(id);
      if (!dir) return;
      for await (const entry of dir.values()) return;
      await index.removeEntry(id).catch(error => {
        if (error.name !== "InvalidModificationError") throw error;
      });
    });
  }
  state.generated = state.generated.filter(path => active.has(path));
}

function beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, archiveSpace, searchBudget, capacityBytes}) {
  return {version: 2, buildId: saved?.buildId || globalThis.crypto.randomUUID(), plan: [], excluded: [],
    installed: saved?.installed || map(), working: map(), owned: [...(saved?.owned || [])], generated: [...(saved?.generated || [])],
    parts: map(), verified: map(), joined: map(), prefixes: map(), stagedArchives: map(), sourceOffsets: map(),
    dropped: map(), failures: map(), partBytes, joinArchives, singleArchives, archiveSpace,
    choice, catalogVersion, searchBudget, capacityBytes, pending: true, finished: false, migrated: saved?.migrated,
    syncedAt: saved?.syncedAt};
}

export async function reconcile(drive, {assets, excluded = [], routes = {}, published = {}, navigation = {}, search,
    partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal, onProgress = () => {}, fullVerify = false,
    joinArchives = false, singleArchives = false, archiveSpace = 0, choice, catalogVersion,
    freeBytes = Infinity, capacityBytes, replaceInPlace = [], searchBudget = 16 * 2 ** 20, prepareSources,
    network = createNetwork({fetchFile, signal, onWaiting: () => onProgress({kind: "waiting-network"})})}) {
  const inspection = await inspectDrive(drive), saved = inspection.state;
  if (!assets.some(isKnowledgeFile)) throw Error("Choose knowledge files with browser-accessible sources.");
  choice ??= saved?.choice || {kind: "recommended", split: !singleArchives && !joinArchives};
  const comparison = await compareLibrary(drive, {assets, choice, catalogVersion, partBytes, singleArchives, joinArchives, fullVerify, signal,
    inspection, freeBytes});
  const state = beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, archiveSpace,
    capacityBytes: capacityBytes ?? saved?.capacityBytes, searchBudget: saved?.pending ? saved.searchBudget ?? searchBudget : searchBudget});
  const {legacy} = inspection;
  state.adopting = comparison.adoption && legacy.size > 0;
  const held = new Set(comparison.held.filter(row => !replaceInPlace.includes(row.asset.id) || row.old.protected).map(row => row.asset.id));
  const present = new Map(comparison.present.map(row => [row.pin.id, row]));
  const additions = new Map(comparison.adds.map(row => [row.asset.id, row]));
  const ordered = buildOrder(assets);
  state.plan = ordered.map(assetPin);
  state.excluded = excluded;
  const workingFields = ["parts", "verified", "joined", "prefixes", "stagedArchives", "sourceOffsets"];
  for (const asset of ordered) {
    const row = additions.get(asset.id);
    if (row?.working) {
      state.working[asset.id] = row.working;
      for (const field of workingFields) {
        if (saved[field]?.[asset.id] !== undefined) state[field][asset.id] = saved[field][asset.id];
      }
    }
  }
  onProgress({kind: "plan", files: ordered.map(asset => ({id: asset.id, bytes: asset.size_bytes,
    done: present.has(asset.id), savedBytes: additions.get(asset.id)?.savedBytes || 0}))});
  if (saved) await save(drive, state);
  else {
    if (await readBuild(drive)) throw Error("Another sync started on this drive.");
    await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n");
  }
  if (prepareSources) {
    const support = await prepareSources();
    search = support.search;
    published = {...published, publisherPieces: support.publisherPieces};
  }
  const layouts = new Map(), installedParts = map();
  let used = comparison.presentBytes;
  for (const [position, asset] of ordered.entries()) {
    signal?.throwIfAborted();
    const report = event => onProgress({...event, position, total: ordered.length});
    const row = additions.get(asset.id);
    if (present.has(asset.id)) {
      state.verified[asset.id] = true;
      state.parts[asset.id] = present.get(asset.id).parts;
      if (present.get(asset.id).layout.length === 1 && layoutFor(asset, partBytes).length > 1) state.joined[asset.id] = true;
      report({kind: "verified", asset});
      continue;
    }
    used -= row.savedBytes;
    if (held.has(asset.id)) {
      state.failures[asset.id] = "The replacement needs more free space beside the existing copy.";
      report({kind: "failed", asset, message: state.failures[asset.id]});
      continue;
    }
    let file = row.working ? diskAsset(asset, row.working) : await reservePaths(drive, state, asset, partBytes, joinArchives || singleArchives);
    const layout = layoutFor(file, partBytes);
    const single = singleArchives && layout.length > 1;
    if (single || joinArchives && layout.length > 1) {
      const path = joinedLayout(file)[0].path;
      if (!state.owned.includes(path)) {
        if (await fileAt(drive, path)) throw Error("An existing file blocks the archive. Choose another library folder.");
        state.owned.push(path);
      }
    }
    await save(drive, state);
    if (replaceInPlace.includes(asset.id) && comparison.held.includes(row) && !row.old.protected) {
      for (const part of row.old.layout) if (state.owned.includes(part.path)) await removeFile(drive, part.path);
      delete state.installed[asset.id];
      await save(drive, state);
    }
    const options = {routes, published, fetchFile, signal, onProgress: report, fullVerify, network};
    try {
      const wasStaged = state.stagedArchives[asset.id];
      if (!await checkJoined(drive, state, file, layout, options)) {
        if (single && !wasStaged) await prepareSingleArchive(drive, state, file, layout, options);
        if (state.joined[asset.id]) await removeSplitParts(drive, state, file, layout);
        else {
          if (single) {
            const [{path}] = joinedLayout(file);
            if ((await fileAt(drive, path))?.size < asset.size_bytes) await removeFile(drive, path);
          }
          await buildAsset(drive, state, file, layout, options);
          if (layout.length > 1 && (joinArchives || (single && (archiveSpace - used >= 2 * asset.size_bytes || wasStaged)))) {
            await joinParts(drive, state, file, layout, options);
          }
        }
      }
      if (state.joined[asset.id]) delete state.stagedArchives[asset.id];
      used += asset.size_bytes;
      state.verified[asset.id] = true;
      const savedLayout = state.joined[asset.id] ? joinedLayout(file) : layout;
      present.set(asset.id, {asset, pin: assetPin(asset), layout: savedLayout,
        parts: state.joined[asset.id] ? [{sha256: asset.sha256, bytes: asset.size_bytes}] : state.parts[asset.id]});
      report({kind: "verified", asset});
    } catch (error) {
      signal?.throwIfAborted();
      if (isNoSpace(error)) {
        if (!(layout.length > 1 && publisherPin(published.publisherPieces, asset))) {
          await forgetParts(drive, state, file, layout);
          delete state.stagedArchives[asset.id];
        }
        state.dropped[asset.id] = "Drive ran out of space";
        report({kind: "dropped", asset, message: state.dropped[asset.id]});
      } else if (error instanceof SourceError) {
        if (error.whole) await forgetParts(drive, state, file, layout);
        state.failures[asset.id] = error.message;
        report({kind: "failed", asset, message: error.message});
      } else throw error;
    }
    await save(drive, state);
  }
  signal?.throwIfAborted();
  const complete = !excluded.length && !Object.keys(state.failures).length && !Object.keys(state.dropped).length;
  if (!complete) {
    for (const old of Object.values(state.installed)) {
      if (!present.has(old.pin.id) && !additions.get(old.pin.id)?.corrupt && await layoutExists(drive, old.layout)) present.set(old.pin.id, old);
    }
  }
  for (const [id, row] of present) {
    layouts.set(id, row.layout);
    installedParts[id] = row.parts;
  }
  const completed = [...present.values()].map(row => row.asset);
  const missing = [...excluded, ...ordered.flatMap(asset => {
    const reason = state.dropped[asset.id] || state.failures[asset.id];
    return reason ? [{id: asset.id, title: asset.title, reason}] : [];
  })];
  onProgress({kind: "assembling"});
  if (legacy.size) {
    // Keep ownership available on retry even if assembly replaces the old checksum list.
    await recordAdoptedGeneration(drive, state, legacy, signal);
    await save(drive, state);
  }
  const syncedAt = new Date().toISOString();
  const searchWarnings = await assembleLibrary(guardReader(drive, state, legacy), {completed, missing, navigation, layouts,
    parts: installedParts, search, searchBudget: state.searchBudget, fetchFile, signal, network, syncedAt});
  // The start page now points to the new reader, and the checksum list includes reused shards.
  await retireReaderFiles(drive, state, signal);
  state.installed = Object.fromEntries(present);
  const recorded = new Set(state.owned);
  for (const row of present.values()) {
    if (row.protected) continue;
    for (const part of row.layout) recorded.add(part.path);
  }
  state.owned = [...recorded];
  const finished = complete && !Object.keys(state.stagedArchives).length && !searchWarnings.length;
  state.syncedAt = syncedAt;
  if (finished) {
    await save(drive, state);
    const keep = new Set([...present.values()].flatMap(row => row.layout.map(part => part.path)));
    for (const path of state.owned) {
      signal?.throwIfAborted();
      if (!keep.has(path)) await removeFile(drive, path);
    }
    state.owned = state.owned.filter(path => keep.has(path));
    state.migrated = false;
    state.adopting = false;
  }
  state.pending = false;
  state.finished = finished;
  await save(drive, state);
  return {state, completed, missing, searchWarnings};
}

export {reconcile as buildLibrary};
