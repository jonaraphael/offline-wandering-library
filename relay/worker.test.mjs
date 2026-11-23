import assert from "node:assert/strict";
import {test} from "node:test";
import {probeBrowserRoutes} from "../scripts/check_csp_routes.cjs";
import {relay} from "./worker.mjs";

const origin = "https://example.github.io";
const bytes = "0123456789";
const allowed = {reference: {url: "https://publisher.example/file", bytes: bytes.length}};
const env = {ALLOWED_ORIGIN: origin, REQUEST_LIMIT: {limit: async () => ({success: true})}};

function request(range, method = "GET") {
  const headers = {Origin: origin, "CF-Connecting-IP": "192.0.2.1"};
  if (range) headers.Range = range;
  return new Request("https://relay.example/assets/reference", {headers, method});
}

test("an ignored whole-file Range passes through with the pinned length", async () => {
  for (const range of ["bytes=0-", "bytes=0-9", "bytes=0-99"]) {
    const worker = relay(allowed, (_, options) => {
      assert.equal(options.headers.get("Range"), range);
      return new Response(options.method === "HEAD" ? null : bytes, {
        headers: {"Content-Length": "10", "Content-Range": "bytes 0-9/10"}
      });
    });
    for (const method of ["GET", "HEAD"]) {
      const response = await worker.fetch(request(range, method), env);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("Content-Length"), "10");
      assert.equal(response.headers.get("Content-Range"), null);
      assert.equal(await response.text(), method === "GET" ? bytes : "");
    }
  }
});

test("an ignored sub-range exposes the whole-file fallback and cancels the response", async () => {
  let cancelled = false;
  const worker = relay(allowed, (_, options) => {
    if (!options.headers.has("Range")) return new Response(bytes);
    return new Response(new ReadableStream({cancel() { cancelled = true; }}));
  });
  const response = await worker.fetch(request("bytes=0-3"), env);
  assert.equal(response.status, 416);
  assert.equal(response.headers.get("X-OWL-Reason"), "publisher-ignores-range");
  assert.match(response.headers.get("Access-Control-Expose-Headers"), /\bX-OWL-Reason\b/i);
  assert.equal(response.headers.get("Content-Range"), "bytes */10");
  assert.equal(cancelled, true);
  assert.equal(await (await worker.fetch(request(), env)).text(), bytes);
});

test("an ignored whole-file Range requires a pinned-length, identity-encoded response", async () => {
  for (const headers of [{}, {"Content-Length": "9"}, {"Content-Length": "10", "Content-Encoding": "gzip"}]) {
    const worker = relay(allowed, () => new Response(bytes, {headers}));
    assert.equal((await worker.fetch(request("bytes=0-"), env)).status, 502);
  }
});

test("archive relay peers never pass through an upstream full body", async () => {
  const worker = relay({reference: {...allowed.reference, max_range_bytes: 10}},
    () => new Response(bytes, {headers: {"Content-Length": "10"}}));
  const response = await worker.fetch(request("bytes=0-9"), env);
  assert.equal(response.status, 416);
  assert.equal(response.headers.get("X-OWL-Reason"), "publisher-ignores-range");
});

test("the production browser route check follows the relay's whole-file fallback", async () => {
  const body = bytes.repeat(4);
  const worker = relay({reference: {...allowed.reference, bytes: body.length}},
    () => new Response(body, {headers: {"Content-Length": String(body.length)}}));
  const requested = [];
  const results = await probeBrowserRoutes(["https://relay.example/assets/reference"], (_, options) => {
    const range = options.headers?.Range;
    requested.push(range);
    return worker.fetch(request(range), env);
  });
  assert.deepEqual(requested, ["bytes=0-15", undefined]);
  assert.deepEqual(results, [{ok: true, detail: "HTTP 200"}]);
});
