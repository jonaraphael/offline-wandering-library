import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash, webcrypto} from "node:crypto";
import {createServer} from "node:http";
import {once} from "node:events";
import {test} from "node:test";
import {archiveJoinLimitReached, browserSelection, buildLibrary as runBuild, MANIFEST, partLayout, readBuild} from "../web/builder.mjs";
import {assembleLibrary} from "../web/offline.mjs";
import {measureFreeSpace, writeFile} from "../web/drive.mjs";
import {createNetwork} from "../web/network.mjs";
import {Directory} from "./browser-drive-fixture.mjs";
import {archiveDriveOptions, completionState, estimateLabelCapacity, prepareDownloadSources, probesCapacity, relayLimitMessage,
  reportedDriveCapacity, slowRouteMessage, warnBeforeLeaving} from "../web/builder-ui.mjs";
import {createRelayWait, RELAY_WAIT_MESSAGE} from "../web/relay-wait.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;
const hash = data => createHash("sha256").update(data).digest("hex");
function asset(id, body, fields = {}) {
  return {id, title: "File " + id, format: "pdf", destination: "BOOKS/" + id + ".pdf",
    size_bytes: body.length, sha256: hash(body), redistributable: true, utility_tier: "USEFUL", ...fields};
}

function readerNavigation(assets, extra = {}) {
  const template = file => readFileSync(new URL("../src/owl/templates/" + file, import.meta.url), "utf8");
  const categories = JSON.parse(readFileSync(new URL("../src/owl/categories.json", import.meta.url)));
  return {...extra, reader: {assets, categories: [...categories.categories, categories.other],
    layout: JSON.parse(template("offline-layout.json")), css: template("site.css"), reader: template("reader.html"),
    document: template("reader-document.html"), runtime: template("reader.js"), bootstrap: template("search.js"),
    readme: template("reader-readme.txt"), redirect: template("search.html"),
    csp: "default-src 'none'; script-src 'self' file:; style-src 'unsafe-inline'"}};
}

async function readReaderFile(drive, name) {
  const start = await (await (await drive.file("START_HERE.html")).getFile()).text();
  const generation = start.match(/src="(LIBRARY\/INDEX\/[a-f0-9]{12})\/search\.js"/)?.[1];
  assert.ok(generation);
  return (await (await drive.file(generation + "/" + name)).getFile()).text();
}

function readerData(script, id) {
  const prefix = "globalThis.OWLReaderData(" + JSON.stringify(id) + ",";
  assert.ok(script.startsWith(prefix) && script.endsWith(");\n"));
  return JSON.parse(script.slice(prefix.length, -3));
}

function buildLibrary(drive, options) {
  if (!options.search) return runBuild(drive, options);
  const {manifest, ...config} = options.search;
  const chunks = {};
  const sources = options.assets.flatMap(asset => {
    const shard = manifest.sources[asset.sha256];
    if (!shard) return [];
    const paths = [];
    const add = (pool, pin, number) => {
      const path = "sources/" + pool + "/" + String(number).padStart(5, "0") + ".js";
      chunks[path] = {pin, rank: {pool, number, bloom: pin.bloom, vectors: pin.vectors}};
      paths.push(path);
    };
    for (const pool of shard.shared || []) manifest.shared[pool].parts.forEach((pin, number) => add(pool, pin, number));
    (shard.parts || []).forEach((pin, number) => add(asset.sha256, pin, number));
    const {id, title, category, sha256, source_url = "", format} = asset;
    return [{row: {id, title, category, sha256, format, critical: Boolean(asset.critical),
      discussion: source_url.includes("/stack_exchange/"), records: shard.records},
      parts: paths, sha256: shard.sha256}];
  });
  const weights = manifest.model_parts || [];
  const model = [["model.js", manifest.model], ["model-license.txt", manifest.license],
    ...weights.map((pin, i) => ["model/" + String(i).padStart(2, "0") + ".js", pin])];
  return runBuild(drive, {...options, search: {...config, plan: {
    version: manifest.version, model_parts: weights.length, reserve: 64_000, model, sources, chunks
  }}});
}

async function httpFixture(t, handle) {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push({path: request.url, range: request.headers.range, origin: request.headers.origin});
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Expose-Headers", "Content-Range");
    handle(request, response);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  return {requests, url: suffix => "http://127.0.0.1:" + server.address().port + suffix,
    fetchFile: (url, options) => fetch(url, {...options, headers: {...options.headers, Origin: "https://example.github.io"}})};
}

function sendRange(request, response, content, {interrupt = false, wrongRange = false} = {}) {
  const [, from, to] = /^bytes=(\d+)-(\d+)$/.exec(request.headers.range);
  const data = content.subarray(Number(from), Number(to) + 1);
  response.writeHead(206, {"Content-Range": "bytes " + (wrongRange ? 0 : from) + "-" + to + "/" + content.length,
    "Content-Length": data.length});
  if (interrupt) response.write(data.subarray(0, 1), () => response.destroy());
  else response.end(data);
}

test("capacity probe runs on macOS and Windows and leaves Linux to label confirmation", () => {
  for (const platform of ["MacIntel", "macOS", "Win32", "Windows"]) assert.equal(probesCapacity(platform), true, platform);
  for (const platform of ["Linux x86_64", "Linux", "", undefined]) assert.equal(probesCapacity(platform), false, String(platform));
  assert.equal(probesCapacity("", "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0.0.0"), false);
  assert.equal(estimateLabelCapacity(128e9), 115.2e9);
});

test("changing the saved storage limit replaces a pending sync's search budget", async () => {
  const drive = new Directory();
  const body = Buffer.from("verified knowledge file");
  const doc = asset("doc", body);
  const initial = {kind: "recommended", split: false, limitBytes: 8e9};
  const options = {assets: [doc], capacityBytes: 59.6e9, catalogVersion: "one", singleArchives: true,
    routes: {doc: ["https://example.test/doc"]}, fetchFile: async () => new Response(body)};
  await assert.rejects(runBuild(drive, {...options, choice: initial, searchBudget: 100e6,
    prepareSources: async () => { throw Error("Interrupted before downloading"); }}), /Interrupted/);
  const pending = await readBuild(drive);
  assert.equal(pending.pending, true);
  assert.deepEqual(pending.choice, initial);

  const reduced = {kind: "recommended", split: false, limitBytes: 1e9};
  const result = await runBuild(drive, {...options, choice: reduced, searchBudget: 16 * MiB});
  assert.equal(result.state.finished, true);
  const saved = await readBuild(drive);
  assert.deepEqual(saved.choice, reduced);
  assert.equal(saved.capacityBytes, 59.6e9);
  assert.equal(saved.searchBudget, 16 * MiB);
});

test("native allocation probe estimates to one MiB and removes the swap placeholder", async () => {
  for (const name of ["QuotaExceededError", "InvalidStateError"]) {
    const free = 26 * GiB + 12345;
    let aborts = 0;
    const drive = new Directory("drive", {truncate: length => {
      if (length > free) throw new DOMException("Cannot set length", name);
    }, onAbort: () => aborts++});
    // This fake gives every file the whole free space, so measure one file;
    // tests/capacity-probe.test.mjs covers space shared across files.
    const result = await measureFreeSpace(drive, {maxFiles: 1});
    assert.equal(result.kind, "measured");
    assert.ok(result.bytes <= free && free - result.bytes <= MiB);
    assert.equal(drive.entries.size, 0);
    assert.ok(aborts <= 27, "number of probe attempts including repeats");
  }
});

test("probe falls back for sparse files and when capped files never locate the volume boundary", async () => {
  assert.deepEqual(await measureFreeSpace(new Directory()), {kind: "sparse-or-large", largeFiles: true});
  for (const error of [
    new DOMException("EFBIG", "InvalidStateError"),
    new DOMException("Cannot set length", "InvalidStateError")
  ]) {
    const drive = new Directory("drive", {truncate: length => { if (length > 2 ** 32 - 1) throw error; }});
    assert.deepEqual(await measureFreeSpace(drive, {maxFat32Files: 2}), {kind: "limited", splitArchives: true});
    assert.equal(drive.entries.size, 0);
  }
  const denied = new Directory("drive", {truncate: () => { throw new DOMException("Denied", "NotAllowedError"); }});
  await assert.rejects(measureFreeSpace(denied), {name: "NotAllowedError"});
  assert.equal(denied.entries.size, 0);
});

test("range build resumes after a disrupted stream and only indexes verified files", async t => {
  const content = Buffer.from("ABCDEFGHIJKLM");
  const zim = asset("wiki", content, {format: "zim", destination: "ZIM/wiki.zim"});
  let interrupted = true;
  const {requests, url, fetchFile} = await httpFixture(t, (request, response) => sendRange(request, response, content, {
    interrupt: interrupted && request.headers.range === "bytes=5-9"
  }));
  const drive = new Directory();
  const options = {assets: [zim], routes: {wiki: [url("/wiki")]}, fetchFile, partBytes: 5,
    navigation: readerNavigation({wiki: {category:"health", topics:[["medical","Medicine"]]}})};
  const first = await buildLibrary(drive, options);
  assert.equal(first.completed.length, 0);
  assert.match(first.state.failures.wiki, /Connection or browser access failed/);
  const state = await readBuild(drive);
  assert.equal(state.parts.wiki.length, 1);
  assert.equal(state.parts.wiki[0].sha256, hash(content.subarray(0, 5)));
  assert.doesNotMatch(await (await (await drive.file("START_HERE.html")).getFile()).text(), /LIBRARY\/ZIM\/wiki/);
  const checkpoint = requests.length;
  interrupted = false;
  const finish = await buildLibrary(drive, {...options, resume: true});
  assert.equal(finish.completed.length, 1);
  assert.equal(finish.state.finished, true);
  assert.ok(requests.every(row => row.origin === "https://example.github.io"));
  assert.deepEqual(requests.slice(checkpoint).map(row => row.range), ["bytes=5-9", "bytes=10-12"]);
  const parts = partLayout(zim, 5);
  assert.deepEqual(parts.map(part => part.path), ["LIBRARY/ZIM/wiki.zimaa", "LIBRARY/ZIM/wiki.zimab", "LIBRARY/ZIM/wiki.zimac"]);
  for (const part of parts) {
    const blob = await (await drive.file(part.path)).getFile();
    assert.equal(blob.size, part.bytes);
    assert.equal(await blob.text(), content.subarray(part.start, part.start + part.bytes).toString());
  }
  const sumFile = await (await (await drive.file("LIBRARY/SHA256SUMS.txt")).getFile()).text();
  for (const line of sumFile.trim().split("\n")) {
    const [digest, path] = line.split("  ");
    assert.equal(digest, hash(Buffer.from(await (await (await drive.file(path)).getFile()).arrayBuffer())));
  }

  // A repair verifies a replacement before removing the recorded archive.
  (await drive.file("LIBRARY/ZIM/wiki.zimab")).bytes = new Blob(["wrong"]);
  requests.length = 0;
  await buildLibrary(drive, {...options, resume: true});
  assert.deepEqual(requests, [], "routine resume trusts same-size checkpoints");
  const repaired = await buildLibrary(drive, {...options, fullVerify: true});
  assert.deepEqual(requests.map(row => row.range), ["bytes=0-4", "bytes=5-9", "bytes=10-12"]);
  assert.equal(repaired.state.installed.wiki.pin.sha256, zim.sha256);
});

test("bad range or published digest advances to the byte-identical fallback", async t => {
  const content = Buffer.from("ABCDEFGHIJ");
  const zim = asset("wiki", content, {format: "zim", destination: "ZIM/wiki.zim"});
  const {requests, url, fetchFile} = await httpFixture(t, (request, response) => {
    if (request.url === "/bad-digest") sendRange(request, response, Buffer.from("bad!!FGHIJ"));
    else sendRange(request, response, content, {wrongRange: request.url === "/bad-range"});
  });
  const drive = new Directory();
  const entries = [hash(content.subarray(0, 5)), hash(content.subarray(5))];
  const result = await buildLibrary(drive, {assets: [zim], routes: {wiki: [url("/bad-digest"), url("/bad-range"), url("/good")]},
    published: {chunks: {wiki: {part_bytes: 5, sha256: zim.sha256, hashes: entries}}}, fetchFile, partBytes: 5});
  assert.equal(result.completed[0].id, "wiki");
  assert.ok(requests.some(row => row.path === "/good"));
  assert.deepEqual(result.state.parts.wiki.map(part => part.sha256), entries);
});

test("same-origin parts are checked before closing a single ordinary file", async t => {
  const data = Buffer.from("pdf-example");
  const pdf = asset("pdf", data);
  const a = data.subarray(0, 4), b = data.subarray(4);
  const {requests, url, fetchFile} = await httpFixture(t, (request, response) => {
    if (request.url === "/unavailable") { response.writeHead(404); response.end(); }
    else response.end(request.url === "/a" ? a : b);
  });
  const drive = new Directory();
  const published = {files: {pdf: [
    {url: url("/a"), bytes: a.length, sha256: hash(a)}, {url: url("/b"), bytes: b.length, sha256: hash(b)}
  ]}};
  const result = await buildLibrary(drive, {assets: [pdf], routes: {pdf: [url("/unavailable")]}, published, fetchFile});
  assert.equal(result.completed[0].id, "pdf");
  assert.equal(await (await (await drive.file("LIBRARY/BOOKS/pdf.pdf")).getFile()).text(), data.toString());
  assert.deepEqual(requests.map(row => row.path), ["/unavailable", "/a", "/b"]);
});

test("a same-length byte change at close is read back and the file is downloaded again before reporting verified", async () => {
  const body = Buffer.from("pinned PDF");
  const pdf = asset("book", body);
  let writes = 0, requests = 0, verified = 0;
  const drive = new Directory("drive", {async beforeClose(name, bytes) {
    if (name === "book.pdf" && ++writes === 1) {
      const changed = new Uint8Array(await bytes.arrayBuffer());
      changed[0] ^= 1;
      return new Blob([changed]);
    }
  }});
  const result = await runBuild(drive, {assets: [pdf], routes: {book: ["https://example.test/book"]},
    fetchFile: async () => { requests++; return new Response(body); },
    onProgress(event) {
      if (event.kind !== "verified") return;
      assert.equal(requests, 2);
      assert.equal(writes, 2);
      verified++;
    }});
  assert.equal(verified, 1);
  assert.equal(result.state.finished, true);
  assert.equal(await (await (await drive.file("LIBRARY/BOOKS/book.pdf")).getFile()).text(), body.toString());
});

test("archive metadata is skipped for PDFs and a failed request only defers affected encyclopedias", async () => {
  const body = Buffer.from("pinned PDF");
  const book = asset("book", body);
  const smallBody = Buffer.alloc(5 * MiB);
  const small = asset("small", smallBody, {format: "zim", destination: "ZIM/small.zim"});
  const archive = asset("wiki", body, {format: "zim", destination: "ZIM/wiki.zim", size_bytes: GiB + 1});
  const routes = {book: ["https://example.test/book"], wiki: ["https://example.test/wiki.zim"],
    small: ["https://example.test/small.zim"]};
  const requested = [];
  const network = createNetwork({retryMs: 0});
  const read = async url => {
    requested.push(url);
    if (url === "./kiwix-pieces.json") throw Error("Network fixture");
  };
  const prepareSources = assets => prepareDownloadSources(assets, {routes, published: {}, network, read});
  const fetchFile = async url => {
    if (url === routes.small[0]) return new Response(smallBody);
    assert.equal(url, routes.book[0]);
    return new Response(body);
  };
  const pdfOnly = await runBuild(new Directory(), {assets: [book], routes, prepareSources, fetchFile});
  assert.equal(pdfOnly.state.finished, true);
  assert.deepEqual(requested.splice(0), ["./search-build.json"]);
  const mixed = await runBuild(new Directory(), {assets: [book, archive, small], routes, prepareSources, fetchFile});
  assert.deepEqual(requested, ["./search-build.json", "./kiwix-pieces.json"]);
  assert.deepEqual(mixed.completed.map(file => file.id), ["small", "book"]);
  assert.deepEqual(mixed.missing.map(file => file.title), [archive.title]);
  assert.match(mixed.missing[0].reason, /Could not load the checksums for this encyclopedia/);
});

test("a mismatched source is reported and a full drive stops later downloads", async t => {
  const correct = Buffer.from("correct"), corrupt = Buffer.from("corrupt");
  const first = asset("first", correct, {utility_tier: "CRITICAL"});
  const wrong = asset("wrong", correct, {utility_tier: "CRITICAL"});
  const huge = asset("huge", correct);
  const small = asset("small", correct);
  const {url, fetchFile} = await httpFixture(t, (request, response) => response.end(request.url === "/wrong" ? corrupt : correct));
  const drive = new Directory("drive", {beforeWrite: name => {
    if (name === "huge.pdf") throw new DOMException("Disk full", "QuotaExceededError");
  }});
  const routes = Object.fromEntries([first, huge, small, wrong].map(row => [row.id, [url("/" + row.id)]]));
  const result = await buildLibrary(drive, {assets: [huge, small, wrong, first], routes, fetchFile});
  assert.deepEqual(result.completed.map(row => row.id), ["first"]);
  assert.equal(result.state.dropped.huge, "Drive ran out of space");
  assert.match(result.state.failures.wrong, /SHA-256/);
  assert.deepEqual(result.missing.map(row => row.id), ["wrong", "huge", "small"]);
  await assert.rejects(drive.file("LIBRARY/BOOKS/wrong.pdf"), {name: "NotFoundError"});
  await assert.rejects(drive.file("LIBRARY/BOOKS/huge.pdf"), {name: "NotFoundError"});
});

test("a fresh sync writes a start page and reserves space before the first content download", async () => {
  const body = Buffer.from("emergency guide");
  const critical = asset("critical", body, {utility_tier: "CRITICAL"});
  const drive = new Directory();
  await buildLibrary(drive, {assets: [critical], routes: {critical: ["https://example.test/guide"]}, async fetchFile() {
    assert.match(await (await (await drive.file("START_HERE.html")).getFile()).text(), /href="LIBRARY\/"/);
    const library = await drive.getDirectoryHandle("LIBRARY");
    const work = await library.getDirectoryHandle(".owl");
    assert.ok([...work.entries.keys()].some(name => /^assembly-.*\.tmp$/.test(name)));
    return new Response(body);
  }});
  const library = await drive.getDirectoryHandle("LIBRARY");
  assert.ok([...((await library.getDirectoryHandle(".owl")).entries.keys())].every(name => !name.endsWith(".tmp")));
});

test("a fresh start page survives a quota error on the first record and is adopted on retry", async () => {
  const body = Buffer.from("emergency guide");
  const critical = asset("critical", body, {utility_tier: "CRITICAL"});
  let full = true;
  const drive = new Directory("drive", {beforeWrite(name) {
    if (full && name === "browser-build.json") throw new DOMException("Disk full", "QuotaExceededError");
  }});
  const options = {assets: [critical], routes: {critical: ["https://example.test/guide"]}, fetchFile: async () => new Response(body)};
  await assert.rejects(buildLibrary(drive, options), {name: "QuotaExceededError"});
  assert.ok((await (await drive.file("START_HERE.html")).getFile()).size);
  full = false;
  assert.equal((await buildLibrary(drive, options)).state.finished, true);
});

test("an interrupted first record is rebuilt beside OWL's starter without taking ownership of existing files", async () => {
  let stop = true;
  const drive = new Directory("drive", {beforeClose(name, swap) {
    if (stop && name === "browser-build.json") throw new DOMException("Interrupted before close", "AbortError");
    return swap;
  }});
  const pinned = Buffer.from("emergency guide");
  const existing = asset("existing", pinned), blocked = asset("blocked", pinned);
  const assets = [existing, blocked];
  const routes = Object.fromEntries(assets.map(({id}) => [id, ["https://example.test/" + id]]));
  const existingPath = "LIBRARY/" + existing.destination;
  const blockedPath = "LIBRARY/" + blocked.destination;
  await writeFile(drive, existingPath, pinned);
  await writeFile(drive, blockedPath, "emergency Guide");
  const requests = [];
  const options = {assets, routes, async fetchFile(url) { requests.push(url); return new Response(pinned); }};
  await assert.rejects(runBuild(drive, options), {name: "AbortError"});
  assert.equal((await (await drive.file(MANIFEST)).getFile()).size, 0);
  assert.equal(await readBuild(drive), null);
  stop = false;
  const first = await runBuild(drive, options);
  assert.equal(first.state.finished, true);
  assert.deepEqual(requests, routes.blocked, "verify the matching file by hash and redownload the same-size mismatch");
  assert.equal(first.state.installed.existing.protected, true);
  assert.ok(!first.state.owned.includes(existingPath));
  assert.notEqual(first.state.installed.blocked.layout[0].path, blockedPath);
  const committed = await (await drive.file(MANIFEST)).getFile();
  stop = true;
  await assert.rejects(runBuild(drive, options), {name: "AbortError"});
  assert.equal(await (await (await drive.file(MANIFEST)).getFile()).text(), await committed.text());
  stop = false;
  await runBuild(drive, {...options, assets: [blocked]});
  assert.equal(await (await (await drive.file(existingPath)).getFile()).text(), pinned.toString());
  assert.equal(await (await (await drive.file(blockedPath)).getFile()).text(), "emergency Guide");
});

test("malformed first record recovery requires the exact OWL starter", async () => {
  const drive = new Directory();
  await writeFile(drive, MANIFEST, '{"version":');
  await writeFile(drive, "START_HERE.html", "Offline Wandering Library notes");
  await assert.rejects(readBuild(drive), /saved drive record is unreadable/);
  const starterDrive = new Directory("drive", {beforeWrite(name) {
    if (name === "browser-build.json") throw new DOMException("Interrupted", "AbortError");
  }});
  const guide = asset("guide", Buffer.from("guide"));
  await assert.rejects(runBuild(starterDrive, {assets: [guide]}), {name: "AbortError"});
  await writeFile(drive, "START_HERE.html", await (await starterDrive.file("START_HERE.html")).getFile());
  assert.equal(await readBuild(drive), null);
  const result = await runBuild(drive, {assets: [guide], routes: {guide: ["https://example.test/guide"]},
    fetchFile: async () => new Response("guide")});
  assert.equal(result.state.finished, true);
});

test("assembly quota recovery drops the least essential new file and writes the build report", async () => {
  const body = Buffer.from("emergency guide");
  const essential = asset("critical", body, {utility_tier: "CRITICAL", source_url: "https://example.test/guide",
    version: "2026-11", redistributable: false});
  const optional = asset("optional", body, {utility_tier: "NONESSENTIAL"});
  let assembling, ranOut = false;
  const drive = new Directory("drive", {beforeWrite(name) {
    if (assembling && !ranOut && name === "INVENTORY.json") {
      ranOut = true;
      throw new DOMException("Drive is full", "QuotaExceededError");
    }
  }});
  const result = await buildLibrary(drive, {assets: [optional, essential],
    routes: {critical: ["https://example.test/guide"], optional: ["https://example.test/optional"]},
    fetchFile: async () => new Response(body), onProgress: ({kind}) => { assembling ||= kind === "assembling"; }});
  assert.deepEqual(result.completed.map(file => file.id), ["critical"]);
  const readJSON = async name => JSON.parse(await (await (await drive.file("LIBRARY/" + name)).getFile()).text());
  assert.deepEqual(await readJSON("BUILD_INFO.json"), {schema_version: 1, asset_count: 1, selected_count: 2,
    missing: [{id: "optional", title: "File optional", utility_tier: "NONESSENTIAL", reason: "Drive ran out of space"}],
    kept_in_parts: [], content_complete: false, support_complete: true, support_missing: [],
    layout: {entry_page: "START_HERE.html", content_directory: "LIBRARY"}});
  const [{source_url, version, redistributable}] = (await readJSON("INVENTORY.json")).assets;
  assert.deepEqual({source_url, version, redistributable},
    {source_url: essential.source_url, version: essential.version, redistributable: essential.redistributable});
  const retry = await buildLibrary(drive, {assets: [optional, essential], routes: {optional: ["https://example.test/optional"]},
    fetchFile: async () => new Response(body)});
  assert.equal(retry.state.finished, true);
  assert.equal(retry.state.installed.optional.layout[0].path, "LIBRARY/BOOKS/optional.pdf");
});

test("completion distinguishes zero knowledge files, partial content and installed split archives", () => {
  const book = asset("book", Buffer.from("book"));
  const app = asset("app", Buffer.from("app"), {destination: "SOFTWARE/app.zip"});
  const missing = [{utility_tier: "CRITICAL"}, {utility_tier: "NONESSENTIAL"}];
  const outcome = {state: {finished: false}, missing, searchWarnings: [], keptInParts: []};
  assert.deepEqual(completionState({...outcome, completed: [app]}), {
    mode: "failed", title: "Sync could not finish", message: "0 files arrived. 1 essential file missing."});
  assert.deepEqual(completionState({...outcome, completed: [book, app]}), {
    mode: "done-gaps", title: "Ready, with 2 items missing", message: "1 file arrived. 1 essential file missing."});
  assert.deepEqual(completionState({...outcome, state: {finished: true}, completed: [book], missing: [], keptInParts: [{parts: 2}]}),
    {mode: "done", extra: "1 encyclopedia kept in parts."});
});

test("failed Kiwix apps leave the books ready and are reported as missing support", async () => {
  const body = Buffer.from("field guide");
  const book = asset("book", body);
  const app = asset("kiwix_linux", Buffer.from("app"), {title: "Kiwix reader app for Linux", destination: "SOFTWARE/LINUX/kiwix"});
  const drive = new Directory();
  const result = await buildLibrary(drive, {assets: [book, app],
    routes: {book: ["https://example.test/book"], kiwix_linux: ["https://example.test/app"]},
    fetchFile: async url => url.endsWith("/book") ? new Response(body) : new Response(null, {status: 404})});
  assert.deepEqual(result.completed.map(row => row.id), ["book"]);
  const read = async path => (await (await drive.file(path)).getFile()).text();
  const info = JSON.parse(await read("LIBRARY/BUILD_INFO.json"));
  assert.equal(info.content_complete, true);
  assert.equal(info.selected_count, info.asset_count);
  assert.equal(info.support_complete, false);
  assert.deepEqual(info.support_missing, [{kind: "app", id: app.id, title: app.title, reason: "example.test — HTTP 404"}]);
  assert.deepEqual(result.supportMissing, info.support_missing);
  assert.match(await read("LIBRARY/BUILD_REPORT.html"), /Kiwix reader app for Linux/);
  const completion = completionState(result);
  assert.equal(completion.mode, "done-gaps");
  assert.equal(completion.title, "Ready, with 1 item missing");
  assert.match(completion.message, /Kiwix opens the encyclopedias on this drive/);
});

test("free space on a partly full drive is used directly with any space OWL already holds", () => {
  assert.equal(reportedDriveCapacity(4, "GB", 0), 4e9);
  assert.equal(estimateLabelCapacity(16e9), 14.4e9);
  assert.equal(reportedDriveCapacity(4, "GB", 2e9), 6e9);
  assert.equal(reportedDriveCapacity(4.5, "GiB", GiB), 5.5 * GiB);
  assert.equal(reportedDriveCapacity(0, "GB", 0), 0);
  assert.equal(reportedDriveCapacity(NaN, "GB", 0), undefined);
});

test("the relay notice counts 4 MiB archive pieces and one request per smaller relay file", () => {
  const url = "https://relay.test/assets/";
  const routes = {report: [url + "report"], direct: ["https://publisher.test/paper.pdf"]};
  const published = {archiveRelay: {large: [url + "large"], finished: [url + "finished"]}};
  const row = (id, format, bytes) => ({asset: {id, format}, bytes});
  const borderline = [row("large", "zim", 80_000 * 4 * MiB), row("finished", "zim", 0),
    row("direct", "pdf", MiB), row("same-origin", "zim", 1e12)];
  assert.equal(relayLimitMessage(borderline, routes, published), "");
  assert.match(relayLimitMessage([...borderline, row("report", "pdf", MiB)], routes, published), /more than a day/);
  assert.match(relayLimitMessage([row("large", "zim", 80_000 * 4 * MiB + 1)], routes, published), /no daily download limit/);
});

function relayFixture(rangeStatus = 502) {
  const body = Buffer.from("verified guide");
  const relay = "https://relay.test/assets/";
  const direct = "https://publisher.test/guide";
  const page = "https://pages.test/.nojekyll";
  const ids = ["a-relay", "b-relay", "c-relay", "d-relay", "x-mixed", "z-direct"];
  const assets = ids.map(id => asset(id, body));
  const routes = Object.fromEntries(ids.slice(0, 5).map(id => [id, [relay + id]]));
  routes["x-mixed"].push(direct);
  routes["z-direct"] = [direct];
  const drive = new Directory();
  const requests = [];
  let down = true, offline = false, throttle = false, headStatus = 200;
  async function fetchFile(url, {method, mode, headers} = {}) {
    requests.push({url, method, mode, range: headers?.Range});
    if (offline) throw new TypeError("The whole network is offline");
    if (url.startsWith(relay)) {
      if (down) throw new TypeError("The platform error page has no CORS header");
      if (throttle) {
        throttle = false;
        return new Response(null, {status: 429, headers: {"Retry-After": "7", "Access-Control-Allow-Origin": "https://pages.test"}});
      }
      const responseHeaders = {"Access-Control-Allow-Origin": "https://pages.test",
        ...(rangeStatus === 416 ? {"X-OWL-Reason": "publisher-ignores-range"} : {})};
      if (headers?.Range) return new Response(null, {status: rangeStatus, headers: responseHeaders});
      if (method === "HEAD") return new Response(null, {status: headStatus, headers: responseHeaders});
    }
    if (url === page || method === "HEAD") return new Response(null, {status: 204});
    return new Response(body);
  }
  function network(options = {}) {
    return createNetwork({fetchFile, retryMs: 0, probeURL: page, online: () => !offline, ...options});
  }
  const info = async () => JSON.parse(await (await (await drive.file("LIBRARY/BUILD_INFO.json")).getFile()).text());
  return {drive, assets, routes, fetchFile, network, info, requests, relay, direct, page,
    up(status = 200) { down = false; headStatus = status; }, offline(value) { offline = value; }, throttle() { throttle = true; }};
}

test("automatic relay recovery uses HEAD when the deployed Worker rejects Range with 502", async t => {
  const fixture = relayFixture();
  let now = Date.parse("2026-11-22T23:29:00Z");
  t.mock.method(Date, "now", () => now);
  const events = [], delays = [];
  const network = fixture.network();
  network.delay = async ms => {
    now += ms || 0;
    if (!ms) return;
    delays.push(ms);
    const saved = await readBuild(fixture.drive);
    assert.deepEqual(saved.failures, {});
    assert.equal(saved.pending, true);
    assert.deepEqual(new Set(saved.relayDeferred), new Set(["a-relay", "b-relay", "c-relay", "d-relay"]));
    assert.deepEqual(Object.keys(saved.installed).sort(), ["x-mixed", "z-direct"]);
    assert.deepEqual((await fixture.info()).missing.map(row => row.reason), Array(4).fill("waiting for the download relay"));
    if (delays.length === 3) fixture.up();
  };
  const result = await buildLibrary(fixture.drive, {...fixture, network, onProgress: event => events.push(event)});
  assert.deepEqual(delays, [15 * 60_000, 15 * 60_000, 6 * 60_000]);
  const waits = events.filter(row => row.kind === "waiting-relay");
  assert.equal(waits.length, 3);
  assert.equal(typeof waits[0].tryNow, "function");
  assert.ok(events.findIndex(row => row.kind === "verified" && row.asset.id === "z-direct") < events.indexOf(waits[0]));
  assert.ok(!events.some(row => row.kind === "failed" || row.kind === "waiting-network"));
  const probes = fixture.requests.filter(row => row.method === "HEAD" && row.url.startsWith(fixture.relay));
  assert.equal(probes.length, 3);
  assert.ok(probes.every(row => row.url === fixture.relay + "a-relay" && !row.range && row.mode === "cors"));
  const firstProbe = fixture.requests.indexOf(probes[0]);
  const beforeProbe = fixture.requests.slice(0, firstProbe);
  assert.deepEqual(new Set(beforeProbe.filter(row => row.url.startsWith(fixture.relay)).map(row => row.url)),
    new Set(["a-relay", "b-relay", "c-relay"].map(id => fixture.relay + id)));
  assert.ok(beforeProbe.some(row => row.url === fixture.page && row.method === "HEAD"));
  assert.ok(beforeProbe.some(row => row.url === fixture.direct && row.method === "HEAD"));
  assert.equal(fixture.requests.filter(row => row.url === fixture.direct && row.method !== "HEAD").length, 2);
  assert.equal(result.state.finished, true);
  assert.equal(result.completed.length, fixture.assets.length);
  assert.deepEqual((await fixture.info()).missing, []);
});

test("Try now immediately recovers when the Worker rejects Range with 416", async t => {
  for (const status of [200, 416, 429]) await t.test("readable HTTP " + status, {timeout: 2000}, async () => {
    const fixture = relayFixture(416);
    let attempts = 0;
    const result = await runBuild(fixture.drive, {...fixture, network: fixture.network(), onProgress(event) {
      if (event.kind !== "waiting-relay") return;
      attempts++;
      fixture.up(status);
      event.tryNow();
    }});
    assert.match(RELAY_WAIT_MESSAGE, /isn’t answering\. It may have reached today’s free limit/);
    assert.equal(attempts, 1);
    assert.deepEqual(fixture.requests.filter(row => row.method === "HEAD" && row.url.startsWith(fixture.relay)),
      [{url: fixture.relay + "a-relay", method: "HEAD", mode: "cors", range: undefined}]);
    assert.equal(result.state.finished, true);
  });
});

test("a paused relay wait preserves the report and probes first when Sync is reopened", async () => {
  const fixture = relayFixture(), controller = new AbortController();
  const {signal} = controller;
  const network = fixture.network({signal});
  await assert.rejects(buildLibrary(fixture.drive, {...fixture, signal, network, onProgress(event) {
    if (event.kind === "waiting-relay") controller.abort();
  }}), {name: "AbortError"});
  const saved = await readBuild(fixture.drive);
  assert.equal(saved.pending, true);
  assert.equal(saved.relayDeferred.length, 4);
  assert.deepEqual(saved.failures, {});
  assert.equal(saved.plan.length, fixture.assets.length);
  assert.equal((await fixture.info()).missing.length, 4);

  fixture.up();
  fixture.requests.length = 0;
  const result = await buildLibrary(fixture.drive, {...fixture, network: fixture.network()});
  assert.deepEqual(fixture.requests.slice(0, 2).map(row => [row.url, row.method, row.range]), [
    [fixture.page, "HEAD", undefined], [fixture.relay + "a-relay", "HEAD", undefined]
  ]);
  assert.equal(result.state.pending, false);
  assert.equal(result.state.finished, true);
  assert.deepEqual((await fixture.info()).missing, []);
});

test("Pause during another download still publishes the relay deferrals", async () => {
  const fixture = relayFixture(), controller = new AbortController();
  const {signal} = controller;
  await assert.rejects(buildLibrary(fixture.drive, {...fixture, signal, network: fixture.network({signal}), onProgress(event) {
    if (event.kind === "downloading" && event.asset.id === "x-mixed") controller.abort();
  }}), {name: "AbortError"});
  const info = await fixture.info();
  assert.equal(info.missing.filter(row => row.reason === "waiting for the download relay").length, 4);
  assert.equal(info.missing.find(row => row.id === "x-mixed").reason, "Sync paused before this file arrived.");
  assert.deepEqual((await readBuild(fixture.drive)).failures, {});
});

test("a readable relay 429 retries after Retry-After without entering the relay wait", async t => {
  const fixture = relayFixture();
  fixture.up();
  fixture.throttle();
  let now = Date.parse("2026-11-22T12:00:00Z");
  t.mock.method(Date, "now", () => now);
  const network = fixture.network(), delays = [];
  network.delay = async ms => { delays.push(ms); now += ms; };
  const result = await buildLibrary(fixture.drive, {...fixture, network, assets: [fixture.assets[0]], onProgress(event) {
    assert.notEqual(event.kind, "waiting-relay");
  }});
  assert.deepEqual(delays, [7_000]);
  assert.equal(fixture.requests.length, 2);
  assert.equal(result.state.finished, true);
});

test("an actual loss of internet still waits for the internet and retries the same file", async () => {
  const fixture = relayFixture();
  fixture.offline(true);
  const events = new EventTarget();
  let networkWaits = 0;
  const network = fixture.network({events, onWaiting() {
    networkWaits++;
    fixture.offline(false);
    fixture.up();
    setTimeout(() => events.dispatchEvent(new Event("online")), 0);
  }});
  const result = await buildLibrary(fixture.drive, {...fixture, network, onProgress(event) {
    assert.notEqual(event.kind, "waiting-relay");
  }});
  assert.equal(networkWaits, 1);
  assert.equal(result.state.finished, true);
  assert.ok(!fixture.requests.some(row => row.range));
});

test("closing the tab is canceled only while the Sync warning is registered", () => {
  const tab = new EventTarget();
  const leave = () => {
    const event = new Event("beforeunload", {cancelable: true});
    Object.defineProperty(event, "returnValue", {writable: true});
    return tab.dispatchEvent(event);
  };
  assert.equal(leave(), true);
  const finished = warnBeforeLeaving(tab);
  assert.equal(leave(), false);
  finished();
  assert.equal(leave(), true);
});

test("browser selection names unroutable assets and leaves unrelated library files alone", async () => {
  const row = asset("blocked", Buffer.from("bytes"), {redistributable: false});
  const available = asset("open", Buffer.from("bytes"));
  const routes = {open: ["https://example.com/open"]};
  const selection = browserSelection([row, available], routes, {});
  assert.deepEqual(selection.assets, [available]);
  assert.equal(selection.excluded[0].id, "blocked");
  const drive = new Directory();
  const library = await drive.getDirectoryHandle("LIBRARY", {create: true});
  await library.getFileHandle("existing.pdf", {create: true});
  const result = await buildLibrary(drive, {...selection, routes, fetchFile: async () => new Response("bytes")});
  assert.equal(result.completed[0].id, "open");
  assert.equal((await (await library.getFileHandle("existing.pdf")).getFile()).size, 0);
});

test("the largest archive in the catalog fits within the split naming and FAT32 limits", () => {
  const zim = {id: "archive", title: "Large archive", destination: "ZIM/large.zim", format: "zim",
    size_bytes: 220_347_600_505, sha256: "f".repeat(64)};
  const layout = partLayout(zim);
  assert.equal(layout.length, 206);
  assert.equal(layout[26].path, "LIBRARY/ZIM/large.zimba");
  assert.ok(layout.every(part => part.bytes <= 2 ** 32 - 1));
  assert.equal(layout.reduce((total, part) => total + part.bytes, 0), zim.size_bytes);
});

test("Pause preserves the first committed part for a later Resume", async t => {
  const content = Buffer.from("ABCDEFGHIJKLM");
  const zim = asset("wiki", content, {format: "zim", destination: "ZIM/wiki.zim"});
  const {requests, url, fetchFile} = await httpFixture(t, (request, response) => sendRange(request, response, content));
  const drive = new Directory(), controller = new AbortController();
  const options = {assets: [zim], routes: {wiki: [url("/wiki")]}, fetchFile, partBytes: 5};
  await assert.rejects(buildLibrary(drive, {...options, signal: controller.signal,
    onProgress: event => {
      if (event.kind === "downloading" && event.index === 1) controller.abort();
    }}), {name: "AbortError"});
  assert.equal((await readBuild(drive)).parts.wiki.length, 1);
  requests.length = 0;
  assert.equal((await buildLibrary(drive, {...options, resume: true})).completed.length, 1);
  assert.deepEqual(requests.map(row => row.range), ["bytes=5-9", "bytes=10-12"]);
});

test("resuming a split archive repairs a same-length change before publishing the archive", async () => {
  const contents = Buffer.from("ABCDEFGHIJKLM");
  const wiki = asset("wiki", contents, {format: "zim", destination: "ZIM/wiki.zim"});
  const drive = new Directory(), abort = new AbortController();
  const ranges = [];
  const options = {assets: [wiki], routes: {wiki: ["https://example.test/wiki"]}, partBytes: 5,
    fetchFile: async (_url, {headers}) => {
      const [, first, last] = /^bytes=(\d+)-(\d+)$/.exec(headers.Range);
      ranges.push(headers.Range);
      return new Response(contents.subarray(Number(first), Number(last) + 1), {status: 206,
        headers: {"Content-Range": "bytes " + first + "-" + last + "/" + contents.length}});
    }};
  await assert.rejects(buildLibrary(drive, {...options, signal: abort.signal, onProgress(event) {
    if (event.kind === "downloading" && event.index === 1) abort.abort();
  }}), {name: "AbortError"});
  const layout = partLayout(wiki, 5);
  await writeFile(drive, layout[0].path, "XBCDE");
  ranges.length = 0;
  const result = await buildLibrary(drive, options);
  assert.equal(result.state.finished, true);
  assert.deepEqual(ranges, ["bytes=0-4", "bytes=5-9", "bytes=10-12"]);
  const parts = await Promise.all(layout.map(async ({path}) =>
    Buffer.from(await (await (await drive.file(path)).getFile()).arrayBuffer())));
  assert.equal(hash(Buffer.concat(parts)), wiki.sha256);
});

test("search assembly verifies and publishes only selected source digests", async () => {
  const body = Buffer.from("selected bytes");
  const chosen = asset("indexed", body);
  const source = asset("unselected", Buffer.from("other"));
  const model = "globalThis.OWLShardModel({});\n";
  const license = "MIT";
  const weights = "globalThis.OWLModelWeights([0,\"AA==\"]);\n";
  const chunk = "globalThis.OWLShardPart([]);\n";
  const pin = data => ({bytes: Buffer.byteLength(data), sha256: hash(data)});
  const shard = {sha256: hash(chunk), records: 1, parts: [{...pin(chunk), bloom: "", vectors: 1}]};
  const urls = [];
  const route = new Map([["https://example.test/book", body], ["/index/model.js", model], ["/index/model-license.txt", license],
    ["/index/model/00.js", weights],
    ["/index/sources/" + chosen.sha256 + "/00000.js", chunk]]);
  const fetchFile = async url => {
    urls.push(url);
    return route.has(url) ? new Response(route.get(url)) : new Response("", {status: 404});
  };
  const drive = new Directory();
  const config = {manifest: {version: 1, model: pin(model), license: pin(license), model_parts: [pin(weights)],
    sources: {[chosen.sha256]: shard, [source.sha256]: shard}}, base: "/index/", records: [],
    page: "<p>search</p>", runtime: "// catalog runtime", rankRuntime: "// article runtime"};
  const options = {assets: [chosen], catalogAssets: [chosen, source], routes: {indexed: ["https://example.test/book"]},
    navigation: {assets: {indexed: {shelves: []}}}, search: config, fetchFile};
  const result = await buildLibrary(drive, options);
  assert.deepEqual(result.searchWarnings, []);
  assert.ok(urls.some(path => path.includes(chosen.sha256)));
  assert.ok(!urls.some(path => path.includes(source.sha256)));
  const check = await (await drive.file("LIBRARY/SHA256SUMS.txt")).getFile();
  assert.match(await check.text(), new RegExp(shard.sha256 + "  LIBRARY/SEARCH/sources/" + chosen.sha256));
  assert.match(await check.text(), new RegExp(hash(weights) + "  LIBRARY/SEARCH/model/00.js"));
  const script = await (await (await drive.file("LIBRARY/SEARCH/shards.js")).getFile()).text();
  assert.equal(JSON.parse(script.slice("globalThis.OWLShardSelection(".length, -3)).model_parts, 1);
  const beforeResume = urls.length;
  const resumed = await buildLibrary(drive, {...options, resume: true, searchBudget: 1});
  assert.equal(resumed.state.searchBudget, 1);
  assert.equal(urls.length, beforeResume, "verified search data is reused at the saved allowance");
});

test("selected sources reuse one verified search pool", async () => {
  const first = Buffer.from("first source");
  const second = Buffer.from("second source");
  const a = asset("first", first, {category: "medical", critical: true});
  const b = asset("second", second, {source_url: "https://example.test/zim/stack_exchange/second.zim"});
  const pool = "a".repeat(64);
  const chunk = "shared pool";
  const pin = value => ({bytes: Buffer.byteLength(value), sha256: hash(value)});
  const path = "/index/sources/" + pool + "/00000.js";
  const data = new Map([["/index/model.js", "model"], ["/index/model-license.txt", "license"],
    ["https://example.test/first", first], ["https://example.test/second", second], [path, chunk]]);
  const shard = {records: 1, shared: [pool], sha256: hash(chunk)};
  const drive = new Directory();
  const requests = [];
  const result = await buildLibrary(drive, {assets: [a, b],
    routes: {first: ["https://example.test/first"], second: ["https://example.test/second"]},
    navigation: {assets: {first: {shelves: []}, second: {shelves: []}}},
    fetchFile: async url => { requests.push(url); return new Response(data.get(url)); },
    search: {base: "/index/", page: "<p>search</p>", records: [], runtime: "", rankRuntime: "", manifest: {
      version: 1, model: pin("model"), license: pin("license"), sources: {[a.sha256]: shard, [b.sha256]: shard},
      shared: {[pool]: {parts: [{...pin(chunk), bloom: "", vectors: 0}]}}
    }}});
  assert.deepEqual(result.searchWarnings, []);
  assert.equal(requests.filter(url => url === path).length, 1);
  const script = await (await (await drive.file("LIBRARY/SEARCH/shards.js")).getFile()).text();
  const selection = JSON.parse(script.slice("globalThis.OWLShardSelection(".length, -3));
  assert.deepEqual(selection.sources.map(row => [row.sha256, row.parts[0].pool]), [[a.sha256, pool], [b.sha256, pool]]);
  assert.deepEqual(selection.sources.map(row => [row.category, row.critical, row.discussion]),
    [["medical", true, false], [b.category, false, true]]);
});

test("a corrupted search chunk leaves the catalog search and static pages usable", async () => {
  const content = Buffer.from("source file");
  const doc = asset("indexed", content);
  const pin = text => ({bytes: Buffer.byteLength(text), sha256: hash(text)});
  const drive = new Directory();
  const fetchFile = async path => new Response(path === "https://example.test/book" ? content : "good");
  const result = await buildLibrary(drive, {assets: [doc], routes: {indexed: ["https://example.test/book"]}, fetchFile,
    navigation: readerNavigation({indexed: {category:"health"}}),
    search: {base: "/index/", page: "<p>search</p>", records: [], runtime: "", rankRuntime: "", manifest: {
      version: 1, model: pin("good"), license: pin("good"),
      sources: {[doc.sha256]: {records: 1, sha256: hash("evil"),
        parts: [{...pin("evil"), bloom: "", vectors: 0}]}}
    }}});
  assert.equal(result.state.finished, false);
  assert.match(result.searchWarnings.join(" "), /SHA-256/);
  assert.equal(result.supportMissing[0].kind, "search");
  assert.doesNotMatch(await readReaderFile(drive, "manifest.js"), /"shards":true/);
  assert.match(await (await (await drive.file("START_HERE.html")).getFile()).text(), /<main class="static">[^]*How to open a book/);
});

test("FAT32 and large-file mode join verified parts and keep them if a second copy cannot fit", async () => {
  const content = Buffer.from("ABCDEFGHIJKLM");
  const zim = asset("wiki", content, {format: "zim", destination: "ZIM/wiki.zim"});
  const fetchFile = async (url, {headers}) => {
    const [, first, last] = /^bytes=(\d+)-(\d+)$/.exec(headers.Range);
    return new Response(content.subarray(Number(first), Number(last) + 1), {status: 206,
      headers: {"Content-Range": "bytes " + first + "-" + last + "/" + content.length}});
  };
  const modes = [{joinArchives: true}, {fat32: true}];
  for (const [mode, full] of modes.flatMap(mode => [[mode, false], [mode, true]])) {
    const drive = new Directory("drive", {beforeWrite: name => {
      if (full && name === "wiki.zim") throw new DOMException("Disk full", "QuotaExceededError");
    }});
    const options = {assets: [zim], routes: {wiki: ["https://example.test/wiki"]}, fetchFile, partBytes: 5, ...mode};
    const result = await buildLibrary(drive, options);
    assert.equal(result.state.finished, true);
    assert.equal(Boolean(result.state.joined.wiki), !full);
    const good = full ? "wiki.zimaa" : "wiki.zim";
    const absent = full ? "wiki.zim" : "wiki.zimaa";
    assert.equal((await (await drive.file("LIBRARY/ZIM/" + good)).getFile()).size, full ? 5 : content.length);
    await assert.rejects(drive.file("LIBRARY/ZIM/" + absent), {name: "NotFoundError"});
    await buildLibrary(drive, {...options, resume: true, fullVerify: true,
      fetchFile: () => assert.fail("verified archive should not be downloaded again")});
  }
});

test("an unknown filesystem keeps parts until answered and 4 GiB write errors have a separate message", async () => {
  const body = Buffer.from("ABCDEFGHIJ");
  const zim = asset("wiki", body, {format: "zim", destination: "ZIM/wiki.zim"});
  const drive = new Directory();
  const setup = {assets: [zim], routes: {wiki: ["https://example.test/wiki"]}, partBytes: 5,
    fetchFile: async (_url, {headers}) => {
      const [, start, end] = /^bytes=(\d+)-(\d+)$/.exec(headers.Range);
      return new Response(body.subarray(Number(start), Number(end) + 1), {status: 206,
        headers: {"Content-Range": "bytes " + start + "-" + end + "/" + body.length}});
    }};
  const unknown = await runBuild(drive, {...setup, ...archiveDriveOptions("unknown", true)});
  assert.equal(unknown.keptInParts[0].parts, 2);
  await assert.rejects(drive.file("LIBRARY/ZIM/wiki.zim"), {name: "NotFoundError"});
  const answered = await runBuild(drive, {...setup, ...archiveDriveOptions("large", false),
    fetchFile: () => assert.fail("the verified parts should be joined without downloading")});
  assert.equal(answered.keptInParts.length, 0);
  for (const name of ["InvalidStateError", "QuotaExceededError"]) {
    const error = new DOMException("Write failed", name);
    assert.equal(archiveJoinLimitReached(error, 4 * GiB - MiB, 4 * GiB), true);
    assert.equal(archiveJoinLimitReached(error, 4 * GiB, 4 * GiB + MiB), true);
    assert.equal(archiveJoinLimitReached(error, GiB, GiB + MiB), false);
  }
  assert.equal(completionState({...unknown, state: {...unknown.state, largeFileLimited: true}}).extra,
    "This drive can’t hold files over 4 GB. OWL kept that encyclopedia in parts.");
});

test("readers alone cannot start a browser build", async () => {
  const reader = asset("reader", Buffer.from("reader"), {destination: "SOFTWARE/reader.zip"});
  await assert.rejects(buildLibrary(new Directory(), {assets: [reader], routes: {}}), /Choose knowledge files/);
});

test("published Metalink piece mismatch advances to the next source before commit", async () => {
  const body = Buffer.from("pinned archive");
  const zim = asset("wiki", body, {format: "zim", destination: "ZIM/wiki.zim"});
  const bad = "https://example.test/bad", good = "https://example.test/good";
  const sha1 = createHash("sha1").update(body).digest("base64");
  const attempts = [];
  const result = await buildLibrary(new Directory(), {assets:[zim], routes:{wiki:[bad, good]},
    published:{publisherPieces:{piece_bytes:4 * 2 ** 20, archives:{wiki:{sha256:zim.sha256, sha1}}}},
    fetchFile: async url => { attempts.push(url); return new Response(url === good ? body : Buffer.alloc(body.length)); }});
  assert.deepEqual(attempts, [bad, good]);
  assert.equal(result.state.finished, true);
});

test("the static reader lists completed urgent files and reports omissions", async () => {
  const body = Buffer.from("verified water guide");
  const water = asset("water", body, {title:"Water guide", critical:true});
  const aid = asset("hesperian_en_wtnd_2025_10", body, {title:"First aid chapter", critical:true});
  const drive = new Directory();
  await buildLibrary(drive, {assets:[water, aid], routes:{water:["https://example.test/water"], [aid.id]:["https://example.test/aid"]},
    excluded:[{id:"missing", title:"Unfinished guide", reason:"Source blocked"}],
    navigation: readerNavigation({water:{category:"shelter"}, [aid.id]:{category:"health"}}), fetchFile:async () => new Response(body)});
  const read = async path => (await (await drive.file(path)).getFile()).text();
  const start = await read("START_HERE.html");
  // The task links to the page inside the document and says which page that is.
  assert.match(start, /<a href="LIBRARY\/BOOKS\/hesperian_en_wtnd_2025_10.pdf#page=6">Stop severe bleeding<\/a><\/b><small>First aid chapter · page 6<\/small>/);
  assert.match(start, /<a class="tile" href="#c-health"[^>]*>.*Health<small>1 guide<\/small><\/a>/);
  assert.match(start, /<section class="shelf" id="c-health"/);
  assert.match(start, /<a href="LIBRARY\/BOOKS\/water.pdf">Make drinking water safer<\/a>.*Water guide.*LIBRARY › BOOKS › <b>water.pdf<\/b>/);
  assert.doesNotMatch(start, /Unfinished guide/);
  assert.match(await read("LIBRARY/BUILD_REPORT.html"), /Unfinished guide.*Source blocked/);
  const home = readerData(await readReaderFile(drive, "home.js"), "home");
  const route = home.tasks.find(task => task.task === "Make drinking water safer");
  assert.equal(route.href, "LIBRARY/BOOKS/water.pdf");
  assert.equal(home.stats.missing, 1);
});

test("a connection cut during a file and again during search pauses the queue and resumes", async t => {
  const body = Buffer.from("first verified asset");
  const book = asset("book", body, {critical: true});
  const next = asset("next", body);
  const model = "model";
  const license = "license";
  const bytes = value => ({bytes: Buffer.byteLength(value), sha256: hash(value)});
  const start = performance.now();
  const times = [];
  let offline = false;
  const cut = new Set(["/book", "/search/model.js"]);
  const fixture = await httpFixture(t, (request, response) => {
    if (cut.delete(request.url)) {
      response.writeHead(200);
      response.write("first", () => {
        offline = true;
        response.destroy();
      });
      return;
    }
    if (request.url === "/probe") response.writeHead(204).end();
    else if (request.url === "/search/model.js") response.end(model);
    else if (request.url === "/search/model-license.txt") response.end(license);
    else if (request.url.startsWith("/search/sources/")) response.end("index");
    else response.end(body);
  });
  const events = new EventTarget();
  let pending = false;
  let pauses = 0;
  const fetchFile = (url, options) => {
    if (offline) throw new TypeError("test network disconnected");
    return fetch(url, options);
  };
  const network = createNetwork({fetchFile, probeURL: fixture.url("/probe"), events, retryMs: 20,
    onWaiting() {
      if (pending) return;
      pending = true;
      pauses++;
      const cutAt = performance.now();
      setTimeout(() => {
        offline = false;
        pending = false;
        times.push(performance.now() - cutAt);
        events.dispatchEvent(new Event("online"));
      }, 120);
    }
  });
  const drive = new Directory();
  const trace = [];
  const shard = {records: 1, sha256: hash("index"), parts: [{...bytes("index"), bloom: "", vectors: 0}]};
  const result = await buildLibrary(drive, {assets: [book, next], routes: {
    book: [fixture.url("/book")], next: [fixture.url("/next")]},
    fetchFile, network, onProgress: event => trace.push(event.kind),
    search: {base: fixture.url("/search/"), page: "<p>Search</p>", records: [], runtime: "", rankRuntime: "", manifest: {
      version: 1, model: bytes(model), license: bytes(license), sources: {[book.sha256]: shard}
    }}, navigation: {assets: {}}});
  assert.equal(result.state.finished, true);
  assert.equal(result.completed.length, 2);
  assert.deepEqual(Object.keys(result.state.failures), []);
  assert.deepEqual(result.searchWarnings, []);
  assert.equal(pauses, 2);
  assert.equal(trace.includes("failed"), false);
  assert.equal(fixture.requests.filter(row => row.path === "/next").length, 1);
  t.diagnostic("Connection cuts lasted " + times.map(value => Math.round(value)).join(" and ") +
    " ms. Build finished in " + Math.round(performance.now() - start) + " ms.");
});

test("low-space single-file builds resume from durable parts and join when the workspace fits", async () => {
  const drive = new Directory();
  const body = Buffer.from("0123456789abcdefghijklmnopqrstuvwxyz");
  const item = asset("archive", body, {format: "zim", destination: "ZIM/archive.zim"});
  const controller = new AbortController();
  const requests = [];
  const fetchFile = async (_url, {headers}) => {
    const [start, end] = headers.Range.slice(6).split("-").map(Number);
    requests.push(start);
    return new Response(body.subarray(start, end + 1), {status: 206,
      headers: {"Content-Range": "bytes " + start + "-" + end + "/" + body.length}});
  };
  const options = {assets: [item], routes: {archive: ["https://example.test/archive.zim"]},
    fetchFile, singleArchives: true, partBytes: 8, archiveSpace: 72};
  await assert.rejects(buildLibrary(drive, {...options, signal: controller.signal,
    onProgress(event) {
      if (event.kind === "downloading" && event.index === 2 && event.received) controller.abort();
    }}), {name: "AbortError"});
  const target = "LIBRARY/ZIM/archive.zim";
  await assert.rejects(drive.file(target), {name: "NotFoundError"});
  assert.equal((await readBuild(drive)).parts.archive.length, 2);
  requests.length = 0;
  const done = await buildLibrary(drive, {...options, resume: true});
  assert.equal(done.state.finished, true);
  assert.equal(done.state.joined.archive, true);
  assert.deepEqual(requests, [16, 24, 32]);
  assert.equal(hash(Buffer.from(await (await (await drive.file(target)).getFile()).arrayBuffer())), item.sha256);
  await assert.rejects(drive.file(target + "aa"), {name: "NotFoundError"});
});

test("emergency encyclopedia tasks carry their Kiwix article and file location", async () => {
  const drive = new Directory();
  const body = Buffer.from("synthetic archive");
  const item = asset("wikimed_en", body, {format: "zim", destination: "ZIM/medical.zim"});
  await buildLibrary(drive, {assets: [item], routes: {wikimed_en: ["https://example.test/archive.zim"]},
    fetchFile: async () => new Response(body), navigation: readerNavigation({wikimed_en:{category:"health"}})});
  const start = await (await (await drive.file("START_HERE.html")).getFile()).text();
  const home = readerData(await readReaderFile(drive, "home.js"), "home");
  assert.match(start, /<b>Labor and birth<\/b>.*Look up Childbirth in Kiwix.*LIBRARY › ZIM › <b>medical.zim<\/b>/);
  assert.match(start, /id="kiwix".*class="device d-iphone"/);
  const route = home.tasks.find(task => task.task === "Labor and birth");
  assert.deepEqual(route.articles, ["Childbirth"]);
  assert.equal(route.format, "zim");
});

test("the browser installs the largest pinned phone PDF and indexes its checksum", async () => {
  const folder = new URL("../catalog/wikimed-phone/", import.meta.url);
  const pin = JSON.parse(readFileSync(new URL("manifest.json", folder)));
  const volume = pin.volumes.reduce((largest, item) => largest.bytes > item.bytes ? largest : item);
  const archive = {id: pin.source_id, sha256: pin.source_sha256, title: "WikiMed", size_bytes: 10,
    format: "zim", critical: true, destination: "ZIM/medicine.zim"};
  const destination = "CRITICAL/MEDICAL/WIKIMED-PHONE/";
  const path = "LIBRARY/" + destination + volume.file;
  const drive = new Directory();
  const {warnings} = await assembleLibrary(drive, {
    completed: [archive], missing: [],
    navigation: readerNavigation({[archive.id]:{category:"health"}},
      {phone: {...pin, destination, base: "./phone/", volumes: [volume]}}),
    layouts: new Map([[archive.id, [{path: "LIBRARY/" + archive.destination, bytes: archive.size_bytes}]]]),
    parts: {[archive.id]: [{sha256: archive.sha256}]}, searchBudget: 200_000_000,
    network: {retry: task => task()},
    async fetchFile(url) {
      assert.equal(url, "./phone/" + volume.file);
      return new Response(readFileSync(new URL(volume.file, folder)));
    }
  });
  assert.deepEqual(warnings, []);
  const contents = await (await drive.file(path)).getFile();
  assert.equal(hash(Buffer.from(await contents.arrayBuffer())), volume.sha256);
  const checksums = await (await (await drive.file("LIBRARY/SHA256SUMS.txt")).getFile()).text();
  const shelf = await readReaderFile(drive, "c-health.js");
  assert.ok(checksums.includes(volume.sha256 + "  " + path));
  assert.ok(shelf.includes(path));
});

test("the build report records a missing phone volume even when every selected content file arrived", async () => {
  const body = Buffer.from("WikiMed");
  const archive = asset("wikimed_en", body, {format: "zim", destination: "ZIM/medicine.zim"});
  const title = "Emergencies", file = "wikimed-emergencies.pdf";
  const drive = new Directory();
  const result = await buildLibrary(drive, {assets: [archive], routes: {wikimed_en: ["https://example.test/archive"]},
    fetchFile: async url => url.endsWith("/archive") ? new Response(body) : new Response(null, {status: 404}),
    navigation: {phone: {source_id: archive.id, source_sha256: archive.sha256, base: "https://example.test/phone/",
      destination: "CRITICAL/MEDICAL/WIKIMED-PHONE/", volumes: [{file, title, bytes: body.length, sha256: hash(body)}]}}});
  const info = JSON.parse(await (await (await drive.file("LIBRARY/BUILD_INFO.json")).getFile()).text());
  assert.equal(info.content_complete, true);
  assert.equal(info.support_complete, false);
  assert.deepEqual(info.support_missing, [{kind: "phone", id: "wikimed-phone-" + file, title: "WikiMed phone volume " + title,
    reason: "HTTP 404"}]);
  assert.deepEqual(result.supportMissing, info.support_missing);
  assert.match(completionState(result).message, /Some WikiMed phone files are missing/);
});

test("reader assembly failure leaves the simple start page and records missing reader support", async () => {
  const body = Buffer.from("Emergency guide");
  const doc = asset("guide", body, {utility_tier: "CRITICAL"});
  const navigation = readerNavigation({guide: {category: "health"}});
  delete navigation.reader.layout.tasks;
  const drive = new Directory();
  const result = await buildLibrary(drive, {assets: [doc], routes: {guide: ["https://example.test/guide"]}, navigation,
    fetchFile: async () => new Response(body)});
  const info = JSON.parse(await (await (await drive.file("LIBRARY/BUILD_INFO.json")).getFile()).text());
  assert.equal(info.content_complete, true);
  assert.equal(info.support_complete, false);
  assert.deepEqual(info.support_missing.map(row => row.kind), ["reader"]);
  assert.match(await (await (await drive.file("START_HERE.html")).getFile()).text(), /LIBRARY\/BOOKS\/guide.pdf/);
  assert.match(completionState(result).message, /Some reader or search files are missing/);
});

const PIECE_BYTES = 4 * MiB;
function rangedFixture(count, tail = 7) {
  const body = Buffer.concat([...Array.from({length: count}, (_, i) => Buffer.alloc(PIECE_BYTES, i)), Buffer.alloc(tail, count)]);
  const item = asset("parallel", body, {format: "zim", destination: "ZIM/parallel.zim"});
  const pins = [];
  for (let start = 0; start < body.length; start += PIECE_BYTES) {
    pins.push(createHash("sha1").update(body.subarray(start, start + PIECE_BYTES)).digest());
  }
  const published = {publisherPieces: {piece_bytes: PIECE_BYTES, archives: {
    [item.id]: {sha256: item.sha256, sha1: Buffer.concat(pins).toString("base64")}
  }}};
  const indexOf = options => Number(/^bytes=(\d+)-/.exec(options.headers.Range)[1]) / PIECE_BYTES;
  function response(index) {
    const start = index * PIECE_BYTES;
    const end = Math.min(start + PIECE_BYTES, body.length);
    return new Response(body.subarray(start, end), {status: 206,
      headers: {"Content-Range": "bytes " + start + "-" + (end - 1) + "/" + body.length}});
  }
  return {item, published, indexOf, response};
}

test("read-back corruption of a ranged archive part refetches the piece instead of using the journal", async () => {
  const {item, published, indexOf, response} = rangedFixture(2);
  const counts = new Map();
  let corrupt = true;
  const drive = new Directory("drive", {async beforeClose(name, bytes) {
    if (corrupt && name === "parallel.zimaa") {
      corrupt = false;
      return new Blob([new Uint8Array([99]), bytes.slice(1)]);
    }
  }});
  const result = await runBuild(drive, {assets: [item], published, partBytes: PIECE_BYTES,
    routes: {[item.id]: ["https://example.test/wiki.zim"]},
    fetchFile: async (_url, request) => {
      const index = indexOf(request);
      counts.set(index, (counts.get(index) || 0) + 1);
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  assert.equal(counts.get(0), 2);
  assert.equal(counts.get(1), 1);
  const stored = await (await drive.file("LIBRARY/ZIM/parallel.zimaa")).getFile();
  assert.equal(hash(Buffer.from(await stored.arrayBuffer())), result.state.parts[item.id][0].sha256);
});

test("an archive falls back to the mirror and counts once toward relay outage detection", async () => {
  const fixture = relayFixture();
  const {item, published, indexOf, response} = rangedFixture(1);
  const mirror = "https://publisher.test/archive.zim";
  const peer = fixture.relay + "parallel--peer";
  const routes = {...fixture.routes, [item.id]: [mirror]};
  let mirrorPieces = 0, relayPieces = 0;
  async function fetchFile(url, options) {
    if (url === mirror && options.headers?.Range) {
      mirrorPieces++;
      return response(indexOf(options));
    }
    if (url === peer) relayPieces++;
    return fixture.fetchFile(url, options);
  }
  const network = createNetwork({fetchFile, probeURL: fixture.page, retryMs: 0});
  network.delay = async ms => {
    if (!ms) return;
    const saved = await readBuild(fixture.drive);
    assert.ok(saved.installed[item.id], "the mirror installed the archive before waiting");
    assert.equal(new Set(fixture.requests.filter(row => row.url.startsWith(fixture.relay) &&
      row.url !== peer).map(row => row.url)).size, 2, "the archive counted once along with two documents");
    fixture.up();
  };
  const result = await buildLibrary(fixture.drive, {assets: [item, ...fixture.assets], routes,
    published: {...published, archiveRelay: {[item.id]: [peer]}}, fetchFile, network});
  assert.ok(relayPieces > 0);
  assert.ok(mirrorPieces > 0);
  assert.equal(result.state.finished, true);
});

test("out-of-order pieces survive pause and resume in single-file mode", async () => {
  const {item, published, indexOf, response} = rangedFixture(6);
  const drive = new Directory();
  const controller = new AbortController();
  const received = [];
  let active = 0, maxActive = 0;
  const direct = "https://example.test/archive.zim";
  const options = {assets: [item], routes: {[item.id]: [direct]}, published,
    singleArchives: true, partBytes: 4 * PIECE_BYTES, archiveSpace: item.size_bytes * 3,
    async fetchFile(url, fetchOptions) {
      active++;
      maxActive = Math.max(active, maxActive);
      const index = indexOf(fetchOptions);
      received.push(index);
      try {
        if (index === 0 && !controller.signal.aborted) {
          await new Promise((resolve, reject) => {
            fetchOptions.signal.addEventListener("abort", () => reject(fetchOptions.signal.reason), {once: true});
          });
        }
        await new Promise(resolve => setTimeout(resolve, 10));
        return response(index);
      } finally { active--; }
    }};
  await assert.rejects(buildLibrary(drive, {...options, signal: controller.signal, onProgress(event) {
    if (event.received === 2 * PIECE_BYTES) controller.abort();
  }}), {name: "AbortError"});
  assert.equal(maxActive, 4);
  const root = "LIBRARY/.owl/download-pieces/" + item.id + "/0/";
  const saved = [];
  for (const index of [1, 2, 3]) {
    try {
      const piece = await (await drive.file(root + index)).getFile();
      if (piece.size === PIECE_BYTES) saved.push(index);
    } catch (error) { assert.equal(error.name, "NotFoundError"); }
  }
  assert.equal(saved.length >= 2, true);
  // Corruption invalidates only this independently pinned piece.
  const corrupt = await (await drive.file(root + saved[0])).createWritable();
  await corrupt.write(Buffer.alloc(PIECE_BYTES, 255));
  await corrupt.close();
  received.length = 0;
  const result = await buildLibrary(drive, {...options, resume: true});
  assert.equal(result.state.joined[item.id], true);
  assert.equal(result.state.finished, true);
  const expected = [0, 1, 2, 3, 4, 5, 6].filter(index => !saved.slice(1).includes(index));
  assert.deepEqual(received.sort((a, b) => a - b), expected);
  const joined = await (await drive.file("LIBRARY/" + item.destination)).getFile();
  assert.equal(hash(Buffer.from(await joined.arrayBuffer())), item.sha256);
  await assert.rejects(drive.file(root + saved[0]), {name: "NotFoundError"});
});

test("a throttled range retries on fewer workers and successful pieces are not fetched again", async () => {
  const {item, published, indexOf, response} = rangedFixture(8);
  const seen = new Map();
  const delays = [];
  let active = 0, retryPeak = 0;
  const result = await buildLibrary(new Directory(), {assets: [item], published,
    routes: {[item.id]: ["https://example.test/archive.zim"]},
    network: {offline: () => false, delay: async delay => { delays.push(delay); }},
    async fetchFile(_url, options) {
      const index = indexOf(options);
      seen.set(index, (seen.get(index) || 0) + 1);
      if (index === 0 && seen.get(index) === 1) return new Response(null, {status: 429});
      active++;
      if (delays.length) retryPeak = Math.max(retryPeak, active);
      await new Promise(resolve => setTimeout(resolve, 10));
      active--;
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  assert.deepEqual(delays, [2000]);
  assert.equal(seen.get(0), 2);
  assert.equal([...seen].slice(1).every(([, attempts]) => attempts === 1), true);
  assert.equal(retryPeak <= 3, true);
});

test("a faster verified archive relay is tried and a limited peer falls back to direct", async () => {
  const {item, published, indexOf, response} = rangedFixture(5);
  const direct = "https://example.test/archive.zim", peer = "https://relay.example.test/peer";
  const seen = [];
  const result = await buildLibrary(new Directory(), {assets: [item],
    published: {...published, archiveRelay: {[item.id]: [peer]}}, routes: {[item.id]: [direct]},
    async fetchFile(url, options) {
      const index = indexOf(options);
      seen.push([url, index]);
      if (index === 0 && url === direct) await new Promise(resolve => setTimeout(resolve, 150));
      if (index === 1 && url === peer) return new Response("Limited", {status: 503});
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  assert.equal(seen.some(([url, index]) => url === peer && index === 1), true);
  assert.equal(seen.some(([url, index]) => url === direct && index === 1), true);
});

test("Sync reports whether an archive downloads on the fast or the slow route", async () => {
  for (const relayAnswers of [true, false]) {
    const {item, published, indexOf, response} = rangedFixture(3);
    const direct = "https://example.test/archive.zim", peer = "https://relay.example.test/peer";
    const flags = [];
    const result = await buildLibrary(new Directory(), {assets: [item],
      published: {...published, archiveRelay: {[item.id]: [peer]}}, routes: {[item.id]: [direct]},
      onProgress: event => { if (event.kind === "route") flags.push([event.asset.id, event.fast]); },
      async fetchFile(url, options) {
        const index = indexOf(options);
        if (url === direct) await new Promise(resolve => setTimeout(resolve, 40));
        // A Worker past its daily limit answers without CORS, so fetch rejects.
        if (url === peer && !relayAnswers) throw new TypeError("Failed to fetch");
        return response(index);
      }});
    assert.equal(result.state.finished, true);
    assert.deepEqual(flags, [[item.id, relayAnswers]]);
  }
});

test("an unavailable relay is rechecked 15 minutes after it failed and becomes available again", async () => {
  const relay = "https://relay.test/assets/small", calls = [];
  const realNow = Date.now;
  let now = Date.UTC(2026, 10, 23, 12);
  Date.now = () => now;
  try {
    const wait = createRelayWait({routes: {small: [relay], other: ["https://direct.test/other.pdf"]},
      assets: [{id: "small", format: "pdf", size_bytes: 10}],
      fetchFile: async (url, options) => { calls.push([url, options.method]); return new Response(null, {status: 200}); },
      network: {reachable: async () => true}});
    for (const id of ["a", "b", "c"]) await wait.observeFailure(id);
    assert.equal(wait.unavailable, true);
    assert.equal(wait.refresh(), undefined);
    now += 14 * 60_000;
    assert.equal(wait.refresh(), undefined);
    assert.deepEqual(calls, []);
    now += 2 * 60_000;
    await wait.refresh();
    assert.deepEqual(calls, [[relay, "HEAD"]]);
    assert.equal(wait.unavailable, false);
  } finally {
    Date.now = realNow;
  }
});

test("the slow-route note gives the relay's midnight UTC reset in local time", () => {
  const reset = new Date(Date.UTC(2026, 10, 24)).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  assert.ok(slowRouteMessage(Date.UTC(2026, 10, 23, 15, 30)).includes("resets at " + reset + "."));
});

test("a relay 429 without Retry-After rotates to the direct route for later pieces", async () => {
  // More pieces than lanes, so later pieces start after the 429 arrives.
  const {item, published, indexOf, response} = rangedFixture(40);
  const direct = "https://example.test/archive.zim", peer = "https://relay.example.test/peer";
  const seen = [];
  const result = await buildLibrary(new Directory(), {assets: [item],
    published: {...published, archiveRelay: {[item.id]: [peer]}}, routes: {[item.id]: [direct]},
    async fetchFile(url, options) {
      const index = indexOf(options);
      seen.push([url, index]);
      if (url === direct) await new Promise(resolve => setTimeout(resolve, 150));
      if (index === 1 && url === peer && !seen.some(([u, i], n) => u === peer && i === 1 && n < seen.length - 1)) {
        return new Response("Try again later", {status: 429});
      }
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  const later = seen.filter(([, index]) => index >= 20);
  assert.ok(later.length > 0 && later.every(([url]) => url === direct), "later pieces reused the relay: " + JSON.stringify(later));
});

test("a relay route with bad data is dropped and the next relay route carries the archive", async () => {
  const {item, published, indexOf, response} = rangedFixture(40);
  const direct = "https://example.test/archive.zim";
  const peerA = "https://relay.example.test/a", peerB = "https://relay.example.test/b";
  const seen = [];
  const result = await buildLibrary(new Directory(), {assets: [item],
    published: {...published, archiveRelay: {[item.id]: [peerA, peerB]}}, routes: {[item.id]: [direct]},
    async fetchFile(url, options) {
      const index = indexOf(options);
      seen.push([url, index]);
      if (url === direct) await new Promise(resolve => setTimeout(resolve, 150));
      // Route A samples fastest, so it is preferred until it returns bad data.
      if (url === peerB) await new Promise(resolve => setTimeout(resolve, 40));
      if (url === peerA && index === 1) return new Response("mismatch", {status: 502});
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  const later = seen.filter(([, index]) => index >= 20);
  assert.ok(later.every(([url]) => url === peerB), "later pieces: " + JSON.stringify(later.slice(0, 6)));
});

test("a busy relay route rotates to another relay route instead of the slow mirror", async () => {
  const {item, published, indexOf, response} = rangedFixture(40);
  const direct = "https://example.test/archive.zim";
  const peerA = "https://relay.example.test/a", peerB = "https://relay.example.test/b";
  const seen = [];
  let busy = 0;
  const result = await buildLibrary(new Directory(), {assets: [item],
    published: {...published, archiveRelay: {[item.id]: [peerA, peerB]}}, routes: {[item.id]: [direct]},
    async fetchFile(url, options) {
      const index = indexOf(options);
      seen.push([url, index]);
      if (url === direct) await new Promise(resolve => setTimeout(resolve, 150));
      if (url === peerB) await new Promise(resolve => setTimeout(resolve, 40));
      if (url === peerA && index >= 1 && busy++ < 3) return new Response("busy", {status: 429});
      return response(index);
    }});
  assert.equal(result.state.finished, true);
  assert.ok(seen.some(([url, index]) => url === peerA && index >= 1), "route A was never preferred");
  // After sampling piece 0, no piece should touch the slow mirror: busy pieces
  // retry on route B.
  assert.deepEqual(seen.filter(([url, index]) => url === direct && index >= 1), []);
});

test("a split archive retries the join only when the drive has room", async () => {
  const {item, published, indexOf, response} = rangedFixture(3);
  let attempts = 0, full = true;
  const drive = new Directory("drive", {beforeWrite(name) {
    if (name === "parallel.zim") {
      attempts++;
      if (full) throw new DOMException("Disk full during join", "QuotaExceededError");
    }
  }});
  const options = {assets: [item], routes: {[item.id]: ["https://example.test/archive.zim"]}, published,
    singleArchives: true, partBytes: 2 * PIECE_BYTES, archiveSpace: item.size_bytes * 3};
  const partial = await buildLibrary(drive, {...options, fetchFile: async (_url, opts) => response(indexOf(opts))});
  const keptInParts = [{id: item.id, title: item.title, parts: 2}];
  assert.equal(partial.state.finished, true);
  assert.equal(partial.state.verified[item.id], true);
  assert.deepEqual(partial.keptInParts, keptInParts);
  const report = JSON.parse(await (await (await drive.file("LIBRARY/BUILD_INFO.json")).getFile()).text());
  assert.deepEqual(report.kept_in_parts, keptInParts);
  assert.equal((await (await drive.file("LIBRARY/" + item.destination + "aa")).getFile()).size, 2 * PIECE_BYTES);
  assert.equal(attempts, 1);
  const limited = await buildLibrary(drive, {...options, freeBytes: item.size_bytes - 1,
    fetchFile: () => assert.fail("The verified parts must be reused")});
  assert.equal(limited.state.finished, true);
  assert.deepEqual(limited.keptInParts, keptInParts);
  assert.equal(attempts, 1);
  full = false;
  const done = await buildLibrary(drive, {...options, freeBytes: item.size_bytes,
    fetchFile: () => assert.fail("The verified parts must be reused")});
  assert.equal(done.state.finished, true);
  assert.deepEqual(done.keptInParts, []);
  assert.ok(attempts > 1);
  await assert.rejects(drive.file("LIBRARY/" + item.destination + "aa"), {name: "NotFoundError"});
});

test("a late pause reuses saved ranges when only the split archive fits", async () => {
  const {item, published, indexOf, response} = rangedFixture(22, 0);
  const drive = new Directory();
  const controller = new AbortController();
  const options = {assets: [item], published, routes: {[item.id]: ["https://example.test/archive.zim"]},
    singleArchives: true, partBytes: 16 * PIECE_BYTES, archiveSpace: item.size_bytes + 16 * PIECE_BYTES};
  await assert.rejects(buildLibrary(drive, {...options, signal: controller.signal,
    fetchFile: async (_url, opts) => response(indexOf(opts)),
    onProgress(event) {
      if (event.index === 1 && event.received === 3 * PIECE_BYTES) controller.abort();
    }}), {name: "AbortError"});
  const saved = await readBuild(drive);
  assert.equal(saved.parts[item.id].length, 1);
  const path = "LIBRARY/.owl/download-pieces/" + item.id + "/" + 16 * PIECE_BYTES + "/";
  const retained = new Set();
  for (let index = 16; index <= 21; index++) {
    try {
      if ((await (await drive.file(path + index)).getFile()).size) retained.add(index);
    } catch (error) { assert.equal(error.name, "NotFoundError"); }
  }
  assert.equal(retained.size, 3);
  const resumed = [];
  const finished = await buildLibrary(drive, {...options, resume: true, fetchFile: async (_url, opts) => {
    const index = indexOf(opts);
    resumed.push(index);
    return response(index);
  }});
  assert.ok(finished.state.verified[item.id]);
  assert.equal(finished.state.finished, true);
  assert.deepEqual(finished.keptInParts, [{id: item.id, title: item.title, parts: 2}]);
  assert.deepEqual(resumed.sort((a, b) => a - b), [16, 17, 18, 19, 20, 21].filter(n => !retained.has(n)));
});

test("the reader folds chapter files and keeps the order within the book", async () => {
  const drive = new Directory();
  const chapter = (id, title) => asset(id, Buffer.from(id), {title, destination: "CRITICAL/GUIDE/" + id + ".pdf", critical: true});
  const files = [chapter("c10", "Field Guide — 10 Burns"), chapter("c2", "Field Guide — 2 Bleeding"),
    chapter("front", "Field Guide — Front matter"), asset("solo", Buffer.from("solo"), {title: "Single sheet"})];
  const book = (chapterTitle, order) => ({category: "health", book: {title: "Field Guide", chapter: chapterTitle, order}});
  await buildLibrary(drive, {assets: files, routes: Object.fromEntries(files.map(file => [file.id, ["https://example.test/" + file.id]])),
    fetchFile: async url => new Response(Buffer.from(url.split("/").pop())),
    navigation: readerNavigation({c10: book("10 Burns", 2), c2: book("2 Bleeding", 1),
      front: book("Front matter", 0), solo: {category: "health"}})});
  const read = async path => (await (await drive.file(path)).getFile()).text();
  const rows = readerData(await readReaderFile(drive, "c-health.js"), "health");
  assert.deepEqual(rows.map(row => row.title), ["Field Guide", "Single sheet"]);
  assert.deepEqual(rows[0].chapters.map(row => row.title), ["Front matter", "2 Bleeding", "10 Burns"]);
  const start = await read("START_HERE.html");
  assert.equal(start.match(/Field Guide/g).length, 1);
  assert.match(start, /Book, 3 chapters.*LIBRARY › CRITICAL › <b>GUIDE<\/b>/);
  // Chapters stay folded: listed once, in reading order, inside a closed disclosure.
  assert.match(start, /<details><summary>Show chapters<\/summary><ul>.*Front matter.*2 Bleeding.*10 Burns.*<\/ul><\/details>/);
  assert.equal(start.match(/10 Burns/g).length, 1);
  assert.doesNotMatch(start, /id="kiwix"/);
  await assert.rejects(drive.file("LIBRARY/INDEX/categories.html"), {name:"NotFoundError"});
});

test("the reader starts from local scripts and the old search address redirects", async () => {
  const drive = new Directory();
  const body = Buffer.from("guide");
  const doc = asset("guide", body, {title: "Water guide"});
  const pin = text => ({bytes: Buffer.byteLength(text), sha256: hash(text)});
  await buildLibrary(drive, {assets: [doc], routes: {guide: ["https://example.test/guide"]},
    fetchFile: async url => new Response(url === "https://example.test/guide" ? body : "good"),
    navigation: readerNavigation({guide: {category:"shelter"}}),
    search: {base: "/index/", page: "", records: [], runtime: "", rankRuntime: "",
      manifest: {version: 1, model: pin("good"), license: pin("good"), sources: {}}}});
  const read = async path => (await (await drive.file(path)).getFile()).text();
  const start = await read("START_HERE.html");
  assert.match(start, /Content-Security-Policy" content="default-src &#39;none&#39;; script-src &#39;self&#39; file:/);
  assert.match(start, /<script defer src="LIBRARY\/INDEX\/[a-f0-9]{12}\/search\.js"><\/script>/);
  assert.match(await readReaderFile(drive, "manifest.js"), /OWLDiscoveryManifest/);
  assert.equal(readerData(await readReaderFile(drive, "home.js"), "home").syncedAt, (await readBuild(drive)).syncedAt);
  assert.match(start, /<h1>Library<\/h1>.*Water guide/s);
  assert.match(start, /<nav class="tabs" aria-label="Sections" hidden>/);
  assert.doesNotMatch(start, /<input|<form/);
  assert.match(await read("LIBRARY/SEARCH.html"), /url=..\/START_HERE.html#\/search/);
});
