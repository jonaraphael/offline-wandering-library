/* Build a small drive and check its actual file:// reader in three engines.
 * Usage: NODE_PATH=... node scripts/check_zim_reader.cjs SITE [PREVIEW ZIM_FOLDER EVIDENCE]
 * SITE is the output of scripts/build_pages.py. PREVIEW is a scratch drive
 * assembled from the real drive. ZIM_FOLDER is the real, read-only LIBRARY/ZIM.
 */
const assert = require('node:assert/strict');
const {chromium, firefox, webkit} = require('playwright-core');
const {mkdir, mkdtemp, readFile, readdir, rm, writeFile} = require('node:fs/promises');
const {join, dirname} = require('node:path');
const {pathToFileURL} = require('node:url');
const {tmpdir} = require('node:os');
const {webcrypto, createHash} = require('node:crypto');
const {makeZim} = require('../tests/search/zim-fixture.cjs');

const [site, preview, zimFolder, evidence] = process.argv.slice(2);
const readName = 'Cardiopulmonary_resuscitation';
const cpr = 'a[href*="' + readName + '"].button';
const hash = value => createHash('sha256').update(value).digest('hex');
const url = (drive, route = '#/') => pathToFileURL(join(drive, 'START_HERE.html')).href + route;

async function fixture(output) {
  const {navigation} = JSON.parse(await readFile(join(site, 'catalog.json')));
  const {Directory} = await import('../tests/browser-drive-fixture.mjs');
  const {assembleLibrary} = await import('../web/offline.mjs');
  globalThis.crypto ||= webcrypto;
  const drive = new Directory();
  const layouts = new Map(), parts = {}, records = [];
  const complete = (id, title, format, files) => {
    const destination = Object.keys(files)[0];
    const values = Object.values(files);
    const asset = {id, title, format, destination, size_bytes: values.reduce((total, file) => total + file.length, 0),
      sha256: hash(Buffer.concat(values)), license: 'MIT'};
    layouts.set(id, Object.entries(files).map(([path, data]) => ({path: 'LIBRARY/' + path, bytes: data.length})));
    parts[id] = values.map(data => ({sha256: hash(data)}));
    records.push({id, asset_id: id, title, source_title: title, href: destination, location: 'Complete document',
      kind: 'document', shelves: [], aliases: []});
    return asset;
  };
  const archive = makeZim({compression: 5});
  const files = {
    'ZIM/medical.zimaa': archive.subarray(0, 700),
    'ZIM/medical.zimab': archive.subarray(700),
    'ZIM/scripted.zim': makeZim({scripted: true}),
    'CRITICAL/resuscitation.pdf': Buffer.from('guide'),
    'SOFTWARE/MACOS/kiwix.dmg': Buffer.from('installer'),
  };
  const completed = [
    complete('wikimed_en', 'WikiMed', 'zim', Object.fromEntries(Object.entries(files).slice(0, 2))),
    complete('scripted', 'Script archive', 'zim', {'ZIM/scripted.zim': files['ZIM/scripted.zim']}),
    complete('who_emergency_medical-algorithm', 'Reviewed CPR guide', 'pdf', {'CRITICAL/resuscitation.pdf': files['CRITICAL/resuscitation.pdf']}),
    complete('kiwix_fixture', 'Kiwix for Mac', 'dmg', {'SOFTWARE/MACOS/kiwix.dmg': files['SOFTWARE/MACOS/kiwix.dmg']}),
  ];
  records.push({...records[0], id: 'wikimed_en:section', kind: 'section', title: 'Fixture-specific section',
    archivePath: readName, archiveSection: 'Section target'});
  const {warnings} = await assembleLibrary(drive, {
    completed, layouts, parts, missing: [], navigation, searchBudget: 4_000_000, network: {retry: fn => fn()},
    search: {base: './', plan: {version: 1, model_parts: 0, sources: [], model: [], reserve: 0},
      records: records.filter(record => record.asset_id !== 'kiwix_fixture'), page: navigation.reader.redirect,
      runtime: navigation.reader.bootstrap},
  });
  assert.deepEqual(warnings, []);
  async function publish(dir, parent) {
    await mkdir(parent, {recursive: true});
    for await (const child of dir.values()) {
      const path = join(parent, child.name);
      if (child.kind === 'directory') await publish(child, path);
      else await writeFile(path, Buffer.from(await (await child.getFile()).arrayBuffer()));
    }
  }
  await publish(drive, output);
  for (const [relative, data] of Object.entries(files)) {
    const path = join(output, 'LIBRARY', relative);
    await mkdir(dirname(path), {recursive: true});
    await writeFile(path, data);
  }
}

async function context(browser, name, {width = 1280, theme = 'light'} = {}) {
  const context = await browser.newContext({colorScheme: theme, viewport: {width, height: width === 390 ? 844 : 900},
    isMobile: name !== 'firefox' && width === 390, hasTouch: width === 390});
  await context.route(/^https?:/i, route => route.abort('internetdisconnected'));
  const page = await context.newPage();
  const csp = [], errors = [], requests = [];
  page.setDefaultTimeout(20_000);
  page.on('console', message => {
    if (/content security policy|violates.{0,60}directive/i.test(message.text())) csp.push(message.text());
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (/^https?:/i.test(request.url())) requests.push(request.url()); });
  await page.addInitScript(() => {
    window.archiveEvents = [];
    window.policyEvents = [];
    document.addEventListener('owl:archive', event => archiveEvents.push(event.detail), true);
    document.addEventListener('securitypolicyviolation', event => policyEvents.push([event.violatedDirective, event.blockedURI]));
  });
  if (name === 'chromium') {
    await page.addInitScript(() => {
      window.pickerCalls = 0;
      window.pickerMode = 'valid';
      window.showDirectoryPicker = async ({mode}) => {
        if (mode !== 'read' || !navigator.userActivation.isActive) throw Error('Picker must run within a read-only click');
        pickerCalls++;
        if (pickerMode === 'cancel') throw new DOMException('Cancelled', 'AbortError');
        return pickerMode === 'wrong' ? (await navigator.storage.getDirectory()).getDirectoryHandle('wrong', {create: true})
          : window.testFolder;
      };
    });
  }
  return {context, page, csp, errors, requests};
}

async function seedChromium(page, drive, realZimFolder) {
  const index = (await readdir(join(drive, 'LIBRARY', 'INDEX'))).find(name => /^[a-f0-9]{12}$/.test(name));
  // Only the small fixture goes into OPFS. For the real drive, keep the
  // disk-backed File objects picked by Playwright and use OPFS for the markers.
  const children = realZimFolder ? [] : await readdir(join(drive, 'LIBRARY', 'ZIM'));
  const archives = await Promise.all(children.map(async name => [name, [...await readFile(join(drive, 'LIBRARY/ZIM', name))]]));
  await page.evaluate(async ({index, archives, real}) => {
    const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('KINGSTON', {create: true});
    await root.getFileHandle('START_HERE.html', {create: true});
    const library = await root.getDirectoryHandle('LIBRARY', {create: true});
    const current = await (await library.getDirectoryHandle('INDEX', {create: true})).getDirectoryHandle(index, {create: true});
    await current.getFileHandle('home.js', {create: true});
    if (real) {
      const input = document.createElement('input');
      input.id = 'test-source';
      input.type = 'file';
      input.webkitdirectory = true;
      input.hidden = true;
      document.body.append(input);
      window.testFolder = root;
      return;
    }
    const zim = await library.getDirectoryHandle('ZIM', {create: true});
    for (const [name, data] of archives) {
      const writer = await (await zim.getFileHandle(name, {create: true})).createWritable();
      await writer.write(new Uint8Array(data));
      await writer.close();
    }
    window.testFolder = root;
  }, {index, archives, real: Boolean(realZimFolder)});
  if (realZimFolder) {
    await page.locator('#test-source').setInputFiles(realZimFolder);
    await page.evaluate(() => {
      const input = document.querySelector('#test-source');
      const files = new Map([...input.files].map(file => [file.webkitRelativePath, file]));
      input.remove();
      const zim = path => ({
        getDirectoryHandle: async name => zim(path + '/' + name),
        async getFileHandle(name) {
          const file = files.get(path + '/' + name);
          if (!file) throw new DOMException('Missing', 'NotFoundError');
          return {getFile: async () => file};
        },
      });
      const opfs = window.testFolder;
      window.testFolder = {name: opfs.name, queryPermission: async () => 'granted',
        getFileHandle: name => opfs.getFileHandle(name),
        async getDirectoryHandle(name) {
          const dir = await opfs.getDirectoryHandle(name);
          return name === 'LIBRARY' ? {getDirectoryHandle: async child =>
            child === 'ZIM' ? zim('ZIM') : dir.getDirectoryHandle(child)} : dir;
        }};
    });
  }
}

async function choose(page, button, name, mode, folder) {
  if (name === 'chromium') {
    await page.evaluate(mode => { window.pickerMode = mode; }, mode);
    await button.click();
    return;
  }
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), button.click()]);
  if (mode === 'cancel') {
    // Playwright cannot press the native panel's Cancel button.
    await chooser.element().dispatchEvent('cancel');
  } else await chooser.setFiles(folder);
}

async function archiveEvent(page, prior = 0) {
  await page.waitForFunction(count => archiveEvents.length > count, prior);
  return page.evaluate(() => archiveEvents.at(-1));
}

async function query(page, value = 'cpr') {
  await page.locator('#query').fill(value);
  await page.locator('#query').press('Enter');
  await page.waitForFunction(() => document.querySelector('#search-results').dataset.searchScope === 'complete');
}

async function route(page, hash) {
  await page.evaluate(hash => { location.hash = hash; }, hash);
}

async function flow(browser, name, drive, {realZimFolder, wrong, shot, width, theme} = {}) {
  const state = await context(browser, name, {width, theme});
  const {page} = state;
  const check = {};
  const output = {engine: name + ' ' + browser.version(), check, articles: []};
  const folder = realZimFolder || join(drive, 'LIBRARY', 'ZIM');
  const changeCount = () => page.evaluate(() => archiveEvents.length);
  const result = page.locator(cpr).first();
  const retry = page.getByRole('button', {name: 'Choose KINGSTON', exact: true});
  const frame = page.frameLocator('#article-paper iframe');
  const snapshot = async name => { if (shot) await page.screenshot({path: shot + '-' + name + '.png', animations: 'disabled'}); };
  try {
    await page.goto(url(drive, '#/search'));
    await page.locator('#query').waitFor();
    if (name === 'chromium') await seedChromium(page, drive, realZimFolder);
    await query(page);
    await result.waitFor();
    if (!realZimFolder) assert.match(await page.locator('[data-reviewed]').first().innerText(), /Medical resuscitation algorithm/);
    await snapshot('search');
    await choose(page, result, name, 'cancel');
    await page.locator('dialog[data-reason=cancel]').waitFor();
    assert.equal(await retry.count(), 1);
    assert.match(await page.locator('dialog').innerText(), /KINGSTON/);
    await snapshot('cancel');
    await choose(page, retry, name, 'wrong', wrong);
    await page.locator('dialog[data-reason=wrong]').waitFor();
    assert.match(await page.locator('dialog').innerText(), /That folder is not this library. Choose KINGSTON./);
    await snapshot('wrong-folder');
    // Keep the picker pending just long enough to capture the instruction sheet.
    if (shot) {
      const [chooser] = await Promise.all([page.waitForEvent('filechooser'), retry.click()]);
      await page.locator('dialog[data-reason=picking]').waitFor();
      await snapshot('first-open');
      await chooser.setFiles(folder);
    } else await choose(page, retry, name, 'valid', folder);

    await page.locator('#article-paper[data-ready=true]').waitFor();
    const first = await archiveEvent(page);
    assert.equal(first.path, readName);
    assert.equal(first.images, first.shown);
    output.articles.push(first);
    check.firstOpen = check.wrongFolder = check.cancel = true;
    await snapshot('article');
    assert.equal(await frame.locator('script, iframe, form, base, [onload]').count(), 0);
    assert.equal(await page.locator('#article-paper iframe').getAttribute('sandbox'),
      name === 'webkit' ? 'allow-same-origin allow-scripts' : 'allow-same-origin');
    assert.match(await frame.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content'), /script-src 'none'/);
    if (!realZimFolder) {
      assert.equal(await frame.getByText('Outside link').getAttribute('href'), null);
      assert.match(await frame.locator('.illustration').evaluate(node => getComputedStyle(node).backgroundImage), /blob:/);
      assert.equal(await frame.locator('h1').evaluate(node => getComputedStyle(node).color), 'rgb(21, 80, 90)');
    }
    const oldRoute = await page.evaluate(() => location.hash);
    const anchor = realZimFolder ? '#cite_note-Atkinsetal-1' : '#target';
    await frame.locator('a[href=' + JSON.stringify(anchor) + ']').first().click();
    const focused = await frame.locator(':focus').first().getAttribute('id');
    assert.equal(focused, decodeURIComponent(anchor.slice(1)));
    assert.equal(await page.evaluate(() => location.hash), oldRoute);
    assert.equal(await frame.locator('html').evaluate(node => node.ownerDocument.defaultView.scrollY), 0);
    check.fragment = true;

    let next;
    if (realZimFolder) {
      next = frame.locator('a[title="Cardiac arrest"][href="#"]:visible').first();
    } else next = frame.getByRole('link', {name: 'Next article'});
    const prior = await changeCount();
    await next.click();
    const linked = await archiveEvent(page, prior);
    assert.equal(linked.path, realZimFolder ? 'Cardiac_arrest' : 'Second');
    check.internalLink = true;
    await page.goBack();
    await page.locator('#article-paper[data-ready=true]').waitFor();
    assert.equal(await page.evaluate(() => location.hash), oldRoute);
    await page.locator('[data-read-back]').click();
    await result.waitFor();
    check.back = true;
    const calls = name === 'chromium' ? await page.evaluate(() => pickerCalls) : 0;
    await result.click();
    await page.locator('#article-paper[data-ready=true]').waitFor();
    assert.equal(await page.locator('dialog').evaluate(node => node.open), false);
    if (name === 'chromium') assert.equal(await page.evaluate(() => pickerCalls), calls);
    check.secondOpen = true;
    await page.reload();
    if (name === 'chromium' && !realZimFolder) {
      await page.locator('#article-paper[data-ready=true]').waitFor();
      assert.equal(await page.evaluate(() => pickerCalls), 0);
    } else {
      if (name === 'chromium') await seedChromium(page, drive, realZimFolder);
      const reopen = page.locator('.article-start').getByRole('link', {name: 'Open'});
      await reopen.waitFor();
      assert.equal(await reopen.count(), 1);
      await choose(page, reopen, name, 'valid', folder);
      await page.locator('#article-paper[data-ready=true]').waitFor();
    }
    assert.equal(await page.evaluate(() => location.hash), oldRoute);
    check.reload = true;
    if (!realZimFolder) {
      await page.getByRole('button', {name: 'Save WikiMed'}).click();
      await page.getByRole('link', {name: 'Saved'}).click();
      assert.ok(await page.locator('.archive-row').getByRole('link', {name: 'Open'}).count());
      await page.getByRole('link', {name: 'Search', exact: true}).last().click();
      await query(page, 'Fixture-specific section');
      await page.locator('a[href*="section=Section+target"]').first().click();
      await page.locator('#article-paper[data-ready=true]').waitFor();
      assert.equal(await frame.locator(':focus').first().getAttribute('id'), 'target');
      check.sectionResult = check.saved = true;
    }
    await route(page, '#/all');
    await page.locator('.archive-row').first().waitFor();
    const ids = await page.locator('.archive-row > a[href^="#/read/"]').evaluateAll(links =>
      links.map(link => link.getAttribute('href')).filter(route => route.endsWith('/%40main')));
    assert.equal(ids.length, realZimFolder ? 9 : 2);
    for (const hash of ids) {
      await route(page, '#/all');
      const link = page.locator('.archive-row > a[href=' + JSON.stringify(hash) + ']');
      const prior = await changeCount();
      await link.click();
      const main = await archiveEvent(page, prior);
      output.articles.push(main);
      if (main.reason === 'scripts') {
        assert.match(await page.locator('dialog').innerText(), /Open it in the Kiwix app/);
        assert.equal(await page.locator('dialog .button').count(), 1);
        assert.match(await page.locator('dialog .button').getAttribute('href'), /^LIBRARY\/SOFTWARE\/MACOS\//);
        await snapshot('kiwix');
      } else {
        assert.ok(!main.reason, JSON.stringify(main));
        assert.equal(main.images, main.shown);
      }
    }
    await page.getByRole('link', {name: 'Help', exact: true}).last().click();
    await page.getByText('Books, guides and encyclopedias open right here.', {exact: true}).waitFor();
    await snapshot('help');
    const policies = await page.evaluate(() => policyEvents);
    assert.deepEqual([...state.csp, ...policies], []);
    assert.deepEqual(state.errors, []);
    assert.deepEqual(state.requests, []);
    check.csp = 0;
    check.networkRequests = 0;
    return output;
  } catch (error) {
    console.error(JSON.stringify({engine: output.engine, drive, check, csp: state.csp, errors: state.errors, articles: output.articles}));
    throw error;
  } finally {
    await state.context.close();
  }
}

async function main() {
  if (!site || Boolean(preview) !== Boolean(zimFolder)) throw Error('Usage: check_zim_reader.cjs SITE [PREVIEW ZIM_FOLDER EVIDENCE]');
  const scratch = await mkdtemp(join(tmpdir(), 'owl-file-reader-'));
  const drive = join(scratch, 'KINGSTON'), wrong = join(scratch, 'Wrong');
  const reports = [];
  try {
    await fixture(drive);
    await mkdir(wrong);
    await writeFile(join(wrong, 'unrelated.txt'), 'unrelated');
    for (const [name, runner] of Object.entries({chromium, firefox, webkit})) {
      if (process.env.OWL_ENGINE && name !== process.env.OWL_ENGINE) continue;
      const browser = await runner.launch(name === "chromium" ? {args: ["--allow-file-access-from-files"]} : {});
      try {
        const record = {fixture: await flow(browser, name, drive, {wrong})};
        if (preview) record.real = await flow(browser, name, preview, {realZimFolder: zimFolder, wrong});
        reports.push(record);
        console.log(JSON.stringify(record));
        if (evidence && name === 'webkit') {
          await mkdir(evidence, {recursive: true});
          for (const width of [1280, 390]) {
            for (const theme of ['light', 'dark']) {
              await flow(browser, name, preview || drive, {realZimFolder: zimFolder, wrong, width, theme,
                shot: join(evidence, theme + '-' + width)});
            }
          }
        }
      } finally {
        await browser.close();
      }
    }
    if (evidence) await writeFile(join(evidence, 'browser-results.json'), JSON.stringify(reports, null, 2) + '\n');
  } finally {
    await rm(scratch, {recursive: true, force: true});
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
