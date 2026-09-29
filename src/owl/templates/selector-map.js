/* Deterministic topic clusters: catalog tags, not a claim of semantic embeddings. */
(function(root) {
  'use strict';
  const colors = {CRITICAL:'#a24336', USEFUL:'#286348', NONESSENTIAL:'#66728d'};
  function primary(row, verticals) {
    for (const domain of row.knowledge_domains || []) {
      const vertical = verticals.find(v => v.domains.includes(domain));
      if (vertical) return {vertical:vertical.id, domain};
    }
    throw new Error('No topic vertical for ' + row.id);
  }
  function pack(circles) {
    const placed=[];
    for (const circle of circles.slice().sort((a,b)=>b.r-a.r || a.id.localeCompare(b.id))) {
      let best;
      if (!placed.length) best={x:0,y:0};
      else for (let ring=0; !best && ring<300; ring++) {
        const distance=ring*2;
        for (let step=0;step<96;step++) {
          const angle=step*2*Math.PI/96, x=Math.cos(angle)*distance, y=Math.sin(angle)*distance;
          if (placed.every(p=>Math.hypot(x-p.x,y-p.y)>=p.r+circle.r+3)) { best={x,y}; break; }
        }
      }
      if (!best) throw new Error('Topic layout exceeded bounds');
      placed.push({...circle,...best});
    }
    return placed;
  }
  function layout(model, mode) {
    const verticals=model.topic_verticals, records=mode==='collections' ? model.resources : model.assets;
    const groups=new Map(verticals.map(v=>[v.id,new Map()]));
    for (const row of records) {
      const {vertical,domain}=primary(row,verticals), group=groups.get(vertical);
      if (!group.has(domain)) group.set(domain,[]);
      group.get(domain).push(row);
    }
    const nodes=[],clusters=[];
    for (const vertical of verticals) {
      const groupsHere=[...groups.get(vertical.id)].map(([domain,rows])=>({id:domain, rows:rows.sort((a,b)=>a.id.localeCompare(b.id)),r:Math.max(13,Math.sqrt(rows.length)*8)}));
      const packed=pack(groupsHere), extent=Math.max(1,...packed.map(p=>Math.hypot(p.x,p.y)+p.r));
      const scale=(vertical.radius-30)/extent;
      for (const group of packed) {
        const cx=vertical.x+group.x*scale,cy=vertical.y+group.y*scale+8,r=group.r*scale;
        clusters.push({vertical:vertical.id,domain:group.id,x:cx,y:cy,r});
        group.rows.forEach((record,i)=>{
          const distance=group.rows.length===1 ? 0 : Math.sqrt((i+.4)/group.rows.length)*Math.max(0,r-6);
          const theta=i*Math.PI*(3-Math.sqrt(5));
          nodes.push({id:record.id, record, vertical:vertical.id, domain:group.id,
            x:cx+distance*Math.cos(theta),y:cy+distance*Math.sin(theta),r:mode==='collections'?7:Math.max(2.5,Math.min(5.5,scale*3.5))});
        });
      }
    }
    return {nodes,clusters};
  }
  function mount(container, model, onInspect) {
    const ns='http://www.w3.org/2000/svg';
    let mode='assets', drawn, current=null, filter=()=>true;
    function svgEl(tag,attrs,content) {const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(content)e.textContent=content;return e;}
    const svg=svgEl('svg',{viewBox:'0 0 950 850',role:'group','aria-label':'Knowledge topic map. Arrow keys move among visible items; Enter inspects an item.'});
    container.replaceChildren(svg);
    let elements=[];
    function draw() {
      drawn=layout(model,mode);svg.replaceChildren();elements=[];
      for(const v of model.topic_verticals) {
        svg.append(svgEl('circle',{cx:v.x,cy:v.y,r:v.radius,fill:'#f2f4eb',stroke:'#c5ccbc','stroke-width':1.5}));
        svg.append(svgEl('text',{x:v.x,y:v.y-v.radius+23,'text-anchor':'middle',class:'map-theme'},v.title));
      }
      for(const g of drawn.clusters)svg.append(svgEl('circle',{cx:g.x,cy:g.y,r:g.r,fill:'none',stroke:'#d7ddcd','stroke-dasharray':'3 4'}));
      drawn.nodes.forEach((node,index)=>{
        const e=svgEl('circle',{cx:node.x,cy:node.y,r:node.r,role:'button',tabindex:index===0?0:-1,'data-map-id':node.id,
          'aria-label':`${node.record.title}. ${node.record.utility_tier}. ${node.domain.replaceAll('-',' ')}.`,stroke:colors[node.record.utility_tier],'stroke-width':1.3});
        e.append(svgEl('title',{},`${node.record.title}\n${node.record.utility_tier} · ${node.domain.replaceAll('-',' ')}`));
        e.addEventListener('click',()=>inspect(node,e));
        e.addEventListener('keydown',event=>{
          if(event.key==='Enter'||event.key===' '){event.preventDefault();inspect(node,e);}
          if(['ArrowRight','ArrowDown','ArrowLeft','ArrowUp'].includes(event.key)) {
            event.preventDefault();const visible=elements.filter(item=>filter(item.node.record));const pos=visible.findIndex(item=>item.node.id===node.id);
            const next=visible[(pos+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+visible.length)%visible.length];
            if(next){elements.forEach(item=>item.e.setAttribute('tabindex',-1));next.e.setAttribute('tabindex',0);next.e.focus();}
          }
        });
        elements.push({node,e});svg.append(e);
      });
    }
    function inspect(node,e){current=node.id;elements.forEach(item=>item.e.classList.toggle('map-focused',item.node.id===current));onInspect(node.record,mode);}
    function update(selected, visible) {
      filter=visible;
      let first=true;
      for(const {node,e} of elements) {
        const active=selected(node.record),show=visible(node.record);
        e.setAttribute('fill',active?colors[node.record.utility_tier]:'#fff');
        e.setAttribute('opacity',show?(active?1:.6):.07);
        e.style.pointerEvents=show?'auto':'none';e.setAttribute('aria-hidden',String(!show));
        e.setAttribute('tabindex',show&&first?0:-1);if(show)first=false;
        e.setAttribute('aria-label',`${node.record.title}. ${node.record.utility_tier}. ${node.domain.replaceAll('-',' ')}. ${active?'Selected':'Not selected'}.`);
      }
      return elements.filter(({node})=>visible(node.record)).length;
    }
    draw();
    return {setMode(value){mode=value;current=null;draw();},update};
  }
  root.OWLTopicMap={layout,primary,mount};
})(typeof globalThis!=='undefined'?globalThis:this);
