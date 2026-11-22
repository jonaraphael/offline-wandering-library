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
