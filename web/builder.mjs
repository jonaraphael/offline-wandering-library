import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex, hexToBytes} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, writeFile} from "./drive.mjs";
import {diag} from "./diagnostics.mjs";
import {assembleLibrary, assemblyReserve, startPage} from "./offline.mjs";
import {createNetwork, routeCooldowns, SourceError} from "./network.mjs";
import {canonical} from "./search-build.mjs";
import {archiveSession, checkAlignment, publisherPin, streamRequest} from "./archive-download.mjs";
import {createRelayWait, RELAY_WAIT_REASON} from "./relay-wait.mjs";

export const PART_BYTES = 2 ** 30;
export const MANIFEST = "LIBRARY/.owl/browser-build.json";
const FAT32_MAX = 2 ** 32 - 1;
const START_PAGE = "START_HERE.html";
const DIGEST = /^[0-9a-f]{64}$/;
const encoder = new TextEncoder();
const filePin = contents => {
  const bytes = typeof contents === "string" ? encoder.encode(contents) : contents;
  return {bytes: bytes.length, sha256: bytesToHex(sha256(bytes))};
};
const emptyPin = filePin("");
const READBACK_BUFFER = 16 * 2 ** 20;
const tier = ["CRITICAL", "USEFUL", "NONESSENTIAL"];
const priority = asset => tier.includes(asset.utility_tier) ? tier.indexOf(asset.utility_tier) : tier.length;
const noSpace = "Drive ran out of space";
const isReaderApp = asset => asset.destination.startsWith("SOFTWARE/");
export const LARGE_FILE_MESSAGE = "This drive can’t hold files over 4 GB. OWL kept that encyclopedia in parts.";

export function isKnowledgeFile(asset) {
  return !isReaderApp(asset) && !asset.supporting_file && asset.archive_member?.document !== false;
}

const archiveFileLimit = (fat32, joining, limited) => fat32 || limited ? FAT32_MAX : joining ? Infinity : 0;

export function archiveJoinLimitReached(error, written, next) {
  if (next <= FAT32_MAX) return false;
  if (error.code === "EFBIG" || /EFBIG|file too large/i.test(error.message)) return true;
  return written <= FAT32_MAX + 1 && (error.name === "InvalidStateError" || isNoSpace(error));
}

export function buildOrder(assets, {transfer = true, archiveSpace = Infinity, partBytes = PART_BYTES} = {}) {
  // Give archive transfers their temporary workspace before other files fill
  // the drive, even if the final archive will be kept in parts.
  const archiveSize = asset => transfer && asset.format === "zim" ? asset.size_bytes : 0;
  const ordered = [...assets].sort((a, b) => priority(a) - priority(b) ||
    archiveSize(b) - archiveSize(a) ||
    (a.selection?.level ?? Infinity) - (b.selection?.level ?? Infinity) ||
    (a.selection?.rank ?? Infinity) - (b.selection?.rank ?? Infinity) ||
    a.id.localeCompare(b.id));
  if (!transfer) return ordered;
  const moveEarly = asset => isReaderApp(asset) && priority(asset) > 0;
  const readers = ordered.filter(moveEarly);
  if (!readers.length) return ordered;
  const content = ordered.filter(asset => !moveEarly(asset));
  const readerBytes = readers.reduce((total, asset) => total + asset.size_bytes, 0);
  let position = content.filter(asset => priority(asset) === 0).length;
  let written = 0;
  for (const [index, asset] of content.entries()) {
    const part = Math.min(asset.size_bytes, partBytes ?? asset.size_bytes);
    const remainder = asset.size_bytes % part;
    // The archive writer holds the verified pieces and the part being written.
    const scratch = Math.max(remainder, part - remainder);
    if (asset.format === "zim" && written + asset.size_bytes + scratch + readerBytes > archiveSpace) {
      position = Math.max(position, index + 1);
    }
    written += asset.size_bytes;
  }
  return [...content.slice(0, position), ...readers, ...content.slice(position)];
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
const safePath = path => typeof path === "string" && path.split("/").every(piece =>
  piece && piece !== "." && piece !== ".." && !/[\\:\u0000-\u001f]/.test(piece));
const managedContent = path => safePath(path) && /^LIBRARY\/(BOOKS|CRITICAL|MAPS|REFERENCE|SOFTWARE|ZIM)\/./.test(path);
const versioned = (destination, suffix) => {
  const dot = destination.lastIndexOf(".");
  const offset = dot > destination.lastIndexOf("/") ? dot : destination.length;
  return destination.slice(0, offset) + "-" + suffix + destination.slice(offset);
};

function managedDestination(asset, destination, buildId) {
  return managedContent("LIBRARY/" + destination) && [asset.destination,
    versioned(asset.destination, asset.sha256.slice(0, 12)),
    versioned(asset.destination, asset.sha256.slice(0, 12) + "-" + buildId.slice(0, 8))].includes(destination);
}

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
  const contents = await file.text();
  let state;
  try { state = JSON.parse(contents); }
  catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    // Creating the first handle can leave an empty entry before the first close.
    if (await matchesFile(await candidateFile(drive, START_PAGE), filePin(startPage()))) return null;
  }
  if (!state || ![1, 2].includes(state.version) || !/^[a-z0-9-]+$/i.test(state.buildId || "") || !Array.isArray(state.plan) ||
      !Array.isArray(state.excluded) || !state.parts || !state.verified || !state.dropped || !state.failures ||
      (state.version === 2 && (!state.installed || !state.working || !Array.isArray(state.owned) ||
       !Array.isArray(state.generated)))) {
    throw Error("The saved drive record is unreadable. Choose another drive folder.");
  }
  if (state.version === 1) return legacyRecord(state, file.lastModified);
  state.installed = Object.fromEntries(Object.entries(state.installed)
    .filter(([id, row]) => row?.pin?.id === id && row.asset && matches(row.asset, row.pin) && recordedLayout(row, state.buildId)));
  return state;
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
  // createWritable publishes the complete swap file on close, keeping the old record until then.
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

// The running whole-file hash after a saved part. A resumed download
// continues from it instead of rereading every saved part.
function hashState(hash) {
  return {words: hash.get(), length: hash.length, tail: bytesToHex(hash.buffer.subarray(0, hash.pos))};
}

function restoreHash(saved, part) {
  if (!Array.isArray(saved?.words) || saved.words.length !== 8 || !saved.words.every(Number.isInteger) ||
      saved.length !== part.start + part.bytes || !/^(?:[0-9a-f]{2}){0,63}$/.test(saved.tail ?? "") ||
      saved.tail.length / 2 !== saved.length % 64) return null;
  const hash = sha256.create();
  hash.set(...saved.words);
  const tail = hexToBytes(saved.tail);
  hash.buffer.set(tail);
  hash.pos = tail.length;
  hash.length = saved.length;
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

async function storedDigest(file, signal) {
  signal?.throwIfAborted();
  // Web Crypto needs the entire input in memory. Stream large parts so
  // read-back does not add an archive-sized allocation.
  if (file.size <= READBACK_BUFFER && globalThis.crypto?.subtle) {
    const bytes = await file.arrayBuffer();
    signal?.throwIfAborted();
    return bytesToHex(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)));
  }
  const hash = sha256.create();
  for await (const chunk of file.stream()) {
    signal?.throwIfAborted();
    hash.update(chunk);
  }
  return bytesToHex(hash.digest());
}

async function matchesFile(file, pin, signal) {
  return file && pin && file.size === pin.bytes && DIGEST.test(pin.sha256) &&
    await storedDigest(file, signal) === pin.sha256;
}

class DriveWriteMismatch extends Error {
  constructor(path, actual) {
    super("The drive stored different data for " + path + ".");
    this.actual = actual;
  }
}

async function checkWrittenFile(handle, path, expected, signal) {
  const start = performance.now();
  const file = await handle.getFile();
  const actual = {bytes: file.size, sha256: await storedDigest(file, signal)};
  signal?.throwIfAborted();
  diag("write-readback", {path, bytes: actual.bytes, ms: Math.round(performance.now() - start)});
  if (actual.bytes !== expected.bytes || actual.sha256 !== expected.sha256) throw new DriveWriteMismatch(path, actual);
}

async function checkGeneratedWrite(drive, path, contents, signal) {
  const pin = filePin(contents);
  const handle = await fileHandle(drive, path);
  try { await checkWrittenFile(handle, path, pin, signal); }
  catch (error) {
    if (!(error instanceof DriveWriteMismatch) || !await matchesFile(await handle.getFile(), error.actual, signal)) throw error;
    await writeFile(drive, path, contents);
    await checkWrittenFile(handle, path, pin, signal);
  }
  return pin;
}

async function removePinned(drive, path, pin, signal) {
  if (await matchesFile(await candidateFile(drive, path), pin, signal)) {
    signal?.throwIfAborted();
    await removeFile(drive, path);
  }
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
  const hash = part.start ? sha256.create() : null, next = whole.clone();
  let total = 0;
  for (const piece of source.pieces) {
    const pieceHash = piece.sha256 ? sha256.create() : null;
    await streamRequest(piece.url, range, piece.bytes ?? part.bytes, fetchFile, signal, async chunk => {
      hash?.update(chunk);
      next.update(chunk);
      pieceHash?.update(chunk);
      if (checkPiece) await checkPiece(chunk);
      await writable.write(chunk);
      total += chunk.byteLength;
      onBytes(total);
    });
    if (pieceHash && bytesToHex(pieceHash.digest()) !== piece.sha256) throw new SourceError("Published chunk SHA-256 mismatch");
  }
  const digest = bytesToHex((hash || next.clone()).digest());
  if (total !== part.bytes || (expectedHash && digest !== expectedHash)) throw new SourceError("Part SHA-256 or size mismatch");
  if (last && (hash ? bytesToHex(next.clone().digest()) : digest) !== asset.sha256)
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

async function prunePieceJournal(drive, state, asset, pin, keep) {
  if (!pin) return;
  const prefix = "LIBRARY/.owl/download-pieces/" + asset.id + "/";
  const kept = prefix + keep + "/";
  const removed = new Set();
  for (const path of state.owned) {
    if (!safePath(path) || !path.startsWith(prefix) || path.startsWith(kept)) continue;
    const [start, index, extra] = path.slice(prefix.length).split("/");
    if (extra !== undefined || !/^\d+$/.test(start || "") || !/^\d+$/.test(index || "")) continue;
    const offset = Number(index) * pin.size;
    const partBytes = state.partBytes ?? asset.size_bytes;
    if (Number(start) % partBytes || offset < Number(start) || offset >= Math.min(asset.size_bytes, Number(start) + partBytes)) continue;
    try {
      const file = await candidateFile(drive, path);
      if (file?.size === Math.min(pin.size, asset.size_bytes - offset) &&
          await pin.matches(Number(index), new Uint8Array(await file.arrayBuffer()))) await removeFile(drive, path);
      removed.add(path);
    } catch (error) {
      diag("cleanup-error", {asset: asset.id, error: error.message});
    }
  }
  if (removed.size) state.owned = state.owned.filter(path => !removed.has(path));
}

async function transferRangedPart(asset, part, writable, options) {
  const {whole, expectedHash, signal, last, onBytes, ranged, journal, writeOffset = 0} = options;
  const hash = part.start ? sha256.create() : null, next = whole.clone();
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
      hash?.update(bytes);
      next.update(bytes);
    }
  });
  const digest = bytesToHex((hash || next.clone()).digest());
  diag("part-writes", {asset: asset.id, start: part.start, mb: +(part.bytes / 1e6).toFixed(1),
    journalMs: Math.round(journalMs), partMs: Math.round(partMs)});
  if (total !== part.bytes || (expectedHash && digest !== expectedHash)) throw new SourceError("Part SHA-256 or size mismatch");
  if (last && (hash ? bytesToHex(next.clone().digest()) : digest) !== asset.sha256)
    throw new SourceError("Whole-file SHA-256 mismatch", {whole: true});
  signal?.throwIfAborted();
  return {digest, next};
}

async function writePart(drive, asset, part, source, options) {
  options.signal?.throwIfAborted();
  const handle = await fileHandle(drive, part.path, true);
  const writable = await handle.createWritable({mode: "exclusive"});
  let result;
  try {
    result = options.ranged ? await transferRangedPart(asset, part, writable, options) :
      await transferPart(asset, part, source, writable, options);
    const closing = performance.now();
    await writable.close();
    diag("part-close", {asset: asset.id, start: part.start, mb: +(part.bytes / 1e6).toFixed(1),
      ms: Math.round(performance.now() - closing)});
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
  await checkWrittenFile(handle, part.path, {bytes: part.bytes, sha256: result.digest}, options.signal);
  return result;
}

function routesFor(asset, routes, published) {
  const choices = (routes[asset.id] || []).map(url => ({label: new URL(url).hostname, pieces: [{url}]}));
  if (published.files?.[asset.id]?.length) {
    choices.push({label: "library website", pieces: published.files[asset.id]});
  }
  return choices;
}

export function browserSelection(assets, routes, published) {
  const available = [], excluded = [];
  for (const asset of buildOrder(assets)) {
    if (routesFor(asset, routes, published).length) available.push(asset);
    else excluded.push({id: asset.id, title: asset.title, utility_tier: asset.utility_tier ?? null,
      ...(isReaderApp(asset) ? {kind: "app"} : {}),
      reason: asset.redistributable ? "No browser-accessible pinned copy is published." : "Publisher blocks browser downloads and this site cannot host a copy."});
  }
  return {assets: available, excluded};
}

async function forgetParts(drive, state, asset, layout, published, signal) {
  await assertDrive(drive, state);
  for (const [index, part] of layout.entries()) {
    const digest = layout.length === 1 ? asset.sha256 : state.parts[asset.id]?.[index]?.sha256;
    if (state.owned.includes(part.path)) await removePinned(drive, part.path, {bytes: part.bytes, sha256: digest}, signal);
  }
  await prunePieceJournal(drive, state, asset, publisherPin(published.publisherPieces, asset));
  delete state.parts[asset.id];
  delete state.verified[asset.id];
}

// recheckSince: after a sync cut off without Pause, saved parts written at or
// after this time are reread; older ones are trusted by size.
async function buildAsset(drive, state, asset, layout, options) {
  const {published, signal, onProgress, recheckSince} = options;
  const pins = partPins(asset, layout, published, state.partBytes);
  const checkpoints = state.parts[asset.id] ||= [];
  const files = [];
  for (const [i, part] of layout.entries()) {
    signal?.throwIfAborted();
    const saved = checkpoints[i];
    if (!DIGEST.test(saved?.sha256) || saved.bytes !== part.bytes || (pins[i] && pins[i] !== saved.sha256)) break;
    const file = await fileAt(drive, part.path);
    if (file?.size !== part.bytes) break;
    files.push(file);
  }
  let trusted = files.length;
  if (recheckSince !== undefined) {
    for (const [i, file] of files.entries()) {
      if (file.lastModified < recheckSince) continue;
      onProgress({kind: "checking", asset, index: i, count: layout.length});
      if ((await hashFiles([file], asset, signal)).digest !== checkpoints[i].sha256) { trusted = i; break; }
    }
  }
  let whole = sha256.create(), index = 0;
  if (trusted === layout.length) {
    // Saving the last part required the whole-file SHA-256 to match.
    index = trusted;
  } else if (trusted && (whole = restoreHash(checkpoints[trusted - 1].hash, layout[trusted - 1]))) {
    index = trusted;
  } else {
    // Parts saved before the running hash was recorded: rebuild it by rereading them.
    whole = sha256.create();
    for (; index < trusted; index++) {
      onProgress({kind: "checking", asset, index, count: layout.length});
      const restored = await readCheckpoint(files[index], checkpoints[index].sha256, whole, signal);
      if (!restored) break;
      whole = restored;
    }
  }
  const pin = publisherPin(published.publisherPieces, asset);
  await prunePieceJournal(drive, state, asset, pin, layout[index]?.start);
  if (index === layout.length) return;
  checkpoints.length = index;
  delete state.verified[asset.id];
  await save(drive, state);

  const download = partDownloader(drive, state, asset, layout, options);
  for (; index < layout.length; index++) {
    await options.atSavePoint?.();
    const part = layout[index];
    const existed = await candidateFile(drive, part.path);
    let downloaded;
    try {
      downloaded = await download(index, whole, async (source, writeOptions) => {
        try { return await writePart(drive, asset, part, source, writeOptions); }
        catch (error) {
          if (!(error instanceof DriveWriteMismatch)) throw error;
          onProgress({kind: "retrying", asset, index, count: layout.length, message: error.message});
          writeOptions.onBytes(0);
          // Fetch fresh pieces on retry. The journal serves interrupted writes.
          const journal = writeOptions.journal && {persist: writeOptions.journal.persist};
          return writePart(drive, asset, part, source, {...writeOptions, journal});
        }
      });
    }
    catch (error) {
      if (!existed && (error instanceof SourceError || isNoSpace(error))) await removePinned(drive, part.path, emptyPin);
      throw error;
    }
    whole = downloaded.next;
    // Only the newest part keeps the running hash; the last part needs none.
    delete checkpoints.at(-1)?.hash;
    checkpoints.push({sha256: downloaded.digest, bytes: part.bytes,
      ...(index < layout.length - 1 && {hash: hashState(whole)})});
    await save(drive, state);
    // Release the verified part's temporary pieces before reserving the next part.
    await prunePieceJournal(drive, state, asset, pin, layout[index + 1]?.start);
  }
}

const relaySource = (relay, source) => source.pieces.some(piece => relay.isRelay(piece.url));
const deferredRelayIds = state => Array.isArray(state?.relayDeferred) ? state.relayDeferred : [];

function partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network, relay,
    drain, atSavePoint}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const choices = routesFor(asset, routes, published);
  const cooldown = routeCooldowns(network);
  const sources = choices.flatMap(source => source.pieces.map(piece => piece.url));
  const pin = publisherPin(published.publisherPieces, asset);
  const direct = (routes[asset.id] || []).filter(url => !relay.unavailable || !relay.isRelay(url));
  const archiveRelays = published.archiveRelay?.[asset.id] || [];
  let archiveRelayRejected = false;
  async function fetchRange(url, options) {
    if (!archiveRelays.includes(url)) return fetchFile(url, options);
    try {
      const response = await fetchFile(url, options);
      archiveRelayRejected = false;
      relay.answered();
      return response;
    } catch (error) {
      if (!options.signal?.aborted) archiveRelayRejected = true;
      throw error;
    }
  }
  const ranged = pin && direct.length && asset.size_bytes > pin.size ?
    archiveSession(asset, pin, {direct, relay: archiveRelays, relayReady: () => !relay.unavailable,
      refreshRelay: () => relay.refresh?.(), onRoute: route => onProgress({kind: "route", asset, ...route}),
      drain, atSavePoint, onInflight: () => reportInflight(), fetchFile: fetchRange, signal, network}) : null;
  let preferred = (state.sourceOffsets?.[asset.id] || 0) % (choices.length || 1);
  let reportInflight = () => {};
  return async (index, whole, write) => {
    signal?.throwIfAborted();
    const part = layout[index];
    const progress = {asset, index, count: layout.length};
    const range = layout.length === 1 ? null : {start: part.start, end: part.start + part.bytes - 1, total: asset.size_bytes};
    const failures = new Set();
    if (ranged) {
      checkAlignment(pin, asset, part);
      const journal = await pieceJournal(drive, state, asset, part, pin);
      // Journaled pieces survive a pause; only pieces still arriving are lost.
      let accepted = 0;
      const notify = received => {
        accepted = received;
        onProgress({kind: "downloading", ...progress, received, bytes: part.bytes, ...ranged.inflight()});
      };
      reportInflight = () => notify(accepted);
      notify(0);
      await assertDrive(drive, state);
      let result, failure;
      try {
        result = await write(null, {ranged, journal, pieceSize: pin.size, whole, signal,
          expectedHash: pins[index], last: index === layout.length - 1, onBytes: notify});
      } catch (error) {
        if (!(error instanceof SourceError)) throw error;
        failure = error;
      }
      // Check once per completed transfer, outside the parallel piece fetches.
      const relayRejected = archiveRelayRejected && await relay.observeFailure(asset.id);
      archiveRelayRejected = false;
      if (failure) {
        failure.relayCandidate = archiveRelays.length > 0 && (relay.unavailable || relayRejected);
        throw failure;
      }
      return result;
    }
    const waiting = new Set();
    let wholeMismatch = false, round = 0;
    while (choices.length && round < 2) {
      let connection = false;
      for (let offset = 0; offset < choices.length; offset++) {
        const sourceIndex = (preferred + offset) % choices.length;
        const source = choices[sourceIndex];
        const throughRelay = relaySource(relay, source);
        if (throughRelay && relay.unavailable) { waiting.add(sourceIndex); continue; }
        if (source.pieces.some(piece => cooldown.waiting(piece.url))) continue;
        // A pause discards the unfinished part, so its received bytes are lost.
        const began = performance.now();
        const notify = received => {
          const elapsed = performance.now() - began;
          onProgress({kind: "downloading", ...progress, received, bytes: part.bytes, lost: received,
            toSave: part.bytes - received,
            seconds: received && elapsed >= 500 ? (part.bytes - received) / (received / elapsed) / 1000 : undefined});
        };
        notify(0);
        try {
          await assertDrive(drive, state);
          const result = await write(source, {fetchFile, signal, whole, range,
            expectedHash: pins[index], publisherPieces: published.publisherPieces, last: index === layout.length - 1,
            onBytes: notify});
          if (throughRelay) relay.answered();
          preferred = sourceIndex;
          return result;
        } catch (error) {
          if (!(error instanceof SourceError)) throw error;
          if (throughRelay) {
            if (error.beforeResponse && await relay.observeFailure(asset.id)) waiting.add(sourceIndex);
            else {
              if (!error.beforeResponse) relay.answered();
              waiting.delete(sourceIndex);
            }
          }
          for (const {url} of source.pieces) {
            cooldown.defer(url, error.retryAfterMs ?? (error.status === 429 ? 60_000 : 0));
          }
          wholeMismatch ||= error.whole;
          connection ||= error.connection;
          const message = source.label + " — " + error.message;
          failures.add(message);
          onProgress({kind: "retrying", ...progress, message});
        }
      }
      if ((connection || network.offline()) && await network.waitForConnection()) {
        relay.answered();
        if (!relay.unavailable) waiting.clear();
        continue;
      }
      if (relay.unavailable && waiting.size === choices.length) break;
      if (++round < 2) await cooldown.delay(sources);
    }
    if (wholeMismatch && choices.length > 1) (state.sourceOffsets ||= {})[asset.id] = (preferred + 1) % choices.length;
    const error = new SourceError([...failures].join(". ") || "No browser source is available", {whole: wholeMismatch});
    error.relayCandidate = waiting.size > 0;
    throw error;
  };
}

function joinedLayout(asset) {
  return [{path: "LIBRARY/" + asset.destination, start: 0, bytes: asset.size_bytes}];
}

async function removeSplitParts(drive, state, asset, layout, signal) {
  const installed = new Set(state.installed[asset.id]?.layout.map(part => part.path));
  for (const [index, part] of layout.entries()) {
    const proof = state.parts[asset.id]?.[index];
    if (!installed.has(part.path) && state.owned.includes(part.path) && proof?.bytes === part.bytes) {
      await removePinned(drive, part.path, proof, signal);
    }
  }
}

async function checkJoined(drive, state, asset, layout, {signal}) {
  if (!state.joined[asset.id]) return false;
  const [{path, bytes}] = joinedLayout(asset);
  const file = await fileAt(drive, path);
  if (await matchesFile(file, {bytes, sha256: asset.sha256}, signal)) {
    await removeSplitParts(drive, state, asset, layout, signal);
    return true;
  }
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
    if (bytes > 0 && file?.size === bytes && await matchesFile(file, {bytes, sha256: prefix.sha256}, signal)) {
      // Import the deployed builder's committed prefix without fetching it again.
      const pins = partPins(asset, layout, published, state.partBytes);
      const checkpoints = [];
      const whole = sha256.create();
      onProgress({kind: "checking", asset});
      for (const part of layout.slice(0, prefix.count)) {
        const handle = await fileHandle(drive, part.path, true);
        const writer = await handle.createWritable({mode: "exclusive"});
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
        try { await checkWrittenFile(handle, part.path, {bytes: part.bytes, sha256: sha}, signal); }
        catch (error) {
          if (!(error instanceof DriveWriteMismatch)) throw error;
          break;
        }
        checkpoints.push({sha256: sha, bytes: part.bytes});
      }
      if (checkpoints.length === prefix.count && bytesToHex(whole.digest()) === prefix.sha256) {
        state.parts[asset.id] = checkpoints;
        await save(drive, state);
        await removePinned(drive, path, {bytes, sha256: prefix.sha256}, signal);
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
    await removeSplitParts(drive, state, asset, layout, signal);
    return;
  }
  if (existing?.size) return;
  let writable, written = 0, next = 0;
  const began = performance.now();
  try {
    const handle = await fileHandle(drive, path, true);
    writable = await handle.createWritable({mode: "exclusive"});
    const digest = sha256.create();
    for (const [index, part] of layout.entries()) {
      onProgress({kind: "joining", asset, index, count: layout.length});
      const file = await fileAt(drive, part.path);
      for await (const chunk of file.stream()) {
        signal?.throwIfAborted();
        digest.update(chunk);
        next = written + chunk.byteLength;
        await writable.write(chunk);
        written = next;
      }
    }
    if (bytesToHex(digest.digest()) !== asset.sha256) throw new SourceError("Saved parts failed whole-file SHA-256", {whole: true});
    const closing = performance.now();
    await writable.close();
    diag("join", {asset: asset.id, mb: +(asset.size_bytes / 1e6).toFixed(1),
      copyMs: Math.round(closing - began), closeMs: Math.round(performance.now() - closing)});
    await checkWrittenFile(handle, path, {bytes: asset.size_bytes, sha256: asset.sha256}, signal);
  } catch (error) {
    await writable?.abort().catch(() => {});
    if (!existing || error instanceof DriveWriteMismatch) {
      await removePinned(drive, path, error instanceof DriveWriteMismatch ? error.actual : emptyPin);
    }
    signal?.throwIfAborted();
    if (archiveJoinLimitReached(error, written, next)) {
      state.largeFileLimited = true;
      return;
    }
    if (error instanceof DriveWriteMismatch) return;
    if (isNoSpace(error) || error.name === "InvalidStateError" || /EFBIG|file too large/i.test(error.message)) return;
    throw error;
  }
  state.joined[asset.id] = true;
  try { await save(drive, state); }
  catch (error) {
    if (!isNoSpace(error)) throw error;
    await removePinned(drive, path, {bytes: asset.size_bytes, sha256: asset.sha256}, signal);
    delete state.joined[asset.id];
    return;
  }
  await removeSplitParts(drive, state, asset, layout, signal);
}

function layoutFor(asset, partBytes) {
  return asset.format === "zim" && partBytes === null ? joinedLayout(asset) : partLayout(asset, partBytes);
}

const diskAsset = (asset, destination) => ({...asset, destination});
const bytesOf = rows => rows.reduce((total, row) => total + row.bytes, 0);

function recordedLayout(row, buildId) {
  const {pin, layout} = row;
  if (!pin || !DIGEST.test(pin.sha256) || !managedContent("LIBRARY/" + pin.path) ||
      !Number.isSafeInteger(pin.bytes) || pin.bytes < 1 || !Array.isArray(layout) || !layout.length ||
      !managedContent(layout[0]?.path)) return null;
  const asset = fromPin(pin);
  const destination = layout[0].path.slice("LIBRARY/".length, layout.length > 1 ? -2 : undefined);
  if (!managedDestination(asset, destination, buildId)) return null;
  const file = diskAsset(asset, destination);
  try {
    const expected = layout.length === 1 ? joinedLayout(file) : partLayout(file, layout[0].bytes);
    return layout.length === expected.length && expected.every((part, index) =>
      part.path === layout[index]?.path && part.bytes === layout[index].bytes && part.start === layout[index].start) ? expected : null;
  } catch { return null; }
}

async function removeRecordedContent(drive, state, row, {catalogPaths, previousPins, signal, keep = new Set()}) {
  if (row.protected) return;
  const layout = recordedLayout(row, state.buildId);
  for (const [index, part] of (layout || []).entries()) {
    if (keep.has(part.path) || !state.owned.includes(part.path)) continue;
    const digest = layout.length === 1 ? row.pin.sha256 : row.parts?.[index]?.sha256;
    if (catalogPaths.get(row.pin.id) !== row.pin.path && previousPins.get(part.path) !== digest) continue;
    await removePinned(drive, part.path, {bytes: part.bytes, sha256: digest}, signal);
  }
}

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

// Successful checks in this page session, keyed by checksum, paths, sizes and
// modification times. Opening a paused 1 TB drive and then choosing Sync
// otherwise reads every finished file twice.
// Per drive handle: a copy on another drive with the same names, sizes and
// modification times is still read.
const checkedLayouts = new WeakMap();

// One hashing worker per page, shared by every check; null after it failed
// to start, which leaves hashing on the page as in tests under Node.
let hashWorker, nextHashJob = 0;
const hashJobs = new Map();
function startHashWorker() {
  if (hashWorker !== undefined) return hashWorker;
  hashWorker = null;
  if (typeof Worker !== "function" || typeof document === "undefined") return null;
  try {
    const url = new URL("./hash-worker.mjs" + new URL(import.meta.url).search, import.meta.url);
    hashWorker = new Worker(url, {type: "module"});
  } catch {
    return null;
  }
  hashWorker.onmessage = ({data}) => {
    const job = hashJobs.get(data.id);
    if (!job) return;
    if (data.bytes) job.onBytes(data.bytes);
    if (data.digest || data.error) {
      hashJobs.delete(data.id);
      job.done(data.error ? null : data);
    }
  };
  hashWorker.onerror = () => {
    for (const job of hashJobs.values()) job.done(null);
    hashJobs.clear();
    hashWorker.terminate();
    hashWorker = null;
  };
  return hashWorker;
}

function hashInWorker(files, onBytes, signal) {
  const worker = startHashWorker();
  if (!worker) return null;
  const id = ++nextHashJob;
  return new Promise((resolve, reject) => {
    const abort = () => {
      hashJobs.delete(id);
      worker.postMessage({cancel: id});
      reject(signal.reason);
    };
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener("abort", abort, {once: true});
    hashJobs.set(id, {onBytes, done: result => {
      signal?.removeEventListener("abort", abort);
      resolve(result);
    }});
    worker.postMessage({id, files});
  });
}

async function hashOnPage(files, onBytes, signal) {
  const whole = sha256.create(), parts = [];
  for (const file of files) {
    const hash = files.length > 1 ? sha256.create() : whole;
    for await (const chunk of file.stream()) {
      signal?.throwIfAborted();
      hash.update(chunk);
      if (hash !== whole) whole.update(chunk);
      onBytes(chunk.byteLength);
    }
    parts.push(hash === whole ? null : bytesToHex(hash.digest()));
  }
  const digest = bytesToHex(whole.digest());
  return {digest, parts: parts.map(part => part ?? digest)};
}

// check.sizing: a dry pass that adds up the bytes a real check would read.
// check.progress: called with the bytes read so far in the real check.
async function verifyLayout(drive, asset, layout, signal, {reread = false, check} = {}) {
  const files = [];
  for (const part of layout) {
    const file = await candidateFile(drive, part.path);
    if (file?.size !== part.bytes) return null;
    files.push(file);
  }
  const key = [asset.sha256, ...layout.map((part, index) => part.path + ":" + files[index].size + ":" + files[index].lastModified)].join("|");
  if (!checkedLayouts.has(drive)) checkedLayouts.set(drive, new Map());
  const checked = checkedLayouts.get(drive);
  if (!reread && checked.has(key)) return checked.get(key);
  if (check?.sizing) {
    check.sizing.bytes += asset.size_bytes;
    return layout.map(part => ({sha256: "", bytes: part.bytes}));
  }
  const result = await hashFiles(files, asset, signal, check);
  if (result.digest !== asset.sha256) return null;
  const parts = layout.map((part, index) => ({sha256: result.parts[index], bytes: part.bytes}));
  checked.set(key, parts);
  return parts;
}

async function hashFiles(files, asset, signal, check) {
  let read = 0;
  const onBytes = bytes => { read += bytes; check?.progress?.(bytes, asset); };
  const result = await hashInWorker(files, onBytes, signal);
  if (result) return result;
  check?.progress?.(-read, asset);
  return hashOnPage(files, onBytes, signal);
}

// A sync cut off without Pause (a closed tab, an unplugged drive, a crash)
// can lose only data written shortly before it stopped, which the drive may
// not have stored yet. Its last record save bounds that moment from below.
export const RECENT_WRITES = 10 * 60_000;

// Rereads the files of a finished row written within RECENT_WRITES of the
// last record save, or later, and trusts the older ones by size.
async function verifyRecent(drive, asset, installed, signal, {since, check}) {
  const recent = [];
  for (const [index, part] of installed.layout.entries()) {
    const file = await candidateFile(drive, part.path);
    if (file?.size !== part.bytes) return null;
    // A missing modification time counts as recent.
    if (!(file.lastModified < since)) recent.push({file, part, digest: installed.parts?.[index]?.sha256});
  }
  if (!recent.length) return installed.parts;
  if (!recent.every(row => DIGEST.test(row.digest || ""))) {
    return verifyLayout(drive, asset, installed.layout, signal, {check});
  }
  if (!checkedLayouts.has(drive)) checkedLayouts.set(drive, new Map());
  const checked = checkedLayouts.get(drive);
  for (const {file, part, digest} of recent) {
    const key = digest + "|" + part.path + ":" + file.size + ":" + file.lastModified;
    if (checked.has(key)) continue;
    if (check?.sizing) {
      check.sizing.bytes += file.size;
      continue;
    }
    if ((await hashFiles([file], asset, signal, check)).digest !== digest) return null;
    checked.set(key, true);
  }
  return installed.parts;
}

// Pause, or an error in a live tab while the drive still answers, stops the
// sync after its files were closed or abandoned before publishing. Recording
// that spares the next look at the drive from rereading recent files.
// problem: the error text, kept in the record until the next save.
export async function recordPause(drive, problem) {
  const state = await readBuild(drive);
  if (!state?.pending || state.pausedCleanly && !problem) return;
  state.pausedCleanly = true;
  if (problem) state.lastProblem = {at: new Date().toISOString(), detail: String(problem).slice(0, 2000)};
  await save(drive, state);
}

export async function inspectDrive(drive) {
  const library = await reservedEntry(() => drive.getDirectoryHandle("LIBRARY"), "a file named LIBRARY");
  const start = await reservedEntry(() => fileAt(drive, START_PAGE), "a folder named " + START_PAGE);
  const state = await readBuild(drive);
  // When the record was last saved; a sync cut off without Pause stopped after it.
  const recordModified = state ? (await fileAt(drive, MANIFEST))?.lastModified : undefined;
  const adoption = Boolean(state?.adopting || !state && start);
  const starter = await matchesFile(start, filePin(startPage()));
  let legacy = (adoption && !starter) || state?.migrated || (state && !state.generatedPins) ?
    await publishedReaderFiles(drive) : new Map();
  if (start && !ownsGeneratedFile(state, START_PAGE) && !legacy.has(START_PAGE) && !starter) {
    if (state && !legacy.size) legacy = await publishedReaderFiles(drive);
    if (!legacy.has(START_PAGE)) throw new DrivePathConflict("a different file named " + START_PAGE);
  }
  const installedPaths = Object.values(state?.installed || {}).flatMap(row => row.layout.map(part => part.path));
  const paths = new Set([...(state?.owned || []), ...(state?.generated || []), ...installedPaths].filter(path =>
    safePath(path) && (managedContent(path) || readerPath(path) || path.startsWith("LIBRARY/.owl/download-pieces/") ||
      path === "LIBRARY/.owl/assembly-" + state?.buildId + ".tmp")));
  const sizes = new Map();
  let heldBytes = 0;
  for (const path of paths) {
    const file = await candidateFile(drive, path);
    if (file) {
      sizes.set(path, file.size);
      heldBytes += file.size;
    }
  }
  const availableInstalled = new Set(Object.values(state?.installed || {})
    .filter(row => row.layout.every(part => sizes.get(part.path) === part.bytes)).map(row => row.pin.id));
  let candidates;
  if (adoption && legacy.size) {
    const inventory = await candidateFile(drive, "LIBRARY/INVENTORY.json");
    if (inventory && inventory.size <= 16 * 2 ** 20) {
      const data = JSON.parse(await inventory.text());
      candidates = new Set();
      for (const asset of data.assets || []) {
        if (typeof asset.id !== "string" || typeof asset.destination !== "string" || !DIGEST.test(asset.sha256)) continue;
        const path = "LIBRARY/" + asset.destination.replace(/^LIBRARY\//, "");
        if (!managedContent(path)) continue;
        const file = await candidateFile(drive, path);
        if (legacy.has(path) && file?.size && file.size === (asset.size_bytes ?? asset.bytes)) {
          if (!paths.has(path)) { heldBytes += file.size; paths.add(path); }
          candidates.add(asset.id);
        }
      }
    }
  }
  return {state, recordModified, hasLibrary: Boolean(library), adoption, heldBytes, candidates, legacy, availableInstalled};
}

export class DrivePathConflict extends Error {
  constructor(entry) {
    super("An existing file blocks the library. This drive already has " + entry + ".");
    this.entry = entry;
  }
}

async function reservedEntry(open, conflict) {
  try { return await optional(open); }
  catch (error) {
    if (error.name === "TypeMismatchError") throw new DrivePathConflict(conflict);
    throw error;
  }
}

const readerRevision = (navigation, search, publication) => bytesToHex(sha256(new TextEncoder().encode(
  canonical([navigation, search, publication]))));

async function activeReaderExists(drive, state) {
  if (!(await candidateFile(drive, "START_HERE.html"))?.size) return false;
  return (await Promise.all(state.generated.map(path => readerPath(path) && candidateFile(drive, path)))).every(Boolean);
}

// onCheck({checked, total, asset}) reports a long check of files already on
// the drive. A dry pass first adds up the bytes the check will read.
export async function compareLibrary(drive, options = {}) {
  const {onCheck: report, ...rest} = options;
  if (!report) return compareOnce(drive, rest);
  // A display error must not stop the check.
  const onCheck = value => { try { report(value); } catch (error) { diag("check-progress", {detail: error.message}); } };
  const inspection = rest.inspection || await inspectDrive(drive);
  const sizing = {bytes: 0};
  await compareOnce(drive, {...rest, inspection}, {sizing});
  if (!sizing.bytes) return compareOnce(drive, {...rest, inspection});
  let checked = 0, reported = 0;
  onCheck({checked, total: sizing.bytes});
  return compareOnce(drive, {...rest, inspection}, {progress(bytes, asset) {
    checked = Math.max(0, checked + bytes);
    if (checked - reported < 64 * 2 ** 20 && checked < sizing.bytes) return;
    reported = checked;
    onCheck({checked: Math.min(checked, sizing.bytes), total: sizing.bytes, asset});
  }});
}

async function compareOnce(drive, {assets, choice, catalogVersion, navigation = {}, search, readerPublication, partBytes = PART_BYTES,
    singleArchives = false, joinArchives = false, fat32 = false, fullVerify = false, signal, inspection, freeBytes = Infinity,
    archiveSpace = Infinity} = {}, check) {
  const {state, adoption, legacy, recordModified} = inspection || await inspectDrive(drive);
  // A sync cut off without Pause has its recent files reread.
  const interrupted = state?.pending && !state.relayWaiting && !state.pausedCleanly;
  const since = Number.isFinite(recordModified) ? recordModified - RECENT_WRITES : -Infinity;
  const limit = archiveFileLimit(fat32, singleArchives || joinArchives, state?.largeFileLimited);
  const sameParts = partBytes === state?.partBytes;
  const sameOptions = !state || (sameParts && limit === archiveFileLimit(
    state.fat32, state.singleArchives || state.joinArchives, state.largeFileLimited));
  const adds = [], drops = [], present = [], held = [];
  const planned = new Map(state?.plan.map(pin => [pin.id, pin]));
  let room = freeBytes;
  for (const asset of buildOrder(assets, {archiveSpace, partBytes})) {
    signal?.throwIfAborted();
    const old = state?.installed[asset.id];
    const previous = planned.get(asset.id);
    const split = layoutFor(asset, partBytes).length > 1;
    const mustSplit = (fat32 || state?.largeFileLimited) && asset.format === "zim" && asset.size_bytes > limit;
    const compatible = !split || sameParts;
    const destination = state?.working[asset.id];
    const working = compatible && !(mustSplit && state?.joined?.[asset.id]) &&
      matches(asset, previous) &&
      typeof destination === "string" && managedDestination(asset, destination, state.buildId) && destination;
    let installed = compatible && matches(asset, old?.pin) && !(mustSplit && old.layout.length === 1) ? old : null;
    if (working && state.verified[asset.id] && (!installed || state.pending && state.joined?.[asset.id])) {
      const file = diskAsset(asset, working);
      const layout = state.joined?.[asset.id] ? joinedLayout(file) : layoutFor(file, partBytes);
      installed = {pin: assetPin(asset), asset, layout, parts: state.joined?.[asset.id] ?
        [{sha256: asset.sha256}] : state.parts[asset.id]};
    }
    if (installed && await layoutExists(drive, installed.layout)) {
      const parts = fullVerify ? await verifyLayout(drive, asset, installed.layout, signal, {reread: true, check}) :
        interrupted ? await verifyRecent(drive, asset, installed, signal, {since, check}) : installed.parts;
      if (parts?.length) { present.push({...installed, asset, parts}); continue; }
    }
    // An earlier builder could drop finished files from an unfinished first
    // sync's record. Files OWL wrote are found again by their checksum; a
    // download in progress (saved parts or a staged archive) is left alone.
    const inProgress = Boolean(working && (state.parts[asset.id]?.length || state.stagedArchives?.[asset.id] || state.prefixes?.[asset.id]));
    const ownedPath = Boolean(state?.owned.includes(joinedLayout(asset)[0].path) ||
      state?.owned.includes(layoutFor(asset, partBytes)[0].path));
    if (!old && (!working && !ownedPath || ownedPath && !(working && state.verified[asset.id]) && !inProgress)) {
      const canonical = joinedLayout(asset);
      const split = layoutFor(asset, partBytes);
      const layouts = mustSplit ? [split] : canonical[0].path === split[0].path ? [canonical] : [canonical, split];
      for (const layout of layouts) {
        if (!await layoutExists(drive, layout)) continue;
        const parts = await verifyLayout(drive, asset, layout, signal, {reread: fullVerify, check});
        if (parts) {
          const owned = layout.every((part, index) => legacy.get(part.path) === parts[index].sha256 ||
            state?.owned.includes(part.path));
          present.push({asset, pin: assetPin(asset), layout, parts, protected: !owned});
          installed = true;
          break;
        }
      }
      if (installed === true) continue;
    }
    const savedParts = working && Array.isArray(state.parts[asset.id]) ? state.parts[asset.id] : [];
    const reusable = savedParts.reduce((sum, part) => Number.isSafeInteger(part?.bytes) && part.bytes > 0 ? sum + part.bytes : sum, 0);
    const bytes = Math.max(0, asset.size_bytes - reusable);
    const row = {asset, old, working, bytes, savedBytes: asset.size_bytes - bytes,
      corrupt: Boolean(installed)};
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
  const presentBytes = bytesOf(present.map(row => row.pin)) + adds.reduce((sum, row) => sum + row.savedBytes, 0);
  const joinRoom = Math.min(archiveSpace - presentBytes, freeBytes, limit);
  const joins = present.filter(row => !row.protected && row.layout.length > 1 && row.pin.bytes <= joinRoom);
  const current = Boolean(state?.finished && sameOptions && !adds.length && !drops.length && !joins.length && !changedChoice && !state.migrated &&
    state.catalogVersion === catalogVersion && state.readerRevision === readerRevision(navigation, search, readerPublication) &&
    await activeReaderExists(drive, state));
  return {state, adoption, adds, drops, present, held, joins, changedChoice, current, workCount: adds.length + drops.length,
    addBytes: bytesOf(adds), removeBytes: bytesOf(removes.filter(row => !row.protected).map(row => row.pin)),
    presentBytes};
}

async function reservePaths(drive, state, asset, partBytes, joining) {
  const owned = new Set(state.owned);
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

const readerChecksums = "LIBRARY/SHA256SUMS.txt";
const generationPath = /^LIBRARY\/INDEX\/([a-f0-9]{12})\//;
const readerFiles = /^(?:reader|home|search|search-paths|manifest|rank|rerank|shards|c-(?:health|food|shelter|trades|school|reference|advanced|culture|other))\.js$/;
function readerPath(path) {
  if (!safePath(path)) return false;
  if (path === START_PAGE || path === readerChecksums) return true;
  const generation = generationPath.exec(path);
  if (generation) return readerFiles.test(path.slice(generation[0].length));
  return /^LIBRARY\/(?:INVENTORY\.(?:html|json)|VERIFY\.py|README\.txt|BUILD_INFO\.json|BUILD_REPORT\.html|SOURCE_NOTES\.txt|SEARCH\.html|INDEX\/navigation-report\.json)$/.test(path) ||
    /^LIBRARY\/SEARCH\/(?:(?:search|manifest|rank|shards|model|rerank)\.js|coverage\.json|model-license\.txt|(?:shared|data|chunks)\/[a-f0-9]{64}\.js|sources\/[a-f0-9]{64}\/\d{5}\.js|(?:model|impact|transformer)\/[a-zA-Z0-9.-]+\.(?:js|txt))$/.test(path) ||
    /^LIBRARY\/CRITICAL\/MEDICAL\/WIKIMED-PHONE\/wikimed-[a-z0-9-]+\.pdf$/.test(path);
}

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

export async function publishedReaderFiles(drive) {
  const checksums = await fileAt(drive, readerChecksums);
  if (!checksums || checksums.size > 16 * 2 ** 20) return new Map();
  const pins = await checksumPins(checksums);
  const start = await fileAt(drive, "START_HERE.html");
  if (!start || start.size > 16 * 2 ** 20 || !pins.has("START_HERE.html") ||
      !/offline wandering library/i.test(await start.text()) ||
      !await readCheckpoint(start, pins.get("START_HERE.html"), sha256.create())) return new Map();
  pins.set(readerChecksums, bytesToHex(sha256(new Uint8Array(await checksums.arrayBuffer()))));
  return pins;
}

function ownsGeneratedFile(state, path) {
  return readerPath(path) && state?.generated.includes(path) && Array.isArray(state.generatedPins?.[path]) &&
    state.generatedPins[path].some(pin => Number.isSafeInteger(pin?.bytes) && pin.bytes >= 0 && DIGEST.test(pin.sha256));
}

async function preserveChangedFile(drive, state, path, file, signal) {
  await assertDrive(drive, state);
  const pin = {bytes: file.size, sha256: await storedDigest(file, signal)};
  const extension = path.slice(path.lastIndexOf("."));
  const stem = path.slice(0, -extension.length) + ".changed-" + new Date().toISOString().slice(0, 10) + "-" + pin.sha256.slice(0, 12);
  let copy = stem + extension;
  const existing = await fileAt(drive, copy).catch(error => {
    if (error.name === "TypeMismatchError") return true;
    throw error;
  });
  if (!await matchesFile(existing, pin, signal)) {
    if (existing) {
      copy = stem + "-" + globalThis.crypto.randomUUID() + extension;
      if (await fileAt(drive, copy)) throw Error("An existing file blocks the copy of " + path + ".");
    }
    signal?.throwIfAborted();
    await writeFile(drive, copy, file);
    if (!await matchesFile(await fileAt(drive, copy), pin, signal)) throw Error("Could not verify the copy of " + path + ".");
  }
  if (!await matchesFile(await fileAt(drive, path), pin, signal)) throw Error("The file changed during repair: " + path);
  state.pageRepairs[path] = copy;
  return pin;
}

function guardReader(drive, state, legacy, {fullVerify, signal, beforeReplacing}) {
  return {
    getDirectoryHandle: drive.getDirectoryHandle.bind(drive),
    getFileHandle: drive.getFileHandle.bind(drive),
    async prepareWrite(path, contents) {
      if (!readerPath(path)) throw Error("Invalid generated library path: " + path);
      const file = await candidateFile(drive, path);
      const next = filePin(contents);
      const saved = state.generatedPins[path];
      const proofs = Array.isArray(saved) ? saved : [];
      const previous = [next, ...proofs, {bytes: file?.size, sha256: legacy.get(path)}];
      let current = emptyPin;
      if (file) {
        current = null;
        for (const pin of previous) {
          if (await matchesFile(file, pin, signal)) { current = pin; break; }
        }
        if (!current && fullVerify && ownsGeneratedFile(state, path)) {
          current = await preserveChangedFile(drive, state, path, file, signal);
        }
        if (!current) throw Error("An existing file blocks " + path + ". Choose another library folder.");
      }
      // An interrupted write can leave either the old file or the verified
      // replacement. Persist both pins before changing the published files.
      const known = state.generated.includes(path);
      const unchanged = Boolean(file && current.sha256 === next.sha256);
      if (unchanged && known && proofs.some(pin => pin?.sha256 === next.sha256 && pin.bytes === next.bytes)) return false;
      if (file && !unchanged && beforeReplacing) await beforeReplacing(path, file, next);
      if (!known) state.generated.push(path);
      state.generatedPins[path] = current.sha256 === next.sha256 ? [next] : [current, next];
      await save(drive, state);
      return !unchanged;
    },
    async verifyWrite(path, contents) {
      await assertDrive(drive, state);
      state.generatedPins[path] = [await checkGeneratedWrite(drive, path, contents, signal)];
    }
  };
}

async function publishReplacement(drive, state, legacy, fullVerify, files) {
  const previous = new Map();
  const publishing = guardReader(drive, state, legacy, {fullVerify, async beforeReplacing(path, file, next) {
    previous.set(path, {contents: new Uint8Array(await file.arrayBuffer()), next});
  }});
  try {
    for (const [path, contents] of files) await writeFile(publishing, path, contents);
  } catch (error) {
    // Closing each file is atomic. Restore any changes committed before a later write failed.
    const restoring = guardReader(drive, state, legacy, {fullVerify: false});
    for (const [path, {contents, next}] of [...previous].reverse()) {
      if (await matchesFile(await candidateFile(drive, path), next)) await writeFile(restoring, path, contents);
    }
    throw error;
  }
}

async function recordAdoptedGeneration(drive, state, legacy, signal) {
  for (const [path, digest] of legacy) {
    if (!readerPath(path) || state.generatedPins[path]?.length) continue;
    const file = await candidateFile(drive, path);
    const pin = {bytes: file?.size, sha256: digest};
    if (await matchesFile(file, pin, signal)) {
      if (!state.generated.includes(path)) state.generated.push(path);
      state.generatedPins[path] = [pin];
    }
  }
}

async function removeReaderFile(drive, state, path, signal) {
  if (!readerPath(path)) return false;
  const pins = state.generatedPins[path];
  delete state.generatedPins[path];
  for (const pin of Array.isArray(pins) ? pins : []) {
    if (await matchesFile(await candidateFile(drive, path), pin, signal)) {
      await removeFile(drive, path);
      return true;
    }
  }
  return false;
}

async function retireReaderFiles(drive, state, signal, fullVerify) {
  signal?.throwIfAborted();
  const active = await checksumPins(await fileAt(drive, readerChecksums));
  active.set(readerChecksums, null);
  const generations = new Set();
  for (const path of state.generated) {
    if (active.has(path)) continue;
    signal?.throwIfAborted();
    const repairable = fullVerify && ownsGeneratedFile(state, path);
    let removed = await removeReaderFile(drive, state, path, signal);
    if (!removed && repairable) {
      const changed = await candidateFile(drive, path);
      if (changed) {
        const pin = await preserveChangedFile(drive, state, path, changed, signal);
        await removePinned(drive, path, pin, signal);
        removed = true;
      }
    }
    if (removed) {
      const id = generationPath.exec(path)?.[1];
      if (id) generations.add(id);
    }
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

function beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, fat32, archiveSpace, searchBudget,
    capacityBytes, capacityEstimated, driveFormat}) {
  return {version: 2, buildId: saved?.buildId || globalThis.crypto.randomUUID(), plan: [], excluded: [],
    installed: saved?.installed || map(), working: map(), owned: [...(saved?.owned || [])], generated: [...(saved?.generated || [])],
    generatedPins: Object.assign(map(), saved?.generatedPins), reservePin: saved?.reservePin,
    pageRepairs: Object.assign(map(), saved?.pending ? saved.pageRepairs : undefined),
    parts: map(), verified: map(), joined: map(), prefixes: map(), stagedArchives: map(), sourceOffsets: map(),
    dropped: map(), failures: map(), partBytes, joinArchives, singleArchives, fat32, archiveSpace,
    choice, catalogVersion, searchBudget, capacityBytes, capacityEstimated, driveFormat: driveFormat ?? saved?.driveFormat,
    pending: true, finished: false, migrated: saved?.migrated,
    syncedAt: saved?.syncedAt, readerRevision: saved?.readerRevision, largeFileLimited: saved?.largeFileLimited};
}

export async function reconcile(drive, options) {
  const {assets, routes = {}, published = {}, fetchFile = globalThis.fetch, signal, onProgress = () => {}, drain,
    catalogAssets = assets, prepareSources, freeBytes = Infinity,
    network = createNetwork({fetchFile, signal, onWaiting: () => onProgress({kind: "waiting-network"})})} = options;
  let inspection = await inspectDrive(drive);
  const relay = createRelayWait({routes, archives: published.archiveRelay, assets: catalogAssets, fetchFile, network, signal});
  const target = new Set(assets.map(asset => asset.id));
  if (deferredRelayIds(inspection.state).some(id => target.has(id))) await relay.resume();
  const originalHeld = inspection.heldBytes;
  // After Pause asks to keep the current download (drain), stop where nothing
  // downloaded would be lost and wait there until the pause aborts the sync.
  const atSavePoint = async () => {
    if (!drain?.aborted || !signal) return;
    diag("save-point");
    onProgress({kind: "save-point"});
    if (!signal.aborted) await new Promise(resolve => signal.addEventListener("abort", resolve, {once: true}));
    signal.throwIfAborted();
  };
  let prepared, continuing = false;
  for (;;) {
    const result = await reconcilePass(drive, {...options, inspection, relay, continuing, network, atSavePoint,
      freeBytes: Math.max(0, freeBytes + originalHeld - inspection.heldBytes),
      prepareSources: prepareSources && (assetsToFetch => prepared ??= prepareSources(assetsToFetch))});
    signal?.throwIfAborted();
    if (!result.state.relayDeferred?.length) return result;
    await relay.wait(onProgress);
    inspection = await inspectDrive(drive);
    continuing = true;
  }
}

async function reconcilePass(drive, {assets, excluded = [], routes = {}, published = {}, navigation = {}, search,
    partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal, onProgress = () => {}, fullVerify = false,
    joinArchives = false, singleArchives = false, fat32 = false, archiveSpace = Infinity, choice, catalogVersion, readerPublication,
    freeBytes = Infinity, capacityBytes, capacityEstimated, driveFormat, replaceInPlace = [], searchBudget = 16 * 2 ** 20,
    catalogAssets = assets, prepareSources, onPublished, inspection, relay, continuing, network, drain, atSavePoint}) {
  const saved = inspection.state;
  if (!assets.some(isKnowledgeFile)) throw Error("Choose knowledge files with browser-accessible sources.");
  // Saved parts to reread before resuming: all for Check every file, recent ones after a cut-off sync.
  const recheckSince = fullVerify ? -Infinity : saved?.pending && !saved.relayWaiting && !saved.pausedCleanly ?
    (Number.isFinite(inspection.recordModified) ? inspection.recordModified - RECENT_WRITES : -Infinity) : undefined;
  choice ??= saved?.choice || {kind: "recommended", split: !singleArchives && !joinArchives};
  const revision = readerRevision(navigation, search, readerPublication);
  const comparison = await compareLibrary(drive, {assets, choice, catalogVersion, navigation, search, readerPublication,
    partBytes, singleArchives, joinArchives, fat32, fullVerify, signal, inspection, freeBytes, archiveSpace,
    onCheck: value => onProgress({kind: "checking", ...value})});
  const resuming = saved?.pending && !comparison.changedChoice && catalogVersion === saved.catalogVersion;
  const state = beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, fat32, archiveSpace, driveFormat,
    capacityBytes: capacityBytes ?? saved?.capacityBytes, capacityEstimated: capacityEstimated ?? saved?.capacityEstimated,
    searchBudget: resuming ? Math.min(saved.searchBudget ?? searchBudget, searchBudget) : searchBudget});
  const fileLimit = () => archiveFileLimit(fat32, singleArchives || joinArchives, state.largeFileLimited);
  const {legacy} = inspection;
  const guardedDrive = guardReader(drive, state, legacy, {fullVerify, signal});
  const previousPins = legacy.size ? legacy : saved ? await publishedReaderFiles(drive) : new Map();
  const keepPublished = Boolean(saved?.syncedAt || previousPins.has(START_PAGE));
  const catalogPaths = new Map(catalogAssets.map(asset => [asset.id, asset.destination]));
  const retirement = {catalogPaths, previousPins, signal};
  state.adopting = comparison.adoption && legacy.size > 0;
  const held = new Set(comparison.held.filter(row => !replaceInPlace.includes(row.asset.id) || row.old.protected).map(row => row.asset.id));
  const present = new Map(comparison.present.map(row => [row.pin.id, row]));
  const additions = new Map(comparison.adds.map(row => [row.asset.id, row]));
  const ordered = buildOrder(assets, {archiveSpace, partBytes});
  state.plan = ordered.map(assetPin);
  state.excluded = excluded;
  if (continuing) {
    Object.assign(state.failures, saved.failures);
    Object.assign(state.dropped, saved.dropped);
  }
  const deferred = new Set(relay.unavailable ? deferredRelayIds(saved).filter(id => additions.has(id)) : []);
  const relayCandidates = new Map();
  const onlyRelay = asset => {
    const sources = routesFor(asset, routes, published);
    return sources.length && sources.every(source => relaySource(relay, source));
  };
  let relayConfirmed = false;
  const recordDeferrals = () => {
    if (relay.unavailable) {
      if (!relayConfirmed) {
        for (const {asset} of additions.values()) {
          if (!present.has(asset.id) && !state.failures[asset.id] && !state.dropped[asset.id] && onlyRelay(asset)) {
            deferred.add(asset.id);
          }
        }
        relayConfirmed = true;
      }
      for (const id of relayCandidates.keys()) deferred.add(id);
    }
    state.relayDeferred = [...deferred];
  };
  recordDeferrals();
  const workingFields = ["parts", "verified", "joined", "prefixes", "stagedArchives", "sourceOffsets"];
  for (const asset of ordered) {
    const row = additions.get(asset.id);
    const installed = present.get(asset.id);
    const destination = saved?.working[asset.id];
    // Finished files of an unfinished sync keep their record from the first
    // save on. Starting with an empty record lost them at the next pause.
    const recorded = installed && installed.layout === saved?.installed[asset.id]?.layout;
    const reusing = destination && installed && !recorded &&
      (installed.layout[0].path === "LIBRARY/" + destination ||
      installed.layout.length > 1 && installed.layout[0].path === "LIBRARY/" + destination + "aa");
    if (row?.working || reusing) {
      state.working[asset.id] = row?.working || destination;
      for (const field of workingFields) {
        if (saved[field]?.[asset.id] !== undefined) state[field][asset.id] = saved[field][asset.id];
      }
    } else if (installed && !recorded && !installed.protected) {
      // Found again by checksum after the record lost it.
      const path = installed.layout[0].path.slice("LIBRARY/".length);
      state.working[asset.id] = installed.layout.length > 1 ? path.slice(0, -2) : path;
      if (installed.layout.length === 1 && layoutFor(asset, partBytes).length > 1) state.joined[asset.id] = true;
    }
    if (installed && !recorded && state.working[asset.id]) {
      state.verified[asset.id] = true;
      state.parts[asset.id] = installed.parts;
    }
  }
  onProgress({kind: "plan", files: ordered.map(asset => ({id: asset.id, bytes: asset.size_bytes,
    done: present.has(asset.id), savedBytes: additions.get(asset.id)?.savedBytes || 0}))});
  const starter = startPage();
  const start = await fileAt(drive, "START_HERE.html");
  if (start && await matchesFile(start, filePin(starter))) {
    if (!state.generated.includes("START_HERE.html")) state.generated.push("START_HERE.html");
    state.generatedPins["START_HERE.html"] = [filePin(starter)];
  }
  if (saved) {
    await save(drive, state);
    if (!start?.size) await writeFile(guardedDrive, START_PAGE, starter);
  } else {
    if (await readBuild(drive)) throw Error("Another sync started on this drive.");
    if (!start) {
      await drive.getDirectoryHandle("LIBRARY", {create: true});
      await writeFile(drive, START_PAGE, starter);
      await checkGeneratedWrite(drive, START_PAGE, starter, signal);
      state.generated.push("START_HERE.html");
      state.generatedPins["START_HERE.html"] = [filePin(starter)];
    }
    await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n");
  }
  let unavailableSupport = [];
  let archivesWithoutMetadata = new Set();
  if (prepareSources) {
    const support = await prepareSources(comparison.adds.map(({asset}) => asset));
    search = support.search;
    unavailableSupport = support.unavailableSupport || [];
    archivesWithoutMetadata = support.archivesWithoutMetadata || archivesWithoutMetadata;
    published = {...published, publisherPieces: support.publisherPieces ?? published.publisherPieces};
  }
  const reservePath = "LIBRARY/.owl/assembly-" + state.buildId + ".tmp";
  const releaseReserve = async () => {
    if (!state.owned.includes(reservePath)) return;
    const file = await candidateFile(drive, reservePath);
    if (state.reservePin && (await matchesFile(file, state.reservePin) || await matchesFile(file, emptyPin))) {
      await removeFile(drive, reservePath);
    }
    state.owned = state.owned.filter(path => path !== reservePath);
    delete state.reservePin;
  };
  await releaseReserve();
  if (await candidateFile(drive, reservePath)) throw Error("An existing file blocks the assembly reserve.");
  const reserveBytes = assemblyReserve({assets, excluded, navigation, search, searchBudget: state.searchBudget,
    partCount: asset => layoutFor(asset, partBytes).length});
  const reserve = new Uint8Array(reserveBytes);
  const reserveFilePin = filePin(reserve);
  state.owned.push(reservePath);
  state.reservePin = reserveFilePin;
  await save(drive, state);
  let reserved = false;
  try {
    await writeFile(drive, reservePath, reserve);
    reserved = true;
  } catch (error) {
    await removePinned(drive, reservePath, emptyPin);
    await releaseReserve();
    if (!isNoSpace(error)) throw error;
  }
  let used = comparison.presentBytes;
  let free = freeBytes;
  let full = false;
  const downloaded = new Map(), incomplete = new Map(), toJoin = [];
  try {
    for (const [position, asset] of ordered.entries()) {
      signal?.throwIfAborted();
      const report = event => onProgress({...event, position, total: ordered.length});
      const row = additions.get(asset.id);
      if (present.has(asset.id)) {
        const row = present.get(asset.id);
        state.verified[asset.id] = true;
        state.parts[asset.id] = row.parts;
        if (row.layout.length === 1 && layoutFor(asset, partBytes).length > 1) {
          state.joined[asset.id] = true;
          if (!row.protected) state.working[asset.id] = row.layout[0].path.slice("LIBRARY/".length);
        }
        report({kind: "verified", asset});
        continue;
      }
      used -= row.savedBytes;
      deferred.delete(asset.id);
      if (continuing && (state.failures[asset.id] || state.dropped[asset.id])) continue;
      if (archivesWithoutMetadata.has(asset.id)) {
        state.failures[asset.id] = "Could not load the checksums for this encyclopedia. Sync can try it again.";
        report({kind: "failed", asset, message: state.failures[asset.id]});
        continue;
      }
      if (full && asset.utility_tier !== "CRITICAL") {
        state.dropped[asset.id] = noSpace;
        report({kind: "dropped", asset, message: noSpace});
        continue;
      }
      if (held.has(asset.id)) {
        state.failures[asset.id] = "The replacement needs more free space beside the existing copy.";
        report({kind: "failed", asset, message: state.failures[asset.id]});
        continue;
      }
      if (relay.unavailable && onlyRelay(asset)) {
        deferred.add(asset.id);
        continue;
      }
      await atSavePoint?.();
      const joining = asset.format === "zim" && asset.size_bytes <= fileLimit();
      const file = row.working ? diskAsset(asset, row.working) : await reservePaths(drive, state, asset, partBytes, joining);
      const layout = layoutFor(file, partBytes);
      const single = (singleArchives || fat32) && joining && layout.length > 1;
      if (joining && layout.length > 1) {
        const path = joinedLayout(file)[0].path;
        if (!state.owned.includes(path)) {
          if (await fileAt(drive, path)) throw Error("An existing file blocks the archive. Choose another library folder.");
          state.owned.push(path);
        }
      }
      const replacement = replaceInPlace.includes(asset.id) && comparison.held.includes(row) && !row.old.protected;
      const options = {routes, published, fetchFile, signal, onProgress: report, network, relay, drain, atSavePoint, recheckSince};
      const download = async () => {
        await save(drive, state);
        if (replacement && state.installed[asset.id]) {
          await removeRecordedContent(drive, state, row.old, retirement);
        }
        const wasStaged = state.stagedArchives[asset.id];
        if (!await checkJoined(drive, state, file, layout, options)) {
          if (single && !wasStaged) await prepareSingleArchive(drive, state, file, layout, options);
          if (state.joined[asset.id]) await removeSplitParts(drive, state, file, layout, signal);
          else {
            await buildAsset(drive, state, file, layout, options);
            // Parts are combined after every download, in the pass before assembly.
            if (joining && layout.length > 1) toJoin.push(asset.id);
          }
        }
        delete state.stagedArchives[asset.id];
        used += asset.size_bytes;
        free -= row.bytes;
        state.verified[asset.id] = true;
        const savedLayout = state.joined[asset.id] ? joinedLayout(file) : layout;
        const installed = {asset, pin: assetPin(asset), layout: savedLayout,
          parts: state.joined[asset.id] ? [{sha256: asset.sha256, bytes: asset.size_bytes}] : state.parts[asset.id]};
        present.set(asset.id, installed);
        downloaded.set(asset.id, installed);
        report({kind: "verified", asset});
      };
      try {
        try { await download(); }
        catch (error) {
          if (!reserved || asset.utility_tier !== "CRITICAL" || !isNoSpace(error)) throw error;
          await releaseReserve();
          reserved = false;
          full = true;
          await download();
        }
      } catch (error) {
        signal?.throwIfAborted();
        if (isNoSpace(error)) {
          full = true;
          await releaseReserve();
          reserved = false;
          if (!(layout.length > 1 && publisherPin(published.publisherPieces, asset))) {
            await forgetParts(drive, state, file, layout, published, signal);
            delete state.stagedArchives[asset.id];
          }
          incomplete.set(asset.id, {file, layout});
          state.dropped[asset.id] = noSpace;
          report({kind: "dropped", asset, message: state.dropped[asset.id]});
        } else if (error instanceof DriveWriteMismatch) {
          state.failures[asset.id] = error.message;
          report({kind: "failed", asset, message: error.message});
        } else if (error instanceof SourceError) {
          if (error.whole) await forgetParts(drive, state, file, layout, published, signal);
          if (error.relayCandidate) relayCandidates.set(asset.id, {asset, message: error.message, report});
          else {
            state.failures[asset.id] = error.message;
            report({kind: "failed", asset, message: error.message});
          }
        } else throw error;
      }
      recordDeferrals();
      try { await save(drive, state); }
      catch (error) {
        if (!reserved || !isNoSpace(error)) throw error;
        await releaseReserve();
        reserved = false;
        full = true;
        await save(drive, state);
      }
    }
  } catch (error) {
    recordDeferrals();
    if (!signal?.aborted || !deferred.size) throw error;
  } finally { await releaseReserve(); }
  recordDeferrals();
  let paused = Boolean(signal?.aborted && deferred.size);
  if (!paused) signal?.throwIfAborted();
  if (!relay.unavailable) for (const {asset, message, report} of relayCandidates.values()) {
    state.failures[asset.id] = message;
    report({kind: "failed", asset, message});
  }
  if (deferred.size) {
    state.relayWaiting = true;
    await save(drive, state);
    // The working plan and its checkpoints live in the browser record.
    // Leave the published reader and checksums alone while the relay is down.
    if (keepPublished) return {state};
  }
  // Combine split archives, those already on the drive and those this sync
  // downloaded, once every download is done. Leave the old parts available to
  // the published reader until the new start page and checksum list are in place.
  const splitRows = [...comparison.present, ...toJoin.map(id => present.get(id)).filter(row => row?.layout.length > 1)];
  if (fileLimit() && !full && !deferred.size) for (const row of splitRows) {
    if (row.protected || row.layout.length < 2 ||
        row.pin.bytes > Math.min(archiveSpace - used, free, fileLimit())) continue;
    const file = diskAsset(row.asset, row.layout[0].path.slice("LIBRARY/".length, -2));
    const [{path}] = joinedLayout(file);
    const existing = await candidateFile(drive, path);
    if (existing && !(existing.size === row.pin.bytes &&
        await readCheckpoint(existing, row.pin.sha256, sha256.create(), signal))) continue;
    if (!state.owned.includes(path)) state.owned.push(path);
    state.working[file.id] = file.destination;
    await save(drive, state);
    try {
      await joinParts(drive, state, file, row.layout, {signal, onProgress});
    } catch (error) {
      if (!(error instanceof SourceError)) throw error;
      // Reconciliation will repair this archive on a full check.
      state.failures[file.id] = error.message;
      delete state.verified[file.id];
      present.delete(file.id);
    }
    if (!state.joined[file.id]) continue;
    free -= existing?.size === row.pin.bytes ? 0 : row.pin.bytes;
    const parts = [{sha256: row.pin.sha256, bytes: row.pin.bytes}];
    state.parts[file.id] = parts;
    present.set(file.id, {...row, layout: joinedLayout(file), parts});
    if (downloaded.has(file.id)) downloaded.set(file.id, present.get(file.id));
  }
  if (excluded.length || deferred.size || Object.keys(state.failures).length || Object.keys(state.dropped).length) {
    for (const old of Object.values(state.installed)) {
      if (!present.has(old.pin.id) && !additions.get(old.pin.id)?.corrupt && await layoutExists(drive, old.layout)) present.set(old.pin.id, old);
    }
  }
  onProgress({kind: "assembling"});
  if (legacy.size && !paused) {
    // Keep ownership available on retry even if assembly replaces the old checksum list.
    await recordAdoptedGeneration(drive, state, legacy, signal);
    await save(drive, state);
  }
  const syncedAt = new Date().toISOString();
  const apps = new Set([...catalogAssets, ...assets].filter(isReaderApp).map(asset => asset.id));
  const missingApp = row => row.kind === "app" || apps.has(row.id);
  let completed, missing, keptInParts, searchWarnings, supportMissing, compact = paused, keptPublished;
  const retainPublished = async () => {
    state.updateSupportMissing = supportMissing;
    await save(drive, state);
    return {state, completed, missing, keptInParts, searchWarnings, supportMissing, keptPublished: true, repairedPages: []};
  };
  for (;;) {
    completed = [...present.values()].map(row => row.asset);
    const omissions = [...excluded, ...ordered.flatMap(asset => {
      const reason = deferred.has(asset.id) ? RELAY_WAIT_REASON : state.dropped[asset.id] || state.failures[asset.id] ||
        (paused && !present.has(asset.id) ? "Sync paused before this file arrived." : "");
      return reason ? [{id: asset.id, title: asset.title, utility_tier: asset.utility_tier ?? null, reason}] : [];
    })];
    missing = omissions.filter(row => !missingApp(row));
    const missingApps = omissions.filter(missingApp).map(({id, title, reason}) => ({kind: "app", id, title, reason}));
    keptInParts = [...present.values()].filter(row => row.layout.length > 1)
      .map(({asset, layout}) => ({id: asset.id, title: asset.title, parts: layout.length}));
    const before = new Set(state.generated);
    const assemblySignal = paused ? undefined : signal;
    const assemblyDrive = paused ? guardReader(drive, state, legacy, {fullVerify, signal: assemblySignal}) : guardedDrive;
    try {
      ({warnings: searchWarnings, supportMissing, keptPublished} = await assembleLibrary(assemblyDrive,
        {completed, missing, keptInParts, compact, unavailableSupport: [...unavailableSupport, ...missingApps],
        searchMissing: compact && Boolean(search),
        selectedCount: assets.length + excluded.length - missingApps.length, navigation, search: compact ? undefined : search,
        layouts: new Map([...present].map(([id, row]) => [id, row.layout])),
        parts: Object.fromEntries([...present].map(([id, row]) => [id, row.parts])),
        searchBudget: state.searchBudget, fetchFile, signal: assemblySignal, network, syncedAt, onPublished,
        publishReplacement: keepPublished ? files => publishReplacement(drive, state, legacy, fullVerify, files) : undefined}));
      if (keptPublished) return retainPublished();
      break;
    } catch (error) {
      if (!paused && signal?.aborted && deferred.size) {
        paused = compact = true;
        continue;
      }
      assemblySignal?.throwIfAborted();
      if (!isNoSpace(error)) throw error;
      for (const path of state.generated) if (!before.has(path)) await removeReaderFile(drive, state, path, assemblySignal);
      state.generated = [...before];
      if (incomplete.size) {
        for (const {file, layout} of incomplete.values()) await forgetParts(drive, state, file, layout, published, assemblySignal);
        incomplete.clear();
        continue;
      }
      const lowest = [...downloaded.values()].at(-1);
      if (!compact && (!lowest || lowest.asset.utility_tier === "CRITICAL" ||
          isKnowledgeFile(lowest.asset) && completed.filter(isKnowledgeFile).length === 1)) {
        compact = true;
        continue;
      }
      if (!lowest) {
        if (!keepPublished) throw error;
        const issue = {kind: "reader", title: "Full reader", reason: "The drive ran out of space."};
        supportMissing = [...unavailableSupport, ...missingApps, issue];
        searchWarnings = supportMissing.map(({title, reason}) => title + " — " + reason);
        return retainPublished();
      }
      const {asset, layout} = lowest;
      await forgetParts(drive, state, asset, layout, published, assemblySignal);
      delete state.joined[asset.id];
      downloaded.delete(asset.id);
      present.delete(asset.id);
      state.dropped[asset.id] = noSpace;
      onProgress({kind: "dropped", asset, message: noSpace});
    }
  }
  // The start page now points to the new reader, and the checksum list includes reused shards.
  await retireReaderFiles(drive, state, deferred.size ? undefined : signal, fullVerify);
  const recorded = new Set(state.owned);
  for (const row of present.values()) {
    if (row.protected) continue;
    for (const part of row.layout) recorded.add(part.path);
  }
  state.owned = [...recorded];
  const finished = !deferred.size && !missing.length && completed.some(isKnowledgeFile) && !searchWarnings.length;
  state.syncedAt = syncedAt;
  state.readerRevision = revision;
  state.keptInParts = keptInParts;
  if (finished) {
    await save(drive, state);
    const keep = new Set([...present.values()].flatMap(row => row.layout.map(part => part.path)));
    for (const row of Object.values(state.installed)) {
      signal?.throwIfAborted();
      await removeRecordedContent(drive, state, row, {...retirement, keep});
    }
    state.owned = state.owned.filter(path => keep.has(path));
    state.migrated = false;
    state.adopting = false;
  }
  state.installed = Object.fromEntries(present);
  const repairedPages = Object.entries(state.pageRepairs)
    .filter(([path, copy]) => readerPath(path) && safePath(copy))
    .map(([path, copy]) => state.generated.includes(path) ? {path, copy} : {path, copy, retired: true});
  if (!deferred.size) {
    delete state.pageRepairs;
    delete state.relayDeferred;
  }
  if (deferred.size) state.relayWaiting = true;
  state.pending = deferred.size > 0;
  state.finished = finished;
  await save(drive, state);
  return {state, completed, missing, keptInParts, searchWarnings, supportMissing, repairedPages};
}

export {reconcile as buildLibrary};
