/* Exercise the pinned ordinary-file Python search and feedback flows offline. */
const fs=require('node:fs'), path=require('node:path'), crypto=require('node:crypto');
const {pathToFileURL,fileURLToPath}=require('node:url');
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');

async function main() {
  const o={};
  for(let i=2;i<process.argv.length;i+=2) {
    if(!['--fragment','--root','--output','--browser','--playwright'].includes(process.argv[i]) || !process.argv[i+1]) throw Error('Unexpected or incomplete option');
    o[process.argv[i].slice(2)]=process.argv[i+1];
  }
  for(const key of ['fragment','root','output','browser','playwright']) if(!o[key]) throw Error(`Missing --${key}`);
  const manifest=fs.readFileSync(o.fragment), fragment=JSON.parse(manifest), root=path.resolve(o.root);
  const assets=fragment.assets.filter(a=>a.generation), pinned=new Map();
  if(!assets.length || assets.length>2000) throw Error('Expected a bounded complete generated package');
  for(const a of assets) {
    const p=path.resolve(root,a.destination);
    if(!p.startsWith(root+path.sep) || pinned.has(p)) throw Error('Unsafe or duplicate package path');
    const bytes=fs.readFileSync(p);
    if(bytes.length!==a.size_bytes || sha(bytes)!==a.sha256) throw Error(`Changed package output: ${a.id}`);
    pinned.set(p,a);
  }
  const searches=[...pinned.keys()].filter(p=>p.endsWith('/search.html'));
  if(searches.length!==1) throw Error('Ambiguous or absent Python search entry');
  const packageDir=path.dirname(searches[0]);
  function member(suffix) {
    const found=path.resolve(packageDir,suffix);
    if(!pinned.has(found)) throw Error(`Absent package member: ${suffix}`);
    return found;
  }
  function localTarget(url) {
    const u=new URL(url);
    if(u.protocol!=='file:') throw Error('Expected an ordinary-file result');
    const p=fileURLToPath(u);
    if(!pinned.has(p)) throw Error('Result is outside the pinned complete package');
    return p;
  }
  const glossary=JSON.parse(fs.readFileSync(member('_static/glossary.json')));
  const browser=await require(o.playwright).chromium.launch({headless:true,executablePath:o.browser,chromiumSandbox:true});
  const results=[];
  try {
    for(const width of [1280,390]) {
      const context=await browser.newContext({offline:true,viewport:{width,height:900}});
      for(const query of ['iterator','asyncio']) {
        const page=await context.newPage(), errors=[],requests=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('console',m=>{if(m.type()==='error') errors.push(m.text());});
        page.on('requestfailed',r=>errors.push(`${r.url()}: ${r.failure()?.errorText}`));
        page.on('request',r=>{if(/^https?:/.test(r.url())) requests.push(r.url());});
        const url=new URL(pathToFileURL(member('search.html')));url.searchParams.set('q',query);
        await page.goto(url.href,{waitUntil:'load'});
        await page.waitForFunction(()=>document.querySelectorAll('#search-results ul.search li').length>0,{},{timeout:15000});
        const state=await page.evaluate(()=>({
          note:document.querySelector('#owl-file-search-note')?.textContent,
          results:[...document.querySelectorAll('#search-results ul.search li a')].map(a=>({title:a.textContent,url:a.href})),
          glossaryTitle:document.querySelector('#glossary-title').textContent,
          glossaryBody:document.querySelector('#glossary-body').innerHTML,
          glossaryVisible:getComputedStyle(document.querySelector('#glossary-result')).display!=='none',
          width:document.documentElement.scrollWidth
        }));
        if(!state.note || !state.results.length || state.width>width) throw Error(`Unusable file search: ${query}/${width}`);
        for(const result of state.results) localTarget(result.url);
        if(glossary[query]) {
          const equal=await page.evaluate(expected=>{
            const div=document.createElement('div');div.innerHTML=expected;
            for(const a of div.querySelectorAll('a[href^="#"]')) a.href='glossary.html'+a.getAttribute('href');
            return div.innerHTML===document.querySelector('#glossary-body').innerHTML;
          },glossary[query].body);
          if(!state.glossaryVisible || !equal || state.glossaryTitle!=='Glossary: '+glossary[query].title) throw Error('Complete glossary definition was not preserved in search');
        }
        await page.locator('#search-results ul.search li a').first().click();
        await page.waitForLoadState('load');localTarget(page.url());
        const bodyLength=await page.locator('body').innerText().then(s=>s.length);
        if(bodyLength===0 || errors.length || requests.length) throw Error(`Search interaction failed: ${JSON.stringify({errors,requests}).slice(0,1200)}`);
        results.push({kind:'search',query,width,result_count:state.results.length,complete_glossary:!!glossary[query],opened_local_result:true,errors,requests,passed:true});
        await page.close();
      }
      for(const contextual of [false,true]) {
        const page=await context.newPage(), errors=[],requests=[];
        page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>errors.push(r.url()));
        page.on('request',r=>{if(/^https?:/.test(r.url())) requests.push(r.url());});
        let title='Python documentation index', source='index.rst', expected=pathToFileURL(member('index.html')).href;
        if(contextual) {
          const origin=member('tutorial/index.html');expected=pathToFileURL(origin).href;source='tutorial/index.rst';
          await page.goto(expected,{waitUntil:'load'});
          title=await page.locator('meta[property="og:title"]').getAttribute('content');
          if(width<600) {
            await page.locator('label[for="menuToggler"]').click();
            await page.locator('.mobile-nav a.improvepage').click();
          } else await page.locator('.sphinxsidebar a.improvepage').click();
          await page.waitForLoadState('load');
        } else await page.goto(pathToFileURL(member('improve-page.html')).href,{waitUntil:'load'});
        const state=await page.locator('#improve-a-documentation-page').evaluate(e=>({text:e.innerText,links:[...e.querySelectorAll('a[href]')].map(a=>a.href)}));
        if(!state.text.includes(title) || !state.links.includes(expected) || !state.links.some(u=>u.includes('/Doc/'+source+'?plain=1')) || /PAGEURL|PAGETITLE|PAGESOURCE/.test(state.text)) throw Error('Feedback defaults or supplied page context were lost');
        for(const u of state.links.filter(u=>u.startsWith('file:'))) localTarget(u);
        if(errors.length || requests.length) throw Error('Feedback needs an unavailable runtime dependency');
        results.push({kind:'feedback',contextual,width,retained_page_context:true,errors,requests,passed:true});
        await page.close();
      }
      await context.close();
    }
  } finally {await browser.close();}
  const report={schema_version:1,content_ready:false,package_sha256:sha(manifest),verified_asset_count:assets.length,checks:results.length,passed:results.filter(r=>r.passed).length,new_downloads:0,results};
  fs.mkdirSync(path.dirname(path.resolve(o.output)),{recursive:true});fs.writeFileSync(o.output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({checks:report.checks,passed:report.passed,verified_asset_count:assets.length,new_downloads:0,report:o.output}));
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
