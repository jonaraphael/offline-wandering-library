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
