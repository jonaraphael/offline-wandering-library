/* Bounded offline browser review of exact generated direct-edition candidates. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL,fileURLToPath} = require('node:url');

async function main() {
  const options={};
  for(let i=2;i<process.argv.length;i+=2) {
    const key=process.argv[i].slice(2);
    if(!['fragment','root','checks','output','screenshots','browser','playwright'].includes(key)||!process.argv[i+1]) throw Error('Unexpected/missing option');
    options[key]=process.argv[i+1];
  }
  for(const key of ['fragment','root','checks','output']) if(!options[key])throw Error(`Missing --${key}`);
  const fragmentBytes=fs.readFileSync(options.fragment), checkBytes=fs.readFileSync(options.checks);
  if(fragmentBytes.length>16*1024*1024||checkBytes.length>65536)throw Error('Control evidence exceeds its bound');
  const fragment=JSON.parse(fragmentBytes), checks=JSON.parse(checkBytes);
  if(!Array.isArray(checks.assets)||!checks.assets.length||checks.assets.length>24||new Set(checks.assets).size!==checks.assets.length)throw Error('Need1–24 unique explicit HTML asset IDs');
  const assets=new Map(fragment.assets.map(a=>[a.id,a]));
  const root=path.resolve(options.root), results=[];
  const playwright=require(options.playwright||'playwright-core');
  const browser=await playwright.chromium.launch({headless:true,executablePath:options.browser,chromiumSandbox:true});
  try {
    for(const width of [1280,390]) {
      const context=await browser.newContext({offline:true,viewport:{width,height:900}});
      for(const id of checks.assets) {
        const asset=assets.get(id);
        if(!(asset?.export_document||asset?.archive_member?.document||asset?.generation)||asset.format!=='html')throw Error(`Expected exact generated/package HTML document: ${id}`);
        const file=path.resolve(root,asset.destination);
        if(!file.startsWith(root+path.sep))throw Error('Output escapes preview root');
        const data=fs.readFileSync(file);
        if(data.length>64*1024*1024||data.length!==asset.size_bytes||crypto.createHash('sha256').update(data).digest('hex')!==asset.sha256)throw Error(`Changed output pin: ${id}`);
        const page=await context.newPage(), errors=[],failedRequests=[],network=[];
        page.on('pageerror',e=>errors.push(e.message.slice(0,400)));
        page.on('requestfailed',r=>failedRequests.push({url:r.url().slice(0,1000),error:r.failure()?.errorText}));
        page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url().slice(0,1000));});
        await page.goto(pathToFileURL(file).href,{waitUntil:'load',timeout:20000});
        // Render every image without unbounded page scrolling. Original static
        // content remains unchanged on disk; lazy loading is disabled in this QA context.
        await page.evaluate(async()=>{
          if(document.images.length>2000)throw Error('Page exceeds2,000-image QA bound');
          for(const image of document.images)image.loading='eager';
          await Promise.race([Promise.all([...document.images].map(image=>image.decode().catch(()=>{}))),new Promise(resolve=>setTimeout(resolve,10000))]);
        });
        const state=await page.evaluate(()=>({title:document.title,language:document.documentElement.lang,
          textLength:document.body.innerText.length,scrollWidth:document.documentElement.scrollWidth,
          headings:[...document.querySelectorAll('h1,h2,h3')].map(h=>h.textContent.trim()).slice(0,40),
          images:document.images.length,figcaptions:document.querySelectorAll('figcaption').length,
          tables:document.querySelectorAll('table').length,math:document.querySelectorAll('math,svg').length,
          brokenImages:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.getAttribute('src')),
          links:[...document.querySelectorAll('a[href]')].map(a=>({url:a.href,raw:a.getAttribute('href')}))}));
        const brokenFiles=state.links.filter(a=>a.url.startsWith('file:')).filter(a=>!fs.existsSync(fileURLToPath(new URL(a.url)))).map(a=>a.raw);
        if(options.screenshots){fs.mkdirSync(options.screenshots,{recursive:true});await page.screenshot({path:path.join(options.screenshots,`${id}-${width}.png`)});}
        const {links,...summary}=state;
        results.push({asset_id:id,source_entry:asset.source_archive_entry,output_sha256:asset.sha256,width,...summary,
          brokenFiles,errors,failedRequests,network,passed:state.textLength>100&&state.scrollWidth<=width&&!state.brokenImages.length&&!brokenFiles.length&&!errors.length&&!failedRequests.length&&!network.length});
        await page.close();
      }
      await context.close();
    }
  } finally {await browser.close();}
  const report={schema_version:1,content_ready:false,offline:true,physical_device_certification:'pending',
    fragment_sha256:crypto.createHash('sha256').update(fragmentBytes).digest('hex'),checks_sha256:crypto.createHash('sha256').update(checkBytes).digest('hex'),
    checks:results.length,passed:results.filter(r=>r.passed).length,substantive_review:'pending; bounded browser checks are not whole-collection approval',results};
  fs.mkdirSync(path.dirname(path.resolve(options.output)),{recursive:true});fs.writeFileSync(options.output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({checks:report.checks,passed:report.passed,content_ready:false,failures:results.filter(r=>!r.passed).map(r=>({asset_id:r.asset_id,width:r.width,brokenImages:r.brokenImages.length,overflow:r.scrollWidth-r.width,failedRequests:r.failedRequests.length})),detail:options.output}));
  if(report.checks!==report.passed)process.exitCode=1;
}
main().catch(error=>{console.error(error.message.slice(0,1500));process.exitCode=1;});
