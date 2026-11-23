// Exercise the built page's CSP and its live browser fetch routes.
const {once} = require("node:events");
const {createReadStream} = require("node:fs");
const {readFile, stat} = require("node:fs/promises");
const {createServer} = require("node:http");
const path = require("node:path");
const {pipeline} = require("node:stream/promises");

const READER_IDS = ["kiwix_windows", "kiwix_linux", "kiwix_macos", "kiwix_android"];
const TYPES = {".html": "text/html", ".mjs": "text/javascript", ".js": "text/javascript",
  ".json": "application/json", ".css": "text/css", ".svg": "image/svg+xml"};

async function routesToCheck(root, pageURL) {
  const read = async file => JSON.parse(await readFile(path.join(root, file), "utf8"));
  const [{routes}, {archiveRelay}, search] = await Promise.all([
    read("catalog.json"), read("chunk-manifests.json"), read("search-build.json")
  ]);
  const byOrigin = new Map();
  const requests = new Map();
  function check(id, value) {
    const url = new URL(value, pageURL);
    if (!byOrigin.has(url.origin)) byOrigin.set(url.origin, [url.href, id]);
  }
  for (const id of READER_IDS) {
    if (!routes[id]?.length) throw Error("No route for reader package " + id);
    for (const url of routes[id]) requests.set(new URL(url, pageURL).href, id);
  }
  // Prefer an archive relay route when enabled, since those routes require a range.
  for (const [id, urls] of Object.entries(archiveRelay || {})) {
    for (const url of urls) check(id, url);
  }
  for (const [id, urls] of Object.entries(routes)) {
    if (READER_IDS.includes(id)) continue;
    for (const url of urls) check(id, url);
  }
  const chunk = Object.keys(search.plan.chunks)[0];
  if (chunk) check("search", new URL(chunk, new URL(search.base, pageURL)));
  for (const [url, id] of byOrigin.values()) requests.set(url, id);
  return requests;
}

async function serve(root, request, response) {
  const relative = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const file = path.resolve(root, "." + relative);
  if (!file.startsWith(root + path.sep)) return response.writeHead(404).end();
  const info = await stat(file).catch(() => null);
  if (!info?.isFile()) return response.writeHead(404).end();
  const ranged = request.headers.range === "bytes=0-15" && info.size > 0;
  const bytes = ranged ? Math.min(16, info.size) : info.size;
  const headers = {"Content-Type": TYPES[path.extname(file)] || "application/octet-stream",
    "Content-Length": bytes};
  if (ranged) headers["Content-Range"] = "bytes 0-" + (bytes - 1) + "/" + info.size;
  response.writeHead(ranged ? 206 : 200, headers);
  await pipeline(createReadStream(file, ranged ? {end: bytes - 1} : {}), response);
}

async function probeBrowserRoutes(urls, fetchURL = fetch) {
  return Promise.all(urls.map(async url => {
    try {
      const signal = AbortSignal.timeout(20_000);
      let response = await fetchURL(url, {headers: {Range: "bytes=0-15"}, signal});
      if (response.status === 416 && response.headers.get("X-OWL-Reason") === "publisher-ignores-range") {
        await response.body?.cancel();
        response = await fetchURL(url, {signal});
      }
      const range = response.headers.get("Content-Range");
      const reader = response.body?.getReader();
      // Read only a prefix so a route check never downloads an archive.
      let bytes = 0;
      if (response.ok && reader) {
        while (bytes < 16) {
          const {value, done} = await reader.read();
          if (done) break;
          bytes += value.byteLength;
        }
      }
      await reader?.cancel();
      return {ok: response.ok && bytes >= 16, detail: "HTTP " + response.status + (range ? " " + range : "")};
    } catch (error) {
      return {ok: false, detail: error.message};
    }
  }));
}

async function main(directory, chrome, playwright, siteURL) {
  if (!directory || !chrome || !playwright) {
    throw Error("Usage: node scripts/check_csp_routes.cjs <pages-dir> <chrome> <playwright-core> [published-site-url]");
  }
  const root = path.resolve(directory);
  const server = createServer((request, response) => {
    serve(root, request, response).catch(error => response.destroy(error));
  });
  const {chromium} = require(playwright);
  let browser;
  try {
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const local = "http://127.0.0.1:" + server.address().port;
    const pageURL = new URL("index.html", siteURL || local + "/");
    const requests = await routesToCheck(root, pageURL);
    browser = await chromium.launch({executablePath: chrome});
    const page = await browser.newPage();
    if (siteURL) {
      // Give the locally served artifact its production origin. The relay
      // deliberately grants CORS only to that origin. External fetches and
      // redirects still go through Chrome's normal CSP and CORS checks.
      const base = new URL(".", pageURL).href;
      await page.route(url => url.href.startsWith(base), async route => {
        const response = await route.fetch({url: local + "/" + route.request().url().slice(base.length)});
        await route.fulfill({response});
        await response.dispose();
      });
    }
    const violations = [];
    await page.exposeFunction("reportRoutePolicyViolation", message => violations.push(message));
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", event => {
        window.reportRoutePolicyViolation(event.effectiveDirective + " blocked " + event.blockedURI);
      });
    });
    const navigation = await page.goto(pageURL.href, {waitUntil: "domcontentloaded", timeout: 30_000});
    if (!navigation?.ok()) throw Error("Could not load the built Pages index");
    const results = await page.evaluate(probeBrowserRoutes, [...requests.keys()]);
    let passed = 0;
    let index = 0;
    for (const [url, id] of requests) {
      const result = results[index++];
      if (result.ok) passed++;
      console.log((result.ok ? "PASS" : "FAIL") + " " + id + " " + url + " " + result.detail);
    }
    for (const violation of violations) console.error(violation);
    console.log(passed + "/" + requests.size + " browser routes passed. CSP violations: " + violations.length);
    if (passed !== requests.size || violations.length) process.exitCode = 1;
  } finally {
    try {
      await browser?.close();
    } finally {
      await new Promise(resolve => server.close(resolve));
    }
  }
}

if (require.main === module) {
  main(...process.argv.slice(2)).catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
}

module.exports = {probeBrowserRoutes};
