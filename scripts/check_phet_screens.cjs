#!/usr/bin/env node
/* Pinned, offline, explicit-screen PhET evidence. Sources and model state are read-only.
 * This helper shares input validation with check_phet.cjs, and never admits content.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const base = require('./check_phet.cjs');

function options(argv) {
  const out = {};
  for(let i=0;i<argv.length;i+=2) {
    const key=argv[i].replace(/^--/,'');
    if(!['manifest','root','output','browser','playwright','mode','screenshots'].includes(key)||!argv[i+1]) throw Error('Unknown option or missing value');
    out[key]=argv[i+1];
  }
  for(const key of ['manifest','root','output','playwright','browser']) if(!out[key])throw Error('Missing --'+key);
  out.mode ||= 'inspect';
  if(!['inventory','inspect','run'].includes(out.mode))throw Error('Invalid mode');
  return out;
}

// No setters or source execution. Read the exact screen objects initialized by the sim.
async function observe(page) {
  return page.evaluate(() => {
    const sim=phet.joist.sim;
    const screens=sim.screens || sim.simScreens || [];
    const label=s=>String(s?.nameProperty?.value ?? s?.name ?? s?.screenName ?? '').slice(0,160);
    const current=sim.selectedScreenProperty?.value || sim.currentScreenProperty?.value || sim.screenProperty?.value || screens[sim.screenIndexProperty?.value || 0];
    const home=!!(sim.showHomeScreenProperty?.value || sim.homeScreen && current===sim.homeScreen);
    const index=screens.indexOf(current);
    const root=home?sim.homeScreen?.view:(current?.view||current?._view);
    const nodes=[], seen=new Set();let scanned=0;
    function walk(n,p,depth) {
      if(!n||seen.has(n)||++scanned>10000||depth>22||n.visible===false)return;
      seen.add(n);
      const text=String(n.text ?? n.string ?? '').slice(0,300);
      if(text||n._inputListeners?.length||depth<2)try {
        const b=n.localToGlobalBounds(n.localBounds), bounds=[b.minX,b.minY,b.maxX,b.maxY];
        if(bounds.every(Number.isFinite)&&b.maxX>0&&b.maxY>0&&b.minX<innerWidth&&b.minY<innerHeight)nodes.push({path:p,text,bounds,listeners:n._inputListeners?.length||0});
      }catch{}
      (n.children||n._children||[]).forEach((v,i)=>walk(v,p+'.'+i,depth+1));
    }
    walk(root,'view',0);
    const model={}, objects=new Set();
    function values(o,p,depth) {
      if(!o||typeof o!=='object'||objects.has(o)||depth>5||Object.keys(model).length>8000)return;
      objects.add(o);
      for(const k of Object.keys(o).sort()) {
        if(/tandem|phetio|listener|emitter|validat|context|parents|renderer/i.test(k)||['_view','view','children','_children','screens','simScreens'].includes(k))continue;
        let v;try{v=o[k]}catch{continue}
        if(/Property$/.test(k)&&v&&['string','boolean','number'].includes(typeof v.value))model[p+k]=v.value;
        else if(Array.isArray(v)) {model[p+k+'.length']=v.length;if(v.length<=30)v.forEach((x,i)=>values(x,p+k+'.'+i+'.',depth+1));}
        else if(v&&typeof v==='object'&&!k.endsWith('Property'))values(v,p+k+'.',depth+1);
      }
    }
    if(!home){const m=current?.model||current?._model;values(m,'',0);for(const k of ['challengeProperty','equationProperty'])if(m?.[k]?.value&&typeof m[k].value==='object'){objects.clear();values(m[k].value,'active_'+k+'.',0);}}
    return {inventory:screens.slice(0,20).map((s,i)=>({index:i,name:label(s),home:s===sim.homeScreen})),inventory_count:screens.length,
      selected:{index,name:label(current),home},nodes:nodes.slice(0,1000),scanned,model,
      controls:Array.from(document.querySelectorAll('[role]')).filter(e=>e.getClientRects().length).slice(0,150).map(e=>({role:e.getAttribute('role'),label:e.getAttribute('aria-label')||e.textContent.slice(0,200)})),
      layout:{width:innerWidth,scroll_width:document.documentElement.scrollWidth,render_surfaces:Array.from(document.querySelectorAll('canvas,svg')).filter(e=>{const b=e.getBoundingClientRect();return b.width&&b.height&&b.right>0&&b.bottom>0&&b.left<innerWidth&&b.top<innerHeight}).length}};
  });
}

async function actions(page,steps,viewport) {
  base.validateActions(steps);let count=0;
  for(const a of steps) {
    if(a.viewport_width&&a.viewport_width!==viewport.width)continue;
    if(a.role) {
      const l=page.getByRole(a.role,a.name?{name:a.name,exact:true}:{}).first();
      if(a.hold_ms){await l.focus({timeout:5000});await page.keyboard.down(a.key);await page.waitForTimeout(a.hold_ms);await page.keyboard.up(a.key);}
      else if(a.key)await l.press(a.key,{timeout:5000});else await l.click({timeout:5000});
    } else if(a.scene) {
      async function point(scene,fraction=[.5,.5]) {return page.evaluate(({scene,fraction})=>{
        const s=phet.joist.sim, screens=s.screens||s.simScreens;
        const current=s.selectedScreenProperty?.value||s.currentScreenProperty?.value||s.screenProperty?.value||screens[s.screenIndexProperty?.value||0];
        const home=!!(s.showHomeScreenProperty?.value||s.homeScreen&&current===s.homeScreen);
        let node=home?s.homeScreen?.view:(current?.view||current?._view);
        for(const n of scene.split('.').slice(1)){if(!node||node.visible===false)throw Error('Hidden/absent ancestor');node=(node.children||node._children||[])[Number(n)];}
        if(!node||node.visible===false)throw Error('Hidden/absent control');
        const b=node.localToGlobalBounds(node.localBounds),p=[b.minX+(b.maxX-b.minX)*fraction[0],b.minY+(b.maxY-b.minY)*fraction[1]];
        if(!(b.maxX>b.minX&&b.maxY>b.minY)||!p.every(Number.isFinite)||p[0]<0||p[0]>innerWidth||p[1]<0||p[1]>innerHeight)throw Error('Control outside viewport');return p;
      },{scene,fraction});}
      const start=await point(a.scene,a.fraction);
      if(a.drag_to_scene){const end=await point(a.drag_to_scene);await page.mouse.move(...start);await page.mouse.down();await page.mouse.move(...end,{steps:10});await page.mouse.up();}
      else if(a.hold_ms){await page.mouse.move(...start);await page.mouse.down();await page.waitForTimeout(a.hold_ms);await page.mouse.up();}
      else await page.mouse.click(...start);
    } else if(a.click)await page.mouse.click(...a.click);
    else {await page.mouse.move(a.drag[0],a.drag[1]);await page.mouse.down();await page.mouse.move(a.drag[2],a.drag[3],{steps:10});await page.mouse.up();}
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));count++;
  }
  if(!count)throw Error('No applicable action');
}

function checkIdentity(actual,expected) {
  return !actual.home&&actual.index===expected.index&&actual.name===expected.name;
}
function write(file,data) {
  const bytes=JSON.stringify(data,null,2)+'\n';if(Buffer.byteLength(bytes)>32*1024*1024)throw Error('Evidence exceeds32MiB');
  fs.mkdirSync(path.dirname(file),{recursive:true});const tmp=file+'.part-'+process.pid;fs.writeFileSync(tmp,bytes);fs.renameSync(tmp,file);
}
async function main(argv=process.argv.slice(2)) {
  const o=options(argv), bytes=fs.readFileSync(o.manifest);
  if(bytes.length>4*1024*1024)throw Error('Manifest exceeds4MiB');
  const m=JSON.parse(bytes), root=fs.realpathSync(o.root), viewports=await base.validate(m,root);
  const assets=new Map(m.assets.map(a=>[a.id,a]));
  const cases=o.mode==='inventory'?m.assets.map(a=>({id:a.id,asset_id:a.id})):m.checks;
  if(!Array.isArray(cases)||!cases.length||cases.length>100)throw Error('Need1–100 explicit cases');
  const ids=new Set();for(const c of cases){if(!/^[a-z0-9_-]+$/.test(c.id)||ids.has(c.id)||!assets.has(c.asset_id))throw Error('Invalid/duplicate check');ids.add(c.id);if(c.entry)base.validateActions(c.entry);}
  const report={schema_version:1,mode:o.mode,runner_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),created_at:new Date().toISOString(),manifest_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),content_ready:false,physical_device_certification:'pending',downloads:0,offline:true,checks:[]};
  const browser=await require(o.playwright).chromium.launch({headless:true,executablePath:o.browser,chromiumSandbox:true});
  report.browser_version=browser.version();
  try{for(const c of cases)for(const viewport of viewports) {
    const a=assets.get(c.asset_id),context=await browser.newContext({viewport,offline:true,permissions:[]});
    const row={id:c.id,asset_id:a.id,sha256:a.sha256,viewport,expected_screen:c.screen||null,errors:[],blocked_remote_requests:[],success:false};
    await context.route(/^https?:/,async r=>{const u=r.request().url().split('?')[0];if(row.blocked_remote_requests.length<50&&!row.blocked_remote_requests.includes(u))row.blocked_remote_requests.push(u);await r.abort();});
    const page=await context.newPage();page.on('pageerror',e=>{if(row.errors.length<20)row.errors.push(e.message.slice(0,500));});
    try {
      const localURL=pathToFileURL(base.inside(root,a.destination));
      if(c.random_seed!==undefined){if(!Number.isFinite(c.random_seed)||c.random_seed<0||c.random_seed>1000000)throw Error('Invalid random seed');localURL.searchParams.set('randomSeed',String(c.random_seed));row.random_seed=c.random_seed;}
      await page.goto(localURL.href,{timeout:20000});
      await page.waitForFunction(()=>globalThis.phet?.joist?.sim?.frameCounter>=20,null,{timeout:20000});
      row.initial=await observe(page);
      if(c.entry)await actions(page,c.entry,viewport);
      const settle=c.settle_ms??200;if(!Number.isInteger(settle)||settle<0||settle>2000)throw Error('Invalid bounded settle delay');
      await page.waitForTimeout(settle);
      row.entered=await observe(page);
      if(o.mode!=='inventory'&&!checkIdentity(row.entered.selected,c.screen))throw Error('Selected screen differs from declared identity: '+JSON.stringify(row.entered.selected));
      if(o.mode==='run') {
        if(!Array.isArray(c.expected_changed_keys)||!c.expected_changed_keys.length)throw Error('Require meaningful model properties');
        row.expected_changed_keys=c.expected_changed_keys;row.interaction=c.interaction;row.reset_actions=c.reset;
        await actions(page,c.interaction,viewport);await page.waitForTimeout(settle);row.after=await observe(page);
        if(o.screenshots){fs.mkdirSync(o.screenshots,{recursive:true});await page.screenshot({path:path.join(o.screenshots,c.id+'-'+viewport.width+'-after.png')});}
        await actions(page,c.reset,viewport);await page.waitForTimeout(settle);row.reset=await observe(page);
        row.changed_keys=c.expected_changed_keys.filter(k=>JSON.stringify(row.entered.model[k])!==JSON.stringify(row.after.model[k]));
        row.restored_keys=row.changed_keys.filter(k=>JSON.stringify(row.entered.model[k])===JSON.stringify(row.reset.model[k]));
        row.success=c.expected_changed_keys.every(k=>Object.hasOwn(row.entered.model,k)&&row.changed_keys.includes(k)&&row.restored_keys.includes(k))&&checkIdentity(row.after.selected,c.screen)&&checkIdentity(row.reset.selected,c.screen)&&!row.errors.length&&row.entered.layout.scroll_width<=viewport.width+1&&row.entered.layout.render_surfaces>0;
        if(!row.success)row.failure='Meaningful interaction/reset, identity, browser, or layout check failed';
      }else row.status='inspected_awaiting_review';
      if(o.screenshots){fs.mkdirSync(o.screenshots,{recursive:true});await page.screenshot({path:path.join(o.screenshots,c.id+'-'+viewport.width+'.png')});}
    }catch(e){row.failure=e.message.slice(0,1200);}finally{await context.close();}
    report.checks.push(row);write(o.output,report);
  }}finally{await browser.close();}
  report.success=o.mode==='run'&&report.checks.every(c=>c.success);write(o.output,report);
  console.log(JSON.stringify({checks:report.checks.length,passed:report.checks.filter(c=>c.success).length,failures:report.checks.filter(c=>c.failure).map(c=>({id:c.id,width:c.viewport.width,failure:c.failure})).slice(0,10),content_ready:false,report:o.output}));
  if(o.mode==='run'&&!report.success)process.exitCode=1;
}
module.exports={options,checkIdentity};
if(require.main===module)main().catch(e=>{console.error(e.message);process.exitCode=1;});
