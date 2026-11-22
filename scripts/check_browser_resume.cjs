/* Local fixture. Run with a scratch directory, an installed Chrome and playwright-core. */
const {createHash} = require("node:crypto");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const {createServer} = require("node:http");
const {readFile} = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");

const [scratch, chrome, playwright, test] = process.argv.slice(2);
if (!scratch || !chrome || !playwright) throw Error("Specify a scratch directory, Chrome, and playwright-core.");
const {chromium} = require(playwright);
const GiB = 2 ** 30;
const block = Buffer.alloc(1024 * 1024, 42);
const diskFull = test === "disk-full";
const bytes = diskFull ? 2 ** 20 : 20 * GiB;
const digest = createHash("sha256");
for (let offset = 0; offset < bytes; offset += block.length) digest.update(block);
const archive = {id:"scale", title:"Scale fixture", format:"zim", destination:"ZIM/scale.zim",
  size_bytes:bytes, sha256:digest.digest("hex"), utility_tier:"USEFUL"};
const requests = [];
if (diskFull) Object.assign(archive, {format:"pdf", destination:"BOOKS/too-big.pdf", utility_tier:"CRITICAL",
  selection:{level:0, rank:1}});
const marker = {id:"marker", title:"After disk full", format:"pdf", destination:"BOOKS/marker.pdf",
  size_bytes:5, sha256:createHash("sha256").update("works").digest("hex"), utility_tier:"CRITICAL",
  selection:{level:0, rank:2}};
const optional = {...marker, id:"optional", destination:"BOOKS/optional.pdf", utility_tier:"NONESSENTIAL"};
const server = createServer(async (request, response) => {
  if (request.url === "/") return response.end("<!doctype html><title>OWL local scale test</title>");
  if (request.url === "/marker") return response.end("works");
  if (request.url === "/asset") {
    const match = /^bytes=(\d+)-(\d+)$/.exec(request.headers.range);
    const [, from, to] = match || [null, 0, bytes - 1];
    const size = Number(to) - Number(from) + 1;
    requests.push(Number(from));
    const headers = {"Content-Length":size};
    if (match) headers["Content-Range"] = "bytes " + from + "-" + to + "/" + bytes;
    response.writeHead(match ? 206 : 200, headers);
    try {
      for (let off = 0; off < size && !response.destroyed; off += block.length) {
        if (!response.write(block.subarray(0, Math.min(block.length, size - off)))) {
          await new Promise(resolve => {
            const done = () => { response.off("close", done); response.off("drain", done); resolve(); };
            response.once("close", done).once("drain", done);
          });
        }
      }
    } finally { response.end(); }
    return;
  }
  if (/^\/web\/[a-zA-Z0-9_./-]+$/.test(request.url) && !request.url.includes("..")) {
    try {
      const source = await readFile(path.join(process.cwd(), request.url));
      response.writeHead(200, {"Content-Type": "text/javascript"});
      response.end(source);
    } catch (_) { response.writeHead(404).end(); }
  } else response.writeHead(404).end();
});

async function openChrome() {
  const profile = path.join(scratch, diskFull ? "chrome-quota-fixture" : "chrome-test-profile");
  const process = spawn(chrome, ["--headless", "--remote-debugging-port=0", "--no-first-run", "--disable-background-networking",
    "--user-data-dir=" + profile, "about:blank"], {stdio:["ignore","ignore","pipe"]});
  const listening = new Promise((resolve, reject) => {
    let logs = "";
    process.stderr.on("data", data => {
      logs += data;
      const url = /DevTools listening on (ws:\/\/\S+)/.exec(logs)?.[1];
      if (url) resolve(url);
    });
    process.once("exit", code => reject(Error("Chrome exited before connecting: " + code + " " + logs)));
  });
  const browser = await chromium.connectOverCDP(await listening);
  const page = browser.contexts()[0].pages()[0];
  await page.goto("http://127.0.0.1:" + server.address().port);
  return {process, browser, page};
}

async function main() {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  if (diskFull) {
    const {browser, page, process: child} = await openChrome();
    const before = performance.now();
    try {
      const result = await page.evaluate(async ({archive, marker, optional}) => {
        const {buildLibrary} = await import("/web/builder.mjs");
        const {pickDrive} = await import("/web/drive.mjs");
        const wrap = handle => ({
          getDirectoryHandle: async (...args) => wrap(await handle.getDirectoryHandle(...args)),
          getFileHandle: async (name, options) => {
            const file = await handle.getFileHandle(name, options);
            if (name !== "too-big.pdf") return file;
            return {getFile: () => file.getFile(), async createWritable(...args) {
              const stream = await file.createWritable(...args);
              let written = 0;
              return {
                async write(data) {
                  written += data.byteLength;
                  if (written > 256 * 2 ** 10) throw new DOMException("Simulated disk full", "QuotaExceededError");
                  await stream.write(data);
                },
                abort: () => stream.abort(), close: () => stream.close()
              };
            }};
          },
          removeEntry: (...args) => handle.removeEntry(...args), values: () => handle.values()
        });
        globalThis.showDirectoryPicker = async () => wrap(await navigator.storage.getDirectory());
        const drive = await pickDrive();
        const result = await buildLibrary(drive, {assets:[archive, marker, optional],
          routes:{scale:[location.origin + "/asset"], marker:[location.origin + "/marker"],
            optional:[location.origin + "/marker"]}});
        return {dropped:result.state.dropped, verified:result.completed.map(asset => asset.id)};
      }, {archive, marker, optional});
      console.log(JSON.stringify({seconds:(performance.now()-before)/1000,...result}));
      assert.deepEqual(result, {dropped:{scale:"Drive ran out of space", optional:"Drive ran out of space"}, verified:["marker"]});
    } finally {
      await browser.close();
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
      if (child.exitCode === null && child.signalCode === null) await once(child, "exit");
    }
    return;
  }
  for (const [run, killAt] of [2, 8, 15, null].entries()) {
    const {page, process, browser} = await openChrome();
    const before = performance.now();
    let interrupted;
    try {
      const stopped = new Promise(resolve => { interrupted = resolve; });
      page.on("console", msg => { if (msg.text() === "STOP") interrupted(); });
      const building = page.evaluate(async ({archive, killAt, run}) => {
        const {buildLibrary, readBuild} = await import("/web/builder.mjs");
        const {pickDrive} = await import("/web/drive.mjs");
        // This test picker persists real Chromium writable files across process restarts.
        globalThis.showDirectoryPicker = () => navigator.storage.getDirectory();
        const drive = await pickDrive();
        const prior = await readBuild(drive);
        const result = await buildLibrary(drive, {assets:[archive], routes:{scale:[location.origin + "/asset"]}, resume:run > 0,
          onProgress: event => {
            if (event.kind === "downloading" && event.index === killAt && event.received >= 128 * 2 ** 20) console.log("STOP");
          }});
        return {before:prior?.parts.scale.length || 0, after:result.state.parts.scale.length, finished:result.state.finished};
      }, {archive, killAt, run});
      if (killAt === null) {
        const result = await building;
        assert.deepEqual(result, {before:15, after:20, finished:true});
        await browser.close();
      } else {
        await Promise.race([stopped, building.then(() => { throw Error("Fixture finished before the intended interruption"); })]);
        process.kill("SIGKILL");
        await building.catch(() => {});
      }
      console.log(JSON.stringify({run, killAt, seconds:Number(((performance.now() - before)/1000).toFixed(2)), requestStarts:requests.splice(0)}));
    } finally {
      if (process.exitCode === null && process.signalCode === null) process.kill("SIGKILL");
      if (process.exitCode === null && process.signalCode === null) await once(process, "exit");
    }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; })
  .finally(() => { server.closeAllConnections(); server.close(); });
