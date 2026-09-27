#!/usr/bin/env node
/* Bounded, offline browser QA for pinned ordinary HTML documents. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {argumentsFor, inside, validate} = require('./check_phet.cjs');

const HELP = `Usage: node scripts/check_documents.cjs --manifest checks.json --root DIR --output report.json [--screenshots DIR] [--browser /path/to/chromium] [--playwright /path/to/playwright-core]

Uses existing Node>=18, Playwright/playwright-core and Chromium. Downloads nothing.
Manifest: {"assets":[{"id":"example","destination":"document.html","sha256":"64 lower-case hex digits","expected_images":4,"expected_tables":9,"allow_missing_local":["companion.pdf"]}],"viewports":[{"width":1280,"height":900},{"width":390,"height":844}]}
Every allowed absent local link is reported as pending; it never proves a finished
library. Other missing local links, broken same-page anchors, failed images,
network requests, browser errors, and horizontal page overflow fail the check.
Screenshots show the beginning, a representative table and a figure at each size.
`;

async function sha256(file) {
  const digest = crypto.createHash('sha256');
  for await (const block of fs.createReadStream(file)) digest.update(block);
  return digest.digest('hex');
}

function save(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  fs.writeFileSync(file + `.part-${process.pid}`, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(file + `.part-${process.pid}`, file);
}

async function main(argv = process.argv.slice(2)) {
  const options = argumentsFor(argv);
  if (options.help) { process.stdout.write(HELP); return; }
  for (const key of ['manifest', 'root', 'output']) if (!options[key]) throw Error(`--${key} is required`);
  if (options['validate-only']) throw Error('--validate-only is not supported; use the complete offline document check');
  if (fs.statSync(options.manifest).size > 4 * 1024 * 1024) throw Error('Manifest exceeds 4 MiB');
  const manifest = JSON.parse(fs.readFileSync(options.manifest, 'utf8'));
  const root = fs.realpathSync(options.root);
  const viewports = await validate(manifest, root);
  if (manifest.assets.length > 100) throw Error('At most 100 documents per QA run');
  for (const asset of manifest.assets) {
    for (const key of ['expected_images', 'expected_tables']) if (!Number.isInteger(asset[key]) || asset[key] < 0 || asset[key] > 5000) throw Error(`${asset.id}: ${key} must be an integer between zero and 5000`);
    if (fs.statSync(inside(root, asset.destination)).size > 64 * 1024 * 1024) throw Error(`${asset.id}: HTML exceeds 64 MiB`);
    if (asset.allow_missing_local && (!Array.isArray(asset.allow_missing_local) || asset.allow_missing_local.length > 500 || asset.allow_missing_local.some(value => typeof value !== 'string' || value.length > 2048))) throw Error(`${asset.id}: allow_missing_local must be a bounded list of exact local hrefs`);
  }
  let playwright;
  try { playwright = require(options.playwright || 'playwright'); }
  catch {
    try { if (options.playwright) throw Error(); playwright = require('playwright-core'); }
    catch { throw Error('Supply --playwright /path/to/playwright-core and --browser /path/to/already-installed/chromium; no dependencies were downloaded.'); }
  }
  const report = {schema_version: 1, network_blocked: true, downloads: false,
    scope: 'Pinned local HTML browser rendering. Explicitly allowed absent companion files remain pending until the normal library build.', checks: []};
  const browser = await playwright.chromium.launch({headless: true, chromiumSandbox: true, executablePath: options.browser});
  report.browser_version = browser.version();
  try {
    for (const asset of manifest.assets) for (const viewport of viewports) {
      const context = await browser.newContext({viewport, offline: true, permissions: []});
      const check = {id: asset.id, source_sha256: asset.sha256, source_bytes: fs.statSync(inside(root, asset.destination)).size,
        viewport, remote_request_count: 0, remote_requests: [], errors: [], missing_local_links: [], pending_local_links: []};
      await context.route(/^https?:/, async route => {
        check.remote_request_count++;
        if (check.remote_requests.length < 20) check.remote_requests.push(route.request().url().slice(0, 500));
        await route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', error => { if (check.errors.length < 20) check.errors.push(error.message.slice(0, 500)); });
      page.on('console', message => { if (message.type() === 'error' && check.errors.length < 20) check.errors.push(message.text().slice(0, 500)); });
      try {
        await page.goto(pathToFileURL(inside(root, asset.destination)).href, {timeout: 20000});
        check.document = await page.evaluate(() => {
          const images = Array.from(document.images);
          const anchors = Array.from(document.querySelectorAll('a[href]'));
          if (images.length > 5000 || anchors.length > 20000) throw Error('Document DOM exceeds bounded QA limits');
          const localLinks = new Set(), brokenAnchors = new Set();
          for (const anchor of anchors) {
            const url = new URL(anchor.href);
            if (url.protocol !== 'file:') continue;
            if (url.pathname === location.pathname) {
              if (url.hash) {
                let id; try { id = decodeURIComponent(url.hash.slice(1)); } catch { brokenAnchors.add(url.hash); continue; }
                if (!document.getElementById(id) && !Array.from(document.getElementsByName(id)).length) brokenAnchors.add(url.hash);
              }
            } else localLinks.add(anchor.getAttribute('href'));
          }
          return {images: images.map(image => ({loaded: image.complete && image.naturalWidth > 0,
            width: image.naturalWidth, height: image.naturalHeight, alt: image.alt.slice(0, 200)})),
            tables: document.querySelectorAll('table').length, broken_anchors: Array.from(brokenAnchors),
            local_links: Array.from(localLinks).sort(), viewport_width: innerWidth,
            document_width: document.documentElement.scrollWidth};
        });
        const sourceURL = pathToFileURL(inside(root, asset.destination));
        for (const href of check.document.local_links) {
          const url = new URL(href, sourceURL);
          url.hash = ''; url.search = '';
          if (!fs.existsSync(fileURLToPath(url))) {
            if ((asset.allow_missing_local || []).includes(href)) check.pending_local_links.push(href);
            else check.missing_local_links.push(href);
          }
        }
        if (options.screenshots) {
          fs.mkdirSync(options.screenshots, {recursive: true});
          const prefix = path.join(options.screenshots, `${asset.id}-${viewport.width}`);
          await page.screenshot({path: prefix + '-top.png'});
          for (const [name, selector] of [['table', 'table'], ['figure', 'img']]) {
            const element = page.locator(selector).first();
            if (await element.count()) {
              await element.scrollIntoViewIfNeeded({timeout: 5000});
              await page.screenshot({path: prefix + `-${name}.png`});
            }
          }
        }
        check.source_unchanged = await sha256(inside(root, asset.destination)) === asset.sha256;
        check.success = check.source_unchanged && check.document.images.length === asset.expected_images &&
          check.document.images.every(image => image.loaded) && check.document.tables === asset.expected_tables &&
          check.document.broken_anchors.length === 0 && check.missing_local_links.length === 0 &&
          check.document.document_width <= viewport.width + 1 && check.remote_request_count === 0 && check.errors.length === 0;
        if (!check.success) check.failure = 'Integrity, images, tables, anchors, local links, layout, or offline checks failed';
      } catch (error) { check.success = false; check.failure = error.message.slice(0, 1000); }
      finally { await context.close(); }
      report.checks.push(check);
      save(options.output, report);
    }
  } finally { await browser.close(); }
  report.success = report.checks.every(check => check.success);
  report.companion_files_complete = report.checks.every(check => !check.pending_local_links.length && !check.missing_local_links.length);
  save(options.output, report);
  process.stdout.write(JSON.stringify({success: report.success, companion_files_complete: report.companion_files_complete,
    checks: report.checks.length, failures: report.checks.filter(check => !check.success).map(check => ({id: check.id, width: check.viewport.width, failure: check.failure.slice(0, 100)})).slice(0, 8), report: options.output}) + '\n');
  if (!report.success) process.exitCode = 1;
}

module.exports = {main};
if (require.main === module) main().catch(error => { console.error(error.message.slice(0, 1800)); process.exitCode = 1; });
