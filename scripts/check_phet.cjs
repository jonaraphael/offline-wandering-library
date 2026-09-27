#!/usr/bin/env node
/* Offline PhET desktop/browser QA. No downloads and no machine-specific paths.
 * Requires Node >=18, playwright or playwright-core, and a local Chromium build.
 * Run --help for a portable manifest example. Physical-device QA stays pending.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');

const HELP = `Usage: node scripts/check_phet.cjs --manifest checks.json --root LIBRARY --output evidence.json [--browser /path/to/chromium] [--playwright /path/to/playwright-core] [--screenshots DIR] [--validate-only | --inspect-only]

Install Node >=18 and playwright (with an already-installed Chromium browser),
or playwright-core plus --browser. This command never installs or downloads them.
Manifest: {"assets":[{"id":"phet_example","version":"1.0","destination":"REFERENCE/sim.html","sha256":"64 lower-case hex digits","entry":[{"role":"button","name":"Intro Screen","key":"Enter"}],"interaction":[{"role":"slider","key":"ArrowRight"}],"reset":[{"role":"button","name":"Reset All","key":"Enter"}],"expected_changed_keys":["exampleProperty"]}],"viewports":[{"width":1280,"height":900},{"width":390,"height":844}]}
Entry/interaction/reset are optional; accessible first-screen, slider/checkbox,
and Reset All controls are the defaults. Canvas actions may use {"click":[x,y]}
or {"drag":[x1,y1,x2,y2]}, with an optional viewport_width to limit applicability.
Reviewed canvas controls may instead use {"scene":"view.1.2"}, a child-index
path in the pinned simulation's scene graph. Optional fraction:[0.5,0.5],
drag_to_scene:"view.3", or hold_ms:300 select a point, drag target, or short hold.
These only resolve coordinates; interactions use ordinary mouse/keyboard input.
Require meaningful expected_changed_keys to certify interaction and reset.
Unconfigured or unsuccessful controls fail visibly. Reports include only actual
browser checks; success never certifies physical phones/tablets.
--validate-only checks manifest and pinned files without claiming browser QA.
--inspect-only performs configured entry actions, then reads bounded scene
geometry for review; it never runs interaction/reset or certifies a pass.
`;

function argumentsFor(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i++) {
    const name = argv[i];
    if (['--help', '--validate-only', '--inspect-only'].includes(name)) result[name.slice(2)] = true;
    else if (['--manifest', '--root', '--output', '--browser', '--playwright', '--screenshots'].includes(name) && argv[i + 1] && !argv[i + 1].startsWith('--')) result[name.slice(2)] = argv[++i];
    else throw Error(`Unknown option or missing value: ${name}`);
  }
  return result;
}

async function sha256(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

function inside(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || relative.includes('\\') || relative.split('/').some(p => !p || p === '..' || p === '.')) throw Error('Unsafe source destination');
  const file = path.join(root, relative);
  let check = root;
  for (const part of relative.split('/')) {
    check = path.join(check, part);
    if (fs.lstatSync(check).isSymbolicLink()) throw Error(`Symbolic link rejected: ${relative}`);
  }
  if (!fs.statSync(file).isFile()) throw Error(`Source is not a regular file: ${relative}`);
  return file;
}

function validateActions(actions) {
  if (!Array.isArray(actions) || actions.length > 30) throw Error('Actions must be a bounded list');
  for (const action of actions) {
    if (!action || typeof action !== 'object' || Array.isArray(action)) throw Error('Action must be an object');
    if (['role','click','drag','scene'].filter(key => action[key] !== undefined).length !== 1) throw Error('Action must have exactly one input modality');
    if (action.role && (!['button', 'slider', 'checkbox', 'radio', 'combobox'].includes(action.role) || (action.name !== undefined && typeof action.name !== 'string'))) throw Error('Invalid accessible action');
    if (action.key && !['Enter', 'Space', 'ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(action.key)) throw Error('Unsupported control key');
    if (!action.role && !action.click && !action.drag && !action.scene) throw Error('Action needs role, click, drag or a reviewed scene path');
    for (const key of ['scene','drag_to_scene']) if (action[key] !== undefined && (typeof action[key] !== 'string' || !/^view(?:\.\d+){0,20}$/.test(action[key]))) throw Error('Invalid reviewed scene path');
    if ((action.drag_to_scene !== undefined || action.fraction !== undefined) && !action.scene) throw Error('Scene options require a scene action');
    if (action.key !== undefined && !action.role) throw Error('Keys require an accessible control');
    if (action.hold_ms !== undefined && ((!action.scene && !action.role) || action.drag_to_scene || (action.role && !action.key))) throw Error('Hold requires a scene or accessible key without dragging');
    if (action.viewport_width !== undefined && (!Number.isInteger(action.viewport_width) || action.viewport_width < 200 || action.viewport_width > 4096)) throw Error('Invalid viewport width');
    if (action.fraction !== undefined && (!Array.isArray(action.fraction) || action.fraction.length !== 2 || action.fraction.some(n => !Number.isFinite(n) || n < 0 || n > 1))) throw Error('Invalid scene fraction');
    if (action.hold_ms !== undefined && (!Number.isInteger(action.hold_ms) || action.hold_ms < 1 || action.hold_ms > 2000)) throw Error('Hold must be 1–2000 milliseconds');
    for (const [key, size] of [['click', 2], ['drag', 4]]) if (action[key] && (!Array.isArray(action[key]) || action[key].length !== size || action[key].some(v => !Number.isFinite(v) || v < 0))) throw Error(`Invalid ${key} coordinates`);
  }
}

async function validate(manifest, root) {
  if (!Array.isArray(manifest.assets) || !manifest.assets.length || manifest.assets.length > 1000) throw Error('Manifest requires 1–1000 assets');
  const ids = new Set();
  for (const asset of manifest.assets) {
    if (!/^[a-z0-9_-]+$/.test(asset.id) || ids.has(asset.id) || !/^[a-f0-9]{64}$/.test(asset.sha256)) throw Error('Unique safe asset IDs and whole-file SHA-256 pins are required');
    ids.add(asset.id);
    for (const key of ['entry', 'interaction', 'reset']) if (asset[key]) validateActions(asset[key]);
    if (asset.expected_changed_keys !== undefined && (!Array.isArray(asset.expected_changed_keys) || !asset.expected_changed_keys.length || asset.expected_changed_keys.some(key => typeof key !== 'string' || !key.trim()))) throw Error('expected_changed_keys must be nonempty strings');
    const file = inside(root, asset.destination);
    if (await sha256(file) !== asset.sha256) throw Error(`Source checksum changed: ${asset.id}`);
  }
  const viewports = manifest.viewports || [{ width: 1280, height: 900 }, { width: 390, height: 844 }];
  if (!Array.isArray(viewports) || !viewports.length || viewports.length > 8 || viewports.some(v => !Number.isInteger(v.width) || !Number.isInteger(v.height) || v.width < 200 || v.height < 200 || v.width > 4096 || v.height > 4096)) throw Error('Choose 1–8 bounded viewports');
  return viewports;
}

async function state(page) {
  return page.evaluate(() => {
    const sim = globalThis.phet.joist.sim;
    const screen = sim.selectedScreenProperty?.value || sim.currentScreenProperty?.value || sim.screenProperty?.value || (sim.screens || sim.simScreens)[sim.screenIndexProperty?.value || 0];
    const output = {}, seen = new Set();
    function walk(object, prefix, depth) {
      if (!object || typeof object !== 'object' || seen.has(object) || depth > 4 || Object.keys(output).length > 5000) return;
      seen.add(object);
      for (const key of Object.keys(object).sort()) {
        if (/tandem|phetio|listener|emitter|validat|context|parents|renderer/i.test(key)) continue;
        let value;
        try { value = object[key]; } catch { continue; }
        const name = prefix + key;
        if (/Property$/.test(key) && value && ['string', 'boolean', 'number'].includes(typeof value.value)) output[name] = value.value;
        else if (Array.isArray(value)) {
          output[name + '.length'] = value.length;
          if (value.length <= 30) value.forEach((item, index) => walk(item, name + '.' + index + '.', depth + 1));
        } else if (value && typeof value === 'object' && !key.endsWith('Property')) walk(value, name + '.', depth + 1);
      }
    }
    walk(screen.model || screen._model, '', 0);
    return output;
  });
}

async function inspectScene(page) {
  return page.evaluate(() => {
    const sim = phet.joist.sim;
    const screen = sim.selectedScreenProperty?.value || sim.currentScreenProperty?.value || sim.screenProperty?.value || (sim.screens || sim.simScreens)[sim.screenIndexProperty?.value || 0];
    const home = !!(sim.showHomeScreenProperty?.value || (sim.selectedScreenProperty?.value || sim.screenProperty?.value) === sim.homeScreen && sim.homeScreen);
    const root = home ? sim.homeScreen?.view : (screen?.view || screen?._view);
    const nodes = [], seen = new Set(); let scanned = 0;
    function walk(node, path, depth) {
      if (!node || seen.has(node) || ++scanned > 5000 || depth > 20) return;
      seen.add(node);
      if (node.visible === false) return;
      const text = typeof node.text === 'string' ? node.text : typeof node.string === 'string' ? node.string : '';
      if (text || node._inputListeners?.length || depth <= 2) {
        try {
          const b = node.localToGlobalBounds(node.localBounds);
          const bounds = [b.minX,b.minY,b.maxX,b.maxY];
          if (bounds.every(Number.isFinite) && b.maxX > 0 && b.maxY > 0 && b.minX < innerWidth && b.minY < innerHeight)
            nodes.push({path, text:text.slice(0,160), bounds, listeners:node._inputListeners?.length || 0});
        } catch {}
      }
      (node.children || node._children || []).forEach((child,i) => walk(child, path + '.' + i, depth + 1));
    }
    walk(root, 'view', 0);
    return {home, root_found:!!root, scanned, nodes:nodes.slice(0,300)};
  });
}

async function actions(page, steps, viewport) {
  let count = 0;
  for (const action of steps) {
    if (action.viewport_width && action.viewport_width !== viewport.width) continue;
    if (action.role) {
      const options = action.name ? { name: action.name, exact: true } : {};
      const control = page.getByRole(action.role, options).first();
      if (action.hold_ms) {
        if (!action.key) throw Error('Holding an accessible control requires a key');
        await control.focus({timeout:5000});
        await page.keyboard.down(action.key);
        await page.waitForTimeout(action.hold_ms);
        await page.keyboard.up(action.key);
      }
      else if (action.key) await control.press(action.key, { timeout: 5000 });
      else await control.click({ timeout: 5000 });
    } else if (action.scene) {
      const point = async (scene, fraction = [0.5,0.5]) => page.evaluate(({scene,fraction}) => {
        const s = phet.joist.sim;
        const screen = s.selectedScreenProperty?.value || s.currentScreenProperty?.value || s.screenProperty?.value || (s.screens || s.simScreens)[s.screenIndexProperty?.value || 0];
        const home = !!(s.showHomeScreenProperty?.value || (s.selectedScreenProperty?.value || s.screenProperty?.value) === s.homeScreen && s.homeScreen);
        let node = home ? s.homeScreen?.view : (screen?.view || screen?._view);
        for (const index of scene.split('.').slice(1)) {
          if (!node || node.visible === false) throw Error('Reviewed scene ancestor is absent/hidden');
          node = (node.children || node._children || [])[Number(index)];
        }
        if (!node || node.visible === false) throw Error('Reviewed scene control is absent/hidden');
        const b = node.localToGlobalBounds(node.localBounds);
        if (!(b.maxX > b.minX && b.maxY > b.minY)) throw Error('Reviewed scene control has empty bounds');
        const p = [b.minX+(b.maxX-b.minX)*fraction[0], b.minY+(b.maxY-b.minY)*fraction[1]];
        if (!p.every(Number.isFinite) || p[0] < 0 || p[0] > innerWidth || p[1] < 0 || p[1] > innerHeight) throw Error('Reviewed scene control is outside viewport');
        return p;
      }, {scene,fraction});
      const start = await point(action.scene,action.fraction);
      if (action.drag_to_scene) {
        const end = await point(action.drag_to_scene);
        await page.mouse.move(...start); await page.mouse.down();
        await page.mouse.move(...end,{steps:10}); await page.mouse.up();
      } else if (action.hold_ms) {
        await page.mouse.move(...start); await page.mouse.down();
        await page.waitForTimeout(action.hold_ms); await page.mouse.up();
      } else await page.mouse.click(...start);
    } else if (action.click) {
      await page.mouse.click(...action.click);
    } else {
      const [x1, y1, x2, y2] = action.drag;
      await page.mouse.move(x1, y1); await page.mouse.down();
      await page.mouse.move(x2, y2, { steps: 8 }); await page.mouse.up();
    }
    count++;
    // Let input listeners and model notifications settle, without changing state directly.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  if (!count) throw Error('No applicable action configured for this viewport');
}

function writeReport(file, report) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = file + `.part-${process.pid}`;
  fs.writeFileSync(temporary, JSON.stringify(report, null, 2) + '\n');
  fs.renameSync(temporary, file);
}

async function main(argv = process.argv.slice(2)) {
  const options = argumentsFor(argv);
  if (options['validate-only'] && options['inspect-only']) throw Error('Choose only one validation mode');
  if (options.help) { process.stdout.write(HELP); return; }
  for (const key of ['manifest', 'root', 'output']) if (!options[key]) throw Error(`--${key} is required; use --help`);
  const root = fs.realpathSync(options.root);
  if (fs.statSync(options.manifest).size > 4 * 1024 * 1024) throw Error('Manifest exceeds 4 MiB');
  const manifestBytes = fs.readFileSync(options.manifest);
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const viewports = await validate(manifest, root);
  const report = { schema_version: 1, manifest_sha256: crypto.createHash('sha256').update(manifestBytes).digest('hex'), offline: true, downloads: false, physical_device_certification: 'pending', scope: options['validate-only'] ? 'source-integrity-only' : 'local Chromium browser', checks: [] };
  if (options['validate-only']) {
    report.sources_verified = manifest.assets.length;
    report.browser_qa = 'pending';
    writeReport(options.output, report);
    process.stdout.write(JSON.stringify({ sources_verified: manifest.assets.length, browser_qa: 'pending', report: options.output }) + '\n');
    return;
  }
  let playwright;
  try { playwright = require(options.playwright || 'playwright'); }
  catch {
    try { if (options.playwright) throw Error(); playwright = require('playwright-core'); }
    catch { throw Error('Missing Playwright. Supply --playwright /path/to/playwright-core and --browser /path/to/already-installed/chromium; no dependencies were downloaded.'); }
  }
  const browser = await playwright.chromium.launch({ headless: true, executablePath: options.browser, chromiumSandbox: true });
  report.browser_version = browser.version();
  try {
    for (const asset of manifest.assets) for (const viewport of viewports) {
      const context = await browser.newContext({ viewport, permissions: [], offline: true });
      const check = { id: asset.id, sha256: asset.sha256, version: asset.version, viewport, errors: [], blocked_remote_requests: [] };
      await context.route(/^https?:/, async route => {
        const url = route.request().url().split('?')[0];
        if (check.blocked_remote_requests.length < 50 && !check.blocked_remote_requests.includes(url)) check.blocked_remote_requests.push(url);
        await route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', error => { if (check.errors.length < 20) check.errors.push(error.message.slice(0, 500)); });
      try {
        await page.goto(pathToFileURL(inside(root, asset.destination)).href, { timeout: 20000 });
        await page.waitForFunction(() => globalThis.phet?.joist?.sim?.frameCounter >= 20, null, { timeout: 20000 });
        if (asset.entry) await actions(page, asset.entry, viewport);
        else if (!options['inspect-only']) {
          const home = await page.evaluate(() => { const s = phet.joist.sim; return !!(s.showHomeScreenProperty?.value || (s.selectedScreenProperty?.value || s.screenProperty?.value) === s.homeScreen && s.homeScreen); });
          if (home) {
            const first = page.getByRole('button', { name: / Screen$/ }).first();
            if (!await first.count()) throw Error('Home screen needs a reviewed entry action');
            await first.press('Enter');
          }
        }
        if (options['inspect-only']) {
          check.inspection = await inspectScene(page);
          check.success = false;
          check.failure = 'Inspection only; interaction and reset were not certified';
          if (options.screenshots) {
            fs.mkdirSync(options.screenshots,{recursive:true});
            await page.screenshot({path:path.join(options.screenshots,`${asset.id}-${viewport.width}-inspect.png`)});
          }
        } else {
        check.layout = await page.evaluate(() => ({ viewport_width: innerWidth, scroll_width: document.documentElement.scrollWidth,
          visible_rendering_surfaces: Array.from(document.querySelectorAll('canvas,svg')).filter(element => { const rect = element.getBoundingClientRect(); return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight; }).length }));
        check.before = await state(page);
        let interaction = asset.interaction;
        if (!interaction) {
          if (await page.getByRole('slider').count()) interaction = [{ role: 'slider', key: 'ArrowRight' }];
          else if (await page.getByRole('checkbox').count()) interaction = [{ role: 'checkbox', key: 'Space' }];
          else throw Error('Simulation needs a reviewed interaction action');
        }
        check.interaction = interaction;
        await actions(page, interaction, viewport);
        check.after = await state(page);
        check.changed_keys = Object.keys(check.after).filter(key => JSON.stringify(check.before[key]) !== JSON.stringify(check.after[key]));
        await actions(page, asset.reset || [{ role: 'button', name: 'Reset All', key: 'Enter' }], viewport);
        check.reset = await state(page);
        check.restored_keys = check.changed_keys.filter(key => JSON.stringify(check.reset[key]) === JSON.stringify(check.before[key]));
        const expected = asset.expected_changed_keys || [];
        check.success = expected.length > 0 && expected.every(key => check.changed_keys.includes(key) && check.restored_keys.includes(key)) && check.errors.length === 0 && check.layout.scroll_width <= viewport.width + 1 && check.layout.visible_rendering_surfaces > 0;
        if (!check.success) check.failure = 'Interaction/reset, layout, or browser error checks failed; inspect evidence';
        if (options.screenshots) {
          fs.mkdirSync(options.screenshots, { recursive: true });
          await page.screenshot({ path: path.join(options.screenshots, `${asset.id}-${viewport.width}-reset.png`) });
        }
        }
      } catch (error) { check.success = false; check.failure = error.message.slice(0, 1000); }
      finally { await context.close(); }
      report.checks.push(check);
      writeReport(options.output, report);
    }
  } finally { await browser.close(); }
  report.success = report.checks.every(check => check.success);
  writeReport(options.output, report);
  process.stdout.write(JSON.stringify({ checks: report.checks.length, failed: report.checks.filter(check => !check.success).map(check => ({ id: check.id, width: check.viewport.width, failure: check.failure.slice(0, 110) })).slice(0, 8), physical_device_certification: 'pending', report: options.output }) + '\n');
  if (!report.success) process.exitCode = 1;
}

module.exports = { argumentsFor, inside, validate, validateActions, main };
if (require.main === module) main().catch(error => { console.error(error.message.slice(0, 2000)); process.exitCode = 1; });
