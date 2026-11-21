import assert from "node:assert/strict";
import {createHash, webcrypto} from "node:crypto";
import {createServer} from "node:http";
import {once} from "node:events";
import {test} from "node:test";
import {browserSelection, buildLibrary, partLayout, readBuild} from "../web/builder.mjs";
import {measureFreeSpace} from "../web/drive.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;
const hash = data => createHash("sha256").update(data).digest("hex");
const missing = () => new DOMException("Missing entry", "NotFoundError");

class Directory {
  kind = "directory";
  entries = new Map();
  constructor(name = "drive", options = {}) {
    this.name = name;
    this.options = options;
  }
  async getDirectoryHandle(name, {create = false} = {}) {
    if (!this.entries.has(name) && create) this.entries.set(name, new Directory(name, this.options));
    if (!this.entries.has(name)) throw missing();
    const handle = this.entries.get(name);
    if (handle.kind !== "directory") throw new DOMException("Wrong type", "TypeMismatchError");
    return handle;
  }
  async *values() { yield* this.entries.values(); }
  async getFileHandle(name, {create = false} = {}) {
    if (!this.entries.has(name) && create) this.entries.set(name, new FileHandle(name, this.options));
    if (!this.entries.has(name)) throw missing();
    const handle = this.entries.get(name);
    if (handle.kind !== "file") throw new DOMException("Wrong type", "TypeMismatchError");
    return handle;
  }
  async removeEntry(name) { if (!this.entries.delete(name)) throw missing(); }
  async file(path) {
    const names = path.split("/");
    const basename = names.pop();
    let directory = this;
    for (const name of names) directory = await directory.getDirectoryHandle(name);
    return directory.getFileHandle(basename);
  }
}

class FileHandle {
  kind = "file";
  bytes = new Blob([]);
  constructor(name, options) {
    this.name = name;
    this.options = options;
  }
  async getFile() { return this.bytes; }
  async createWritable() {
    const chunks = [];
    return {
      write: async contents => {
        this.options.beforeWrite?.(this.name, contents);
        chunks.push(contents);
      },
      truncate: async bytes => this.options.truncate?.(bytes),
      close: async () => { this.bytes = new Blob(chunks); },
      abort: async () => { this.options.onAbort?.(); }
    };
  }
}

function asset(id, body, fields = {}) {
  return {id, title: "File " + id, format: "pdf", destination: "BOOKS/" + id + ".pdf",
    size_bytes: body.length, sha256: hash(body), redistributable: true, utility_tier: "USEFUL", ...fields};
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
  const chunk = "globalThis.OWLShardPart([]);\n";
  const pin = data => ({bytes: Buffer.byteLength(data), sha256: hash(data)});
  const shard = {sha256: hash(chunk), records: 1, parts: [{...pin(chunk), bloom: "", vectors: 1}]};
  const urls = [];
  const route = new Map([["https://example.test/book", body], ["/index/model.js", model], ["/index/model-license.txt", license],
    ["/index/sources/" + chosen.sha256 + "/00000.js", chunk]]);
  const fetchFile = async url => {
    urls.push(url);
    return route.has(url) ? new Response(route.get(url)) : new Response("", {status: 404});
  };
  const drive = new Directory();
  const config = {manifest: {version: 1, model: pin(model), license: pin(license),
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
  const beforeResume = urls.length;
  await buildLibrary(drive, {...options, resume: true});
  assert.equal(urls.length, beforeResume, "verified data is reused");
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
