import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, writeFile} from "./drive.mjs";
import {assembleLibrary} from "./offline.mjs";
import {createNetwork, receiveFile, SourceError} from "./network.mjs";

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

async function streamRequest(url, range, expected, fetchFile, signal, onChunk) {
  let count = 0;
  await receiveFile(url, {
    fetchFile, signal, headers: range ? {Range: "bytes=" + range.start + "-" + range.end} : {},
    check(response) {
      if (range ? response.status !== 206 ||
          response.headers.get("Content-Range") !== "bytes " + range.start + "-" + range.end + "/" + range.total :
          response.status !== 200) {
        throw new SourceError(range && response.ok ? "Source did not return the pinned byte range" : "HTTP " + response.status);
      }
    },
    async onChunk(chunk) {
      count += chunk.byteLength;
      if (count > expected) throw new SourceError("Source exceeded the pinned byte count");
      await onChunk(chunk);
    }
  });
  if (count !== expected) throw new SourceError("Source ended before the pinned byte count", {connection: true});
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

async function writePart(drive, asset, part, source, options) {
  const writable = await (await fileHandle(drive, part.path, true)).createWritable({mode: "exclusive"});
  try {
    const result = await transferPart(asset, part, source, writable, options);
    await writable.close();
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
  }
}

function partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const choices = routesFor(asset, routes, published);
  let preferred = (state.sourceOffsets?.[asset.id] || 0) % (choices.length || 1);
  return async (index, whole, write) => {
    signal?.throwIfAborted();
    const part = layout[index];
    const progress = {asset, index, count: layout.length};
    const range = layout.length === 1 ? null : {start: part.start, end: part.start + part.bytes - 1, total: asset.size_bytes};
    const failures = new Set();
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
    if (bytesToHex(digest.digest()) !== asset.sha256) throw new SourceError("Saved parts failed whole-file SHA-256", {whole: true});
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
  const occupied = new Set(ordered.filter(asset => state.verified[asset.id] ||
    state.parts[asset.id]?.length || state.prefixes[asset.id] || state.joined[asset.id]).map(asset => asset.id));
  let used = ordered.filter(asset => occupied.has(asset.id)).reduce((sum, asset) => sum + asset.size_bytes, 0);
  for (const [position, asset] of ordered.entries()) {
    if (occupied.has(asset.id)) used -= asset.size_bytes;
    signal?.throwIfAborted();
    await assertDrive(drive, state);
    const layout = layouts.get(asset.id);
    const report = event => onProgress({...event, position, total: ordered.length});
    try {
      const options = {routes, published, fetchFile, signal, onProgress: report, fullVerify, network};
      if (!await checkJoined(drive, state, asset, layout, {fullVerify, signal})) {
        if (state.singleArchives && layout.length > 1) {
          await buildSingleArchive(drive, state, asset, layout, state.archiveSpace - used, options);
        } else {
          await buildAsset(drive, state, asset, layout, options);
          if (state.joinArchives && layout.length > 1) {
            await joinParts(drive, state, asset, layout, {signal, onProgress: report});
          }
        }
      }
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
        state.dropped[asset.id] = "Drive ran out of space";
        delete state.failures[asset.id];
        report({kind: "dropped", asset, message: state.dropped[asset.id]});
      } else if (error instanceof SourceError) {
        if (error.whole) await forgetParts(drive, state, asset, layout);
        state.failures[asset.id] = error.message;
        if (state.parts[asset.id]?.length || state.prefixes[asset.id]) used += asset.size_bytes;
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
  state.finished = Object.keys(state.failures).length === 0 && Object.keys(state.dropped).length === 0 && !searchWarnings.length;
  await save(drive, state);
  return {state, completed, missing, searchWarnings};
}
