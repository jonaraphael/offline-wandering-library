/* Exercise the generated Pages entry, real browser storage and the downloaded offline reader. */
const assert = require("node:assert/strict");
const {createHash} = require("node:crypto");
const {execFileSync} = require("node:child_process");
const {mkdtemp, mkdir, readFile, readdir, rm} = require("node:fs/promises");
const {tmpdir} = require("node:os");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const browsers = require("playwright-core");
const engine = process.argv[3] || "firefox";

async function check(site, scratch) {
  const prefix = "/" + path.basename(scratch) + "/";
  const url = "http://localhost" + prefix;
  const catalog = JSON.parse(await readFile(path.join(site, "catalog.json"), "utf8"));
  const article = "<h1>Offline fixture article</h1>";
  const asset = catalog.planner.assets.find(row => row.id === "sanitation");
  Object.assign(asset, {title: "Fixture article", destination: "CRITICAL/" + "shelf/".repeat(18) + "café.html",
    size_bytes: Buffer.byteLength(article), sha256: createHash("sha256").update(article).digest("hex"), format: "html"});
  for (const other of catalog.planner.assets) if (other !== asset) other.utility_tier = "USEFUL";
  catalog.routes = {[asset.id]: [url + "article"]};
  const context = await browsers[engine].launchPersistentContext(path.join(scratch, "profile"));
  const errors = [];
  const page = context.pages()[0];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await context.route(url + "**", async route => {
      const name = new URL(route.request().url()).pathname.slice(prefix.length);
      if (name === "catalog.json") return route.fulfill({json: catalog});
      if (name === "article") return route.fulfill({body: article});
      if (name === "chunk-manifests.json") return route.fulfill({json: {}});
      if (name === "search-build.json") return route.fulfill({json: {
        plan: {version: 1, sources: [], model: [], reserve: 0}, records: [], page: "", runtime: "", rankRuntime: ""
      }});
      return route.fulfill({path: path.join(site, name || "index.html"),
        contentType: /\.m?js$/.test(name) ? "text/javascript" : "text/html"});
    });
    await page.goto(url);
    const openLocal = () => page.getByRole("button", {name: "Open local builder"}).click();
    await openLocal();
    await page.getByRole("link", {name: "Manage what goes on it"}).click();
    assert.match(await page.locator("#manage-limit-value").textContent(), /1 GB/);
    await page.getByRole("button", {name: "Done", exact: true}).click();
    await page.getByRole("button", {name: "Sync", exact: true}).click();
    const prepare = page.getByRole("button", {name: "Prepare download"});
    await prepare.waitFor();
    await page.reload();
    await openLocal();
    await prepare.click();
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("link", {name: "Download library (.tar)"}).click();
    const archive = path.join(scratch, "library.tar");
    await (await downloadEvent).saveAs(archive);
    const drive = path.join(scratch, "extracted");
    await mkdir(drive);
    execFileSync("tar", ["-xf", archive, "-C", drive]);
    assert.deepEqual((await readdir(drive)).sort(), ["LIBRARY", "START_HERE.html"]);
    assert.ok(!(await readdir(path.join(drive, "LIBRARY"))).includes(".owl"));
    assert.equal(await readFile(path.join(drive, "LIBRARY", asset.destination), "utf8"), article);
    const offline = await context.newPage();
    // WebKit's offline emulation also blocks file: navigation. Block the
    // network protocols so the browser can still read the extracted drive.
    const network = [];
    await offline.route(/^https?:/, route => {
      network.push(route.request().url());
      return route.abort();
    });
    await offline.goto(pathToFileURL(path.join(drive, "START_HERE.html")).href);
    assert.match(await offline.title(), /Offline Wandering Library/i);
    await offline.getByRole("link", {name: "Help"}).click();
    await offline.getByRole("link", {name: "Every file, with its location"}).click();
    await offline.getByRole("link", {name: asset.title}).click();
    assert.equal(await offline.locator("h1").innerText(), "Offline fixture article");
    assert.deepEqual(network, []);
    page.once("dialog", dialog => dialog.accept());
    await page.getByRole("link", {name: "Clear local copy"}).click();
    await openLocal();
    await page.getByRole("button", {name: "Sync", exact: true}).waitFor();
    assert.equal(await prepare.count(), 0);
    await offline.reload();
    assert.equal(await offline.locator("h1").innerText(), "Offline fixture article");
    assert.deepEqual(errors, []);
    console.log(engine + " built, reopened, exported, read and cleared the local library.");
  } catch (error) {
    console.error(await page.locator("#sync-stage").innerText(), errors);
    throw error;
  } finally { await context.close(); }
}

async function main() {
  const scratch = await mkdtemp(path.join(tmpdir(), "owl-local-build-"));
  try { await check(process.argv[2], scratch); }
  finally { await rm(scratch, {recursive: true, force: true}); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
