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
    if (url === direct) await new Promise(resolve => setTimeout(resolve, 120));
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
