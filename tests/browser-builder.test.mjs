import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash, webcrypto} from "node:crypto";
import {createServer} from "node:http";
import {once} from "node:events";
import {test} from "node:test";
import {archiveCheckpoints, browserSelection, buildLibrary as runBuild, partLayout, readBuild} from "../web/builder.mjs";
import {measureFreeSpace} from "../web/drive.mjs";
import {createNetwork} from "../web/network.mjs";
import {Directory} from "./browser-drive-fixture.mjs";
import {probesCapacity} from "../web/builder-ui.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;
const hash = data => createHash("sha256").update(data).digest("hex");
function asset(id, body, fields = {}) {
  return {id, title: "File " + id, format: "pdf", destination: "BOOKS/" + id + ".pdf",
    size_bytes: body.length, sha256: hash(body), redistributable: true, utility_tier: "USEFUL", ...fields};
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
});

test("native allocation probe estimates to one MiB and removes the swap placeholder", async () => {
  for (const name of ["QuotaExceededError", "InvalidStateError"]) {
    const free = 26 * GiB + 12345;
    let aborts = 0;
    const drive = new Directory("drive", {truncate: length => {
      if (length > free) throw new DOMException("Cannot set length", name);
    }, onAbort: () => aborts++});
    const result = await measureFreeSpace(drive);
    assert.equal(result.kind, "measured");
    assert.ok(result.bytes <= free && free - result.bytes <= MiB);
    assert.equal(drive.entries.size, 0);
    assert.ok(aborts <= 27, "number of probe attempts including repeats");
  }
});

test("probe falls back for sparse files, FAT32, indistinguishable limits and denied access", async () => {
  assert.deepEqual(await measureFreeSpace(new Directory()), {kind: "sparse-or-large"});
  for (const [error, expected] of [
    [new DOMException("EFBIG", "InvalidStateError"), "fat32"],
    [new DOMException("Cannot set length", "InvalidStateError"), "limited"]
  ]) {
    const drive = new Directory("drive", {truncate: length => { if (length > 2 ** 32 - 1) throw error; }});
    assert.deepEqual(await measureFreeSpace(drive), {kind: expected});
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
    navigation: {topics: {medical: {title: "Medicine", parents: []}},
      entrances: {Subjects: ["medical"]}, assignments: [{topic_id: "medical", asset_id: "wiki"}]}};
  const first = await buildLibrary(drive, options);
  assert.equal(first.completed.length, 0);
  assert.match(first.state.failures.wiki, /Connection or browser access failed/);
  const state = await readBuild(drive);
  assert.equal(state.parts.wiki.length, 1);
  assert.equal(state.parts.wiki[0].sha256, hash(content.subarray(0, 5)));
  assert.doesNotMatch(await (await (await drive.file("START_HERE.html")).getFile()).text(), /href="LIBRARY\/ZIM/);
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
  const atlas = await (await (await drive.file("LIBRARY/INDEX/topics/medical.html")).getFile()).text();
  assert.match(atlas, /href="..\/..\/..\/LIBRARY\/ZIM\/wiki.zimaa"/);
  const sumFile = await (await (await drive.file("LIBRARY/SHA256SUMS.txt")).getFile()).text();
  for (const line of sumFile.trim().split("\n")) {
    const [digest, path] = line.split("  ");
    assert.equal(digest, hash(Buffer.from(await (await (await drive.file(path)).getFile()).arrayBuffer())));
  }

  // Corruption of an existing part must trigger a new range beginning at that part.
  (await drive.file("LIBRARY/ZIM/wiki.zimab")).bytes = new Blob(["wrong"]);
  requests.length = 0;
  await buildLibrary(drive, {...options, resume: true});
  assert.deepEqual(requests, [], "routine resume trusts same-size checkpoints");
  await buildLibrary(drive, {...options, resume: true, fullVerify: true});
  assert.deepEqual(requests.map(row => row.range), ["bytes=5-9", "bytes=10-12"]);
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

test("a mismatched source or full drive yields a partial library and keeps later files moving", async t => {
  const correct = Buffer.from("correct"), corrupt = Buffer.from("corrupt");
  const first = asset("first", correct, {utility_tier: "CRITICAL"});
  const wrong = asset("wrong", correct);
  const huge = asset("huge", correct);
  const small = asset("small", correct);
  const {url, fetchFile} = await httpFixture(t, (request, response) => response.end(request.url === "/wrong" ? corrupt : correct));
  const drive = new Directory("drive", {beforeWrite: name => {
    if (name === "huge.pdf") throw new DOMException("Disk full", "QuotaExceededError");
  }});
  const routes = Object.fromEntries([first, huge, small, wrong].map(row => [row.id, [url("/" + row.id)]]));
  const result = await buildLibrary(drive, {assets: [huge, small, wrong, first], routes, fetchFile});
  assert.deepEqual(result.completed.map(row => row.id), ["first", "small"]);
  assert.equal(result.state.dropped.huge, "Drive ran out of space");
  assert.match(result.state.failures.wrong, /SHA-256/);
  assert.deepEqual(result.missing.map(row => row.id), ["huge", "wrong"]);
  await assert.rejects(drive.file("LIBRARY/BOOKS/wrong.pdf"), {name: "NotFoundError"});
  await assert.rejects(drive.file("LIBRARY/BOOKS/huge.pdf"), {name: "NotFoundError"});
});

test("browser selection names unroutable assets and protects an existing library", async () => {
  const row = asset("blocked", Buffer.from("bytes"), {redistributable: false});
  const available = asset("open", Buffer.from("bytes"));
  const routes = {open: ["https://example.com/open"]};
  const selection = browserSelection([row, available], routes, {});
  assert.deepEqual(selection.assets, [available]);
  assert.equal(selection.excluded[0].id, "blocked");
  const drive = new Directory();
  const library = await drive.getDirectoryHandle("LIBRARY", {create: true});
  await library.getFileHandle("existing.pdf", {create: true});
  await assert.rejects(buildLibrary(drive, {...selection, routes}), /already contains library files/);
  await assert.rejects(drive.file("START_HERE.html"), {name: "NotFoundError"});
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
  assert.equal(resumed.state.searchBudget, result.state.searchBudget);
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
    navigation: {assets: {indexed: {shelves: []}}},
    search: {base: "/index/", page: "<p>search</p>", records: [], runtime: "", rankRuntime: "", manifest: {
      version: 1, model: pin("good"), license: pin("good"),
      sources: {[doc.sha256]: {records: 1, sha256: hash("evil"),
        parts: [{...pin("evil"), bloom: "", vectors: 0}]}}
    }}});
  assert.equal(result.state.finished, false);
  assert.match(result.searchWarnings.join(" "), /SHA-256/);
  assert.match(await (await (await drive.file("LIBRARY/SEARCH/manifest.js")).getFile()).text(), /"shards":false/);
  assert.match(await (await (await drive.file("START_HERE.html")).getFile()).text(), /Search offline/);
});

test("large-file mode joins verified parts and keeps them if a second copy cannot fit", async () => {
  const content = Buffer.from("ABCDEFGHIJKLM");
  const zim = asset("wiki", content, {format: "zim", destination: "ZIM/wiki.zim"});
  const fetchFile = async (url, {headers}) => {
    const [, first, last] = /^bytes=(\d+)-(\d+)$/.exec(headers.Range);
    return new Response(content.subarray(Number(first), Number(last) + 1), {status: 206,
      headers: {"Content-Range": "bytes " + first + "-" + last + "/" + content.length}});
  };
  for (const full of [false, true]) {
    const drive = new Directory("drive", {beforeWrite: name => {
      if (full && name === "wiki.zim") throw new DOMException("Disk full", "QuotaExceededError");
    }});
    const options = {assets: [zim], routes: {wiki: ["https://example.test/wiki"]}, fetchFile, partBytes: 5, joinArchives: true};
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

test("the emergency directory links only to completed files and keeps omissions on the report", async () => {
  const body = Buffer.from("verified water guide");
  const water = asset("water", body, {title:"Water guide", critical:true});
  const layout = JSON.parse(readFileSync(new URL("../src/owl/templates/offline-layout.json", import.meta.url)));
  const drive = new Directory();
  await buildLibrary(drive, {assets:[water], routes:{water:["https://example.test/water"]},
    excluded:[{id:"missing", title:"Unfinished guide", reason:"Source blocked"}],
    navigation:{layout}, fetchFile:async () => new Response(body)});
  const read = async path => (await (await drive.file(path)).getFile()).text();
  const start = await read("START_HERE.html");
  assert.match(start, /id="emergency".*Make drinking water safer.*LIBRARY\/BOOKS\/water.pdf/);
  assert.doesNotMatch(start, /Unfinished guide/);
  assert.match(await read("LIBRARY/INDEX/build-report.html"), /Unfinished guide.*Source blocked/);
  assert.match(await read("LIBRARY/INDEX/phone.html"), /Water guide/);
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
  assert.deepEqual(result.state.failures, {});
  assert.deepEqual(result.searchWarnings, []);
  assert.equal(pauses, 2);
  assert.equal(trace.includes("failed"), false);
  assert.equal(fixture.requests.filter(row => row.path === "/next").length, 1);
  t.diagnostic("Connection cuts lasted " + times.map(value => Math.round(value)).join(" and ") +
    " ms. Build finished in " + Math.round(performance.now() - start) + " ms.");
});

test("single-file archives resume from a durable prefix and remain one verified file", async () => {
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
    fetchFile, singleArchives: true, partBytes: 8, archiveSpace: 54};
  assert.deepEqual(archiveCheckpoints(item.size_bytes, 8, 54), [1, 2]);
  await assert.rejects(buildLibrary(drive, {...options, signal: controller.signal,
    onProgress(event) {
      if (event.kind === "downloading" && event.index === 2 && event.received) controller.abort();
    }}), {name: "AbortError"});
  const target = "LIBRARY/ZIM/archive.zim";
  assert.equal((await (await drive.file(target)).getFile()).size, 16);
  assert.equal((await readBuild(drive)).prefixes.archive.count, 2);
  requests.length = 0;
  const done = await buildLibrary(drive, {...options, resume: true});
  assert.equal(done.state.finished, true);
  assert.equal(done.state.joined.archive, true);
  assert.deepEqual(requests, [16, 24, 32]);
  assert.equal(hash(Buffer.from(await (await (await drive.file(target)).getFile()).arrayBuffer())), item.sha256);
  await assert.rejects(drive.file(target + "aa"), {name: "NotFoundError"});
});

test("emergency archive tasks link to named offline articles and their printed paths", async () => {
  const drive = new Directory();
  const body = Buffer.from("synthetic archive");
  const item = asset("wikimed_en", body, {format: "zim", destination: "ZIM/medical.zim"});
  const layout = JSON.parse(readFileSync(new URL("../src/owl/templates/offline-layout.json", import.meta.url)));
  await buildLibrary(drive, {assets: [item], routes: {wikimed_en: ["https://example.test/archive.zim"]},
    fetchFile: async () => new Response(body), navigation: {layout}});
  const start = await (await (await drive.file("START_HERE.html")).getFile()).text();
  const entry = await (await (await drive.file("LIBRARY/INDEX/sections.html")).getFile()).text();
  assert.match(start, /LIBRARY\/INDEX\/sections.html#emergency-6">Childbirth<\/a>/);
  assert.match(entry, /id="emergency-6"/);
  assert.match(entry, /<code>Childbirth<\/code>/);
});
