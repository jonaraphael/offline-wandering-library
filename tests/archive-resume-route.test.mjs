import assert from "node:assert/strict";
import {test} from "node:test";
import {createHash, webcrypto} from "node:crypto";
import {archiveSession, publisherPin} from "../web/archive-download.mjs";

globalThis.crypto ||= webcrypto;
const PIECE = 4 * 2 ** 20;

// On Resume the first pieces of each window are already on the drive. The
// route must still be sampled on the first piece that needs downloading.
test("resumed archives still move to a faster relay route", async () => {
  const count = 40, savedUpTo = 20;
  const body = Buffer.concat(Array.from({length: count}, (_, i) => Buffer.alloc(PIECE, i)));
  const sha1 = Buffer.concat(Array.from({length: count}, (_, i) =>
    createHash("sha1").update(body.subarray(i * PIECE, (i + 1) * PIECE)).digest())).toString("base64");
  const asset = {id: "resumed", size_bytes: body.length, sha256: createHash("sha256").update(body).digest("hex")};
  const published = {piece_bytes: PIECE, archives: {resumed: {sha256: asset.sha256, sha1}}};
  const direct = "https://mirror.example/archive.zim", peer = "https://relay.example/assets/resumed--fast";
  const seen = [];
  const fetchFile = async (url, options) => {
    const start = Number(/^bytes=(\d+)-/.exec(options.headers.Range)[1]);
    seen.push([url, start / PIECE]);
    // The mirror answers after the sample's 3 s cutoff, so a busy test machine
    // cannot slow the relay probe enough to make the mirror look as fast.
    if (url === direct) await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, 4_000);
      options.signal.addEventListener("abort", () => { clearTimeout(timer); reject(options.signal.reason); }, {once: true});
    });
    return new Response(body.subarray(start, start + PIECE), {status: 206,
      headers: {"Content-Range": `bytes ${start}-${start + PIECE - 1}/${body.length}`}});
  };
  const network = {offline: () => false, waitForConnection: async () => false, delay: async () => {}};
  const run = archiveSession(asset, publisherPin(published, asset), {direct: [direct], relay: [peer], fetchFile, network});
  const written = new Set();
  await run({start: 0, bytes: body.length}, {
    restore: async index => index < savedUpTo ? body.subarray(index * PIECE, (index + 1) * PIECE) : null,
    accept: async index => { written.add(index); },
    ordered: () => {}
  });
  assert.equal(written.size, count);
  const downloads = seen.filter(([, index]) => index >= savedUpTo);
  const slow = downloads.filter(([url, index]) => url === direct && index > savedUpTo);
  assert.deepEqual(slow, [], "pieces after the sample used the slow mirror");
  assert.ok(downloads.some(([url]) => url === peer));
});

test("a failed sample on the first unrestored piece still hashes the complete resumed archive", async () => {
  const data = Uint8Array.of(1, 2, 3, 4, 5, 6, 7, 8, 9);
  const pin = {size: 3, matches: async (index, bytes) => bytes.every((byte, i) => byte === data[index * 3 + i])};
  const attempts = new Map();
  const run = archiveSession({id: "resume", size_bytes: data.length}, pin, {
    direct: ["https://mirror.example/archive.zim"], relay: ["https://relay.example/assets/resume"],
    network: {offline: () => false, delay: async () => {}},
    async fetchFile(_url, {headers}) {
      const start = Number(/^bytes=(\d+)-/.exec(headers.Range)[1]);
      const count = (attempts.get(start) || 0) + 1;
      attempts.set(start, count);
      if (start === 3 && count <= 2) return new Response("Busy", {status: 503});
      return new Response(data.slice(start, start + 3), {status: 206, headers: {"Content-Range": `bytes ${start}-${start + 2}/9`}});
    }
  });
  const committed = [], ordered = [];
  await run({start: 0, bytes: data.length}, {
    restore: async index => index === 0 ? data.slice(0, 3) : null,
    accept: async index => { committed.push(index); },
    ordered: bytes => ordered.push(...bytes)
  });
  assert.deepEqual(committed.sort(), [0, 1, 2]);
  assert.deepEqual(ordered, [...data]);
  assert.equal(attempts.get(3), 3);
});

test("busy routes wait for readable Retry-After and older relays wait 60 seconds on a bare 429", async t => {
  let now = Date.parse("2026-11-22T12:00:00Z");
  t.mock.method(Date, "now", () => now);
  for (const [kind, expected] of [["seconds", 73_000], ["date", 80_000], ["hidden", 60_000]]) {
    const header = kind === "seconds" ? "73" : kind === "date" ? new Date(now + expected).toUTCString() : null;
    let retried = false;
    const delays = [];
    const run = archiveSession({id: "rate-limit", size_bytes: 1}, {size: 1, matches: async () => true}, {
      direct: ["https://mirror.example/archive.zim"], relay: ["https://relay.example/assets/rate-limit"],
      network: {offline: () => false, async delay(ms) { delays.push(ms); now += ms; retried = true; }},
      async fetchFile(url) {
        if (!retried && url.includes("relay.example")) {
          return new Response(null, {status: 429, headers: header ? {"Retry-After": header} : {}});
        }
        if (!retried) return new Response("Busy", {status: 503});
        return new Response("a", {status: 206, headers: {"Content-Range": "bytes 0-0/1"}});
      }
    });
    const accepted = [];
    await run({start: 0, bytes: 1}, {
      restore: async () => null, accept: async (_index, bytes) => { accepted.push(...bytes); }, ordered() {}
    });
    assert.deepEqual(delays, [expected]);
    assert.deepEqual(accepted, [97]);
  }
});

function tinyArchive(pieces) {
  const data = Uint8Array.from({length: pieces * 3}, (_, i) => (i * 7) % 251);
  const pin = {size: 3, matches: async (index, bytes) => bytes.every((byte, i) => byte === data[index * 3 + i])};
  const respond = start => new Response(data.slice(start, start + 3),
    {status: 206, headers: {"Content-Range": `bytes ${start}-${start + 2}/${data.length}`}});
  return {data, pin, respond, asset: {id: "tiny", size_bytes: data.length}};
}
const quietNetwork = {offline: () => false, waitForConnection: async () => false, delay: async () => {}};

// Windows are 16 pieces. The relay serves windows 0-1, stops answering for
// windows 2-9 (a Worker past its daily limit), and answers again from window 10,
// where the 8-window resample finds it.
test("a relay that stops answering mid-archive moves the archive to the mirror and back, reporting each route", async () => {
  const {data, pin, respond, asset} = tinyArchive(16 * 12);
  const direct = "https://mirror.example/archive.zim", peer = "https://relay.example/assets/tiny";
  const seen = [], flags = [], ordered = [];
  const run = archiveSession(asset, pin, {direct: [direct], relay: [peer], network: quietNetwork,
    onRoute: ({fast}) => flags.push(fast),
    async fetchFile(url, {headers}) {
      const start = Number(/^bytes=(\d+)-/.exec(headers.Range)[1]), piece = start / 3;
      seen.push([url, piece]);
      if (url === direct) await new Promise(resolve => setTimeout(resolve, 5));
      else if (piece >= 32 && piece < 160) throw new TypeError("Failed to fetch");
      return respond(start);
    }});
  await run({start: 0, bytes: data.length}, {restore: async () => null, accept: async () => {},
    ordered: bytes => ordered.push(...bytes)});
  assert.deepEqual(ordered, [...data]);
  assert.deepEqual(flags, [true, false, true]);
  assert.deepEqual(seen.filter(([url, piece]) => url === peer && piece >= 48 && piece < 160), [],
    "pieces kept trying the failing relay");
  assert.ok(seen.filter(([, piece]) => piece >= 176).every(([url]) => url === peer));
});

test("an unavailable relay leaves archives on the mirror until a recheck brings it back", async () => {
  const {data, pin, respond, asset} = tinyArchive(16 * 3);
  const direct = "https://mirror.example/archive.zim", peer = "https://relay.example/assets/tiny";
  const seen = [], flags = [];
  let ready = false, refreshes = 0;
  const run = archiveSession(asset, pin, {direct: [direct], relay: [peer], network: quietNetwork,
    relayReady: () => ready,
    refreshRelay: () => { if (++refreshes === 2) ready = true; },
    onRoute: ({fast}) => flags.push(fast),
    async fetchFile(url, {headers}) {
      const start = Number(/^bytes=(\d+)-/.exec(headers.Range)[1]);
      seen.push([url, start / 3]);
      if (url === direct) await new Promise(resolve => setTimeout(resolve, 5));
      return respond(start);
    }});
  await run({start: 0, bytes: data.length}, {restore: async () => null, accept: async () => {}, ordered: () => {}});
  assert.equal(refreshes, 2);
  assert.deepEqual(flags, [false, true]);
  assert.deepEqual(seen.filter(([url, piece]) => url === peer && piece < 32), []);
  assert.ok(seen.some(([url, piece]) => url === peer && piece >= 32));
});

test("a drained archive session journals the pieces in flight, starts no more and waits at the save point", async () => {
  const {data, pin, respond, asset} = tinyArchive(64);
  const drain = new AbortController();
  const started = [], accepted = new Set();
  let afterDrain = 0, atPause;
  const run = archiveSession(asset, pin, {direct: ["https://mirror.example/archive.zim"], network: quietNetwork,
    drain: drain.signal,
    async atSavePoint() {
      atPause = {accepted: accepted.size, inflight: run.inflight()};
      throw new DOMException("Paused", "AbortError");
    },
    async fetchFile(_url, {headers}) {
      const start = Number(/^bytes=(\d+)-/.exec(headers.Range)[1]);
      if (drain.signal.aborted) afterDrain++;
      started.push(start / 3);
      await new Promise(resolve => setTimeout(resolve, 5));
      return respond(start);
    }});
  await assert.rejects(run({start: 0, bytes: data.length}, {restore: async () => null,
    accept: async (index, _bytes, persist) => {
      assert.equal(persist, true);
      accepted.add(index);
      if (accepted.size === 10) drain.abort();
    },
    ordered: () => {}}), {name: "AbortError"});
  // Every piece that started was received and handed to the journal before the pause.
  assert.deepEqual([...accepted].sort((a, b) => a - b), [...new Set(started)].sort((a, b) => a - b));
  assert.equal(atPause.accepted, accepted.size);
  assert.deepEqual(atPause.inflight, {lost: 0, toSave: 0, seconds: 0});
  assert.ok(afterDrain <= 8, afterDrain + " pieces started after the drain");
  assert.ok(accepted.size < 64);
});

test("an archive session reports bytes still arriving before any piece finishes", async () => {
  const {data, pin, asset} = tinyArchive(4);
  const reports = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const run = archiveSession(asset, pin, {direct: ["https://mirror.example/archive.zim"], network: quietNetwork,
    onInflight: () => reports.push(run.inflight()),
    async fetchFile(_url, {headers}) {
      const start = Number(/^bytes=(\d+)-/.exec(headers.Range)[1]);
      // Two bytes arrive at once; the third waits until the test releases it.
      return new Response(new ReadableStream({async start(stream) {
        stream.enqueue(data.slice(start, start + 2));
        await gate;
        stream.enqueue(data.slice(start + 2, start + 3));
        stream.close();
      }}), {status: 206, headers: {"Content-Range": `bytes ${start}-${start + 2}/${data.length}`}});
    }});
  const finished = run({start: 0, bytes: data.length}, {restore: async () => null, accept: async () => {}, ordered: () => {}});
  while (!reports.length) await new Promise(resolve => setTimeout(resolve, 1));
  assert.ok(reports[0].lost >= 2 && reports[0].toSave >= 1, JSON.stringify(reports[0]));
  // Each piece got 2 of 3 bytes in about 0.6 s, so the last byte needs about 0.3 s.
  await new Promise(resolve => setTimeout(resolve, 600));
  const {seconds} = run.inflight();
  assert.ok(seconds >= 0.2 && seconds <= 0.6, "estimated " + seconds + " s");
  release();
  await finished;
  assert.deepEqual(run.inflight(), {lost: 0, toSave: 0, seconds: 0});
});
