import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {fileHandle, isNoSpace, optional, removeFile, writeFile} from "./drive.mjs";
import {diag} from "./diagnostics.mjs";
import {assembleLibrary, assemblyReserve, startPage} from "./offline.mjs";
import {createNetwork, routeCooldowns, SourceError} from "./network.mjs";
import {canonical} from "./search-build.mjs";
import {archiveSession, checkAlignment, publisherPin, streamRequest} from "./archive-download.mjs";

export const PART_BYTES = 2 ** 30;
export const MANIFEST = "LIBRARY/.owl/browser-build.json";
const FAT32_MAX = 2 ** 32 - 1;
const DIGEST = /^[0-9a-f]{64}$/;
const encoder = new TextEncoder();
const filePin = contents => {
  const bytes = typeof contents === "string" ? encoder.encode(contents) : contents;
  return {bytes: bytes.length, sha256: bytesToHex(sha256(bytes))};
};
const emptyPin = filePin("");
const tier = ["CRITICAL", "USEFUL", "NONESSENTIAL"];
const priority = asset => tier.includes(asset.utility_tier) ? tier.indexOf(asset.utility_tier) : tier.length;
const noSpace = "Drive ran out of space";

export function isKnowledgeFile(asset) {
  return !asset.destination.startsWith("SOFTWARE/") && !asset.supporting_file && asset.archive_member?.document !== false;
}

export function buildOrder(assets, {transfer = true} = {}) {
  // Give archive transfers their temporary workspace before other files fill
  // the drive, even if the final archive will be kept in parts.
  const archiveSize = asset => transfer && asset.format === "zim" ? asset.size_bytes : 0;
  return [...assets].sort((a, b) => priority(a) - priority(b) ||
    archiveSize(b) - archiveSize(a) ||
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
  const state = JSON.parse(await file.text());
  if (![1, 2].includes(state.version) || !/^[a-z0-9-]+$/i.test(state.buildId || "") || !Array.isArray(state.plan) ||
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

async function readCheckpoint(file, digest, whole, signal) {
  const next = whole.clone(), current = sha256.create();
  for await (const chunk of file.stream()) {
    signal?.throwIfAborted();
    next.update(chunk);
    current.update(chunk);
  }
  return bytesToHex(current.digest()) === digest ? next : null;
}

async function matchesFile(file, pin, signal) {
  return file && pin && file.size === pin.bytes && DIGEST.test(pin.sha256) &&
    Boolean(await readCheckpoint(file, pin.sha256, sha256.create(), signal));
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

async function buildAsset(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const checkpoints = state.parts[asset.id] ||= [];
  let whole = sha256.create(), index = 0;
  for (const [i, part] of layout.entries()) {
    signal?.throwIfAborted();
    const saved = checkpoints[i];
    if (!DIGEST.test(saved?.sha256) || saved.bytes !== part.bytes || (pins[i] && pins[i] !== saved.sha256)) break;
    const file = await fileAt(drive, part.path);
    if (file?.size !== part.bytes) break;
    onProgress({kind: "checking", asset, index: i, count: layout.length});
    const restored = await readCheckpoint(file, saved.sha256, whole, signal);
    if (!restored) break;
    whole = restored;
    index++;
  }
  const pin = publisherPin(published.publisherPieces, asset);
  await prunePieceJournal(drive, state, asset, pin, layout[index]?.start);
  if (index === layout.length) {
    if (bytesToHex(whole.digest()) === asset.sha256) return;
    throw new SourceError("Saved parts failed whole-file SHA-256", {whole: true});
  }
  checkpoints.length = index;
  delete state.verified[asset.id];
  await save(drive, state);

  const download = partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network});
  for (; index < layout.length; index++) {
    const part = layout[index];
    const existed = await candidateFile(drive, part.path);
    let downloaded;
    try { downloaded = await download(index, whole, (source, options) => writePart(drive, asset, part, source, options)); }
    catch (error) {
      if (!existed && (error instanceof SourceError || isNoSpace(error))) await removePinned(drive, part.path, emptyPin);
      throw error;
    }
    whole = downloaded.next;
    checkpoints.push({sha256: downloaded.digest, bytes: part.bytes});
    await save(drive, state);
    // Release the verified part's temporary pieces before reserving the next part.
    await prunePieceJournal(drive, state, asset, pin, layout[index + 1]?.start);
  }
}

function partDownloader(drive, state, asset, layout, {routes, published, fetchFile, signal, onProgress, network}) {
  const pins = partPins(asset, layout, published, state.partBytes);
  const choices = routesFor(asset, routes, published);
  const cooldown = routeCooldowns(network);
  const sources = choices.flatMap(source => source.pieces.map(piece => piece.url));
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
        if (source.pieces.some(piece => cooldown.waiting(piece.url))) continue;
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
      if ((connection || network.offline()) && await network.waitForConnection()) continue;
      if (++round < 2) await cooldown.delay(sources);
    }
    if (wholeMismatch && choices.length > 1) (state.sourceOffsets ||= {})[asset.id] = (preferred + 1) % choices.length;
    throw new SourceError([...failures].join(". ") || "No browser source is available", {whole: wholeMismatch});
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
    if (!existing) await removePinned(drive, path, emptyPin);
    signal?.throwIfAborted();
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
    parts.push({sha256: bytesToHex(hash.digest()), bytes: part.bytes});
  }
  return bytesToHex(whole.digest()) === asset.sha256 ? parts : null;
}

export async function inspectDrive(drive) {
  const state = await readBuild(drive);
  const library = await optional(() => drive.getDirectoryHandle("LIBRARY"));
  const adoption = Boolean(state?.adopting || !state && await candidateFile(drive, "START_HERE.html"));
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
  const legacy = adoption || state?.migrated || (state && !state.generatedPins) ? await previousReader(drive) : new Map();
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
  return {state, hasLibrary: Boolean(library), adoption, heldBytes, candidates, legacy, availableInstalled};
}

const readerRevision = (navigation, search, publication) => bytesToHex(sha256(new TextEncoder().encode(
  canonical([navigation, search, publication]))));

async function activeReaderExists(drive, state) {
  if (!(await candidateFile(drive, "START_HERE.html"))?.size) return false;
  return (await Promise.all(state.generated.map(path => readerPath(path) && candidateFile(drive, path)))).every(Boolean);
}

export async function compareLibrary(drive, {assets, choice, catalogVersion, navigation = {}, search, readerPublication, partBytes = PART_BYTES,
    singleArchives = false, joinArchives = false, fullVerify = false, signal, inspection, freeBytes = Infinity,
    archiveSpace = Infinity} = {}) {
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
    const compatible = !split || sameOptions || (wantsSingle && partBytes === state?.partBytes);
    const destination = state?.working[asset.id];
    const working = (sameOptions || !split) && matches(asset, previous) &&
      typeof destination === "string" && managedDestination(asset, destination, state.buildId) && destination;
    let installed = compatible && matches(asset, old?.pin) ? old : null;
    if (working && state.verified[asset.id] && (!installed || state.pending && state.joined?.[asset.id])) {
      const file = diskAsset(asset, working);
      const layout = state.joined?.[asset.id] ? joinedLayout(file) : layoutFor(file, partBytes);
      installed = {pin: assetPin(asset), asset, layout, parts: state.joined?.[asset.id] ?
        [{sha256: asset.sha256}] : state.parts[asset.id]};
    }
    if (installed && await layoutExists(drive, installed.layout)) {
      const parts = fullVerify || state?.pending && (installed.layout.length > 1 || installed.layout !== old?.layout) ?
        await verifyLayout(drive, asset, installed.layout, signal) : installed.parts;
      if (parts?.length) { present.push({...installed, asset, parts}); continue; }
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
  const joinRoom = Math.min(archiveSpace - presentBytes, freeBytes);
  const joins = wantsSingle ? present.filter(row => !row.protected && row.layout.length > 1 && row.pin.bytes <= joinRoom) : [];
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
  if (path === "START_HERE.html" || path === readerChecksums) return true;
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

async function previousReader(drive) {
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

function guardReader(drive, state, legacy) {
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
          if (await matchesFile(file, pin)) { current = pin; break; }
        }
        if (!current) throw Error("An existing file blocks the start page or search index. Choose another library folder.");
      }
      // An interrupted write can leave either the old file or the verified
      // replacement. Persist both pins before changing the published files.
      const known = state.generated.includes(path);
      const unchanged = Boolean(file && current.sha256 === next.sha256);
      if (unchanged && known && proofs.some(pin => pin?.sha256 === next.sha256 && pin.bytes === next.bytes)) return false;
      if (!known) state.generated.push(path);
      state.generatedPins[path] = current.sha256 === next.sha256 ? [next] : [current, next];
      await save(drive, state);
      return !unchanged;
    }
  };
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

async function retireReaderFiles(drive, state, signal) {
  signal?.throwIfAborted();
  const active = await checksumPins(await fileAt(drive, readerChecksums));
  active.set(readerChecksums, null);
  const generations = new Set();
  for (const path of state.generated) {
    if (active.has(path)) continue;
    signal?.throwIfAborted();
    if (await removeReaderFile(drive, state, path, signal)) {
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

function beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, archiveSpace, searchBudget,
    capacityBytes, capacityEstimated}) {
  return {version: 2, buildId: saved?.buildId || globalThis.crypto.randomUUID(), plan: [], excluded: [],
    installed: saved?.installed || map(), working: map(), owned: [...(saved?.owned || [])], generated: [...(saved?.generated || [])],
    generatedPins: Object.assign(map(), saved?.generatedPins), reservePin: saved?.reservePin,
    parts: map(), verified: map(), joined: map(), prefixes: map(), stagedArchives: map(), sourceOffsets: map(),
    dropped: map(), failures: map(), partBytes, joinArchives, singleArchives, archiveSpace,
    choice, catalogVersion, searchBudget, capacityBytes, capacityEstimated, pending: true, finished: false, migrated: saved?.migrated,
    syncedAt: saved?.syncedAt};
}

export async function reconcile(drive, {assets, excluded = [], routes = {}, published = {}, navigation = {}, search,
    partBytes = PART_BYTES, fetchFile = globalThis.fetch, signal, onProgress = () => {}, fullVerify = false,
    joinArchives = false, singleArchives = false, archiveSpace = Infinity, choice, catalogVersion, readerPublication,
    freeBytes = Infinity, capacityBytes, capacityEstimated, replaceInPlace = [], searchBudget = 16 * 2 ** 20,
    catalogAssets = assets, prepareSources, onPublished,
    network = createNetwork({fetchFile, signal, onWaiting: () => onProgress({kind: "waiting-network"})})}) {
  const inspection = await inspectDrive(drive), saved = inspection.state;
  if (!assets.some(isKnowledgeFile)) throw Error("Choose knowledge files with browser-accessible sources.");
  choice ??= saved?.choice || {kind: "recommended", split: !singleArchives && !joinArchives};
  const revision = readerRevision(navigation, search, readerPublication);
  const joining = singleArchives || joinArchives;
  const comparison = await compareLibrary(drive, {assets, choice, catalogVersion, navigation, search, readerPublication,
    partBytes, singleArchives, joinArchives, fullVerify, signal, inspection, freeBytes, archiveSpace});
  const resuming = saved?.pending && !comparison.changedChoice && catalogVersion === saved.catalogVersion;
  const state = beginRecord(saved, {choice, catalogVersion, partBytes, joinArchives, singleArchives, archiveSpace,
    capacityBytes: capacityBytes ?? saved?.capacityBytes, capacityEstimated: capacityEstimated ?? saved?.capacityEstimated,
    searchBudget: resuming ? Math.min(saved.searchBudget ?? searchBudget, searchBudget) : searchBudget});
  const {legacy} = inspection;
  const previousPins = legacy.size ? legacy : saved ? await previousReader(drive) : new Map();
  const catalogPaths = new Map(catalogAssets.map(asset => [asset.id, asset.destination]));
  const retirement = {catalogPaths, previousPins, signal};
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
  const starter = startPage();
  const start = await fileAt(drive, "START_HERE.html");
  if (start && await matchesFile(start, filePin(starter))) {
    if (!state.generated.includes("START_HERE.html")) state.generated.push("START_HERE.html");
    state.generatedPins["START_HERE.html"] = [filePin(starter)];
  }
  if (saved) {
    await save(drive, state);
    if (!start?.size) await writeFile(guardReader(drive, state, legacy), "START_HERE.html", starter);
  } else {
    if (await readBuild(drive)) throw Error("Another sync started on this drive.");
    if (!start) {
      await drive.getDirectoryHandle("LIBRARY", {create: true});
      await writeFile(drive, "START_HERE.html", starter);
      state.generated.push("START_HERE.html");
      state.generatedPins["START_HERE.html"] = [filePin(starter)];
    }
    try { await writeFile(drive, MANIFEST, JSON.stringify(state) + "\n"); }
    catch (error) {
      if (isNoSpace(error) && (await fileAt(drive, MANIFEST))?.size === 0) await removeFile(drive, MANIFEST);
      throw error;
    }
  }
  let unavailableSupport = [];
  if (prepareSources) {
    const support = await prepareSources();
    search = support.search;
    unavailableSupport = support.unavailableSupport || [];
    published = {...published, publisherPieces: support.publisherPieces};
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
  const downloaded = new Map(), incomplete = new Map();
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
      const file = row.working ? diskAsset(asset, row.working) : await reservePaths(drive, state, asset, partBytes, joining);
      const layout = layoutFor(file, partBytes);
      const single = singleArchives && layout.length > 1;
      if (joining && layout.length > 1) {
        const path = joinedLayout(file)[0].path;
        if (!state.owned.includes(path)) {
          if (await fileAt(drive, path)) throw Error("An existing file blocks the archive. Choose another library folder.");
          state.owned.push(path);
        }
      }
      const replacement = replaceInPlace.includes(asset.id) && comparison.held.includes(row) && !row.old.protected;
      const options = {routes, published, fetchFile, signal, onProgress: report, network};
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
            const joinRoom = Math.min(archiveSpace - used - asset.size_bytes, free - row.bytes - (reserved ? reserveBytes : 0));
            if (joining && layout.length > 1 && joinRoom >= asset.size_bytes) {
              await joinParts(drive, state, file, layout, options);
            }
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
        } else if (error instanceof SourceError) {
          if (error.whole) await forgetParts(drive, state, file, layout, published, signal);
          state.failures[asset.id] = error.message;
          report({kind: "failed", asset, message: error.message});
        } else throw error;
      }
      try { await save(drive, state); }
      catch (error) {
        if (!reserved || !isNoSpace(error)) throw error;
        await releaseReserve();
        reserved = false;
        full = true;
        await save(drive, state);
      }
    }
  } finally { await releaseReserve(); }
  signal?.throwIfAborted();
  // Leave the old parts available to the published reader until the new
  // start page and checksum list are in place.
  if (joining && !full) for (const row of comparison.present) {
    if (row.protected || row.layout.length < 2 ||
        row.pin.bytes > Math.min(archiveSpace - used, free)) continue;
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
  }
  if (excluded.length || Object.keys(state.failures).length || Object.keys(state.dropped).length) {
    for (const old of Object.values(state.installed)) {
      if (!present.has(old.pin.id) && !additions.get(old.pin.id)?.corrupt && await layoutExists(drive, old.layout)) present.set(old.pin.id, old);
    }
  }
  onProgress({kind: "assembling"});
  if (legacy.size) {
    // Keep ownership available on retry even if assembly replaces the old checksum list.
    await recordAdoptedGeneration(drive, state, legacy, signal);
    await save(drive, state);
  }
  const syncedAt = new Date().toISOString();
  let completed, missing, keptInParts, searchWarnings, supportMissing, compact = false;
  for (;;) {
    completed = [...present.values()].map(row => row.asset);
    missing = [...excluded, ...ordered.flatMap(asset => {
      const reason = state.dropped[asset.id] || state.failures[asset.id];
      return reason ? [{id: asset.id, title: asset.title, utility_tier: asset.utility_tier ?? null, reason}] : [];
    })];
    keptInParts = [...present.values()].filter(row => row.layout.length > 1)
      .map(({asset, layout}) => ({id: asset.id, title: asset.title, parts: layout.length}));
    const before = new Set(state.generated);
    try {
      ({warnings: searchWarnings, supportMissing} = await assembleLibrary(guardReader(drive, state, legacy),
        {completed, missing, keptInParts, compact, unavailableSupport, searchMissing: compact && Boolean(search),
        selectedCount: assets.length + excluded.length, navigation, search: compact ? undefined : search,
        layouts: new Map([...present].map(([id, row]) => [id, row.layout])),
        parts: Object.fromEntries([...present].map(([id, row]) => [id, row.parts])),
        searchBudget: state.searchBudget, fetchFile, signal, network, syncedAt, onPublished}));
      break;
    } catch (error) {
      signal?.throwIfAborted();
      if (!isNoSpace(error)) throw error;
      for (const path of state.generated) if (!before.has(path)) await removeReaderFile(drive, state, path, signal);
      state.generated = [...before];
      if (incomplete.size) {
        for (const {file, layout} of incomplete.values()) await forgetParts(drive, state, file, layout, published, signal);
        incomplete.clear();
        continue;
      }
      const lowest = [...downloaded.values()].at(-1);
      if (!compact && (!lowest || lowest.asset.utility_tier === "CRITICAL" ||
          isKnowledgeFile(lowest.asset) && completed.filter(isKnowledgeFile).length === 1)) {
        compact = true;
        continue;
      }
      if (!lowest) throw error;
      const {asset, layout} = lowest;
      await forgetParts(drive, state, asset, layout, published, signal);
      delete state.joined[asset.id];
      downloaded.delete(asset.id);
      present.delete(asset.id);
      state.dropped[asset.id] = noSpace;
      onProgress({kind: "dropped", asset, message: noSpace});
    }
  }
  // The start page now points to the new reader, and the checksum list includes reused shards.
  await retireReaderFiles(drive, state, signal);
  const recorded = new Set(state.owned);
  for (const row of present.values()) {
    if (row.protected) continue;
    for (const part of row.layout) recorded.add(part.path);
  }
  state.owned = [...recorded];
  const finished = !missing.length && completed.some(isKnowledgeFile) && !searchWarnings.length;
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
  state.pending = false;
  state.finished = finished;
  await save(drive, state);
  return {state, completed, missing, keptInParts, searchWarnings, supportMissing};
}

export {reconcile as buildLibrary};
