/* Offline decode evidence for exact captured media; never an admission gate. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const args={};for(let i=2;i<process.argv.length;i+=2){if(!['--input','--output','--budget-root','--browser','--playwright'].includes(process.argv[i])||!process.argv[i+1])throw Error('Explicit media review paths required');args[process.argv[i].slice(2)]=process.argv[i+1];}
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
async function fileHash(file){const h=crypto.createHash('sha256');for await(const block of fs.createReadStream(file))h.update(block);return h.digest('hex');}
function usage(dir){if(!fs.existsSync(dir))return 0;let n=0;for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,entry.name);if(entry.isSymbolicLink())throw Error('Symlink in review evidence');n+=entry.isDirectory()?usage(p):fs.statSync(p).size;}return n;}
function save(file,data){if(!Buffer.isBuffer(data))data=Buffer.from(JSON.stringify(data,null,2)+'\n');const old=fs.existsSync(file)?fs.statSync(file).size:0;const disk=fs.statfsSync(args['budget-root']);if(usage(args['budget-root'])+data.length>500000000||disk.bavail*disk.bsize<data.length+10000000000)throw Error('Review write exceeds500MB peak or10GB reserve');fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file+'.pending',data);fs.renameSync(file+'.pending',file);}
(async()=>{
 const raw=fs.readFileSync(args.input);if(raw.length>16*1024*1024)throw Error('Media input exceeds16MiB');const input=JSON.parse(raw);if(!input.media.length||input.media.length>500)throw Error('Expected1–500 exact media records');
 const {chromium}=require(args.playwright);const browser=await chromium.launch({headless:true,executablePath:args.browser});
 const results=[];const binding={input_sha256:digest(raw),checker_sha256:digest(fs.readFileSync(__filename)),browser_version:browser.version()};const report={schema_version:1,content_ready:false,...binding,tool:'Chromium metadata, three seeks and brief playback; no whole-stream decode claim',results};
 try{
  const context=await browser.newContext({offline:true,viewport:{width:1280,height:900}});const page=await context.newPage();
  const player=path.join(args.output,'player.html');save(player,Buffer.from('<!doctype html><meta charset="utf-8"><body style="margin:0;background:#111"><video muted preload="auto" style="display:block;max-width:1280px;max-height:850px"></video>'));
  await page.goto(pathToFileURL(player).href);page.setDefaultTimeout(30000);
  for(const item of input.media){
   const row={id:item.id,title:item.title,source_url:item.source_url,size_bytes:item.size_bytes,sha256:item.sha256,binding,frames:[],passed:false};
   try{
    const stat=fs.lstatSync(item.path);if(!stat.isFile()||stat.isSymbolicLink()||stat.size!==item.size_bytes||await fileHash(item.path)!==item.sha256)throw Error('Observed media differs from source/preview pin');
    const cached=path.join(args.output,item.id+'.json');
    if(fs.existsSync(cached)){const old=JSON.parse(fs.readFileSync(cached));if(old.sha256===item.sha256&&JSON.stringify(old.binding)===JSON.stringify(binding)&&old.passed&&old.frames.every(f=>fs.existsSync(f.path)&&digest(fs.readFileSync(f.path))===f.sha256)){results.push(old);continue;}}
    await page.locator('video').evaluate((v,url)=>{v.pause();v.removeAttribute('controls');v.src=url;v.load();},pathToFileURL(item.path).href);
    await page.waitForFunction(()=>{const v=document.querySelector('video');return v.error||v.readyState>=2;},null,{timeout:30000});
    Object.assign(row,await page.locator('video').evaluate(v=>({width:v.videoWidth,height:v.videoHeight,duration_seconds:v.duration,error:v.error?.message||null})));
    if(row.error||!row.width||!row.height||!Number.isFinite(row.duration_seconds)||row.duration_seconds<=0)throw Error(row.error||'Invalid decoded media metadata');
    const times=[Math.min(2,row.duration_seconds*.1),row.duration_seconds*.5,Math.max(0,row.duration_seconds-2)];
    for(let i=0;i<times.length;i++){
     await page.locator('video').evaluate((v,t)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Seek timeout')),30000);v.addEventListener('seeked',()=>{clearTimeout(timer);resolve();},{once:true});v.currentTime=t;}),times[i]);
     await page.waitForFunction(()=>document.querySelector('video').readyState>=2);
     const data=await page.locator('video').screenshot({type:'jpeg',quality:85});if(data.length>2*1024*1024)throw Error('Frame exceeds2MiB evidence bound');
     const file=path.join(args.output,item.id+'-'+i+'.jpg');save(file,data);row.frames.push({path:file,sha256:digest(data),bytes:data.length,time_seconds:times[i]});
    }
    row.playback=await page.locator('video').evaluate(async v=>{v.currentTime=0;await v.play();const before=v.currentTime;await new Promise(r=>setTimeout(r,400));v.pause();return {before,after:v.currentTime,advanced:v.currentTime>before,error:v.error?.message||null};});
    if(!row.playback.advanced||row.playback.error)throw Error('Media did not advance during native playback');row.passed=true;
   }catch(error){row.failure=String(error.message).slice(0,1000);}
   results.push(row);save(path.join(args.output,item.id+'.json'),row);save(path.join(args.output,'checkpoint.json'),{content_ready:false,requested:input.media.length,checked:results.length,passed:results.filter(r=>r.passed).length});
  }
  await context.close();
 }finally{await browser.close();}
 report.requested=input.media.length;report.checked=results.length;report.passed=results.filter(r=>r.passed).length;save(path.join(args.output,'report.json'),report);console.log(JSON.stringify({requested:report.requested,checked:report.checked,passed:report.passed,content_ready:false}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
