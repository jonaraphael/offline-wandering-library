import assert from "node:assert/strict";
import {createHash, webcrypto} from "node:crypto";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {compareLibrary, MANIFEST, readBuild, reconcile} from "../web/builder.mjs";
import {removeFile, writeFile} from "../web/drive.mjs";
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
    return {drive, oldId: await openGeneration(drive, "original")};
  }
  let assembling = false;
  const sample = await fixture(name => { if (assembling) writes.push(name); });
  await reconcile(sample.drive, {...update, onProgress: ({kind}) => { assembling ||= kind === "assembling"; }});
  assert.ok(writes.includes("START_HERE.html"));
  const startWrite = writes.indexOf("START_HERE.html");

  for (const [stop, expected] of writes.entries()) {
    let position = 0;
    let assembling = false;
    const {drive, oldId} = await fixture(name => {
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
    assert.equal(await text(drive, next.shared), "globalThis.OWLTestShard();\n");
  }

  const controller = new AbortController();
  let cutAfterStart = false;
  const {drive, oldId} = await fixture(name => { if (cutAfterStart && name === "START_HERE.html") controller.abort(); });
  const oldPath = "LIBRARY/INDEX/" + oldId;
  await writeFile(drive, oldPath + "/owner-note.txt", "keep");
  cutAfterStart = true;
  await assert.rejects(reconcile(drive, {...update, signal: controller.signal}), {name: "AbortError"});
  assert.notEqual(await openGeneration(drive, "updated"), oldId);
  assert.equal((await readBuild(drive)).pending, true);
  assert.ok(await text(drive, oldPath + "/search.js"), "cleanup has not started");
  cutAfterStart = false;
  const result = await reconcile(drive, {...update, fetchFile: () => assert.fail("all pinned files are already on the drive")});
  assert.equal(result.state.finished, true);
  await openGeneration(drive, "updated");
  assert.equal(result.state.generated.some(path => path.startsWith(oldPath + "/")), false);
  assert.equal(await text(drive, oldPath + "/owner-note.txt"), "keep");
  const index = await (await drive.getDirectoryHandle("LIBRARY")).getDirectoryHandle("INDEX");
  assert.deepEqual([...((await index.getDirectoryHandle(oldId)).entries.keys())], ["owner-note.txt"]);
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
