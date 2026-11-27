// Usage: node scripts/check_archive_pages.cjs DRIVE PAGE ZIM_FOLDER chrome,firefox,webkit [EVIDENCE_DIR]
// Requires playwright-core and its browsers. Set OWL_CHROME to the Chrome executable on other platforms.
// Set OWL_VIDEO_SAMPLE to at least 60 if the full OER4Schools video sweep exceeds the time budget.
'use strict';

const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {openAsBlob} = require('node:fs');
const {mkdir, readFile, writeFile} = require('node:fs/promises');
const {join, resolve} = require('node:path');
const {performance} = require('node:perf_hooks');
const {setTimeout: delay} = require('node:timers/promises');
const {pathToFileURL} = require('node:url');
const {chromium, firefox, webkit} = require('playwright-core');
const {Zim} = require('../src/owl/templates/zim.js');
const {readRoute} = require('../src/owl/templates/zim-drive.js');

const phet = 'phet_archive';
const oer = 'oer4schools_en_all_2025_10';
const seed = 'owl-archive-pages-v1';
const html = entry => /^(?:text\/html|application\/xhtml\+xml)\b/i.test(entry.mime || '');
const ready = '#article-paper[data-ready="true"]';
const frameSelector = '#article-paper iframe';
const timeout = 15_000;
const viewport = {width: 1280, height: 900};
const engineTypes = {chrome: chromium, chromium, firefox, webkit};
const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const cleanTitle = title => title.replace(/[\u200e\u200f\u202a-\u202e]/g, '').replace(/\s+/g, ' ').trim();

function randomIndexes(key, count) {
  let state = createHash('sha256').update(seed + '/' + key).digest().readUInt32LE(0);
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return Math.floor(state / 0x100000000 * count);
  };
}

async function pagePlan(drive, folder, videoLimit) {
  const inventory = JSON.parse(await readFile(join(drive, 'LIBRARY', 'INVENTORY.json'), 'utf8'));
  const archives = inventory.assets.filter(asset => asset.parts?.length &&
    asset.parts.every(part => part.path.startsWith('LIBRARY/ZIM/')));
  assert.ok(archives.length, 'No ZIMs in this drive inventory');
  const priority = id => id === phet ? 0 : id === oer ? 1 : 2;
  archives.sort((first, second) => priority(first.id) - priority(second.id));
  const plan = [];
  for (const {id, title, parts} of archives) {
    const files = await Promise.all(parts.map(part => openAsBlob(join(folder, part.path.slice('LIBRARY/ZIM/'.length)))));
    const zim = await new Zim(files).init();
    const main = await zim.get('@main');
    assert.ok(main && html(main), id + ' has no HTML main page');
    const pages = [{path: '@main', type: 'home'}];
    const routePath = entry => (zim.minor === 0 ? entry.ns + '/' : '') + entry.path;
    if (id === phet || id === oer) {
      for (let index = 0; index < zim.entryCount; index++) {
        const entry = await zim.entry(index);
        if (entry.ns !== zim.contentNamespace() || !html(entry)) continue;
        if (id === phet) {
          pages.push({path: routePath(entry), type: /_en\.html$/.test(entry.path) ? 'simulation' : 'catalogue',
            title: cleanTitle(entry.title)});
        } else if (entry.index !== main.index) {
          const markup = await (await zim.blob(entry)).text();
          const target = markup.match(/#\/(playlist|watch)\/([^?'"]+)/);
          pages.push({path: routePath(entry), type: target?.[1] || 'page', title: cleanTitle(entry.title),
            segment: target?.[2]});
        }
      }
    } else {
      const next = randomIndexes(id, zim.entryCount);
      const seen = new Set([main.index]);
      while (pages.length < 26 && seen.size < zim.entryCount) {
        const index = next();
        if (seen.has(index)) continue;
        seen.add(index);
        const entry = await zim.entry(index);
        if (entry.ns === zim.contentNamespace() && html(entry)) pages.push({path: routePath(entry), type: 'article'});
      }
      assert.equal(pages.length, 26, id + ' must have at least 25 HTML entries besides its main page');
    }
    let included = pages;
    if (id === oer && videoLimit) {
      const videos = pages.filter(page => page.type === 'watch');
      const next = randomIndexes(id + '/watch', videos.length);
      const selected = new Set();
      while (selected.size < Math.min(videoLimit, videos.length)) selected.add(videos[next()]);
      included = pages.filter(page => page.type !== 'watch' || selected.has(page));
    }
    plan.push({id, title, pages: included});
  }
  return plan;
}

function installObservers() {
  delete window.showDirectoryPicker;
  const events = [], diagnostics = [], draws = new WeakMap();
  document.addEventListener('owl:archive', event => events.push(event.detail), true);
  document.addEventListener('owl:archive-diagnostic', event => diagnostics.push(event.detail), true);
  document.addEventListener('securitypolicyviolation', event => diagnostics.push({
    type: 'csp', directive: event.effectiveDirective, blocked: event.blockedURI,
  }));
  if (window !== top) {
    // Keep the canvas context the simulation chose. Observing its draw calls also
    // works for WebGL canvases that clear their back buffer after compositing.
    for (const [type, methods] of [
      [window.CanvasRenderingContext2D, ['drawImage', 'fill', 'stroke', 'fillRect', 'strokeRect', 'putImageData', 'fillText']],
      [window.WebGLRenderingContext, ['drawArrays', 'drawElements']],
      [window.WebGL2RenderingContext, ['drawArrays', 'drawElements', 'drawArraysInstanced', 'drawElementsInstanced']],
    ]) {
      for (const method of methods) {
        const draw = type?.prototype[method];
        if (!draw) continue;
        type.prototype[method] = function (...args) {
          const result = draw.apply(this, args);
          draws.set(this.canvas, (draws.get(this.canvas) || 0) + 1);
          return result;
        };
      }
    }
  }
  const measure = () => {
    const text = document.body?.innerText.replace(/\s+/g, ' ').trim() || '';
    const size = node => {
      const {width, height} = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {width: Math.round(width), height: Math.round(height),
        visible: width > 3 && height > 3 && style.visibility === 'visible' && Number(style.opacity) > 0};
    };
    const collection = (selector, details) => Array.from(document.querySelectorAll(selector), node => ({
      ...size(node), ...details?.(node),
    }));
    const canvases = collection('canvas', node => ({draws: draws.get(node) || 0}));
    const svgs = collection('svg', node => ({shapes: node.childElementCount}));
    const videos = collection('video', node => ({ready: node.readyState, error: node.error?.code,
      source: node.currentSrc, seconds: node.currentTime, mediaWidth: node.videoWidth, mediaHeight: node.videoHeight}));
    const screenButtons = collection('button', node => ({
      label: (node.getAttribute('aria-label') || node.textContent).trim(),
    })).filter(button => /screen/i.test(button.label));
    return {textLength: text.length, textStart: text.slice(0, 160), title: document.title,
      bodyHeight: document.body?.scrollHeight, viewportHeight: innerHeight,
      mainHeading: document.querySelector('main h1, article h1')?.textContent.trim(),
      emptyListing: document.querySelector('main.article-list #list')?.childElementCount === 0,
      canvases, svgs, videos, screenButtons,
      visibleImages: [...document.images].filter(node => node.naturalWidth > 0 && size(node).visible).length};
  };
  window.owlSweep = {events, diagnostics, measure};
}

async function openPage(page, route, folder) {
  const prior = await page.evaluate(hash => {
    const count = owlSweep.events.length;
    // Keep one session history entry while opening hundreds of pages.
    const oldURL = location.href;
    history.replaceState(null, '', hash);
    dispatchEvent(new HashChangeEvent('hashchange', {oldURL, newURL: location.href}));
    return count;
  }, route);
  if (folder) {
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.locator('.article-start a').click()]);
    await chooser.setFiles(folder);
  }
  await page.waitForFunction(count => owlSweep.events.length > count, prior);
  return page.evaluate(count => owlSweep.events[count], prior);
}

async function readerFrame(page) {
  const frame = await page.locator(frameSelector).elementHandle();
  try {
    const content = await frame.contentFrame();
    assert.ok(content, 'The reader iframe has no document');
    return content;
  } finally {
    await frame.dispose();
  }
}

async function visibleContent(frame, {type, segment}) {
  await frame.waitForFunction(({type, segment}) => {
    if (!window.owlSweep) return false;
    const m = owlSweep.measure();
    if (type === 'simulation') return m.canvases.some(canvas => canvas.visible && canvas.draws) ||
      m.screenButtons.some(button => button.label && button.width > 0 && button.height > 0) ||
      (window.phet?.joist?.sim && m.svgs.some(svg => svg.visible && svg.shapes));
    if (type === 'watch' || type === 'playlist') {
      if (!location.hash.includes('/' + type + '/' + segment)) return false;
      return type === 'watch' ? m.textLength > 20 && m.videos.some(video => video.visible && video.ready >= 1)
        : document.querySelector('a[href*="/watch/"]') && m.textLength > 20;
    }
    return m.textLength > 10 || m.visibleImages || m.svgs.some(svg => svg.visible && svg.shapes) ||
      m.videos.some(video => video.visible && video.ready >= 1);
  }, {type, segment}, {polling: 150});
}

const scraperError = event => event.source === '555e2078f6462cc157a00a6fc25d0c58.js' &&
  /^(?:Uncaught )?(?:ReferenceError: )?(?:\$ is not defined|Can't find variable: \$)$/.test(event.message);

function archiveSide(archive, info) {
  if (archive.id === 'lowtech_magazine' && info.path.includes('/tags/') && info.render?.emptyListing) {
    return ['The tag page has an empty article list in the archive'];
  }
  if (archive.id !== phet || info.type !== 'simulation') return [];
  const issues = [];
  if (info.diagnostics.some(scraperError)) {
    issues.push('PhET scraper calls jQuery ($) that the sim does not ship');
  }
  if (info.cspBlocked.some(event => event.blocked === 'http://phet.colorado.edu/services/check-html-updates')) {
    issues.push('PhET update check blocked by the offline policy');
  }
  return issues;
}

async function sweepPage(page, url, archive, target, folder, browserEvidence) {
  const info = {archive: archive.id, ...target, route: readRoute(archive.id, target.path), mode: 'unavailable'};
  const marks = Object.fromEntries(Object.entries(browserEvidence).map(([key, values]) => [key, values.length]));
  const start = performance.now();
  let priorDiagnostics = 0;
  let rendered;
  try {
    priorDiagnostics = await page.evaluate(() => owlSweep.diagnostics.length);
    info.reader = await openPage(page, info.route, folder);
    info.mode = info.reader?.reason ? 'problem' : info.reader?.mode || (info.reader?.file ? 'file' : 'article');
    if (info.mode === 'problem') info.failure = info.reader.reason;
    else {
      const frame = await readerFrame(page);
      info.sandbox = await page.locator(frameSelector).getAttribute('sandbox');
      try {
        await visibleContent(frame, target);
        rendered = Math.round(performance.now() - start);
      } catch (error) {
        info.failure = 'Content did not render: ' + error.message.split('\n')[0];
      }
      // Simulations issue their optional update check after rendering the first screen.
      if (info.mode === 'app') await delay(200);
      info.render = await frame.evaluate(() => owlSweep.measure());
      info.frameHeight = Math.round(await page.locator(frameSelector).evaluate(node => node.getBoundingClientRect().height));
      info.titleShown = cleanTitle(await page.locator('#article-title').textContent());
      if (!info.titleShown || info.frameHeight < 20) info.failure ||= 'Reader title or frame height is empty';
      if (info.mode === 'app' && (info.sandbox !== 'allow-scripts' || info.frameHeight < 360 ||
          await frame.evaluate(() => self.origin) !== 'null')) info.failure ||= 'App sandbox or frame height is incorrect';
      if (['simulation', 'playlist', 'watch'].includes(target.type) &&
          (info.mode !== 'app' || info.titleShown !== cleanTitle(info.render.title))) {
        info.failure ||= 'App mode or title differs from the archive page';
      }
    }
  } catch (error) {
    info.failure ||= error.message.split('\n')[0];
  }
  info.ms = rendered ?? Math.round(performance.now() - start);
  const current = new URL(page.url());
  info.finalRoute = current.hash;
  current.hash = '';
  if (current.href !== url) info.failure ||= 'The reader left START_HERE for ' + current.href;
  let received = [];
  try {
    received = await page.evaluate(from => owlSweep.diagnostics.slice(from), priorDiagnostics);
  } catch (error) {
    info.failure ||= 'Could not read diagnostics: ' + error.message.split('\n')[0];
  }
  info.cspBlocked = received.filter(event => event.type === 'csp');
  info.diagnostics = received.filter(event => event.type !== 'csp');
  for (const [key, values] of Object.entries(browserEvidence)) info[key] = values.slice(marks[key]);
  info.archiveSide = archiveSide(archive, info);
  const unexpected = info.diagnostics.find(event => event.type === 'error' &&
    (archive.id !== phet || !scraperError(event)));
  if (unexpected) info.failure ||= 'App error: ' + unexpected.message;
  if (info.outsideRequests.length) info.failure ||= 'The browser issued an outside request';
  info.passed = !info.failure;
  return info;
}

async function withinBrowserBudget(operation, label) {
  const timer = new AbortController();
  try {
    return await Promise.race([
      operation,
      delay(timeout * 3, undefined, {signal: timer.signal}).then(() => {
        throw Error(label + ': the headless browser stopped responding');
      }),
    ]);
  } finally {
    timer.abort();
  }
}

async function interactions(page, ids) {
  const results = [];
  async function openFromLibrary(id) {
    await page.evaluate(() => { location.hash = '#/all'; });
    const route = readRoute(id);
    await page.locator('a[href=' + JSON.stringify(route) + ']').first().click();
    await page.waitForFunction(hash => location.hash === hash, route);
    await page.locator(ready).waitFor();
    return readerFrame(page);
  }
  async function run(name, check) {
    let step = 'open archive from library';
    try { results.push({name, passed: true, ...await check(next => { step = next; })}); }
    catch (error) { results.push({name, passed: false, step, url: page.url(), error: error.message}); }
  }
  if (ids.has(phet)) {
    await run('PhET catalogue, simulation screen, fullscreen and Back', async step => {
      const catalogue = readRoute(phet);
      let frame = await openFromLibrary(phet);
      step('open Calculus Grapher from the catalogue');
      await frame.getByText('Calculus Grapher', {exact: true}).first().click();
      await frame.locator('.swal2-confirm').click();
      await page.waitForFunction(hash => location.hash === hash, readRoute(phet, 'calculus-grapher_en.html'));
      await page.locator(ready).waitFor();
      frame = await readerFrame(page);
      await visibleContent(frame, {type: 'simulation'});
      assert.equal(await frame.evaluate(() => document.fullscreenEnabled), true);
      step('click Derivative Screen');
      const screen = frame.getByRole('button', {name: 'Derivative Screen', exact: true}).first();
      // PhET renders the button graphically and mirrors it in the accessible DOM.
      await screen.evaluate(button => button.click());
      await frame.waitForFunction(() => {
        const sim = window.phet.joist.sim;
        return sim.selectedScreenProperty.value === sim.simScreens[0];
      });
      await visibleContent(frame, {type: 'simulation'});
      step('return to the catalogue with Back');
      await page.goBack({waitUntil: 'commit'});
      await page.waitForFunction(hash => location.hash === hash, catalogue);
      await page.locator(ready).waitFor();
      const back = await readerFrame(page);
      await back.getByText('PhET Interactive Simulations', {exact: true}).first().waitFor();
      return {fullscreenEnabled: true, back: catalogue};
    });
  }
  if (ids.has(oer)) {
    await run('OER4Schools home, playlist, video playback and Back', async step => {
      let frame = await openFromLibrary(oer);
      step('open a playlist from home');
      await frame.locator('a[href^="#/playlist/"]:visible').first().click();
      await page.waitForFunction(() => new URLSearchParams(location.hash.split('?')[1]).get('at')?.startsWith('/playlist/'));
      await page.locator(ready).waitFor();
      frame = await readerFrame(page);
      const playlist = await frame.evaluate(() => location.hash);
      const playlistRoute = await page.evaluate(() => location.hash);
      assert.match(playlist, /^#\/playlist\//);
      step('open a video from the playlist');
      await frame.locator('a[href*="/watch/"]').first().click();
      await page.waitForFunction(() => new URLSearchParams(location.hash.split('?')[1]).get('at')?.startsWith('/watch/'));
      await page.locator(frameSelector).contentFrame().locator('video').first().waitFor();
      frame = await readerFrame(page);
      const video = frame.locator('video').first();
      step('play the video');
      await frame.waitForFunction(() => document.querySelector('video')?.readyState >= 2);
      const initial = await video.evaluate(async node => {
        await node.play();
        return node.currentTime;
      });
      await frame.waitForFunction(time => document.querySelector('video').currentTime > time + 0.25, initial);
      const seconds = await video.evaluate(node => node.currentTime);
      step('return to the playlist with Back');
      await page.goBack({waitUntil: 'commit'});
      await page.waitForFunction(hash => location.hash === hash, playlistRoute);
      await page.locator(ready).waitFor();
      frame = await readerFrame(page);
      await frame.waitForFunction(hash => location.hash === hash, playlist);
      return {playedSeconds: seconds - initial, back: playlist};
    });
  }
  return results;
}

async function runEngine(name, url, folder, plan, evidenceFolder) {
  const browser = await engineTypes[name].launch(name === 'chrome' ? {executablePath: process.env.OWL_CHROME || chromePath} : {});
  try {
    const context = await browser.newContext({viewport});
    const observed = {outsideRequests: [], browserCsp: [], browserErrors: [], frameEvents: []};
    // A request that gets this far already failed the offline check. Abort it
    // before sending anything to the network.
    await context.route(/^(?:https?):/i, route => {
      observed.outsideRequests.push({url: route.request().url(), method: route.request().method()});
      return route.abort('internetdisconnected');
    });
    await context.routeWebSocket(/^wss?:/i, socket => {
      observed.outsideRequests.push({url: socket.url(), method: 'WebSocket'});
      return socket.close();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    page.on('console', message => {
      const detail = {message: message.text().slice(0, 500), ...message.location()};
      if (/content security policy|violates.{0,60}directive|blocked the loading of a resource/i.test(detail.message)) {
        observed.browserCsp.push(detail);
      } else if (message.type() === 'error') observed.browserErrors.push(detail);
    });
    page.on('pageerror', error => observed.browserErrors.push({message: error.message, stack: error.stack}));
    page.on('crash', () => console.error(name, 'browser page crashed at', page.url()));
    for (const event of ['frameattached', 'framenavigated', 'framedetached']) {
      page.on(event, frame => observed.frameEvents.push({event, url: frame.url(), top: frame === page.mainFrame()}));
    }
    await page.addInitScript(installObservers);
    await page.goto(url + '#/all');
    const report = {engine: name, version: browser.version(), page: url, seed, viewport, archives: [], interactions: []};
    let grant = folder;
    for (const archive of plan) {
      const pages = [];
      const record = {id: archive.id, title: archive.title, summary: summarize(pages), pages};
      report.archives.push(record);
      for (const [index, target] of archive.pages.entries()) {
        const label = name + ' ' + archive.id + ' ' + target.path;
        // A headless sweep can open hundreds of large apps in a few minutes.
        // Release detached frames between batches while keeping the same reader
        // page and folder grant.
        if (index > 0 && index % 12 === 0) await withinBrowserBudget(page.requestGC(), label);
        let info = await withinBrowserBudget(sweepPage(page, url, archive, target, grant, observed), label);
        if (!grant && /Timeout \d+ms|Execution context was destroyed/.test(info.failure || '')) {
          console.error(name, archive.id, target.path, 'retrying after', info.failure);
          await withinBrowserBudget(page.requestGC(), label);
          const firstAttempt = info;
          info = await withinBrowserBudget(sweepPage(page, url, archive, target, null, observed), label);
          info.firstAttempt = firstAttempt;
        }
        grant = null;
        pages.push(info);
        if (!info.passed) console.error(name, archive.id, target.path, info.failure);
        if ((index + 1) % 25 === 0 || !info.passed) {
          record.summary = summarize(pages);
          if (evidenceFolder) await saveReport(evidenceFolder, report);
          if (info.passed) console.log(name, archive.id, (index + 1) + '/' + archive.pages.length);
        }
      }
      record.summary = summarize(pages);
      console.log(name, archive.id, JSON.stringify(record.summary));
      if (evidenceFolder) await saveReport(evidenceFolder, report);
    }
    const outsideBefore = observed.outsideRequests.length;
    report.interactions = await interactions(page, new Set(plan.map(archive => archive.id)));
    report.interactionOutsideRequests = observed.outsideRequests.slice(outsideBefore);
    for (const result of report.interactions) console.log(name, JSON.stringify(result));
    if (evidenceFolder) await saveReport(evidenceFolder, report);
    return report.archives.every(archive => archive.summary.failed === 0) &&
      report.interactions.every(result => result.passed) && !report.interactionOutsideRequests.length;
  } finally {
    await browser.close();
  }
}

function summarize(pages) {
  return {opened: pages.length, passed: pages.filter(entry => entry.passed).length,
    failed: pages.filter(entry => !entry.passed).length,
    archiveSide: pages.filter(entry => entry.archiveSide.length).length,
    outsideRequests: pages.reduce((count, page) => count + page.outsideRequests.length, 0)};
}

async function saveReport(folder, report) {
  await writeFile(join(folder, 'archive-pages-' + report.engine + '.json'), JSON.stringify(report, null, 2) + '\n');
}

async function main() {
  const [drive, page, zimFolder, engines, evidenceFolder] = process.argv.slice(2);
  if (!drive || !page || !zimFolder || !engines) throw Error('Usage: see the first line of this script.');
  const names = engines.split(',');
  assert.ok(names.every(name => Object.hasOwn(engineTypes, name)), 'Engines: chrome, chromium, firefox, webkit');
  if (evidenceFolder) await mkdir(evidenceFolder, {recursive: true});
  const folder = resolve(zimFolder);
  const videoLimit = process.env.OWL_VIDEO_SAMPLE ? Number(process.env.OWL_VIDEO_SAMPLE) : 0;
  assert.ok(!process.env.OWL_VIDEO_SAMPLE || Number.isInteger(videoLimit) && videoLimit >= 60,
    'OWL_VIDEO_SAMPLE must be an integer of at least 60');
  const plan = await pagePlan(resolve(drive), folder, videoLimit);
  const url = pathToFileURL(resolve(drive, page)).href;
  for (const name of names) {
    if (!await runEngine(name, url, folder, plan, evidenceFolder)) process.exitCode = 1;
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
