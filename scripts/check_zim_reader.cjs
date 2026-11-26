/* Build a small drive and check its actual file:// reader in three engines.
 * Usage: NODE_PATH=... node scripts/check_zim_reader.cjs SITE [PREVIEW ZIM_FOLDER EVIDENCE]
 * SITE is the output of scripts/build_pages.py. PREVIEW is a scratch drive
 * assembled from the real drive. ZIM_FOLDER is the real, read-only LIBRARY/ZIM.
 */
const assert = require('node:assert/strict');
const {chromium, firefox, webkit} = require('playwright-core');
const {mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile} = require('node:fs/promises');
const {join, dirname} = require('node:path');
const {pathToFileURL} = require('node:url');
const {tmpdir} = require('node:os');
const {webcrypto, createHash} = require('node:crypto');
const {makeZim, inspectMarkup} = require('../tests/search/zim-fixture.cjs');

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

async function context(browser, name, {width = 1280, theme = 'light', folderInput = name !== 'chromium'} = {}) {
  const context = await browser.newContext({colorScheme: theme, viewport: {width, height: width === 390 ? 844 : 900},
    isMobile: name !== 'firefox' && width === 390, hasTouch: width === 390});
  await context.route(/^https?:/i, route => route.abort('internetdisconnected'));
  const page = await context.newPage();
  const csp = [], errors = [], requests = [], app = {csp: 0, errors: 0, requests: 0};
  // Archive pages that run in the sandboxed zim-app.html frame may try the network or
  // throw; their own policy blocks the first, and neither is the reader's fault.
  const inApp = value => /zim-app\.html|^blob:/.test(value || '');
  page.setDefaultTimeout(20_000);
  page.on('console', message => {
    if (!/content security policy|violates.{0,60}directive|blocked the loading of a resource/i.test(message.text())) return;
    if (inApp(message.location().url) || /connect-src blob: data:/.test(message.text())) app.csp++;
    else csp.push(message.text());
  });
  page.on('pageerror', error => {
    if (inApp(error.stack)) app.errors++;
    else errors.push(error.message);
  });
  page.on('request', request => {
    if (!/^https?:/i.test(request.url())) return;
    if (inApp(request.frame().url())) app.requests++;
    else requests.push(request.url());
  });
  await page.addInitScript(() => {
    window.archiveEvents = [];
    window.policyEvents = [];
    window.accessEvents = [];
    document.addEventListener('owl:archive', event => archiveEvents.push(event.detail), true);
    document.addEventListener('securitypolicyviolation', event => policyEvents.push([event.violatedDirective, event.blockedURI]));
    document.addEventListener('DOMContentLoaded', () => {
      const sheet = document.querySelector('dialog.sheet');
      if (!sheet) return;
      new MutationObserver(() => {
        if (sheet.open) accessEvents.push({state: sheet.dataset.reason, text: sheet.innerText,
          keys: [...sheet.querySelectorAll('mark')].map(mark => mark.textContent),
          buttons: [...sheet.querySelectorAll('button')].map(button => button.textContent),
          instruction: sheet.querySelector('.picker-instruction')?.innerHTML,
          notes: [...sheet.querySelectorAll('.note')].map(note => note.innerHTML)});
      }).observe(sheet, {attributes: true, childList: true});
    });
  });
  if (name === 'chromium' && folderInput) await page.addInitScript(() => { delete window.showDirectoryPicker; });
  await page.addInitScript(() => {
    window.inputActivations = [];
    const click = HTMLInputElement.prototype.click;
    HTMLInputElement.prototype.click = function () {
      if (this.id === 'zim-folder') inputActivations.push(navigator.userActivation.isActive);
      return click.call(this);
    };
  });
  if (!folderInput) {
    await page.addInitScript(() => {
      window.pickerCalls = 0;
      window.pickerOptions = [];
      window.pickerMode = 'valid';
      window.permissionChecks = [];
      window.permissionRequests = 0;
      const prototype = FileSystemDirectoryHandle.prototype;
      prototype.queryPermission = ({mode}) => {
        permissionChecks.push(mode);
        const result = sessionStorage.getItem('test-permission') || 'granted';
        return result === 'pending' ? new Promise(() => {}) : Promise.resolve(result);
      };
      prototype.requestPermission = () => {
        permissionRequests++;
        throw Error('The reader must never request permission');
      };
      window.showDirectoryPicker = async ({mode, startIn}) => {
        const active = navigator.userActivation.isActive;
        pickerOptions.push({mode, active, startIn});
        if (mode !== 'read' || !active) throw Error('Picker must run within a read-only click');
        pickerCalls++;
        if (pickerMode === 'cancel') throw new DOMException('Cancelled', 'AbortError');
        if (pickerMode === 'pending') return new Promise(resolve => { window.finishPicker = () => resolve(window.testFolder); });
        if (pickerMode === 'slow-validation') return {
          name: testFolder.name,
          getFileHandle: name => new Promise((resolve, reject) => {
            window.finishValidation = () => testFolder.getFileHandle(name).then(resolve, reject);
          }),
          getDirectoryHandle: name => testFolder.getDirectoryHandle(name),
        };
        if (pickerMode === 'denied') return {name: 'KINGSTON', getFileHandle: async () => {
          throw new DOMException('Access denied', 'NotAllowedError');
        }};
        return pickerMode === 'wrong' ? (await navigator.storage.getDirectory()).getDirectoryHandle('wrong', {create: true})
          : window.testFolder;
      };
    });
  }
  return {context, page, csp, errors, requests, app};
}

async function seedChromium(page, drive, realZimFolder, selection = 'KINGSTON') {
  const index = (await readdir(join(drive, 'LIBRARY', 'INDEX'))).find(name => /^[a-f0-9]{12}$/.test(name));
  // Only the small fixture goes into OPFS. For the real drive, keep the
  // disk-backed File objects picked by Playwright and use OPFS for the markers.
  const children = realZimFolder ? [] : (await readdir(join(drive, 'LIBRARY', 'ZIM'))).filter(name => !name.startsWith('._'));
  const archives = await Promise.all(children.map(async name => [name, [...await readFile(join(drive, 'LIBRARY/ZIM', name))]]));
  await page.evaluate(async ({index, archives, real, selection}) => {
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
    window.testFolder = {KINGSTON: root, LIBRARY: library, ZIM: zim}[selection];
  }, {index, archives, real: Boolean(realZimFolder), selection});
  if (realZimFolder) {
    await page.locator('#test-source').setInputFiles(realZimFolder);
    await page.evaluate(() => {
      const input = document.querySelector('#test-source');
      const files = new Map([...input.files].filter(file => !file.name.startsWith('._'))
        .map(file => [file.webkitRelativePath, file]));
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

async function choose(page, button, folderInput, mode, folder) {
  if (!folderInput) {
    await page.evaluate(mode => { window.pickerMode = mode; }, mode);
    await button.click();
    return;
  }
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), button.click()]);
  assert.equal(await page.evaluate(() => inputActivations.at(-1)), true);
  if (mode === 'cancel') {
    // Playwright cannot press the native panel's Cancel button.
    await chooser.element().dispatchEvent('cancel');
  } else if (mode !== 'pending') await chooser.setFiles(folder);
  return chooser;
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

function checkPickerCopy(name, access, folderInput) {
  assert.ok(access.keys.includes('KINGSTON'));
  assert.match(access.text, /In the folder window, (open|click) KINGSTON/);
  if (!folderInput) {
    assert.deepEqual(access.keys, ['KINGSTON', 'Select']);
    assert.match(access.text, /This page only reads the drive\. Nothing is copied or sent\./);
  } else if (name === 'firefox') {
    assert.deepEqual(access.keys, ['KINGSTON', 'LIBRARY', 'ZIM', 'Open', 'Upload']);
    assert.match(access.text, /Firefox’s Confirm Upload window, click Upload\. Nothing leaves this computer\./);
  } else if (name === 'chromium') {
    assert.deepEqual(access.keys, ['KINGSTON', 'LIBRARY', 'ZIM', 'Upload', 'Upload']);
    assert.match(access.text, /If the browser asks to upload files, click Upload\. Nothing leaves this computer\./);
  } else {
    assert.deepEqual(access.keys, ['KINGSTON', 'LIBRARY', 'ZIM', 'Upload']);
    assert.match(access.text, /Nothing is copied or sent\./);
  }
}

async function checkPicking(page) {
  const sheet = page.locator('dialog[open][data-reason=picking]');
  await sheet.waitFor();
  assert.equal(await sheet.locator('button').count(), 0);
}

async function checkWrongFolder(page, name, folderInput) {
  const sheet = page.locator('dialog[data-reason=wrong]');
  await sheet.waitFor();
  assert.equal(await sheet.locator('h2').innerText(), 'Choose the library folder');
  assert.equal(await sheet.locator('p').first().innerText(), 'That folder is not this library.');
  assert.deepEqual(await sheet.getByRole('button').allTextContents(), ['Try again']);
  const [first, wrong] = await page.evaluate(() => [
    accessEvents.find(event => event.state === 'picking'), accessEvents.findLast(event => event.state === 'wrong'),
  ]);
  checkPickerCopy(name, wrong, folderInput);
  assert.equal(wrong.instruction, first.instruction);
  assert.deepEqual(wrong.notes, first.notes);
}

async function checkExternalLink(state, link) {
  await link.waitFor();
  const href = await link.getAttribute('href');
  assert.match(href, /^https?:/);
  assert.match(await link.getAttribute('aria-label'), /Leaves the library \(opens in a new tab\)/);
  // The navigation reaches the new tab without sending a request to the site.
  await state.context.route(href, route => route.fulfill({contentType: 'text/html', body: '<h1>Outside link check</h1>'}));
  const [tab] = await Promise.all([state.context.waitForEvent('page'), link.click()]);
  await tab.getByRole('heading', {name: 'Outside link check'}).waitFor();
  assert.equal(tab.url(), href);
  assert.equal(await tab.evaluate(() => window.opener === null), true);
  await tab.close();
}

async function flow(browser, name, drive, {realZimFolder, wrong, shot, width, theme} = {}) {
  const state = await context(browser, name, {width, theme});
  const {page} = state;
  const check = {};
  const output = {engine: name + ' ' + browser.version(), check, articles: [], mains: []};
  const folderInput = name !== 'chromium';
  const folder = realZimFolder || join(drive, 'LIBRARY', 'ZIM');
  const changeCount = () => page.evaluate(() => archiveEvents.length);
  const result = page.locator(cpr).first();
  const retry = page.locator('dialog').getByRole('button', {name: 'Try again', exact: true});
  const frame = page.frameLocator('#article-paper iframe');
  const snapshot = async name => { if (shot) await page.screenshot({path: shot + '-' + name + '.png', animations: 'disabled'}); };
  try {
    await page.goto(url(drive, '#/search'));
    await page.locator('#query').waitFor();
    if (realZimFolder) {
      await query(page, 'PhET simulation archive');
      const phet = page.locator('a.button[href*="phet_archive"]').first();
      await phet.waitFor();
      assert.doesNotMatch(await phet.locator('..').innerText(), /Kiwix/);
      await query(page, 'OER4Schools');
      const oer = page.locator('a.button[href*="oer4schools"]').first();
      await oer.waitFor();
      assert.doesNotMatch(await oer.locator('..').innerText(), /Kiwix/);
      if (shot) await oer.locator('..').scrollIntoViewIfNeeded();
      await snapshot('search-app-archives');
      await query(page, 'cpr');
      check.appArchivesListedLikeOthers = true;
    }
    if (name === 'chromium') await seedChromium(page, drive, realZimFolder);
    await query(page);
    await result.waitFor();
    if (!realZimFolder) assert.match(await page.locator('[data-reviewed]').first().innerText(), /Medical resuscitation algorithm/);
    await snapshot('search');
    const priorRoute = await page.evaluate(() => location.hash);
    const chooser = await choose(page, result, folderInput, folderInput ? 'pending' : 'cancel');
    if (chooser) {
      await checkPicking(page);
      await chooser.element().dispatchEvent('cancel');
    }
    await page.locator('dialog[open]').waitFor({state: 'hidden'});
    assert.equal(await page.evaluate(() => location.hash), priorRoute);
    await choose(page, result, folderInput, 'wrong', wrong);
    await checkWrongFolder(page, name, folderInput);
    await snapshot('wrong-folder');
    const nextChooser = await choose(page, retry, folderInput, 'pending');
    await checkPicking(page);
    await snapshot('first-open');
    if (nextChooser) await nextChooser.setFiles(folder);
    else await page.evaluate(() => finishPicker());

    await page.locator('#article-paper[data-ready=true]').waitFor();
    const first = await archiveEvent(page);
    assert.equal(first.path, readName);
    assert.equal(first.images, first.shown);
    output.articles.push(first);
    check.firstOpen = check.wrongFolder = check.cancel = check.pickerActivation = true;
    const captions = await page.evaluate(() => accessEvents.filter(event => event.state === 'picking'));
    assert.ok(captions.length >= 3);
    for (const caption of captions) {
      assert.deepEqual(caption.buttons, []);
      checkPickerCopy(name, caption, folderInput);
    }
    check.pickerCopy = true;
    assert.equal(await page.locator('#article-title').evaluate(node => document.activeElement === node), true);
    assert.match(await page.locator('#article-title').getAttribute('class'), /visually-hidden/);
    assert.deepEqual(await page.locator('.article-bar, #article-content').evaluateAll(nodes =>
      nodes.flatMap(node => [...node.querySelectorAll('a.back, #article-title, button.star, iframe')]
        .map(element => [element.tagName, element.tabIndex]))), [['A', 0], ['H1', -1], ['BUTTON', 0], ['IFRAME', 0]]);
    if (name !== 'webkit') {
      await page.keyboard.press('Shift+Tab');
      assert.equal(await page.locator('[data-read-back]').evaluate(node => document.activeElement === node), true);
      await page.locator('#article-title').focus();
      await page.keyboard.press('Tab');
      assert.match(await page.locator(':focus').getAttribute('aria-label'), /^Save /);
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#article-paper iframe').evaluate(node => document.activeElement === node), true);
      await page.locator('#article-title').focus();
    }
    check.titleFocus = true;
    await snapshot('article');
    assert.equal(await frame.locator('script, iframe, form, base, [onload]').count(), 0);
    assert.equal(await page.locator('#article-paper iframe').getAttribute('sandbox'),
      name === 'webkit' ? 'allow-same-origin allow-scripts' : 'allow-same-origin');
    assert.match(await frame.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content'), /script-src 'none'/);
    if (!realZimFolder) {
      const specimens = await inspectMarkup(page, await page.locator('#article-paper iframe').getAttribute('sandbox'));
      for (const [name, result] of Object.entries(specimens)) {
        assert.deepEqual(result, {active: [], discarded: 0, control: 'Clean control', link: '#'}, name);
      }
      check.sanitized = Object.keys(specimens).length;
      assert.match(await frame.locator('.illustration').evaluate(node => getComputedStyle(node).backgroundImage), /blob:/);
      assert.equal(await frame.locator('h1').evaluate(node => getComputedStyle(node).color), 'rgb(21, 80, 90)');
    }
    const oldRoute = await page.evaluate(() => location.hash);
    const external = realZimFolder ? frame.locator('a[href*="medlineplus.gov/ency"]').first() : frame.getByText('Outside link');
    if (realZimFolder) {
      for (const host of ['icd9cm.chrisendres.com', 'meshb.nlm.nih.gov', 'www.icd-code.de']) {
        assert.match(await frame.locator(`.infobox a[href*="${host}"]`).getAttribute('aria-label'), /Leaves the library/);
      }
    }
    await checkExternalLink(state, external);
    assert.equal(await page.evaluate(() => location.hash), oldRoute);
    check.externalTab = true;
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
    assert.equal(await page.locator('.tabs a[aria-current=page]').innerText(), 'Search');
    assert.match(await page.locator('[data-read-back]').innerText(), /Previous article/);
    check.internalLink = true;
    check.originatingTab = true;
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
      // A second Open must say why the browser needs it.
      assert.match(await page.locator('.article-start').innerText(), /The browser needs one click to read KINGSTON again\./);
      await choose(page, reopen, folderInput, 'valid', folder);
      await page.locator('#article-paper[data-ready=true]').waitFor();
    }
    assert.equal(await page.evaluate(() => location.hash), oldRoute);
    check.reload = true;
    await page.getByRole('button', {name: /Save WikiMed/}).click();
    await page.getByRole('link', {name: 'Saved'}).click();
    const savedRows = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    assert.equal(await savedRows.count(), 2);
    assert.equal(await page.locator('.archive-row > a').getByText('Open', {exact: true}).count(), 0);
    await snapshot('saved-recent');
    await savedRows.first().click();
    await page.locator('#article-paper[data-ready=true]').waitFor();
    await route(page, '#/');
    const recent = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    await recent.waitFor();
    await snapshot('home-recent');
    await recent.click();
    await page.locator('#article-paper[data-ready=true]').waitFor();
    check.saved = check.recent = true;
    if (!realZimFolder) {
      await page.getByRole('link', {name: 'Search', exact: true}).last().click();
      await query(page, 'Fixture-specific section');
      await page.locator('a[href*="section=Section+target"]').first().click();
      await page.locator('#article-paper[data-ready=true]').waitFor();
      assert.equal(await page.locator('#article-title').evaluate(node => document.activeElement === node), true);
      assert.ok(await page.evaluate(() => scrollY) > 1000);
      check.sectionResult = true;
    }
    await route(page, realZimFolder ? '#/c/reference' : '#/c/health');
    const categoryArchive = page.locator('.archive-row > a').first();
    await categoryArchive.waitFor();
    assert.ok(await categoryArchive.locator('b').innerText());
    await categoryArchive.scrollIntoViewIfNeeded();
    await snapshot('category');
    await categoryArchive.click();
    await page.locator('#article-paper[data-ready=true]').waitFor();
    check.category = true;
    await route(page, '#/all');
    await page.locator('.archive-row').first().waitFor();
    if (realZimFolder) {
      const phet = page.locator('.archive-row').filter({hasText: 'PhET simulation archive'});
      assert.match(await phet.innerText(), /Simulations/);
      assert.match(await page.locator('.archive-row').filter({hasText: 'OER4Schools'}).innerText(), /Teacher training/);
      assert.doesNotMatch(await page.locator('.list').first().innerText(), /Kiwix/);
      await phet.scrollIntoViewIfNeeded();
    }
    await snapshot('all');
    const ids = await page.locator('.archive-row > a[href^="#/read/"]').evaluateAll(links =>
      links.map(link => link.getAttribute('href')).filter(route => route.endsWith('/%40main')));
    assert.equal(ids.length, realZimFolder ? 9 : 2);
    const plainTitles = {appropedia_en: 'Appropedia', cd3wd_en: 'CD3WD appropriate-development library',
      lowtech_magazine: 'Low-tech Magazine', wikipedia_en_top: 'English Wikipedia',
      world_factbook_en: 'The World Factbook', wikimed_en: 'WikiMed'};
    for (const hash of ids) {
      await route(page, '#/all');
      const link = page.locator('.archive-row > a[href=' + JSON.stringify(hash) + ']');
      const archiveTitle = await link.locator('b').innerText();
      const prior = await changeCount();
      await link.click();
      const main = await archiveEvent(page, prior);
      output.mains.push(main);
      if (main.mode === 'app') {
        // A page drawn by scripts runs in the sandboxed frame, not a Kiwix hand-off.
        const appFrame = page.locator('#article-paper.app-view iframe');
        assert.equal(await appFrame.getAttribute('sandbox'), 'allow-scripts');
        assert.match(await appFrame.getAttribute('src'), /^LIBRARY\/INDEX\/[0-9a-f]{12}\/zim-app\.html(#|$)/);
        assert.equal(await page.locator('.article-problem').count(), 0);
        const inner = page.frames().find(child => /zim-app\.html/.test(child.url()));
        const expected = realZimFolder ? {phet_archive: /PhET Interactive Simulations/,
          oer4schools_en_all_2025_10: /OER4Schools/}[main.id] : /Script-built page marker/;
        assert.ok(expected, 'unexpected app archive ' + main.id);
        await inner.waitForFunction(pattern => new RegExp(pattern).test(document.body.innerText), expected.source);
        assert.equal(await inner.evaluate(() => self.origin), 'null');
        const height = await appFrame.evaluate(node => node.getBoundingClientRect().height);
        assert.ok(height >= 360, main.id + ' app height ' + height);
        main.frameHeight = height;
        main.firstText = (await inner.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').trim().slice(0, 80);
        if (!realZimFolder) {
          await inner.locator('#fetched', {hasText: 'Fetched from the archive'}).waitFor();
          await inner.waitForFunction(() => document.querySelector('#drawn')?.naturalWidth > 0);
          await inner.locator('#next').click();
          await page.waitForFunction(() => /\/Second(\?|$)/.test(location.hash));
          await page.locator('#article-paper[data-ready=true]').waitFor();
          assert.match(await frame.locator('body').innerText(), /Second-page marker/);
          check.appBridge = true;
        }
        await snapshot('app-' + main.id);
        check.inlineApp = true;
      } else {
        assert.ok(!main.reason, JSON.stringify(main));
        assert.equal(main.images, main.shown);
        const title = page.locator('#article-title');
        assert.equal(await title.innerText(), plainTitles[main.id] || archiveTitle);
        assert.equal(await title.evaluate(node => node.classList.contains('visually-hidden')), false);
        if (realZimFolder && main.id === 'wikimed_en') {
          assert.equal(await frame.locator('#firstHeading').isVisible(), false);
          assert.equal(await frame.locator('#contentSub .subpages').isVisible(), false);
        }
        const {height, first} = await page.locator('#article-paper iframe').evaluate(node => ({
          height: node.getBoundingClientRect().height,
          first: node.contentDocument.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 300),
        }));
        main.frameHeight = height;
        main.firstText = first.slice(0, 80);
        if (realZimFolder) {
          assert.ok(height > 200, main.id + ' frame height ' + height);
          assert.ok(!(/javascript/i.test(first) && /enabl/i.test(first)), main.id + ': ' + first);
        }
        if (['wikipedia_en_top', 'world_factbook_en', 'wikimed_en'].includes(main.id)) {
          await snapshot('main-' + main.id);
        }
        if (main.id === 'wikipedia_en_top' && !shot) {
          const tile = frame.locator('a[data-owl-link]').nth(18);
          await tile.scrollIntoViewIfNeeded();
          assert.ok(await page.evaluate(() => scrollY) > 200);
          await tile.click();
          await page.waitForFunction(mainRoute => location.hash !== mainRoute, hash);
          await page.locator('#article-paper[data-ready=true]').waitFor();
          await page.goBack();
          await page.locator('#article-paper[data-ready=true]').waitFor();
          assert.equal(await page.evaluate(() => location.hash), hash);
          await page.waitForFunction(() => history.state.owlScroll > 200 && Math.abs(scrollY - history.state.owlScroll) <= 1);
          const [restored, saved] = await page.evaluate(() => [scrollY, history.state.owlScroll]);
          assert.ok(saved > 200 && Math.abs(restored - saved) <= 1, `Restored ${restored}px of ${saved}px`);
          check.recoveredPageBack = true;
        }
      }
    }
    await page.getByRole('link', {name: 'Help', exact: true}).last().click();
    await page.getByText('Books, guides and encyclopedias open right here.', {exact: true}).waitFor();
    const phoneHelp = page.locator('.device-choice');
    assert.equal(await phoneHelp.count(), 1);
    assert.equal(await phoneHelp.locator('select').isVisible(), false);
    await snapshot('help');
    await phoneHelp.getByText('Using this drive on a phone', {exact: true}).click();
    await phoneHelp.locator('select').selectOption('android');
    assert.match(await phoneHelp.innerText(), /Tap Open file and choose this drive/);
    await snapshot('help-phone');
    check.phoneHelp = true;
    const policies = await page.evaluate(() => policyEvents);
    assert.deepEqual([...state.csp, ...policies], []);
    assert.deepEqual(state.errors, []);
    assert.deepEqual(state.requests, []);
    check.csp = 0;
    check.networkRequests = 0;
    output.sandboxedArchivePages = {...state.app};
    return output;
  } catch (error) {
    console.error(JSON.stringify({engine: output.engine, drive, check, csp: state.csp, errors: state.errors,
      articles: output.articles, mains: output.mains}));
    throw error;
  } finally {
    await state.context.close();
  }
}

async function folderVariants(browser, name, drive, wrong, evidence) {
  const variants = [];
  const modes = name === 'chromium' ? [false, true] : [true];
  const folders = {KINGSTON: drive, LIBRARY: join(drive, 'LIBRARY'), ZIM: join(drive, 'LIBRARY/ZIM')};
  for (const folderInput of modes) {
    const results = [];
    for (const [selection, folder] of Object.entries(folders)) {
      const state = await context(browser, name, {folderInput});
      const {page} = state;
      try {
        await page.goto(url(drive, '#/all'));
        if (!folderInput) await seedChromium(page, drive, undefined, selection);
        const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
        if (selection === 'KINGSTON') {
          await choose(page, link, folderInput, 'wrong', wrong);
          await checkWrongFolder(page, name, folderInput);
        }
        const open = selection === 'KINGSTON' ? page.getByRole('button', {name: 'Try again', exact: true}) : link;
        await choose(page, open, folderInput, 'valid', folder);
        await page.locator('#article-paper[data-ready=true]').waitFor();
        const copy = await page.evaluate(() => accessEvents.find(event => event.state === 'picking'));
        checkPickerCopy(name, copy, folderInput);
        results.push(selection);
      } finally {
        await state.context.close();
      }
    }
    variants.push({picker: folderInput ? 'folder input' : 'directory handle', roots: results});
    if (evidence && (name === 'chromium' || name === 'firefox')) {
      for (const width of [1280, 390]) {
        for (const theme of ['light', 'dark']) {
          const {page, context: ctx} = await context(browser, name, {folderInput, width, theme});
          try {
            await page.goto(url(drive, '#/all'));
            const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
            const chooser = await choose(page, link, folderInput, 'pending');
            await checkPicking(page);
            const label = name + (name === 'chromium' && folderInput ? '-input' : '');
            await page.screenshot({path: join(evidence, `${theme}-${width}-first-open-${label}.png`), animations: 'disabled'});
            if (name === 'chromium' && chooser) {
              await chooser.setFiles(wrong);
              await checkWrongFolder(page, name, folderInput);
              await page.screenshot({path: join(evidence, `${theme}-${width}-wrong-folder-${label}.png`), animations: 'disabled'});
            }
          } finally {
            await ctx.close();
          }
        }
      }
    }
  }
  return variants;
}

async function reconnect(browser, name, drive, {folderInput, stale, shot, width, theme} = {}) {
  const state = await context(browser, name, {width, theme, folderInput});
  const {page} = state;
  const folder = join(drive, 'LIBRARY/ZIM');
  const part = 'medical.zimaa';
  const path = join(folder, part);
  let restore;
  try {
    await page.goto(url(drive, '#/all'));
    if (!folderInput) await seedChromium(page, drive, undefined, 'ZIM');
    const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    await choose(page, link, folderInput, 'valid', folder);
    await page.locator('#article-paper[data-ready=true]').waitFor();
    if (folderInput) {
      await rename(path, path + '.away');
      restore = () => rename(path + '.away', path);
      await route(page, '#/read/wikimed_en/Second');
    } else {
      // An unplugged drive stops listing its folders; a connected one with a lost file still lists them.
      await page.evaluate(name => {
        const keys = FileSystemDirectoryHandle.prototype.keys;
        FileSystemDirectoryHandle.prototype.keys = function () {
          if (window.unplugged) throw new DOMException('The drive is gone', 'NotFoundError');
          return keys.call(this);
        };
        window.unplugged = true;
        return testFolder.removeEntry(name);
      }, part);
      const data = [...await readFile(path)];
      restore = () => page.evaluate(async ({part, data}) => {
        const writer = await (await testFolder.getFileHandle(part, {create: true})).createWritable();
        await writer.write(new Uint8Array(data));
        await writer.close();
        window.unplugged = false;
      }, {part, data});
      await route(page, '#/all');
      await link.click();
    }
    const sheet = page.locator('dialog[data-reason=disconnected]');
    await sheet.waitFor();
    assert.match(await sheet.innerText(), /KINGSTON is not connected\. Plug it in, then click Try again\./);
    assert.deepEqual(await sheet.getByRole('button').allTextContents(), ['Try again']);
    if (shot) await page.screenshot({path: shot + '-reconnect.png', animations: 'disabled'});
    const retry = sheet.getByRole('button', {name: 'Try again'});
    const probes = folderInput ? 0 : await page.evaluate(() => permissionChecks.length);
    if (stale) {
      await choose(page, retry, false, 'pending');
      await page.waitForFunction(() => typeof window.finishPicker === 'function');
      await checkPicking(page);
      assert.ok(await page.evaluate(() => pickerOptions.at(-1).startIn?.isSameEntry(testFolder)));
      await restore();
      await page.evaluate(() => finishPicker());
    } else {
      await restore();
      if (folderInput) await choose(page, retry, true, 'valid', folder);
      else await retry.click();
    }
    restore = undefined;
    await page.locator('#article-paper[data-ready=true]').waitFor();
    assert.equal(await sheet.isVisible(), false);
    if (!folderInput) {
      const status = await page.evaluate(() => ({pickerCalls, permissionChecks, permissionRequests}));
      assert.equal(status.pickerCalls, stale ? 2 : 1);
      assert.deepEqual(status.permissionChecks.slice(probes), ['read']);
      assert.equal(status.permissionRequests, 0);
    }
    if (stale) return 'reopened picker when the stored handle could not read the split part';
    return folderInput ? 'reselected folder after file read failed' : 'reused handle after split part disappeared';
  } finally {
    try { await restore?.(); } finally { await state.context.close(); }
  }
}

async function missingFile(browser, name, drive, {folderInput}) {
  const state = await context(browser, name, {folderInput});
  const {page} = state;
  const folder = join(drive, 'LIBRARY/ZIM');
  const path = join(folder, 'medical.zimab');
  await rename(path, path + '.away');
  try {
    await page.goto(url(drive, '#/all'));
    if (!folderInput) await seedChromium(page, drive, undefined, 'ZIM');
    const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    await choose(page, link, folderInput, 'valid', folder);
    const problem = page.locator('.article-problem[data-reason=file]');
    await problem.waitFor();
    assert.match(await problem.innerText(), /WikiMed did not copy completely to this drive\./);
    const repair = problem.getByRole('link', {name: 'Repair this drive'});
    assert.equal(await repair.getAttribute('href'), 'https://jonaraphael.com/offline-wandering-library/');
    assert.equal(await page.locator('dialog[open]').count(), 0);
    assert.doesNotMatch(await problem.innerText(), /Kiwix|not connected/);
    return folderInput ? 'missing part with folder input' : 'missing part with directory handle';
  } finally {
    await rename(path + '.away', path);
    await state.context.close();
  }
}

async function rememberedPermission(browser, drive) {
  const {page, context: ctx} = await context(browser, 'chromium');
  try {
    await page.goto(url(drive, '#/all'));
    await seedChromium(page, drive);
    const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    await choose(page, link, false, 'valid');
    await page.locator('#article-paper[data-ready=true]').waitFor();
    // Check that the read-only object really made it to IndexedDB before reload.
    await page.evaluate(async () => {
      const store = await OWLZimDrive.handleStore();
      const stored = await store(new URL(location.pathname, location.href).href);
      if (!await stored?.isSameEntry(testFolder)) throw Error('Missing remembered folder');
    });
    for (const permission of ['prompt', 'pending']) {
      await page.evaluate(value => sessionStorage.setItem('test-permission', value), permission);
      await page.reload();
      await seedChromium(page, drive);
      const reopen = page.locator('.article-start').getByRole('link', {name: 'Open'});
      await reopen.waitFor();
      assert.deepEqual(await page.evaluate(() => permissionChecks), ['read']);
      await choose(page, reopen, false, 'pending');
      await checkPicking(page);
      const access = await page.evaluate(async () => ({
        active: pickerOptions.at(-1).active,
        remembered: await pickerOptions.at(-1).startIn?.isSameEntry(testFolder),
        permissionChecks, permissionRequests,
      }));
      assert.deepEqual(access, {active: true, remembered: true, permissionChecks: ['read', 'read'], permissionRequests: 0});
      const caption = await page.evaluate(() => accessEvents.at(-1));
      assert.deepEqual(caption.keys, ['Select', 'KINGSTON']);
      assert.match(caption.text, /In the folder window, click Select to use KINGSTON\./);
      await page.evaluate(() => finishPicker());
      await page.locator('#article-paper[data-ready=true]').waitFor();
    }
    return ['prompt', 'unanswered permission query'];
  } finally {
    await ctx.close();
  }
}

async function stalledAccess(browser, name, drive, {stage = 'picker', width, theme, shot} = {}) {
  const folderInput = name !== 'chromium';
  const {page, context: ctx} = await context(browser, name, {folderInput, width, theme});
  const folder = join(drive, 'LIBRARY/ZIM');
  const ready = page.locator('#article-paper[data-ready=true]');
  const status = page.locator('#article-status');
  const dialog = page.locator('dialog[open]');
  const screenshot = async () => {
    if (shot) await page.screenshot({path: shot, animations: 'disabled'});
  };
  const checkSlowStatus = async () => {
    assert.equal(await status.innerText(), 'Opening…');
    await page.clock.fastForward(10_000);
    assert.equal(await status.innerText(), 'Still reading from KINGSTON…');
    assert.equal(await status.locator('mark').innerText(), 'KINGSTON');
    assert.equal(await dialog.count(), 0);
    assert.equal(await ready.count(), 0);
    await screenshot();
  };
  try {
    await page.clock.install();
    await page.goto(url(drive, '#/all'));
    if (!folderInput) await seedChromium(page, drive);
    const link = page.locator('.archive-row > a').filter({hasText: 'WikiMed'});
    if (stage === 'article' || stage === 'denied') {
      await page.evaluate(deny => {
        const read = Blob.prototype.arrayBuffer;
        Blob.prototype.arrayBuffer = function () {
          Blob.prototype.arrayBuffer = read;
          if (deny) return Promise.reject(new DOMException('Access denied', 'NotAllowedError'));
          return new Promise((resolve, reject) => {
            window.finishRead = () => read.call(this).then(resolve, reject);
          });
        };
      }, stage === 'denied');
      await choose(page, link, folderInput, 'valid', folder);
      if (stage === 'article') {
        await page.waitForFunction(() => typeof window.finishRead === 'function');
        await checkSlowStatus();
        await page.evaluate(() => finishRead());
      }
    } else if (stage === 'granted parts') {
      await choose(page, link, false, 'valid');
      await ready.waitFor();
      await route(page, '#/all');
      await link.waitFor();
      await page.evaluate(() => {
        const getFile = FileSystemFileHandle.prototype.getFile;
        FileSystemFileHandle.prototype.getFile = function () {
          FileSystemFileHandle.prototype.getFile = getFile;
          return new Promise((resolve, reject) => {
            window.finishRead = () => getFile.call(this).then(resolve, reject);
          });
        };
      });
      await link.click();
      await page.waitForFunction(() => typeof window.finishRead === 'function');
      await checkSlowStatus();
      await page.evaluate(() => finishRead());
      assert.equal(await page.evaluate(() => pickerCalls), 1);
    } else if (stage === 'images') {
      await page.evaluate(() => {
        const held = new Promise(resolve => { window.finishImages = resolve; });
        const descriptor = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentDocument');
        const instrumented = new WeakSet();
        window.heldDecodes = 0;
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentDocument', {...descriptor, get() {
          const doc = descriptor.get.call(this);
          const prototype = doc?.URL === 'about:srcdoc' && doc.defaultView.HTMLImageElement.prototype;
          if (prototype && !instrumented.has(prototype)) {
            instrumented.add(prototype);
            const decode = prototype.decode;
            prototype.decode = function () {
              window.heldDecodes++;
              return held.then(() => decode.call(this));
            };
          }
          return doc;
        }});
      });
      await choose(page, link, folderInput, 'valid', folder);
      await page.waitForFunction(() => heldDecodes > 0);
      await page.clock.fastForward(10_000);
      assert.equal(await ready.isVisible(), true);
      assert.equal(await page.frameLocator('#article-paper iframe').getByRole('link', {name: 'Next article'}).isVisible(), true);
      assert.equal(await status.count(), 0);
      assert.equal(await dialog.count(), 0);
      assert.equal(await page.evaluate(() => archiveEvents.length), 0);
      await page.evaluate(() => { finishImages(); });
      const result = await archiveEvent(page);
      assert.ok(result.images > 0);
      assert.equal(result.images, result.shown);
    } else if (stage === 'selection validation') {
      await choose(page, link, false, 'slow-validation');
      await page.waitForFunction(() => typeof window.finishValidation === 'function');
      await page.clock.fastForward(10_000);
      await checkPicking(page);
      await page.evaluate(() => finishValidation());
    } else if (stage === 'picker denial') await choose(page, link, false, 'denied');
    else {
      const chooser = await choose(page, link, folderInput, 'pending');
      await checkPicking(page);
      const caption = dialog.locator('.picker-instruction');
      const instruction = await caption.innerText();
      const hint = dialog.getByText('If you see “Allow this site to view and copy files?”, click Allow.');
      await page.evaluate(() => dispatchEvent(new Event('blur')));
      await page.clock.fastForward(5000);
      await checkPicking(page);
      assert.equal(await hint.count(), 0);
      await page.evaluate(() => dispatchEvent(new Event('focus')));
      await page.clock.fastForward(750);
      assert.equal(await hint.count(), 0);
      await page.clock.fastForward(10_000);
      await checkPicking(page);
      assert.equal(await caption.innerText(), instruction);
      assert.equal(await hint.count(), folderInput ? 0 : 1);
      if (!folderInput) {
        assert.equal(await hint.locator('mark').innerText(), 'Allow');
        assert.equal(await page.evaluate(() => permissionRequests), 0);
      }
      if (stage === 'dismissed picker') {
        const before = page.url();
        await page.keyboard.press('Escape');
        await dialog.waitFor({state: 'hidden'});
        await page.evaluate(() => finishPicker());
        assert.equal(page.url(), before);
        assert.equal(await ready.count(), 0);
        await choose(page, link, false, 'valid');
      } else {
        if (chooser) await chooser.setFiles(folder);
        else await page.evaluate(() => finishPicker());
      }
    }
    if (stage === 'denied' || stage === 'picker denial') {
      const sheet = page.locator('dialog[open][data-reason=stalled]');
      await sheet.waitFor();
      assert.equal(await sheet.getByRole('heading').innerText(), 'Drive access was denied');
      assert.equal(await sheet.getByRole('status').innerText(), 'The browser blocked this page from reading KINGSTON.' +
        (folderInput ? '' : ' Choose the ZIM folder to open it another way.'));
      assert.deepEqual(await sheet.getByRole('button').allTextContents(), [folderInput ? 'Try again' : 'Choose the ZIM folder']);
      await screenshot();
      await choose(page, sheet.getByRole('button'), true, 'valid', folder);
    }
    await ready.waitFor();
    assert.equal(await dialog.count(), 0);
    assert.equal(await status.count(), 0);
    return stage;
  } finally {
    await ctx.close();
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
    if (evidence) await mkdir(evidence, {recursive: true});
    await writeFile(join(wrong, 'unrelated.txt'), 'unrelated');
    for (const [name, runner] of Object.entries({chromium, firefox, webkit})) {
      if (process.env.OWL_ENGINE && name !== process.env.OWL_ENGINE) continue;
      const browser = await runner.launch(name === "chromium" ? {args: ["--allow-file-access-from-files"]} : {});
      try {
        const record = {fixture: await flow(browser, name, drive, {wrong})};
        record.folders = await folderVariants(browser, name, drive, wrong, evidence);
        record.reconnect = [await reconnect(browser, name, drive, {folderInput: true})];
        record.missing = [await missingFile(browser, name, drive, {folderInput: true})];
        if (name === 'chromium') record.missing.push(await missingFile(browser, name, drive, {folderInput: false}));
        const stages = ['picker', 'article', 'images', 'denied'];
        if (name === 'chromium') {
          record.reconnect.push(await reconnect(browser, name, drive, {folderInput: false}));
          record.reconnect.push(await reconnect(browser, name, drive, {folderInput: false, stale: true}));
          record.rememberedPermission = await rememberedPermission(browser, drive);
          stages.push('selection validation', 'granted parts', 'dismissed picker', 'picker denial');
        }
        record.slowAccess = [];
        for (const stage of stages) record.slowAccess.push(await stalledAccess(browser, name, drive, {stage}));
        if (preview) record.real = await flow(browser, name, preview, {realZimFolder: zimFolder, wrong});
        reports.push(record);
        console.log(JSON.stringify(record));
        if (evidence) {
          for (const width of [1280, 390]) {
            for (const theme of ['light', 'dark']) {
              const shot = join(evidence, `${name}-${width}-${theme}`);
              await stalledAccess(browser, name, drive, {stage: 'article', width, theme, shot: shot + '-still-reading.png'});
              await stalledAccess(browser, name, drive, {stage: 'denied', width, theme, shot: shot + '-access-denied.png'});
            }
          }
        }
        if (evidence && (preview || name === 'webkit')) {
          for (const width of [1280, 390]) {
            for (const theme of ['light', 'dark']) {
              const shot = join(evidence, `${name}-${width}-${theme}`);
              await flow(browser, name, preview || drive, {realZimFolder: zimFolder, wrong, width, theme, shot});
              await reconnect(browser, name, drive, {folderInput: name !== 'chromium', width, theme, shot});
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
