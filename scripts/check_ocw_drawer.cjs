#!/usr/bin/env node
/* Bounded offline Chromium QA of the captured/repaired OCW homepage only. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const args={}; for(let i=2;i<process.argv.length;i+=2){if(!['--root','--preparation','--output','--browser','--playwright'].includes(process.argv[i])||!process.argv[i+1])throw Error('Expected explicit QA paths');args[process.argv[i].slice(2)]=process.argv[i+1];}
function hash(file){return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');}
function assert(value,message){if(!value)throw Error(message);}
(async()=>{
 const proof=JSON.parse(fs.readFileSync(args.preparation,'utf8'));assert(proof.kind==='ocw-homepage-qa-preparation'&&proof.content_ready===false,'Wrong preparation scope');
 for(const row of proof.files){assert(!path.isAbsolute(row.path)&&!row.path.split('/').some(x=>['..',''].includes(x)),'Unsafe QA path');const file=path.join(args.root,row.path);assert(!fs.lstatSync(file).isSymbolicLink()&&fs.statSync(file).size===row.size_bytes&&hash(file)===row.sha256,'Changed prepared member '+row.path);}
 const {chromium}=require(args.playwright);const browser=await chromium.launch({executablePath:args.browser,headless:true});
 const report={schema_version:1,kind:'ocw-homepage-drawer-browser-qa',scope:'Homepage layout and drawer behavior only; media and complete-course review remain pending',content_ready:false,preparation_sha256:hash(args.preparation),source_sha256:proof.source_sha256,html_transform_sha256:proof.html_transform_sha256,checks:[],failures:[],remote_attempts:[],page_errors:[]};
 try{
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
   const context=await browser.newContext({viewport,offline:true});await context.route(/^https?:\/\//,route=>route.abort());
   const page=await context.newPage();page.setDefaultTimeout(10000);
   page.on('request',request=>{if(/^https?:/.test(request.url())&&!report.remote_attempts.includes(request.url())&&report.remote_attempts.length<100)report.remote_attempts.push(request.url());});
   page.on('pageerror',error=>{if(report.page_errors.length<20)report.page_errors.push(error.message.slice(0,500));});
   await page.goto(pathToFileURL(path.join(args.root,'index.html')).href,{waitUntil:'load',timeout:20000});
   assert(await page.locator('h1').count()>0,'Missing original course heading');
   const geometry=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
   assert(geometry.scroll<=viewport.width+2,'Homepage exceeds viewport width');
   report.checks.push({viewport,check:'original-heading-and-layout',passed:true,geometry});
   if(viewport.width<992){
    await page.locator('#mobile-course-nav-toggle').click();
    await page.waitForFunction(()=>document.getElementById('mobile-course-nav').classList.contains('in'));
    await page.locator('#close-mobile-course-menu-button').click();
    await page.waitForFunction(()=>!document.getElementById('mobile-course-nav').classList.contains('in'));
    report.checks.push({viewport,check:'publisher-menu-open-and-close',passed:true});
    // The captured homepage omits its info opener. Exercise the retained close
    // control from an explicitly established visible drawer state; do not claim
    // that a publisher opener existed or that this tests the rest of the course.
    await page.evaluate(()=>{const d=document.getElementById('course-info-drawer');d.classList.add('in','offcanvas-transform');document.body.classList.add('offcanvas-stop-scrolling');});
    await page.locator('#close-mobile-course-info-button').click();
    await page.waitForFunction(()=>!document.getElementById('course-info-drawer').classList.contains('in')&&!document.body.classList.contains('offcanvas-stop-scrolling'));
    report.checks.push({viewport,check:'source-bound-info-close-and-scroll-restoration',passed:true,setup:'Visible info drawer class state established because original homepage has no opener'});
   }
   await context.close();
  }
 }catch(error){report.failures.push(String(error.message).slice(0,1000));}
 finally{await browser.close();}
 report.passed=report.failures.length===0;report.full_course_review_passed=false;
 fs.writeFileSync(args.output,JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({passed:report.passed,content_ready:false,checks:report.checks.length,failures:report.failures,remote_attempts:report.remote_attempts.length,page_errors:report.page_errors.length}));
 if(!report.passed)process.exitCode=1;
})().catch(error=>{console.error(String(error.message).slice(0,1000));process.exitCode=1;});
