/* Offline layout/link QA for a pinned generated manual fragment. No downloads. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {brokenAnchors,hasReadableContent,settleImages}=require('./manual_link_checks.cjs');

async function main() {
  const options = {};
  for (let i=2; i<process.argv.length; i+=2) {
    const key=process.argv[i];
    if (!['--fragment','--root','--output','--browser','--playwright','--screenshots','--package-fragment'].includes(key) || !process.argv[i+1]) throw Error('Expected --fragment, --root, --output and optional --browser, --playwright, --screenshots');
    options[key.slice(2)]=process.argv[i+1];
  }
  for (const key of ['fragment','root','output']) if (!options[key]) throw Error(`Missing --${key}`);
  const fragment=JSON.parse(fs.readFileSync(options.fragment,'utf8'));
  const root=path.resolve(options.root);
  const complete=options['package-fragment']?JSON.parse(fs.readFileSync(options['package-fragment'],'utf8')):fragment;
  const byDestination=new Map(complete.assets.map(a=>[path.resolve(root,a.destination),a]));
  const selected=fragment.assets.filter(a=>a.format==='html' && (a.generation || a.supporting_file));
  if (!selected.length || selected.length>100) throw Error('Expected 1–100 generated manual pages');
  let playwright;
  try { playwright=require(options.playwright || 'playwright'); }
  catch { if(options.playwright) throw Error('Cannot load requested Playwright package'); playwright=require('playwright-core'); }
  const browser=await playwright.chromium.launch({headless:true, executablePath:options.browser, chromiumSandbox:true});
  const results=[];
  try {
    for (const width of [1280,390]) {
      const context=await browser.newContext({offline:true,viewport:{width,height:900}});
      for (const asset of selected) {
        const local=path.resolve(root,asset.destination);
        if (!local.startsWith(root+path.sep)) throw Error('Manual destination escapes root');
        const bytes=fs.readFileSync(local);
        if (bytes.length!==asset.size_bytes || crypto.createHash('sha256').update(bytes).digest('hex')!==asset.sha256) throw Error(`Manual pin changed: ${asset.id}`);
        const page=await context.newPage();
        const errors=[],failedRequests=[],requests=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('requestfailed',r=>failedRequests.push({url:r.url(),error:r.failure()?.errorText}));
        page.on('request',r=>{ if(/^https?:/.test(r.url())) requests.push(r.url()); });
        await page.goto(pathToFileURL(local).href,{waitUntil:'load',timeout:15000});
        let state, finalUrl, navigationAttempts=0, stable=false;
        for (let attempt=0;attempt<3;attempt++) {
          navigationAttempts++;
          try {
            await page.waitForLoadState('domcontentloaded',{timeout:15000});
            await page.waitForTimeout(100);
            const before=page.url();
            const imageDecode=await page.evaluate(settleImages);
            state=await page.evaluate(()=>({
          title:document.title,textLength:document.body.innerText.length,
          scrollWidth:document.documentElement.scrollWidth,viewportWidth:innerWidth,
          headings:[...document.querySelectorAll('h1,h2')].map(h=>h.textContent.trim()),
          tables:document.querySelectorAll('table').length,
          visibleGraphicCount:[...document.querySelectorAll('img,svg')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;}).length,
          brokenImages:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src),
          links:[...document.querySelectorAll('a[href]')].map(a=>({url:a.href,raw:a.getAttribute('href')}))
        }));
            state.imageDecode=imageDecode;
            state.brokenAnchors=await page.evaluate(brokenAnchors);
            finalUrl=page.url();
            if (before!==finalUrl) continue;
            const finalPath=fileURLToPath(new URL(finalUrl));
            const target=byDestination.get(path.resolve(finalPath));
            if (!target || !finalPath.startsWith(root+path.sep)) throw Error('Manual navigation escaped the pinned package');
            const finalBytes=fs.readFileSync(finalPath);
            if (finalBytes.length!==target.size_bytes || crypto.createHash('sha256').update(finalBytes).digest('hex')!==target.sha256) throw Error('Navigated manual target changed');
            stable=true;
            break;
          } catch (error) {
            if (!/Execution context was destroyed|Cannot find context|Frame was detached/.test(error.message) || attempt===2) throw error;
            state=undefined;
          }
        }
        if (!state || !finalUrl || !stable) throw Error('Manual navigation did not stabilize within3 attempts');
        const brokenFiles=state.links.filter(a=>a.url.startsWith('file:')).filter(a=>!fs.existsSync(fileURLToPath(new URL(a.url)))).map(a=>a.raw);
        if(options.screenshots && /(?:ssh_keygen_1|sftp_server_8|ssh_keyscan_1|ssh_keysign_8)$/.test(asset.id)) {
          fs.mkdirSync(options.screenshots,{recursive:true});
          await page.screenshot({path:path.join(options.screenshots,`${asset.id}-${width}.png`)});
        }
        const {links,...bounded}=state;
        results.push({asset_id:asset.id,width,finalUrl,navigationAttempts,...bounded,brokenFiles,errors,failedRequests,requests,
          passed:hasReadableContent(state) && state.scrollWidth<=width && !state.brokenImages.length && !state.brokenAnchors.length && !brokenFiles.length && !errors.length && !failedRequests.length && !requests.length});
        await page.close();
      }
      await context.close();
    }
  } finally { await browser.close(); }
  const report={schema_version:1,checks:results.length,passed:results.filter(r=>r.passed).length,new_downloads:0,results};
  fs.mkdirSync(path.dirname(path.resolve(options.output)),{recursive:true});
  const encoded=JSON.stringify(report,null,2)+'\n';
  if (Buffer.byteLength(encoded)>8*1024*1024) throw Error('Manual browser report exceeds8MiB; use a smaller shard');
  fs.writeFileSync(options.output,encoded);
  console.log(JSON.stringify({checks:report.checks,passed:report.passed,failure_count:results.filter(r=>!r.passed).length,failures:results.filter(r=>!r.passed).slice(0,5).map(r=>({asset_id:r.asset_id,width:r.width,overflow:r.scrollWidth-r.viewportWidth,brokenFiles:r.brokenFiles.slice(0,3),brokenAnchors:r.brokenAnchors.slice(0,3)})),report:options.output}));
  if(report.passed!==report.checks) process.exitCode=1;
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
