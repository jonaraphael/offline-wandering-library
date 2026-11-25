(()=>{
const root=document.documentElement,$=i=>document.getElementById(i),NS="http://www.w3.org/2000/svg";
const hero = document.querySelector(".hero");
const trigger = $("animate-shelf");
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const fit = () => root.style.setProperty("--u", Math.min(1, innerHeight / 900, innerWidth / 1280));
fit();
addEventListener("resize", fit);

// Scene units are px at full size. The stage is 1280 x 540; the drive's final slot is its lower middle 900 x 290.
// The stick ends up lying on the ground to the left of the shelf's low end, a tallest-book-length below it.
const RAD=Math.PI/180,K=.64,S0=.2,TH=9*RAD,T0=.45,G=8000,GV=10000,H=1/240,NST=1080,
SW=172*S0,SH=716*S0,M=24,GND=530.4,RY=GND-SW/2,TOP=GND-SW,EY=TOP-278*K-10,
PF=260,LE=68,TS0=T0+.08,TSD=.42,TZ=.9,
COL=["#27476e","#b5532f","#2f6f62","#c0902a","#b0607a","#2e5d34","#4b3f72","#8c2f2f"],
B=[["Where There Is No Doctor",0,252,46],["A Book for Midwives",0,230,40],["Basic Emergency Care",0,264,38],["MSF Clinical Guidelines",0,244,44],["Where There Is No Dentist",0,238,34],
["Complete Guide to Home Canning",1,270,42],["FAO Farming Manuals",1,236,36],["A Seed Saving Guide",1,214,30],
["WASH in Emergencies",2,246,34],["The Sphere Handbook",2,226,40],["Shelter Safety Handbook",2,236,30],
["iFixit Repair Guides",3,258,44],["Appropedia",3,222,36],["Low-tech Magazine",3,240,32],
["Biology",4,246,40],["Khan Academy",4,266,52],["Siyavula Mathematics",4,232,34],
["Wikipedia",5,278,66],["Maps of the World",5,254,48],["Wiktionary",5,228,38],
["University Physics",6,240,40],["Anatomy and Physiology",6,258,46],
["Project Gutenberg",7,268,56],["Book Dash Stories",7,206,30]],
DEL=[-6,4,-9,7,-2,5,-8,2,7,-4,6,-10,3,-5,7,-1,-7,2,5,-9,4,-3,7,-6];
const cl=x=>Math.max(0,Math.min(1,x)),ease=x=>x<.5?4*x*x*x:1-Math.pow(2-2*x,3)/2,eo=x=>1-Math.pow(1-x,3),sm=x=>x*x*(3-2*x),f=n=>n.toFixed(2),
arr=()=>new Float32Array(NST+1),body=(o)=>Object.assign(o,{rho:Math.hypot(o.w/2,o.h/2),be:Math.atan2(o.w/2,o.h/2),m:0,F:0,X:arr(),Y:arr(),A:arr()});

// Row layout: p0 is each book's downhill bottom corner (its heel), measured up the plank from its low (left) end.
let x=M+SW+10;
const bk=B.map(([name,cat,h,w],i)=>{h*=K;w*=K;const l0=i==13?4:0;if(l0)x+=8;const p0=x;x+=w+2;return body({name,cat,h,w,p0,l0,s:p0,a:18+(i*7%5-2)*.6,ff:(169+DEL[i]*.6)*RAD})});
const L=x-2+M,PX=640+L/2,PY=EY-L*Math.sin(TH),per=COL.map((_,i)=>bk.filter(b=>b.cat==i).length);

// The plank swings about its high (right) end and settles without rebound.
const tilt=t=>{t=(t-T0)*9;return t<=0?0:TH*(1-Math.exp(-t)*(1+t))},
edge=t=>{const th=tilt(t);return[PX-L*Math.cos(th),PY+L*Math.sin(th),th]};
// The row slides with friction and drag, integrated once.
const tq=TS0+.22,V=[0];{let v=0;for(let k=1;k<=NST;k++){const t=T0+k*H,th=tilt(t);if(t>=tq+.1)v=Math.max(0,v+(G*(Math.sin(th)-.02*Math.cos(th))-2.5*v)*H);V.push(v)}}
// Books lean together once the stick has tipped away, then fan: the nearer the end, the further over.
const pack=t=>eo(cl((t-tq)/.4)),fanG=t=>sm(cl((t-tq-.2)/.6)),
lean=(b,p,t)=>Math.max(b.l0,b.a*pack(t)+(LE-b.a)*Math.pow(1-cl(p/PF),1.7)*fanG(t));

// A body pivots on its heel while the heel is on the plank. When the heel passes the end it is in free flight:
// its centre keeps the velocity it left with and falls, and it turns only as fast as keeps its trailing end from rising.
const rel=(o,ex,ey,th,v,F,om)=>{const c=Math.cos(F),s=Math.sin(F),rx=o.w/2*c-o.h/2*s,ry=-o.w/2*s-o.h/2*c;o.cx=ex+rx;o.cy=ey+ry;o.vx=-v*Math.cos(th)+om*ry;o.vy=v*Math.sin(th)-om*rx;o.F=F;o.m=1},
fly=(o,cap,k)=>{o.vy+=GV*H;o.cx+=o.vx*H;o.cy+=o.vy*H;o.F=Math.min(o.ff,o.F+H*Math.max(0,Math.min(.96*o.vy/(o.rho*Math.max(Math.abs(Math.sin(o.F-o.be)),.25)),k*(o.ff-o.F)+1.5,cap)))},
heel=o=>{const c=Math.cos(o.F),s=Math.sin(o.F);return[o.cx-o.w/2*c+o.h/2*s,o.cy+o.w/2*s+o.h/2*c]};
for(let k=0;k<=NST;k++){const t=T0+k*H,[ex,ey,th]=edge(t);
for(const b of bk){let X,Y;
if(!b.m){if(k){const l1=lean(b,b.s,t-H);b.s-=V[k]*H;if(b.s<=0){const l2=lean(b,0,t);rel(b,ex,ey,th,V[k],th+l2*RAD,Math.max(0,(l2-l1)*RAD/H));b.tr=t}}
if(!b.m){b.F=th+lean(b,b.s,t)*RAD;X=ex+b.s*Math.cos(th);Y=ey-b.s*Math.sin(th)}}
else if(b.m==1)fly(b,17,200);
else{b.sp=650+(b.sp-650)*Math.exp(-H/.08);b.cx-=Math.sin(b.F)*b.sp*H;b.cy-=Math.cos(b.F)*b.sp*H}
if(b.m)[X,Y]=heel(b);
b.X[k]=X;b.Y[k]=Y;b.A[k]=b.F;
// It meets the stick's top edge head first and from then on moves only along its own length.
const c=Math.cos(b.F),s=Math.sin(b.F),ty=Y-b.h*c;
if(b.m==1&&Math.max(ty,ty-b.w*s)>TOP){b.m=2;b.ti=t;b.sp=Math.max(650,-b.vx*s-b.vy*c);b.xi=X-b.h*s+b.w*c/2;b.res=(b.ff-b.F)/RAD;b.mis=Math.atan2(-b.vx,b.vy)/RAD-(180-b.F/RAD)}
if(b.m==2&&b.to==null&&Math.min(Y,Y-b.w*s)>TOP+2){b.to=t;b.xo=X+b.w*c/2}}}

// The stick tips off first, turns three quarters of the way round and lands on its side where the books will come down.
const CB=bk.reduce((a,b)=>a+(b.xi+b.xo)/2,0)/bk.length,XF=CB+38*S0,st=body({w:SW,h:SH,ff:270*RAD,CX:arr(),CY:arr()});
const drop=vx=>{st.m=0;for(let k=0;k<=NST;k++){const t=T0+k*H,[ex,ey,th]=edge(t),u=cl((t-TS0)/TSD);
if(!st.m){if(u>=1){rel(st,ex,ey,th,M*6/TSD,th+LE*RAD,2*LE*RAD/TSD);st.tr=t;st.nx=st.vx;if(vx!=null)st.vx=vx;st.x0=st.cx}
else{st.F=th+LE*u*u*RAD;const s=M*(1-Math.pow(u,6)),c=Math.cos(st.F),n=Math.sin(st.F);st.cx=ex+s*Math.cos(th)+st.w/2*c-st.h/2*n;st.cy=ey-s*Math.sin(th)-st.w/2*n-st.h/2*c}}
else if(st.m==1){fly(st,22,1e9);if(st.cy+st.rho*Math.max(Math.abs(Math.cos(st.F-st.be)),Math.abs(Math.cos(st.F+st.be)))>=GND){st.m=3;st.td=t;st.c=[st.cx,st.cy,st.F]}}
else{const u=sm(cl((t-st.td)/.07));st.cx=st.c[0]+(XF-st.c[0])*u;st.cy=st.c[1]+(RY-st.c[1])*u;st.F=st.c[2]+(st.ff-st.c[2])*u}
st.CX[k]=st.cx;st.CY[k]=st.cy;st.A[k]=st.F}};
drop();drop((XF-st.x0)/(st.td-st.tr));
// Its hop: one bounce from landing, then a kick from each book that arrives while it is down.
const tflat=st.td+.07,HB=arr();{let h=0,v=0,e=0,on=0;const ev=bk.map(b=>b.ti).sort((a,b)=>a-b);
for(let k=0;k<=NST;k++){const t=T0+k*H;if(t<tflat)continue;if(!on){on=1;v=240}
while(e<ev.length&&ev[e]<=t){if(h<1.5)v=Math.max(v,215);e++}
v-=2600*H;h+=v*H;if(h<0){h=0;v=v<-60?-v*.42:0}HB[k]=h}}
const tp=Math.max(...bk.map(b=>b.tr))+.1,lastIn=Math.max(...bk.map(b=>b.to)),tz=lastIn+.12,tfade=tz+.3,TEND=Math.max(tz+TZ,tfade+.74)+.05;

const plank=$("plank"),gB=$("books"),cut=$("cutr"),drv=$("drv"),shadow=$("shadow"),led=$("led"),cnt=$("cnt"),trk=$("trk"),
segs=[...$("bar").children].map(e=>[e,+e.getAttribute("width")]),late=[...document.querySelectorAll(".late")];
plank.innerHTML=`<rect x="${f(-L)}" y="12" width="${f(L)}" height="14" fill="#3c230a" opacity=".3" filter="url(#ps)"/><rect x="${f(-L)}" width="${f(L)}" height="14" rx="2" fill="url(#wood)"/>`;
for(const b of bk){const g=document.createElementNS(NS,"g"),l=f(-b.w/2),t=-b.h/2;
g.innerHTML=`<rect x="${l}" y="${f(t)}" width="${f(b.w)}" height="${f(b.h)}" rx="2" fill="${COL[b.cat]}"/><rect x="${l}" y="${f(t)}" width="${f(b.w)}" height="${f(b.h)}" rx="2" fill="url(#sp)"/><path d="M${l} ${f(t+10)}h${f(b.w)}M${l} ${f(-t-10)}h${f(b.w)}" stroke="#f4eee1" stroke-opacity=".55" stroke-width="1.3"/><text class="t" transform="rotate(-90)">${b.name}</text>`;
gB.appendChild(g);b.el=g}

function render(t){
const deg=tilt(t)/RAD,qk=Math.min(NST-.001,Math.max(0,(t-T0)/H)),k=qk|0,r=qk-k,at=A=>A[k]+(A[k+1]-A[k])*r,hop=at(HB),pq=cl((t-tp)/.45);
plank.setAttribute("transform",`translate(${f(PX)} ${f(PY+70*pq*pq)}) rotate(${f(-deg-14*pq*pq)})`);plank.setAttribute("opacity",f(1-pq));
// Books are cut off at the stick's top edge, so nothing shows in the gap under it when it hops.
cut.setAttribute("height",f(TOP-hop+601));
let last=-9,sum=0;const got=COL.map(()=>0);
for(const b of bk){const e=b.el;
if(t>=b.ti){const g=cl((t-b.ti)/(b.to-b.ti));got[b.cat]+=g;sum+=g;last=Math.max(last,b.ti)}
if(t>=b.to){e.setAttribute("display","none");continue}
const X=at(b.X),Y=at(b.Y),F=at(b.A),c=Math.cos(F),s=Math.sin(F);
e.removeAttribute("display");e.setAttribute("transform",`translate(${f(X+b.w/2*c-b.h/2*s)} ${f(Y-b.w/2*s-b.h/2*c)}) rotate(${f(-F/RAD)})`)}
let X=at(st.CX),Y=at(st.CY),R=-90-at(st.A)/RAD,Z=S0,z=0,lo=.3,sh=cl((Y-RY+70)/70);
if(t>=tflat){const kick=Math.exp(-(t-last)/.07);z=ease(cl((t-tz)/TZ));X=XF-2*kick*(1-z)+(640-XF)*z;Y=RY-hop*(1-z)+(384-RY)*z;R=0;Z=S0+(1-S0)*z;sh=1-.03*hop*(1-z);lo=z>0?.3+.7*z:.3+.7*kick}
led.setAttribute("opacity",f(lo));
drv.setAttribute("transform",`translate(${f(X)} ${f(Y)}) rotate(${f(R)}) scale(${Z.toFixed(4)}) translate(-450 -134)`);
shadow.setAttribute("transform",`translate(${f(X)} ${f(RY+(384-RY)*z)}) scale(${Z.toFixed(4)}) translate(-450 -134)`);shadow.setAttribute("opacity",f(sh));
// The label fills as each book goes in, one category at a time.
const F=sum/bk.length;cnt.textContent=Math.round(531*F)+" files · "+(60.8*F).toFixed(1)+" GB";trk.setAttribute("opacity",F<1?"1":"0");
segs.forEach(([e,w],i)=>e.setAttribute("width",f(w*got[i]/per[i])));
late.forEach((e,k)=>{const o=1-Math.pow(1-cl((t-tfade-.12*k)/.5),3);e.style.visibility=o>0?"visible":"hidden";e.style.opacity=f(o);e.style.transform=`translateY(${f((1-o)*12)}px)`});
}

function disarm() {
  trigger.hidden = true;
  hero.removeEventListener("click", play);
  removeEventListener("scroll", play);
  removeEventListener("wheel", play);
}

let frame;
function finish() {
  disarm();
  cancelAnimationFrame(frame);
  render(TEND);
  root.classList.remove("intro");
  motion.removeEventListener("change", reduceMotion);
}

function reduceMotion(event) {
  if (event.matches) finish();
}

function play(event) {
  if (event.type === "wheel" && (event.ctrlKey || !event.deltaY)) return;
  const moveFocus = document.activeElement === trigger;
  disarm();
  const start = performance.now();

  function step(now) {
    const time = (now - start) / 1000;
    if (time >= TEND) {
      finish();
      if (moveFocus && document.activeElement === document.body) {
        hero.querySelector(".btn").focus({preventScroll: true});
      }
      return;
    }
    render(Math.max(0, time));
    frame = requestAnimationFrame(step);
  }

  frame = requestAnimationFrame(step);
}

if (motion.matches) {
  finish();
} else {
  root.classList.add("intro");
  render(0);
  trigger.hidden = false;
  hero.addEventListener("click", play);
  addEventListener("scroll", play, {passive: true});
  addEventListener("wheel", play, {passive: true});
  motion.addEventListener("change", reduceMotion);
}
})();
