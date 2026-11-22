import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, removeTree, writeFile} from "./drive.mjs";
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

async function start(drive, {assets, excluded, partBytes, joinArchives, searchBudget, singleArchives, archiveSpace}) {
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
  const ordered = buildOrder(assets);
  if (singleArchives) {
    // Place large archives early so their committed prefixes fit alongside a swap.
    ordered.sort((a, b) => Number(b.format === "zim" && b.size_bytes > partBytes) * b.size_bytes -
      Number(a.format === "zim" && a.size_bytes > partBytes) * a.size_bytes);
  }
  const state = {version: 1, buildId: globalThis.crypto.randomUUID(), partBytes, joinArchives, searchBudget,
    singleArchives, archiveSpace, prefixes: {}, joined: {},
    plan: ordered.map(assetPin), excluded, parts: {}, verified: {}, dropped: {}, failures: {}, finished: false};
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

// Closed piece files are the chunk journal. Their contents are checked against
// the publisher's digest before reuse, including after an unrecorded swap close.
async function pieceJournal(drive, asset, part, pin) {
  const root = await (await drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle(".owl");
  const downloads = await root.getDirectoryHandle("download-pieces", {create: true});
  const directory = await downloads.getDirectoryHandle(asset.id, {create: true});
  const segment = await directory.getDirectoryHandle(String(part.start), {create: true});
  return {
    async restore(index, length) {
      const file = await optional(async () => (await segment.getFileHandle(String(index))).getFile());
      if (file?.size !== length) return null;
      const bytes = new Uint8Array(await file.arrayBuffer());
      return await pin.matches(index, bytes) ? bytes : null;
    },
    persist: (index, bytes) => writeFile(segment, String(index), bytes)
  };
}

// Cleanup frees journal space but must never stop a build: on exFAT, macOS
// AppleDouble "._" files made a recursive delete fail mid-build with
// NotFoundError. Remove entry by entry and report failures to diagnostics.
async function prunePieceJournal(drive, asset, keep) {
  try {
    const downloads = await optional(async () => {
      const library = await drive.getDirectoryHandle("LIBRARY");
      const root = await library.getDirectoryHandle(".owl");
      return root.getDirectoryHandle("download-pieces");
    });
    if (!downloads) return;
    const directory = await optional(() => downloads.getDirectoryHandle(asset.id));
    if (!directory) return;
    if (keep === undefined) await removeTree(downloads, asset.id);
    else {
      const names = [];
      for await (const entry of directory.values()) names.push(entry.name);
      for (const name of names) {
        if (name !== String(keep) && !name.startsWith("._")) await removeTree(directory, name);
      }
    }
  } catch (error) {
    diag("cleanup-error", {asset: asset.id, keep, error: error.name + ": " + error.message});
  }
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
  await prunePieceJournal(drive, asset);
  delete state.parts[asset.id];
  delete state.verified[asset.id];
}

async function buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, fullVerify, network, archiveJournal}) {
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
  await prunePieceJournal(drive, asset, layout[index]?.start);
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

  const download = partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network, archiveJournal});
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
    // Deleting a finished part's 256 piece files took about 20 s on the owner's
    // USB drive and held up the next part. Run it beside the next part, keeping
    // that part's own journal; cleanup failures only reach diagnostics.
    void prunePieceJournal(drive, asset, layout[index + 1]?.start);
  }
}

function partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network, archiveJournal}) {
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
      const journal = archiveJournal ? await pieceJournal(drive, asset, part, pin) : null;
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

// Chromium copies existing file data into a new on-volume swap. Before
// reopening, cap the committed prefix so prefix + final swap can fit.
export function archiveCheckpoints(bytes, partBytes, available) {
  const maxParts = Math.max(0, Math.floor(Math.min(available - bytes, bytes / 2) / partBytes));
  const checkpoints = [];
  for (let part = 1; part < maxParts; part *= 4) checkpoints.push(part);
  if (maxParts) checkpoints.push(maxParts);
  return checkpoints;
}

async function buildSingleArchive(drive, state, asset, layout, available, options) {
  const {signal, fullVerify} = options;
  const [{path}] = joinedLayout(asset);
  const prefix = state.prefixes[asset.id];
  const file = await fileAt(drive, path);
  let whole = sha256.create(), index = 0;
  if (file?.size === asset.size_bytes &&
      await readCheckpoint(file, asset.sha256, sha256.create(), signal)) {
    state.joined[asset.id] = true;
    delete state.prefixes[asset.id];
    return;
  }
  const start = prefix && layout[prefix.count]?.start;
  if (start > 0 && file?.size >= start) {
    const prefixData = file.slice(0, start);
    const restored = file.size === start && !fullVerify && restoreHash(prefix.hashState, start) ||
      await readCheckpoint(prefixData, prefix.sha256, sha256.create(), signal);
    if (restored) {
      if (file.size !== start) {
        // A previous close may have committed more bytes before the journal
        // was saved. Keep the verified prefix and discard the unknown tail.
        const writer = await (await fileHandle(drive, path)).createWritable({mode: "exclusive"});
        try {
          for await (const bytes of prefixData.stream()) {
            signal?.throwIfAborted();
            await writer.write(bytes);
          }
          await writer.close();
        } catch (error) {
          await writer.abort().catch(() => {});
          throw error;
        }
      }
      whole = restored;
      index = prefix.count;
    }
  }
  if (!index) {
    await removeFile(drive, path);
    delete state.prefixes[asset.id];
  }
  const download = partDownloader(drive, state, asset, layout, options);
  const checkpoints = new Set(archiveCheckpoints(asset.size_bytes, state.partBytes, available));
  let writable;
  try {
    while (index < layout.length) {
      writable = await (await fileHandle(drive, path, true)).createWritable({mode: "exclusive", keepExistingData: index > 0});
      do {
        const part = layout[index];
        const downloaded = await download(index, whole, async (source, transfer) => {
          if (transfer.ranged) return transferRangedPart(asset, part, writable, {...transfer, writeOffset: part.start});
          await writable.seek(part.start);
          return transferPart(asset, part, source, writable, transfer);
        });
        whole = downloaded.next;
        index++;
      } while (index < layout.length && !checkpoints.has(index));
      await writable.close();
      writable = null;
      if (index < layout.length) {
        state.prefixes[asset.id] = {count: index, sha256: bytesToHex(whole.clone().digest()),
          hashState: hashCheckpoint(whole)};
      } else {
        state.joined[asset.id] = true;
        delete state.prefixes[asset.id];
      }
      await save(drive, state);
    }
  } catch (error) {
    await writable?.abort().catch(() => {});
    throw error;
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

async function stageSingleArchive(drive, state, asset, layout, {signal, onProgress, published}) {
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
    await removeSplitParts(drive, layout);
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
  await removeSplitParts(drive, layout);
}

export async function buildLibrary(drive, {assets, excluded = [], catalogAssets = assets, routes,
  published = {}, navigation = {}, search, searchBudget = 16 * 2 ** 20, partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal,
  onProgress = () => {}, resume = false, fullVerify = false, joinArchives = false,
  singleArchives = false, archiveSpace = 0, network = createNetwork({fetchFile, signal, onWaiting: () => onProgress({kind: "waiting-network"})})}) {
  const saved = await readBuild(drive);
  if (saved && !resume) throw Error("This drive has a saved build. Choose Resume.");
  if (!saved && resume) throw Error("No browser build was found on this drive.");
  if (!saved && !assets.some(isKnowledgeFile)) throw Error("Choose knowledge files with browser-accessible sources.");
  const state = saved || await start(drive, {assets, excluded, partBytes, joinArchives, searchBudget, singleArchives, archiveSpace});
  state.searchBudget ??= searchBudget;
  state.joined ||= {};
  state.prefixes ||= {};
  state.stagedArchives ||= {};
  const byId = new Map(catalogAssets.map(asset => [asset.id, asset]));
  const ordered = state.plan.map(pin => {
    const asset = byId.get(pin.id);
    if (!asset || Object.entries(assetPin(asset)).some(([key, value]) => value !== pin[key])) {
      throw Error("The pinned selection has changed since this build started: " + pin.id);
    }
    return asset;
  });
  const layouts = new Map(ordered.map(asset => [asset.id, partLayout(asset, state.partBytes)]));
  diag("build", {resume, files: ordered.length, verified: ordered.filter(asset => state.verified[asset.id]).length,
    partMb: +(state.partBytes / 1e6).toFixed(1), singleArchives: Boolean(state.singleArchives)});
  state.finished = false;
  if (resume) state.dropped = {};
  const occupied = new Set(ordered.filter(asset => state.verified[asset.id] ||
    state.parts[asset.id]?.length || state.prefixes[asset.id] || state.joined[asset.id] ||
    state.stagedArchives[asset.id]).map(asset => asset.id));
  let used = ordered.filter(asset => occupied.has(asset.id)).reduce((sum, asset) => sum + asset.size_bytes, 0);
  for (const [position, asset] of ordered.entries()) {
    if (occupied.has(asset.id)) used -= asset.size_bytes;
    signal?.throwIfAborted();
    await assertDrive(drive, state);
    const layout = layouts.get(asset.id);
    if (!state.verified[asset.id]) diag("file", {asset: asset.id, position, mb: +(asset.size_bytes / 1e6).toFixed(1),
      parts: layout.length, savedParts: state.parts[asset.id]?.length || 0, staged: Boolean(state.stagedArchives[asset.id])});
    const report = event => onProgress({...event, position, total: ordered.length});
    try {
      const options = {routes, published, fetchFile, signal, onProgress: report, fullVerify, network};
      if (!await checkJoined(drive, state, asset, layout, {fullVerify, signal})) {
        const available = state.archiveSpace - used;
        const publisherPinned = Boolean(published.publisherPieces?.archives?.[asset.id]);
        const single = state.singleArchives && layout.length > 1;
        if (single && !state.stagedArchives[asset.id] && publisherPinned && available >= 2 * asset.size_bytes) {
          await stageSingleArchive(drive, state, asset, layout, options);
        }
        if (state.joined[asset.id]) {
          await removeSplitParts(drive, layout);
        } else if (single && !state.stagedArchives[asset.id]) {
          await buildSingleArchive(drive, state, asset, layout, available, options);
        } else {
          if (state.stagedArchives[asset.id]) {
            const [{path}] = joinedLayout(asset);
            if ((await fileAt(drive, path))?.size < asset.size_bytes) await removeFile(drive, path);
          }
          options.archiveJournal = Boolean(state.stagedArchives[asset.id]) ||
            available >= asset.size_bytes + layout[0].bytes;
          await buildAsset(drive, state, asset, layout, options);
          if ((state.joinArchives || state.stagedArchives[asset.id]) && layout.length > 1) {
            await joinParts(drive, state, asset, layout, {signal, onProgress: report});
          }
        }
      }
      if (state.joined[asset.id]) delete state.stagedArchives[asset.id];
      used += asset.size_bytes;
      state.verified[asset.id] = true;
      delete state.failures[asset.id];
    } catch (error) {
      signal?.throwIfAborted();
      if (state.singleArchives && layout.length > 1 && (isNoSpace(error) || error.whole)) {
        await removeFile(drive, joinedLayout(asset)[0].path);
        delete state.prefixes[asset.id];
      }
      if (isNoSpace(error)) {
        // Earlier files are higher priority. Reclaim this unfinished file's
        // space and give the remaining, usually smaller files a chance to fit.
        await forgetParts(drive, state, asset, layout);
        delete state.stagedArchives[asset.id];
        state.dropped[asset.id] = "Drive ran out of space";
        delete state.failures[asset.id];
        report({kind: "dropped", asset, message: state.dropped[asset.id]});
      } else if (error instanceof SourceError) {
        if (error.whole) await forgetParts(drive, state, asset, layout);
        state.failures[asset.id] = error.message;
        if (state.parts[asset.id]?.length || state.prefixes[asset.id] || state.stagedArchives[asset.id]) used += asset.size_bytes;
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
    search, searchBudget: state.searchBudget, fetchFile, signal, network});
  state.finished = Object.keys(state.failures).length === 0 && Object.keys(state.dropped).length === 0 &&
    Object.keys(state.stagedArchives).length === 0 && !searchWarnings.length;
  await save(drive, state);
  return {state, completed, missing, searchWarnings};
}
