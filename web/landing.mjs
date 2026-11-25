(()=>{
const root=document.documentElement,$=i=>document.getElementById(i),NS="http://www.w3.org/2000/svg";
const hero = document.querySelector(".hero");
const trigger = $("animate-shelf");
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const fit = () => root.style.setProperty("--u", Math.min(1, innerHeight / 900, innerWidth / 1280));
fit();
addEventListener("resize", fit);

// Scene units are px at full size. The stage is 1280 x 540; the drive's final slot is its lower middle 900 x 290.
const RAD=Math.PI/180,K=.68,S0=.18,TH=12*RAD,T0=.55,G=5400,H=1/240,
SW=172*S0,SH=716*S0,M=14,PY=222,RX=82,RY=506.5,XL=112,MX=RX+352*S0,TS=.46,TZ=.95,
COL=["#27476e","#b5532f","#2f6f62","#c0902a","#b0607a","#2e5d34","#4b3f72","#8c2f2f"],
B=[["Where There Is No Doctor",0,252,46],["A Book for Midwives",0,230,40],["Basic Emergency Care",0,264,38],["MSF Clinical Guidelines",0,244,44],["Where There Is No Dentist",0,238,34],
["Complete Guide to Home Canning",1,270,42],["FAO Farming Manuals",1,236,36],["A Seed Saving Guide",1,214,30],
["WASH in Emergencies",2,246,34],["The Sphere Handbook",2,226,40],["Shelter Safety Handbook",2,236,30],
["iFixit Repair Guides",3,258,44],["Appropedia",3,222,36],["Low-tech Magazine",3,240,32],
["Biology",4,246,40],["Khan Academy",4,266,52],["Siyavula Mathematics",4,232,34],
["Wikipedia",5,278,66],["Maps of the World",5,254,48],["Wiktionary",5,228,38],
["University Physics",6,240,40],["Anatomy and Physiology",6,258,46],
["Project Gutenberg",7,268,56],["Book Dash Stories",7,206,30]];
const cl=x=>Math.max(0,Math.min(1,x)),ease=x=>x<.5?4*x*x*x:1-Math.pow(2-2*x,3)/2,f=n=>n.toFixed(2);

// Row layout, measured along the plank from its low (left) end: stick as bookend, then the books.
let x=M+SW+10;
const bk=B.map(([name,cat,h,w],i)=>{h*=K;w*=K;const lean=i==13?4:0,a=-lean*RAD,c=x+w/2;x+=w+2+(lean?5:0);
return{name,cat,h,w,c,lean,ox:w/2-w/2*Math.cos(a)+h/2*Math.sin(a),oy:-w/2*Math.sin(a)-h/2*Math.cos(a)}});
const L=x-2+M,PX=640+L/2,per=COL.map((_,i)=>bk.filter(b=>b.cat==i).length);

// The plank swings about its high (right) end like a released spring-damped hinge.
const tilt=t=>{t-=T0;if(t<=0)return 0;const z=.62,w=5.5,wd=w*Math.sqrt(1-z*z),e=Math.exp(-z*w*t);return TH*(1-e*(Math.cos(wd*t)+z*w/wd*Math.sin(wd*t)))};
// Sliding with static and kinetic friction, integrated once: returns t -> [distance, speed].
const sim=(mus,muk)=>{const D=[0],V=[0];let d=0,v=0,go=0;for(let i=1;i<=960;i++){const th=tilt(T0+i*H);if(!go&&Math.tan(th)>mus)go=1;if(go){v=Math.max(0,v+G*(Math.sin(th)-muk*Math.cos(th))*H);d+=v*H}D.push(d);V.push(v)}
return t=>{const q=Math.min(959.999,Math.max(0,(t-T0)/H)),i=q|0,r=q-i;return[D[i]+(D[i+1]-D[i])*r,V[i]+(V[i+1]-V[i])*r]}};
const train=sim(.13,.115),slip=sim(.07,.05),when=(fn,c)=>{let t=T0;while(fn(t)[0]<c&&t<T0+4)t+=H;return t};
const world=(th,xl,yl)=>{const c=Math.cos(th),s=Math.sin(th);return[PX+xl*c+yl*s,PY-xl*s+yl*c]};

// Each book leaves the plank when its base passes the end, then follows a curve into the connector.
for(const b of bk){b.te=when(train,b.c);const th=tilt(b.te),v=train(b.te)[1];b.tf=.46-.1*Math.min(1,v/900);b.ta=b.te+b.tf;b.r0=-th/RAD-b.lean;
const p=world(th,-L+b.ox,b.oy);b.p=[p,[p[0]-v*Math.cos(th)*b.tf/3,p[1]+v*Math.sin(th)*b.tf/3],[MX+62,RY-26],[MX,RY]]}
const st={c:M+SW/2};st.te=when(slip,st.c);{const th=tilt(st.te),v=slip(st.te)[1],p=world(th,-L,-SH/2);st.x0=p[0];st.y0=p[1];st.vx=-v*Math.cos(th);st.vy=v*Math.sin(th);st.r0=-90-th/RAD;st.tl=st.te+TS}
const lastOut=bk[bk.length-1].te,lastIn=Math.max(...bk.map(b=>b.ta)),tz=lastIn+.14,tfade=tz+.3,TEND=Math.max(tz+TZ,tfade+.74)+.05;

const plank=$("plank"),gB=$("books"),drv=$("drv"),shadow=$("shadow"),led=$("led"),cnt=$("cnt"),trk=$("trk"),
segs=[...$("bar").children].map(e=>[e,+e.getAttribute("width")]),late=[...document.querySelectorAll(".late")];
plank.innerHTML=`<rect x="${f(-L)}" y="12" width="${f(L)}" height="14" fill="#3c230a" opacity=".3" filter="url(#ps)"/><rect x="${f(-L)}" width="${f(L)}" height="14" rx="2" fill="url(#wood)"/>`;
for(const b of bk){const g=document.createElementNS(NS,"g"),l=f(-b.w/2),t=-b.h/2;
g.innerHTML=`<rect x="${l}" y="${f(t)}" width="${f(b.w)}" height="${f(b.h)}" rx="2" fill="${COL[b.cat]}"/><rect x="${l}" y="${f(t)}" width="${f(b.w)}" height="${f(b.h)}" rx="2" fill="url(#sp)"/><path d="M${l} ${f(t+11)}h${f(b.w)}M${l} ${f(-t-11)}h${f(b.w)}" stroke="#f4eee1" stroke-opacity=".55" stroke-width="1.4"/><text class="t" transform="rotate(-90)">${b.name}</text>`;
gB.appendChild(g);b.el=g}

function render(t){
const th=tilt(t),deg=th/RAD,q=cl((t-lastOut-.12)/.45),D=train(t)[0];
plank.setAttribute("transform",`translate(${f(PX)} ${f(PY+70*q*q)}) rotate(${f(-deg-14*q*q)})`);plank.setAttribute("opacity",f(1-q));
let last=-9,sum=0;const got=COL.map(()=>0);
for(const b of bk){const e=b.el;
if(t>=b.ta){e.setAttribute("display","none");const g=cl((t-b.ta)/.12);got[b.cat]+=g;sum+=g;last=Math.max(last,b.ta);continue}
let X,Y,R,Z=1,O=1;
if(t<b.te){[X,Y]=world(th,-L+b.c-D+b.ox,b.oy);R=-deg-b.lean}
else{const u=(t-b.te)/b.tf,v=1-u,p=b.p,a=v*v*v,b1=3*v*v*u,c=3*v*u*u,d=u*u*u;
X=a*p[0][0]+b1*p[1][0]+c*p[2][0]+d*p[3][0];Y=a*p[0][1]+b1*p[1][1]+c*p[2][1]+d*p[3][1];
R=b.r0+(-110-b.r0)*Math.pow(u,1.4);Z=1-.95*Math.pow(u,1.9);O=Math.min(1,v/.08)}
e.removeAttribute("display");e.setAttribute("opacity",f(O));e.setAttribute("transform",`translate(${f(X)} ${f(Y)}) rotate(${f(R)}) scale(${Z.toFixed(3)})`)}
// The stick: bookend, then first off the end, then landing on its side with the connector toward the shelf.
let X,Y,R=0,Z=S0,sh=0,z=0;
if(t<st.te){[X,Y]=world(th,-L+st.c-slip(t)[0],-SH/2);R=-90-deg}
else if(t<st.tl){const u=(t-st.te)/TS,u2=u*u,u3=u2*u;X=(2*u3-3*u2+1)*st.x0+(u3-2*u2+u)*st.vx*TS+(3*u2-2*u3)*XL+(u3-u2)*-260*TS;Y=st.y0+st.vy*TS*u+(RY-st.y0-st.vy*TS)*u2;R=st.r0*(1-u)}
else{const p=t-st.tl,pulse=Math.exp(-(t-last)/.07);X=p<.2307?XL-(260*p-563.5*p*p):RX;
Y=RY-(p<.16?28*(p/.16)*(1-p/.16):p<.26?10*((p-.16)/.1)*(1-(p-.16)/.1):0);sh=cl(p/.15);
z=ease(cl((t-tz)/TZ));X+=(640-X)*z-2.5*pulse*(1-z);Y+=(384-Y)*z;Z=(S0+(1-S0)*z)*(1+.05*pulse*(1-z));led.setAttribute("opacity",f(z>0?.3+.7*z:.3+.7*pulse))}
if(t<st.tl)led.setAttribute("opacity",".3");
drv.setAttribute("transform",`translate(${f(X)} ${f(Y)}) rotate(${f(R)}) scale(${Z.toFixed(4)}) translate(-450 -134)`);
shadow.setAttribute("transform",`translate(${f(X)} ${f(Y)}) scale(${Z.toFixed(4)}) translate(-450 -134)`);shadow.setAttribute("opacity",f(sh));
// The label fills as books arrive, one category at a time.
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
