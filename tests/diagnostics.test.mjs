import assert from "node:assert/strict";
import {test} from "node:test";
import {diag, diagnosticsText, routeLabel} from "../web/diagnostics.mjs";

test("routes are labeled by relay peer or direct host", () => {
  assert.equal(routeLabel("https://owl-publisher-relay.example.workers.dev/assets/ifixit_en--dotsrc"), "relay:dotsrc");
  assert.equal(routeLabel("https://owl-publisher-relay.example.workers.dev/assets/ifixit_en"), "relay:primary");
  assert.equal(routeLabel("https://mirror.download.kiwix.org/zim/ifixit/x.zim"), "direct:mirror.download.kiwix.org");
});

test("the copied text carries a per-route summary and every event", () => {
  diag("request", {asset: "a", piece: 0, route: "relay:dotsrc", ok: true, bytes: 4_194_304, ms: 200});
  diag("request", {asset: "a", piece: 1, route: "relay:dotsrc", ok: false, status: 429, error: "HTTP 429"});
  const text = diagnosticsText();
  assert.match(text, /relay:dotsrc: 1\/2 ok, 4\.2 MB/);
  assert.match(text, /failed \(last: HTTP 429/);
  assert.match(text, /request asset=a piece=1 route=relay:dotsrc ok=false status=429/);
});
