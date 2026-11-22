import assert from "node:assert/strict";
import {createHash, webcrypto} from "node:crypto";
import {test} from "node:test";
import {compareLibrary, MANIFEST, readBuild, reconcile} from "../web/builder.mjs";
import {writeFile} from "../web/drive.mjs";
import {Directory} from "./browser-drive-fixture.mjs";

globalThis.crypto ||= webcrypto;
const hash = body => createHash("sha256").update(body).digest("hex");
const item = (id, body) => ({id, title: id, destination: "BOOKS/" + id + ".pdf", format: "pdf",
  size_bytes: Buffer.byteLength(body), sha256: hash(body), utility_tier: "USEFUL"});
const path = file => "LIBRARY/" + file.destination;
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

test("an unrelated start page is never overwritten", async () => {
  const drive = new Directory();
  await writeFile(drive, "START_HERE.html", "My homepage");
  await assert.rejects(reconcile(drive, options({a: "bytes"})), /existing file blocks/);
  assert.equal(await text(drive, "START_HERE.html"), "My homepage");
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
