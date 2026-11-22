import assert from "node:assert/strict";
import {test} from "node:test";
import {relay} from "../relay/worker.mjs";

const origin = "https://example.github.io";
const publisher = "https://publisher.example/pinned.pdf";
const allowed = {reference:{url:publisher, bytes:10}};
const env = {ALLOWED_ORIGIN:origin, REQUEST_LIMIT:{limit:async () => ({success:true})}};
const request = (path, headers = {}) => new Request("https://relay.example" + path,
  {headers:{Origin:origin, "CF-Connecting-IP":"192.0.2.1", ...headers}});

test("the configured relay serves only the pinned publisher URL and exact byte range", async () => {
  const worker = relay(allowed, async (url, options) => {
    assert.equal(url, publisher);
    assert.equal(options.redirect, "manual");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers.get("Range"), "bytes=2-4");
    assert.equal(options.headers.has("Cookie"), false);
    return new Response("abc", {status:206, headers:{"Content-Range":"bytes 2-4/10", "Content-Length":"3"}});
  });
  const result = await worker.fetch(request("/assets/reference", {Range:"bytes=2-4", Cookie:"private"}), env);
  assert.equal(result.status, 206);
  assert.equal(result.headers.get("Access-Control-Allow-Origin"), origin);
  assert.equal(result.headers.get("Content-Range"), "bytes 2-4/10");
  assert.equal(result.headers.get("Cache-Control"), "private, no-store");
  assert.equal(await result.text(), "abc");
});

test("the relay rejects unapproved requests, redirects and requests over the rate limit", async () => {
  const untouched = relay(allowed, () => assert.fail("No publisher request expected"));
  assert.equal((await untouched.fetch(request("/assets/reference"), {})).status, 403);
  assert.equal((await untouched.fetch(request("/assets/reference?url=https://elsewhere.test"), env)).status, 404);
  assert.equal((await untouched.fetch(request("/assets/reference", {Range:"bytes=0-1,3-4"}), env)).status, 416);
  assert.equal((await untouched.fetch(request("/assets/reference"),
    {...env, REQUEST_LIMIT:{limit:async () => ({success:false})}})).status, 429);
  const redirect = relay(allowed, async () => Response.redirect("https://unlisted.example/file"));
  assert.equal((await redirect.fetch(request("/assets/reference"), env)).status, 502);
});

test("optional archive peers only accept bounded ranged requests", async () => {
  const worker = relay({archive:{url:publisher, bytes:10, max_range_bytes:3}}, async () =>
    new Response("abc", {status:206, headers:{"Content-Range":"bytes 2-4/10", "Content-Length":"3"}}));
  assert.equal((await worker.fetch(request("/assets/archive"), env)).status, 416);
  assert.equal((await worker.fetch(request("/assets/archive", {Range:"bytes=2-5"}), env)).status, 416);
  assert.equal((await worker.fetch(request("/assets/archive", {Range:"bytes=2-4"}), env)).status, 206);
});

test("the Worker enforces 64 MiB even with an older allowlist and rejects open or out-of-bounds archive ranges", async () => {
  const limit = 64 * 2 ** 20;
  const size = 2 ** 30;
  const worker = relay({archive:{url:publisher, bytes:size, max_range_bytes:size}},
    () => assert.fail("No upstream request for an invalid range"));
  for (const Range of ["bytes=0-" + limit, "bytes=0-", "bytes=1-" + size, "bytes=0-9999999999999999999999"]) {
    assert.equal((await worker.fetch(request("/assets/archive", {Range}), env)).status, 416);
  }
});

test("a busy or unreachable publisher is reported as retryable, not as a catalog mismatch", async () => {
  const busy = relay(allowed, async () => new Response("slow down", {status:429, headers:{"Retry-After":"5"}}));
  const answer = await busy.fetch(request("/assets/reference", {Range:"bytes=2-4"}), env);
  assert.equal(answer.status, 429);
  assert.equal(answer.headers.get("Retry-After"), "5");
  assert.match(answer.headers.get("Access-Control-Expose-Headers"), /\bRetry-After\b/i);
  const date = "Sun, 22 Nov 2026 12:00:00 GMT";
  const retry = relay(allowed, async () => new Response(null, {status: 503, headers: {"Retry-After": date}}));
  assert.equal((await retry.fetch(request("/assets/reference"), env)).headers.get("Retry-After"), date);
  assert.equal((await relay(allowed, async () => new Response("", {status:503})).fetch(
    request("/assets/reference", {Range:"bytes=2-4"}), env)).status, 503);
  assert.equal((await relay(allowed, async () => { throw new TypeError("network"); }).fetch(
    request("/assets/reference", {Range:"bytes=2-4"}), env)).status, 503);
});
