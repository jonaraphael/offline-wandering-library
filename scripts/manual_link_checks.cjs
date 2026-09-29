/* Serializable browser-side check of same-document fragment navigation. */
function brokenAnchors(document=globalThis.document) {
  return [...document.querySelectorAll('a[href^="#"]')].filter(a => {
    const raw=a.getAttribute('href').slice(1);
    // Empty fragments navigate to the document top; # is also a common UI target.
    if (!raw) return false;
    let fragment;
    try { fragment=decodeURIComponent(raw); } catch { return true; }
    if (document.getElementById(fragment)) return false;
    // HTML's legacy named-anchor target is supported by browsers as well as id.
    if ([...document.getElementsByName(fragment)].some(e=>e.tagName==='A')) return false;
    // The HTML navigation algorithm recognizes an otherwise unmatched "top".
    return fragment.toLowerCase()!=='top';
  }).map(a=>a.getAttribute('href'));
}
// Completeness comes from whole-file/whole-package pins, not an arbitrary word
// threshold: valid API and syntax pages can be a single short paragraph.
function hasReadableContent(state) {
  return typeof state.title==='string' && state.title.trim().length>0 &&
    (state.textLength>0 || state.visibleGraphicCount>0);
}
// Decode every captured image before judging it. Lazy loading and scripted
// navigation can outlive the document's load event; failures still fail QA.
async function settleImages(document=globalThis.document, timeoutMs=10000) {
  if (!Number.isInteger(timeoutMs) || timeoutMs<1 || timeoutMs>10000) throw Error('Invalid image wait bound');
  const images=[...document.images], previous=images.map(i=>i.getAttribute('loading'));
  let timer, timedOut=false;
  try {
    images.forEach(i=>i.setAttribute('loading','eager'));
    await Promise.race([
      Promise.all(images.map(i=>Promise.resolve().then(()=>i.decode()).catch(()=>undefined))),
      new Promise(resolve=>{timer=setTimeout(()=>{timedOut=true;resolve();},timeoutMs);})
    ]);
    return {images:images.length,timed_out:timedOut,failed:images.filter(i=>!i.complete||!i.naturalWidth).length};
  } finally {
    clearTimeout(timer);
    images.forEach((i,index)=>previous[index]===null?i.removeAttribute('loading'):i.setAttribute('loading',previous[index]));
  }
}
module.exports={brokenAnchors,hasReadableContent,settleImages};
