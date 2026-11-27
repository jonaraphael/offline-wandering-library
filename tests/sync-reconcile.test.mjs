import assert from "node:assert/strict";
import {createHash, webcrypto} from "node:crypto";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";
import {compareLibrary, DrivePathConflict, inspectDrive, MANIFEST, partLayout, readBuild, reconcile, recordPause} from "../web/builder.mjs";
import {completionState, prepareDownloadSources} from "../web/builder-ui.mjs";
import {removeFile, writeFile} from "../web/drive.mjs";
import {createNetwork, SourceError} from "../web/network.mjs";
import {readPreviewFile} from "../web/reader-preview.mjs";
import {Directory} from "./browser-drive-fixture.mjs";

globalThis.crypto ||= webcrypto;
const hash = body => createHash("sha256").update(body).digest("hex");
const item = (id, body) => ({id, title: id, destination: "BOOKS/" + id + ".pdf", format: "pdf",
  size_bytes: Buffer.byteLength(body), sha256: hash(body), utility_tier: "USEFUL"});
const path = file => "LIBRARY/" + file.destination;
const bytes = async (drive, path) => new Uint8Array(await (await (await drive.file(path)).getFile()).arrayBuffer());
const text = async (drive, path) => (await (await drive.file(path)).getFile()).text();
const options = (files, other = {}) => ({
  assets: Object.entries(files).map(([id, body]) => item(id, body)),
  routes: Object.fromEntries(Object.keys(files).map(id => [id, ["https://example.test/" + id]])),
  fetchFile: async url => new Response(files[new URL(url).pathname.slice(1)]),
  ...other
});
const pin = asset => ({id: asset.id, path: asset.destination, format: asset.format, bytes: asset.size_bytes, sha256: asset.sha256});

test("a catalog update adds and verifies every new file before deleting old recorded paths", async () => {
  const drive = new Directory();
  const original = options({changed: "old", dropped: "drop", stable: "same"}, {catalogVersion: "2026-01"});
  await reconcile(drive, original);
  await writeFile(drive, "LIBRARY/BOOKS/stray.pdf", "inside");
  await writeFile(drive, "stray.txt", "outside");
  const before = await text(drive, "START_HERE.html");
  const events = [];
  const update = options({changed: "new version", added: "new", stable: "same"}, {catalogVersion: "2026-02",
    onProgress: event => events.push(event)});
  const comparison = await compareLibrary(drive, update);
  assert.deepEqual(comparison.adds.map(row => row.asset.id), ["added", "changed"]);
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["stable"]);
  assert.deepEqual(comparison.drops.map(row => row.pin.id), ["dropped"]);
  assert.equal(comparison.addBytes, 14);
  assert.equal(comparison.removeBytes, 7);
  const fetch = update.fetchFile;
  update.fetchFile = async url => {
    assert.equal(await text(drive, path(original.assets[0])), "old");
    assert.equal(await text(drive, path(original.assets[1])), "drop");
    assert.equal(await text(drive, "START_HERE.html"), before);
    return fetch(url);
  };
  const result = await reconcile(drive, update);
  assert.equal(result.state.finished, true);
  const record = await readBuild(drive);
  assert.equal(record.catalogVersion, "2026-02");
  assert.ok(record.syncedAt);
  assert.equal(await text(drive, record.installed.changed.layout[0].path), "new version");
  await assert.rejects(drive.file(path(original.assets[0])), {name: "NotFoundError"});
  await assert.rejects(drive.file(path(original.assets[1])), {name: "NotFoundError"});
  assert.equal(await text(drive, "LIBRARY/BOOKS/stray.pdf"), "inside");
  assert.equal(await text(drive, "stray.txt"), "outside");
  assert.deepEqual(events.filter(event => event.kind === "downloading" && !event.received).map(event => event.asset.id), ["added", "changed"]);
  assert.ok((await compareLibrary(drive, update)).current);
});

test("the same operation persists a custom target and resumes after an interrupted update", async () => {
  const drive = new Directory();
  await reconcile(drive, options({a: "one", b: "two"}, {catalogVersion: "1"}));
  const controller = new AbortController();
  const choice = {kind: "custom", edits: {b: {included: false}, c: {included: true, excluded: ["last"]}}, split: true};
  const update = options({a: "one", c: "three", d: "four"}, {choice, catalogVersion: "1"});
  await assert.rejects(reconcile(drive, {...update, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "d") controller.abort();
  }}), {name: "AbortError"});
  const comparison = await compareLibrary(drive, update);
  assert.equal(comparison.state.pending, true);
  assert.equal(await text(drive, "LIBRARY/BOOKS/b.pdf"), "two");
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["a", "c"]);
  assert.deepEqual(comparison.state.choice, choice);
  const fetch = update.fetchFile;
  await reconcile(drive, {...update, fetchFile: async url => {
    assert.equal(new URL(url).pathname, "/d");
    return fetch(url);
  }});
  assert.deepEqual((await readBuild(drive)).choice, choice);
  await assert.rejects(drive.file("LIBRARY/BOOKS/b.pdf"), {name: "NotFoundError"});
});

test("files finished before a pause stay recorded through a second pause of the first sync", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two", c: "three", d: "four"}, {catalogVersion: "1"});
  const pauseAt = id => {
    const controller = new AbortController();
    return {signal: controller.signal, onProgress(event) {
      if (event.kind === "downloading" && event.asset.id === id) controller.abort();
    }};
  };
  await assert.rejects(reconcile(drive, {...first, ...pauseAt("c")}), {name: "AbortError"});
  assert.deepEqual((await compareLibrary(drive, first)).present.map(row => row.asset.id), ["a", "b"]);
  await assert.rejects(reconcile(drive, {...first, ...pauseAt("d")}), {name: "AbortError"});
  const comparison = await compareLibrary(drive, first);
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["a", "b", "c"]);
  assert.deepEqual(comparison.adds.map(row => row.asset.id), ["d"]);
  const fetched = [];
  const fetch = first.fetchFile;
  const done = await reconcile(drive, {...first, fetchFile: async url => { fetched.push(new URL(url).pathname); return fetch(url); }});
  assert.equal(done.state.finished, true);
  assert.deepEqual(fetched, ["/d"]);
  for (const id of ["a", "b", "c", "d"]) assert.equal(done.state.installed[id].layout[0].path, "LIBRARY/BOOKS/" + id + ".pdf");
});

test("a pause right after a resumed sync starts keeps the files finished earlier", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two", c: "three"}, {catalogVersion: "1"});
  let controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "c") controller.abort();
  }}), {name: "AbortError"});
  controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, prepareSources: async () => {
    controller.abort();
    controller.signal.throwIfAborted();
  }}), {name: "AbortError"});
  assert.deepEqual((await compareLibrary(drive, first)).present.map(row => row.asset.id), ["a", "b"]);
});

test("files OWL wrote stay usable when the drive record lost their verified marks", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two", c: "three"}, {catalogVersion: "1"});
  const controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "c") controller.abort();
  }}), {name: "AbortError"});
  const record = await readBuild(drive);
  // The record a builder from before this fix left on a real 1 TB drive:
  // only the download in progress kept its entries.
  record.verified = {};
  record.working = {c: record.working.c};
  record.parts = {c: record.parts.c ?? []};
  await writeFile(drive, MANIFEST, JSON.stringify(record) + "\n");
  await writeFile(drive, "LIBRARY/BOOKS/b.pdf", "tampered");
  const comparison = await compareLibrary(drive, first);
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["a"]);
  assert.deepEqual(comparison.adds.map(row => row.asset.id), ["b", "c"]);
  const fetched = [];
  const fetch = first.fetchFile;
  const done = await reconcile(drive, {...first, fetchFile: async url => { fetched.push(new URL(url).pathname); return fetch(url); }});
  assert.equal(done.state.finished, true);
  assert.deepEqual(fetched.sort(), ["/b", "/c"]);
  assert.equal(done.state.installed.a.layout[0].path, "LIBRARY/BOOKS/a.pdf");
  assert.equal(await text(drive, done.state.installed.b.layout[0].path), "two");
});

test("a check of files already on the drive reports its total first and its progress to the end", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two", c: "three"}, {catalogVersion: "1"});
  const controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "c") controller.abort();
  }}), {name: "AbortError"});
  const record = await readBuild(drive);
  record.verified = {};
  record.working = {c: record.working.c};
  record.parts = {c: record.parts.c ?? []};
  await writeFile(drive, MANIFEST, JSON.stringify(record) + "\n");
  const events = [];
  const comparison = await compareLibrary(drive, {...first, onCheck: event => events.push(event)});
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["a", "b"]);
  assert.deepEqual(events.map(({checked, total}) => [checked, total]), [[0, 6], [6, 6]]);
  const syncEvents = [];
  await reconcile(drive, {...first, onProgress: event => { if (event.kind === "checking") syncEvents.push(event.checked); }});
  assert.deepEqual(syncEvents, [], "files checked when the drive was opened are not read again in the same session");
});

test("a file the lost record began to download again under a new name is found at its first path", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two"}, {catalogVersion: "1"});
  const controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "b") controller.abort();
  }}), {name: "AbortError"});
  const record = await readBuild(drive);
  record.verified = {};
  record.parts = {};
  record.working = {a: "BOOKS/a-0123456789ab.pdf"};
  record.owned.push("LIBRARY/BOOKS/a-0123456789ab.pdf");
  await writeFile(drive, "LIBRARY/BOOKS/a-0123456789ab.pdf", "");
  await writeFile(drive, MANIFEST, JSON.stringify(record) + "\n");
  const comparison = await compareLibrary(drive, first);
  assert.deepEqual(comparison.present.map(row => [row.asset.id, row.layout[0].path]), [["a", "LIBRARY/BOOKS/a.pdf"]]);
  const fetched = [];
  const fetch = first.fetchFile;
  const done = await reconcile(drive, {...first, fetchFile: async url => { fetched.push(new URL(url).pathname); return fetch(url); }});
  assert.deepEqual(fetched, ["/b"]);
  assert.equal(done.state.installed.a.layout[0].path, "LIBRARY/BOOKS/a.pdf");
});

test("after Pause, looking at the drive does not reread finished files; after a cut-off sync it does", async () => {
  const drive = new Directory();
  const first = options({a: "one", b: "two"}, {catalogVersion: "1"});
  const controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "b") controller.abort();
  }}), {name: "AbortError"});
  const handle = await drive.file("LIBRARY/BOOKS/a.pdf");
  let reads = 0;
  const getFile = handle.getFile.bind(handle);
  handle.getFile = async () => {
    const file = await getFile();
    // A new modification time each read keeps the session cache from hiding a reread.
    return {size: file.size, lastModified: file.lastModified + reads, stream: () => { reads++; return file.stream(); }};
  };
  assert.deepEqual((await compareLibrary(drive, first)).present.map(row => row.asset.id), ["a"]);
  assert.equal(reads, 1, "a sync cut off without Pause rereads its finished files");
  await recordPause(drive);
  assert.equal((await readBuild(drive)).pausedCleanly, true);
  assert.deepEqual((await compareLibrary(drive, first)).present.map(row => row.asset.id), ["a"]);
  assert.equal(reads, 1, "after Pause the record is trusted");
  // An error in a live tab records its text with the clean stop.
  await recordPause(drive, "TypeError: Failed to fetch");
  assert.equal((await readBuild(drive)).lastProblem.detail, "TypeError: Failed to fetch");
  const done = await reconcile(drive, first);
  assert.equal(done.state.finished, true);
  assert.equal((await readBuild(drive)).pausedCleanly, undefined);
  assert.equal((await readBuild(drive)).lastProblem, undefined);
});

test("after a cut-off sync, only files written in the ten minutes before its last save are reread", async () => {
  let clock = Date.UTC(2026, 10, 24, 16);
  const drive = new Directory("drive", {now: () => clock});
  const first = options({a: "one", b: "two", c: "three"}, {catalogVersion: "1"});
  const controller = new AbortController();
  await assert.rejects(reconcile(drive, {...first, signal: controller.signal, onProgress(event) {
    if (event.kind !== "downloading" || event.received) return;
    if (event.asset.id === "b") clock += 20 * 60_000;
    if (event.asset.id === "c") controller.abort();
  }}), {name: "AbortError"});
  const reads = new Map();
  for (const id of ["a", "b"]) {
    const handle = await drive.file("LIBRARY/BOOKS/" + id + ".pdf");
    const getFile = handle.getFile.bind(handle);
    handle.getFile = async () => {
      const file = await getFile();
      return {size: file.size, lastModified: file.lastModified,
        stream: () => { reads.set(id, (reads.get(id) || 0) + 1); return file.stream(); }};
    };
  }
  const events = [];
  const comparison = await compareLibrary(drive, {...first, onCheck: event => events.push(event)});
  assert.deepEqual(comparison.present.map(row => row.asset.id), ["a", "b"]);
  assert.deepEqual([...reads], [["b", 1]], "a, written 20 minutes before the last save, is trusted");
  assert.deepEqual(events.map(({checked, total}) => [checked, total]), [[0, 3], [3, 3]]);
  clock += 1;
  await writeFile(drive, "LIBRARY/BOOKS/b.pdf", "TWO");
  const damaged = await compareLibrary(drive, first);
  assert.deepEqual(damaged.present.map(row => row.asset.id), ["a"]);
  assert.ok(damaged.adds.some(row => row.asset.id === "b"));
});

test("a replacement that does not fit is held until explicitly approved", async () => {
  const drive = new Directory();
  await reconcile(drive, options({a: "old", b: "keep"}));
  const update = options({a: "new text"}, {freeBytes: 3});
  assert.deepEqual((await compareLibrary(drive, update)).held.map(row => row.asset.id), ["a"]);
  const partial = await reconcile(drive, {...update, fetchFile: () => assert.fail("held items cannot be fetched")});
  assert.equal(partial.state.finished, false);
  assert.equal(await text(drive, "LIBRARY/BOOKS/a.pdf"), "old");
  assert.equal(await text(drive, "LIBRARY/BOOKS/b.pdf"), "keep");
  const done = await reconcile(drive, {...update, replaceInPlace: ["a"]});
  assert.equal(done.state.finished, true);
  assert.equal(await text(drive, done.state.installed.a.layout[0].path), "new text");
});

test("v1 verified files carry forward and changed pins reconcile without refusing the drive", async () => {
  const drive = new Directory();
  const old = options({keep: "verified", change: "before"});
  for (const asset of old.assets) await writeFile(drive, path(asset), old.assets[0] === asset ? "verified" : "before");
  await writeFile(drive, MANIFEST, JSON.stringify({
    version: 1, buildId: "legacy", partBytes: 2 ** 30, plan: old.assets.map(pin), excluded: [],
    parts: Object.fromEntries(old.assets.map(asset => [asset.id, [{sha256: asset.sha256, bytes: asset.size_bytes}]])),
    verified: {keep: true, change: true}, dropped: {}, failures: {}, finished: true
  }));
  const next = options({keep: "verified", change: "after"}, {catalogVersion: "next"});
  const fetch = next.fetchFile;
  await reconcile(drive, {...next, fetchFile: async url => {
    assert.equal(new URL(url).pathname, "/change");
    return fetch(url);
  }});
  const record = JSON.parse(await text(drive, MANIFEST));
  assert.equal(record.version, 2);
  assert.equal(record.buildId, "legacy");
  assert.equal(record.installed.keep.pin.sha256, hash("verified"));
  assert.equal(record.installed.change.pin.sha256, hash("after"));
});

test("a CLI drive keeps hash-matching files, including an unnamed loose copy, without fetching them", async () => {
  const drive = new Directory();
  const candidate = item("a", "from the drive");
  const start = "<!doctype html><title>Offline Wandering Library</title>";
  await writeFile(drive, path(candidate), "from the drive");
  await writeFile(drive, "START_HERE.html", start);
  await writeFile(drive, "LIBRARY/SHA256SUMS.txt", hash(start) + "  START_HERE.html\n");
  const selection = options({a: "from the drive"}, {fetchFile: () => assert.fail("verified bytes are already installed")});
  assert.equal((await compareLibrary(drive, selection)).adoption, true);
  const adopted = await reconcile(drive, selection);
  assert.equal(adopted.state.installed.a.protected, true);
  await reconcile(drive, options({b: "replacement"}));
  assert.equal(await text(drive, path(candidate)), "from the drive");
});

test("a file with the wrong digest at a target path stays untouched", async () => {
  const drive = new Directory();
  const selection = options({a: "new"});
  const logical = path(selection.assets[0]);
  await writeFile(drive, logical, "old");
  const result = await reconcile(drive, selection);
  assert.notEqual(result.state.installed.a.layout[0].path, logical);
  assert.equal(await text(drive, logical), "old");
});

test("retirement leaves paths outside the OWL layout and files whose recorded digest differs", async () => {
  const drive = new Directory();
  await reconcile(drive, options({old: "old", keep: "keep"}));
  await writeFile(drive, "owner.txt", "personal");
  await writeFile(drive, "LIBRARY/BOOKS/owner.txt", "personal");
  await writeFile(drive, "LIBRARY/BOOKS/old.pdf", "new");
  const record = await readBuild(drive);
  const personal = {bytes: 8, sha256: hash("personal")};
  record.owned.push("owner.txt", "LIBRARY/BOOKS/owner.txt");
  record.generated.push("owner.txt", "LIBRARY/BOOKS/owner.txt");
  record.generatedPins["owner.txt"] = [personal];
  record.generatedPins["LIBRARY/BOOKS/owner.txt"] = [personal];
  const foreign = {...item("foreign", "personal"), destination: "BOOKS/owner.txt"};
  record.installed.foreign = {pin: pin(foreign), asset: foreign,
    layout: [{path: path(foreign), bytes: personal.bytes, start: 0}], parts: [personal]};
  await writeFile(drive, MANIFEST, JSON.stringify(record));
  const result = await reconcile(drive, options({keep: "keep"}));
  assert.equal(result.state.finished, true);
  assert.equal(await text(drive, "owner.txt"), "personal");
  assert.equal(await text(drive, "LIBRARY/BOOKS/owner.txt"), "personal");
  assert.equal(await text(drive, "LIBRARY/BOOKS/old.pdf"), "new");
});

test("a personal start page is reported when choosing the drive, before any download or write", async () => {
  const drive = new Directory();
  await writeFile(drive, "START_HERE.html", "My homepage");
  const conflict = error => error instanceof DrivePathConflict && error.entry === "a different file named START_HERE.html";
  await assert.rejects(inspectDrive(drive), conflict);
  await assert.rejects(reconcile(drive, options({a: "bytes"}, {fullVerify: true,
    prepareSources: () => assert.fail("source metadata must not be fetched"),
    fetchFile: () => assert.fail("content must not be fetched")})), conflict);
  assert.deepEqual([...drive.entries.keys()], ["START_HERE.html"]);
  assert.equal(await text(drive, "START_HERE.html"), "My homepage");
});

test("the reserved entry paths report a file named LIBRARY or a folder named START_HERE.html", async () => {
  const file = new Directory(), folder = new Directory();
  await writeFile(file, "LIBRARY", "personal");
  await folder.getDirectoryHandle("START_HERE.html", {create: true});
  await assert.rejects(inspectDrive(file), error => error instanceof DrivePathConflict && /file named LIBRARY/.test(error.message));
  await assert.rejects(inspectDrive(folder), error => error instanceof DrivePathConflict && /folder named START_HERE.html/.test(error.message));
});

test("Check every file saves same-length changes and verifies the rebuilt start page and build report", async () => {
  const drive = new Directory();
  const selection = options({book: "verified content"});
  await reconcile(drive, selection);
  const pages = ["START_HERE.html", "LIBRARY/BUILD_REPORT.html"];
  const originals = await Promise.all(pages.map(path => text(drive, path)));
  const changes = originals.map(page => "!" + page.slice(1));
  for (const [index, path] of pages.entries()) {
    await writeFile(drive, path, changes[index]);
    assert.equal(Buffer.byteLength(changes[index]), Buffer.byteLength(originals[index]));
  }
  const result = await reconcile(drive, {...selection, fullVerify: true,
    fetchFile: () => assert.fail("the verified book must not be fetched again")});
  assert.equal(result.state.finished, true);
  assert.deepEqual(result.repairedPages.map(row => row.path).sort(), pages.toSorted());
  const checksums = (await text(drive, "LIBRARY/SHA256SUMS.txt")).split("\n");
  for (const {path, copy} of result.repairedPages) {
    const index = pages.indexOf(path);
    assert.match(copy, /\.changed-\d{4}-\d{2}-\d{2}-[a-f\d]+\.html$/);
    assert.equal(await text(drive, copy), changes[index]);
    assert.equal(await text(drive, path), originals[index]);
    assert.ok(checksums.includes(hash(originals[index]) + "  " + path));
    assert.ok(!checksums.some(line => line.endsWith("  " + copy)));
  }
});

test("Check every file leaves a personal build report untouched even on an OWL drive", async () => {
  const drive = new Directory();
  const selection = options({book: "content"});
  await reconcile(drive, selection);
  const report = "LIBRARY/BUILD_REPORT.html";
  const record = await readBuild(drive);
  record.generated = record.generated.filter(path => path !== report);
  delete record.generatedPins[report];
  await writeFile(drive, MANIFEST, JSON.stringify(record));
  await writeFile(drive, report, "personal report");
  await assert.rejects(reconcile(drive, {...selection, fullVerify: true}), /existing file blocks/);
  assert.equal(await text(drive, report), "personal report");
  assert.ok(![...(await drive.getDirectoryHandle("LIBRARY")).entries.keys()].some(path => path.includes(".changed-")));
});

test("FAT32 migration can join a 2 GiB archive when there is room and keeps a 5 GiB archive in parts", async () => {
  const GiB = 2 ** 30;
  const drive = new Directory();
  const archive = (id, size) => ({...item(id, id), format: "zim", destination: "ZIM/" + id + ".zim", size_bytes: size * GiB});
  const assets = [archive("fits", 2), archive("split", 5)];
  const installed = {};
  for (const asset of assets) {
    const layout = partLayout(asset);
    for (const part of layout) {
      await writeFile(drive, part.path, "");
      // Only the file size is queried for an already verified, settled build.
      (await drive.file(part.path)).bytes = {size: part.bytes};
    }
    installed[asset.id] = {asset, pin: pin(asset), layout, parts: layout.map(part => ({bytes: part.bytes, sha256: asset.sha256}))};
  }
  await writeFile(drive, MANIFEST, JSON.stringify({version: 2, buildId: "fat32", plan: assets.map(pin),
    excluded: [], installed, working: {}, generated: [], owned: Object.values(installed).flatMap(row => row.layout.map(part => part.path)),
    parts: {}, verified: {}, dropped: {}, failures: {}, partBytes: GiB, finished: true,
    choice: {kind: "recommended", split: true}}));
  const plan = {assets, fat32: true, archiveSpace: 16 * GiB};
  const short = await compareLibrary(drive, {...plan, freeBytes: 2 * GiB - 1});
  assert.deepEqual(short.joins, []);
  const room = await compareLibrary(drive, {...plan, freeBytes: 8 * GiB});
  assert.deepEqual(room.adds, []);
  assert.deepEqual(room.joins.map(row => row.asset.id), ["fits"]);
  assert.deepEqual(room.present.find(row => row.asset.id === "split").layout.map(part => part.path),
    ["aa", "ab", "ac", "ad", "ae"].map(part => "LIBRARY/ZIM/split.zim" + part));
});

test("a sync records the choice before waiting for download metadata", async () => {
  const drive = new Directory(), controller = new AbortController();
  const choice = {kind: "custom", edits: {a: {included: true}}, split: false};
  const selection = options({a: "content"}, {choice, signal: controller.signal, prepareSources: async () => {
    const record = await readBuild(drive);
    assert.deepEqual(record.choice, choice);
    assert.equal(record.pending, true);
    controller.abort();
    controller.signal.throwIfAborted();
  }});
  await assert.rejects(reconcile(drive, selection), {name: "AbortError"});
  assert.equal((await readBuild(drive)).pending, true);
});

test("a user file that blocks a library subfolder stops the sync without overwriting it", async () => {
  const drive = new Directory();
  await writeFile(drive, "LIBRARY/BOOKS", "original bytes");
  await assert.rejects(reconcile(drive, options({a: "new"})), /existing file or folder blocks/);
  assert.equal(await text(drive, "LIBRARY/BOOKS"), "original bytes");
});

function generationOptions(id) {
  const template = name => readFileSync(new URL("../src/owl/templates/" + name, import.meta.url), "utf8");
  const {categories, other} = JSON.parse(readFileSync(new URL("../src/owl/categories.json", import.meta.url)));
  const retained = item("shared", "same content");
  const data = "globalThis.OWLTestShard();\n";
  const chunk = "chunks/" + hash(data) + ".js";
  const selection = options({[id]: id + " content", shared: "same content"}, {
    catalogVersion: id,
    navigation: {reader: {
      assets: {[id]: {category: "health"}, shared: {category: "reference"}},
      categories: [...categories, other], layout: JSON.parse(template("offline-layout.json")),
      css: template("site.css"), reader: template("reader.html"), document: template("reader-document.html"),
      runtime: template("reader.js"), bootstrap: template("search.js"), readme: template("reader-readme.txt"),
      redirect: template("search.html"), csp: "default-src 'none'; script-src 'self' file:; style-src 'unsafe-inline'"
    }},
    search: {base: "https://example.test/", records: [], page: "", runtime: "", rankRuntime: "", rerankRuntime: "",
      plan: {version: 1, model: [], model_parts: 0, reserve: 0,
        sources: [{row: {id: retained.id, title: retained.title, sha256: retained.sha256}, parts: [chunk], sha256: hash(data)}],
        chunks: {[chunk]: {pin: {bytes: Buffer.byteLength(data), sha256: hash(data)}, rank: {path: chunk}}}
      }}
  });
  const fetch = selection.fetchFile;
  selection.fetchFile = async url => url.endsWith(chunk) ? new Response(data) : fetch(url);
  return {selection, shared: "LIBRARY/SEARCH/" + chunk};
}

test("a completed reader and its search and checksums stay active through a deferred update and pause", async () => {
  const {selection, shared} = generationOptions("original");
  const drive = new Directory();
  const added = Object.fromEntries(["a-relay", "b-relay", "c-relay", "x-direct", "z-direct"].map(id => [id, id]));
  const update = options(added);
  const relay = "https://relay.test/assets/";
  for (const id of Object.keys(added).filter(id => id.endsWith("-relay"))) update.routes[id] = [relay + id];
  const probeURL = "https://example.test/.nojekyll";
  let down = true, repeated = 0;
  const fetchFile = async (url, request = {}) => {
    if (url.startsWith(relay)) {
      if (down) throw new TypeError("Unavailable relay response without CORS");
      return new Response(url.split("/").at(-1));
    }
    if (request.method === "HEAD") return new Response(null, {status: 204});
    if (url.endsWith("/x-direct")) repeated++;
    return Object.keys(added).some(id => url.endsWith("/" + id)) ? update.fetchFile(url) : selection.fetchFile(url);
  };
  const original = await reconcile(drive, selection);
  const published = new Map(await Promise.all(original.state.generated.map(async path => [path, await text(drive, path)])));
  const controller = new AbortController();
  const updating = {...selection, assets: [...selection.assets, ...update.assets], catalogVersion: "new",
    routes: {...selection.routes, ...update.routes}, fetchFile};
  await assert.rejects(reconcile(drive, {...updating, signal: controller.signal,
    network: createNetwork({fetchFile, probeURL, signal: controller.signal, retryMs: 0}),
    onProgress(event) {
      if (event.kind === "downloading" && event.asset.id === "z-direct") controller.abort();
    }}), {name: "AbortError"});
  const saved = await readBuild(drive);
  assert.equal(saved.pending, true);
  assert.deepEqual(saved.relayDeferred, ["a-relay", "b-relay", "c-relay"]);
  assert.deepEqual(Object.keys(saved.installed), Object.keys(original.state.installed));
  assert.equal(saved.verified["x-direct"], true);
  assert.ok(published.has(shared));
  for (const [path, contents] of published) assert.equal(await text(drive, path), contents, path);
  await openGeneration(drive, "original");

  const network = createNetwork({fetchFile, probeURL, retryMs: 0});
  const resumed = await reconcile(drive, {...updating, network, onProgress(event) {
    if (event.kind === "waiting-relay") {
      // Let the next probe recover without changing the active generation.
      down = false;
      event.tryNow();
    }
  }});
  assert.equal(resumed.state.finished, true);
  assert.equal(repeated, 1, "the completed direct download survived the paused and deferred passes");
  assert.equal(resumed.completed.length, updating.assets.length);
});

test("Check every file preserves changes across generated reports, inventory, reader, and search", async () => {
  const {selection, shared} = generationOptions("generated");
  selection.navigation.verify = "# OWL Verify fixture\n";
  selection.navigation.atlas = true;
  const model = "globalThis.OWLModel();\n";
  const phone = "Fixture phone PDF";
  const volume = "wikimed-fixture.pdf";
  const phoneFolder = "CRITICAL/MEDICAL/WIKIMED-PHONE/";
  selection.search.runtime = "globalThis.OWLSearch();\n";
  selection.search.rankRuntime = "globalThis.OWLRank();\n";
  selection.search.plan.model = [["model.js", {bytes: model.length, sha256: hash(model)}]];
  selection.navigation.phone = {source_id: "generated", source_sha256: selection.assets[0].sha256,
    base: "https://example.test/phone/", destination: phoneFolder,
    volumes: [{file: volume, title: "Fixture", bytes: phone.length, sha256: hash(phone)}]};
  const fetch = selection.fetchFile;
  selection.fetchFile = async url => {
    if (url.endsWith("/model.js")) return new Response(model);
    if (url.endsWith("/" + volume)) return new Response(phone);
    return fetch(url);
  };
  const drive = new Directory();
  const first = await reconcile(drive, selection);
  const paths = first.state.generated;
  for (const required of ["START_HERE_FOR_IPHONES.pdf", "LIBRARY/BUILD_INFO.json", "LIBRARY/INVENTORY.json", "LIBRARY/SOURCE_NOTES.txt",
    "LIBRARY/VERIFY.py", "LIBRARY/INDEX/navigation-report.json", "LIBRARY/SEARCH/manifest.js", "LIBRARY/SHA256SUMS.txt",
    "LIBRARY/SEARCH/shared/" + hash(model) + ".js", "LIBRARY/" + phoneFolder + volume, shared]) {
    assert.ok(paths.includes(required), required);
  }
  const changed = new Map();
  for (const path of paths) {
    const edit = await bytes(drive, path);
    // Change one byte without altering the size of text or binary files.
    edit[0] ^= 1;
    changed.set(path, edit);
    await writeFile(drive, path, edit);
  }
  const result = await reconcile(drive, {...selection, fullVerify: true});
  assert.equal(result.state.finished, true);
  assert.deepEqual(result.repairedPages.map(row => row.path).sort(), [...paths].sort());
  const checksums = (await text(drive, "LIBRARY/SHA256SUMS.txt")).trim().split("\n");
  for (const {path, copy, retired} of result.repairedPages) {
    assert.match(copy, /\.changed-/);
    assert.deepEqual(await bytes(drive, copy), changed.get(path));
    if (retired) await assert.rejects(drive.file(path), {name: "NotFoundError"});
  }
  for (const line of checksums) {
    const [digest, path] = line.split("  ");
    assert.equal(hash(await bytes(drive, path)), digest, path);
  }
  await openGeneration(drive, "generated");
});

test("Check every file keeps the original index answering a query after two search-build.json 503s", async () => {
  const drive = new Directory();
  const {selection} = generationOptions("guide");
  selection.search.records = [{kind: "document", id: "doc-guide", asset_id: "guide",
    title: "Emergency water treatment", href: "BOOKS/guide.pdf"}];
  const preview = {drive, id: "original"};
  const first = await reconcile(drive, {...selection, onPublished: files => { preview.files = files; }});
  const firstGeneration = await openGeneration(drive, "guide");
  const original = new Map(await Promise.all(first.state.generated.map(async path => [path, await text(drive, path)])));
  let requests = 0;
  const network = createNetwork({fetchFile: selection.fetchFile, retryMs: 0});
  const result = await reconcile(drive, {...selection, fullVerify: true, network,
    prepareSources: assets => prepareDownloadSources(assets, {routes: selection.routes, network,
      async read(url) {
        assert.equal(url, "./search-build.json");
        requests++;
        const response = new Response(null, {status: 503});
        if (!response.ok) throw new SourceError("Could not load " + url, {status: response.status});
      }}),
    onPublished: () => assert.fail("the incomplete replacement must not be published")});
  assert.equal(requests, 2);
  assert.equal(result.state.finished, false);
  assert.equal(result.state.pending, true);
  assert.equal((await readBuild(drive)).updateSupportMissing[0].reason, "Could not load ./search-build.json");
  assert.match(completionState(result).message, /The previous library is still on the drive/);
  for (const [path, contents] of original) assert.equal(await text(drive, path), contents, path);
  assert.equal(await openGeneration(drive, "guide"), firstGeneration);

  const load = async path => (await readPreviewFile(preview, preview.id, path)).text();
  const context = {};
  context.OWLDiscoveryManifest = manifest => { context.manifest = manifest; };
  context.OWLDiscoveryData = payload => { context.payload = payload; };
  const index = "LIBRARY/INDEX/" + firstGeneration + "/";
  runInNewContext(await load(index + "search.js"), context);
  runInNewContext(await load(index + "manifest.js"), context);
  runInNewContext(await load("LIBRARY/" + context.manifest.path), context);
  const matches = context.OWLDiscovery.search(context.OWLDiscovery.prepare(context.payload.records), "water treatment");
  assert.equal(matches[0].record.href, "BOOKS/guide.pdf");

  const retry = await reconcile(drive, {...selection, fetchFile: () => assert.fail("reuse the verified files")});
  assert.equal(retry.state.finished, true);
  assert.equal((await readBuild(drive)).updateSupportMissing, undefined);
});

test("an incomplete search replacement keeps the existing fixed-name model and the published checksums", async () => {
  const drive = new Directory();
  const {selection} = generationOptions("original");
  const model = "verified model";
  const fetch = selection.fetchFile;
  selection.search.plan.model = [["model.js", {bytes: model.length, sha256: hash(model)}]];
  selection.fetchFile = async url => url.endsWith("/model.js") ? new Response(model) : fetch(url);
  await reconcile(drive, selection);
  const checksums = await text(drive, "LIBRARY/SHA256SUMS.txt");
  const update = structuredClone(selection.search);
  const replacement = "replacement model";
  update.plan.model = [["model.js", {bytes: replacement.length, sha256: hash(replacement)}],
    ["model-license.txt", {bytes: 1, sha256: hash("x")}]];
  const requests = [];
  const fetchFile = async url => {
    requests.push(new URL(url).pathname);
    return url.endsWith("/model.js") ? new Response(replacement) : new Response(null, {status: 503});
  };
  const result = await reconcile(drive, {...selection, search: update, fetchFile, network: createNetwork({fetchFile, retryMs: 0})});
  assert.deepEqual(requests, ["/model.js", "/model-license.txt", "/model-license.txt"]);
  assert.equal(result.keptPublished, true);
  assert.equal(await text(drive, "LIBRARY/SHA256SUMS.txt"), checksums);
  assert.equal(await text(drive, "LIBRARY/SEARCH/model.js"), model);
  await openGeneration(drive, "original");
});

async function openGeneration(drive, book) {
  const start = await text(drive, "START_HERE.html");
  const [, id] = /<script defer src="LIBRARY\/INDEX\/([a-f0-9]{12})\/search\.js"/.exec(start) || [];
  assert.ok(id, "START_HERE links to a content-named reader");
  assert.ok(start.includes("LIBRARY/BOOKS/" + book + ".pdf"));
  const generation = await (await (await drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle("INDEX")).getDirectoryHandle(id);
  const names = [...generation.entries.keys()].filter(name => name.endsWith(".js")).sort();
  for (const required of ["search.js", "reader.js", "home.js", "c-health.js", "manifest.js", "shards.js", "search-paths.js"]) {
    assert.ok(names.includes(required), required + " is present in the linked generation");
  }
  assert.match(await text(generation, "c-health.js"), new RegExp("/" + book + "\\.pdf"));
  const pins = await Promise.all(names.map(async name => [name, hash(await text(generation, name))]));
  assert.equal(hash(JSON.stringify(pins)).slice(0, 12), id, "every reader script and data file matches the start page");
  const manifest = await text(generation, "manifest.js");
  const [, dataPath] = /"path":"([^"]+)"/.exec(manifest) || [];
  assert.ok(dataPath);
  await text(drive, "LIBRARY/" + dataPath);
  return id;
}

test("Try it opens the published start page, reader scripts and books from the selected drive", async () => {
  const drive = new Directory();
  const preview = {drive, id: "this-sync"};
  await reconcile(drive, {...generationOptions("guide").selection, onPublished: files => { preview.files = files; }});
  const open = path => readPreviewFile(preview, preview.id, path);
  const start = await open("START_HERE.html");
  assert.match(start.headers.get("Content-Type"), /^text\/html/);
  const script = /<script defer src="([^"]+)"/.exec(await start.text())[1];
  assert.equal(await (await open(script)).text(), await text(drive, script));
  const book = await open("LIBRARY/BOOKS/guide.pdf");
  assert.equal(book.headers.get("Content-Type"), "application/pdf");
  assert.equal(await book.text(), "guide content");
  assert.equal((await open(MANIFEST)).status, 404);
  assert.equal((await readPreviewFile(preview, "different-sync", "START_HERE.html")).status, 404);
  await writeFile(drive, script, "// changed after the build");
  assert.equal((await open(script)).status, 404);
});

test("reader generation stays consistent when interrupted at every assembly write", async () => {
  const old = generationOptions("original"), next = generationOptions("updated");
  const update = {...next.selection, fetchFile: url => {
    assert.equal(new URL(url).pathname, "/updated", "reuse the stored search shard");
    return next.selection.fetchFile(url);
  }};
  const writes = [];
  async function fixture(beforeWrite) {
    const drive = new Directory("drive", {beforeWrite});
    await reconcile(drive, old.selection);
    return {drive, oldId: await openGeneration(drive, "original"), oldChecksums: await text(drive, "LIBRARY/SHA256SUMS.txt")};
  }
  let assembling = false;
  const sample = await fixture(name => { if (assembling) writes.push(name); });
  await reconcile(sample.drive, {...update, onProgress: ({kind}) => { assembling ||= kind === "assembling"; }});
  assert.ok(writes.includes("START_HERE.html"));
  const startWrite = writes.indexOf("START_HERE.html");

  for (const [stop, expected] of writes.entries()) {
    let position = 0;
    let assembling = false;
    const {drive, oldId, oldChecksums} = await fixture(name => {
      if (assembling && position++ === stop) {
        assert.equal(name, expected);
        throw new DOMException("Interrupted before " + name, "AbortError");
      }
    });
    await assert.rejects(reconcile(drive, {...update, onProgress: ({kind}) => { assembling ||= kind === "assembling"; }}),
      {name: "AbortError"});
    assert.equal((await readBuild(drive)).pending, true);
    const openId = await openGeneration(drive, stop <= startWrite ? "original" : "updated");
    assert.equal(openId === oldId, stop <= startWrite, "which generation opens when interrupted before " + expected);
    if (stop <= startWrite) assert.equal(await text(drive, "LIBRARY/SHA256SUMS.txt"), oldChecksums);
    assert.equal(await text(drive, next.shared), "globalThis.OWLTestShard();\n");
    assembling = false;
    const repaired = await reconcile(drive, {...update, fetchFile: () => assert.fail("the downloads were already committed")});
    assert.equal(repaired.state.finished, true, "retry finished after interruption before " + expected);
    await openGeneration(drive, "updated");
    const checksums = await text(drive, "LIBRARY/SHA256SUMS.txt");
    for (const line of checksums.trim().split("\n")) {
      const [digest, path] = line.split("  ");
      assert.equal(hash(await bytes(drive, path)), digest, "checksum after retry: " + path);
    }
  }

  const controller = new AbortController();
  let pauseDuringPublication = false;
  const {drive, oldId} = await fixture(name => { if (pauseDuringPublication && name === "SHA256SUMS.txt") controller.abort(); });
  const oldPath = "LIBRARY/INDEX/" + oldId;
  await writeFile(drive, oldPath + "/owner-note.txt", "keep");
  pauseDuringPublication = true;
  await assert.rejects(reconcile(drive, {...update, signal: controller.signal}), {name: "AbortError"});
  assert.notEqual(await openGeneration(drive, "updated"), oldId);
  assert.equal((await readBuild(drive)).pending, true);
  assert.ok(await text(drive, oldPath + "/search.js"), "cleanup has not started");
  await writeFile(drive, oldPath + "/c-culture.js", "owner changed this file");
  pauseDuringPublication = false;
  const result = await reconcile(drive, {...update, fetchFile: () => assert.fail("all pinned files are already on the drive")});
  assert.equal(result.state.finished, true);
  await openGeneration(drive, "updated");
  assert.equal(result.state.generated.some(path => path.startsWith(oldPath + "/")), false);
  assert.equal(await text(drive, oldPath + "/owner-note.txt"), "keep");
  assert.equal(await text(drive, oldPath + "/c-culture.js"), "owner changed this file");
  const index = await (await drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle("INDEX");
  assert.deepEqual([...((await index.getDirectoryHandle(oldId)).entries.keys())].sort(), ["c-culture.js", "owner-note.txt"]);
  assert.equal([...index.entries.keys()].filter(name => name !== oldId).length, 1);
  const sampleIndex = await (await sample.drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle("INDEX");
  await assert.rejects(sampleIndex.getDirectoryHandle(sample.oldId), {name: "NotFoundError"});
});

test("an adopted reader generation remains recorded across an interrupted publication", async () => {
  let cut = false;
  const drive = new Directory("drive", {beforeWrite(name) {
    if (cut && name === "START_HERE.html") throw new DOMException("Interrupted before publication", "AbortError");
  }});
  await reconcile(drive, generationOptions("original").selection);
  await removeFile(drive, MANIFEST);
  const oldId = await openGeneration(drive, "original");
  const update = generationOptions("updated").selection;
  assert.equal((await compareLibrary(drive, update)).adoption, true);
  cut = true;
  await assert.rejects(reconcile(drive, update), {name: "AbortError"});
  assert.equal(await openGeneration(drive, "original"), oldId);
  assert.ok((await readBuild(drive)).generated.includes("LIBRARY/INDEX/" + oldId + "/search.js"));
  cut = false;
  await reconcile(drive, {...update, fetchFile: () => assert.fail("all requested files are already on the drive")});
  await openGeneration(drive, "updated");
  await assert.rejects(drive.file("LIBRARY/INDEX/" + oldId + "/search.js"), {name: "NotFoundError"});
});

test("an active reader must exist and match the current reader, navigation and search revision", async () => {
  const drive = new Directory();
  const {selection} = generationOptions("original");
  const {navigation, search} = selection;
  const settings = {...selection, readerPublication: "release-one"};
  await reconcile(drive, settings);
  assert.equal((await compareLibrary(drive, settings)).current, true);
  for (const edit of [
    {navigation: {...navigation, input_hashes: {topics: "changed"}}},
    {navigation: {...navigation, reader: {...navigation.reader, bootstrap: "changed"}}},
    {search: {...search, rankRuntime: "changed"}},
    {readerPublication: "release-two"}
  ]) assert.equal((await compareLibrary(drive, {...settings, ...edit})).current, false);
  const generation = await openGeneration(drive, "original");
  await removeFile(drive, "LIBRARY/INDEX/" + generation + "/search.js");
  assert.equal((await compareLibrary(drive, settings)).current, false);
});
