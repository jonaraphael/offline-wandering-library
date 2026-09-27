/* Offline layout/link QA for a pinned generated manual fragment. No downloads. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL, fileURLToPath} = require('node:url');

async function main() {
  const options = {};
  for (let i=2; i<process.argv.length; i+=2) {
    const key=process.argv[i];
    if (!['--fragment','--root','--output','--browser','--playwright','--screenshots'].includes(key) || !process.argv[i+1]) throw Error('Expected --fragment, --root, --output and optional --browser, --playwright, --screenshots');
    options[key.slice(2)]=process.argv[i+1];
  }
  for (const key of ['fragment','root','output']) if (!options[key]) throw Error(`Missing --${key}`);
  const fragment=JSON.parse(fs.readFileSync(options.fragment,'utf8'));
  const root=path.resolve(options.root);
  const selected=fragment.assets.filter(a=>a.format==='html' && a.generation);
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
        const state=await page.evaluate(()=>({
          title:document.title,textLength:document.body.innerText.length,
          scrollWidth:document.documentElement.scrollWidth,viewportWidth:innerWidth,
          headings:[...document.querySelectorAll('h1,h2')].map(h=>h.textContent.trim()),
          tables:document.querySelectorAll('table').length,
          brokenImages:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src),
          links:[...document.querySelectorAll('a[href]')].map(a=>({url:a.href,raw:a.getAttribute('href')})),
          brokenAnchors:[...document.querySelectorAll('a[href^="#"]')].filter(a=>!document.getElementById(decodeURIComponent(a.hash.slice(1)))).map(a=>a.getAttribute('href'))
        }));
        const brokenFiles=state.links.filter(a=>a.url.startsWith('file:')).filter(a=>!fs.existsSync(fileURLToPath(new URL(a.url)))).map(a=>a.raw);
        if(options.screenshots && /(?:ssh_keygen_1|sftp_server_8|ssh_keyscan_1|ssh_keysign_8)$/.test(asset.id)) {
          fs.mkdirSync(options.screenshots,{recursive:true});
          await page.screenshot({path:path.join(options.screenshots,`${asset.id}-${width}.png`)});
        }
        const {links,...bounded}=state;
        results.push({asset_id:asset.id,width,...bounded,brokenFiles,errors,failedRequests,requests,
          passed:state.textLength>500 && state.scrollWidth<=width && !state.brokenImages.length && !state.brokenAnchors.length && !brokenFiles.length && !errors.length && !failedRequests.length && !requests.length});
        await page.close();
      }
      await context.close();
    }
  } finally { await browser.close(); }
  const report={schema_version:1,checks:results.length,passed:results.filter(r=>r.passed).length,new_downloads:0,results};
  fs.mkdirSync(path.dirname(path.resolve(options.output)),{recursive:true});
  fs.writeFileSync(options.output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({checks:report.checks,passed:report.passed,failures:results.filter(r=>!r.passed).map(r=>({asset_id:r.asset_id,width:r.width,overflow:r.scrollWidth-r.viewportWidth,brokenFiles:r.brokenFiles,brokenAnchors:r.brokenAnchors})),report:options.output}));
  if(report.passed!==report.checks) process.exitCode=1;
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
