/* Deterministic topic clusters from catalog tags and validated pseudoindexes. */
(function(root) {
  'use strict';
  const colors = {CRITICAL:'#a24336', USEFUL:'#286348', NONESSENTIAL:'#66728d'};
  function primary(row, verticals) {
    for (const domain of row.knowledge_domains || []) {
      const vertical = verticals.find(v => v.domains.includes(domain));
      if (vertical) return {vertical:vertical.id, domain};
    }
    return null;
  }
  function available(model) {
    const records=[...model.assets,...model.resources];
    return records.length>0 && records.every(row=>colors[row.utility_tier] && primary(row,model.topic_verticals));
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
  function subtopic(row, verticals) {
    // The first declared route anchors a single dot; every route remains searchable.
    const route=row.discovery?.topics?.[0];
    const domain=primary(row,verticals)?.domain;
    return route ? {id:'topic:'+route.id,title:route.title} : {id:domain,title:(domain||'').replaceAll('-',' ')};
  }
  function searchText(row) {
    return [row.title,row.id,...(row.knowledge_domains||[]),...(row.discovery?.terms||[])].join(' ').toLocaleLowerCase();
  }
  function topicTitle(model, domain) {
    if(domain?.startsWith('topic:')) {
      for(const row of model.assets)for(const topic of row.discovery?.topics||[])if('topic:'+topic.id===domain)return topic.title;
    }
    return (domain||'').replaceAll('-',' ');
  }
  function matches(row, verticals, scope={}) {
    if(!scope.vertical)return true;
    const topic=primary(row,verticals);
    return Boolean(topic && topic.vertical===scope.vertical && (!scope.domain || subtopic(row,verticals).id===scope.domain));
  }
  function contentSize(asset) {
    if(Number.isFinite(asset.uncompressed_size_bytes)&&asset.uncompressed_size_bytes>=0)
      return {bytes:asset.uncompressed_size_bytes,estimated:false,basis:'Cataloged uncompressed size'};
    if(!Number.isFinite(asset.size_bytes)||asset.size_bytes<0)return {bytes:null,estimated:false,basis:'Size unknown'};
    // Explicit planning heuristics, not measured compression ratios. Ordinary
    // files (including extracted PDFs) retain their original encoding and size.
    const factor={zim:3,zip:2,appimage:2,dmg:2,apk:2}[asset.format]||1;
    return {bytes:Math.round(asset.size_bytes*factor),estimated:factor!==1,
      basis:factor===1?'Original file size':factor+'× stored size; rough '+asset.format.toUpperCase()+' expansion assumption'};
  }
  function storageGroups(model, selectedIds, matchingIds, scope={}) {
    const groups=new Map();
    // Walk unique assets, not resource memberships: shared files occupy space once.
    for(const asset of model.assets) {
      if(!matchingIds.has(asset.id)||!matches(asset,model.topic_verticals,scope))continue;
      const topic=primary(asset,model.topic_verticals);
      if(!topic)continue;
      const leaf=subtopic(asset,model.topic_verticals);
      const id=scope.vertical?leaf.id:topic.vertical;
      if(!groups.has(id))groups.set(id,{id,
        title:scope.vertical?leaf.title:model.topic_verticals.find(v=>v.id===id).title,
        scope:scope.vertical?{vertical:topic.vertical,domain:leaf.id}:{vertical:topic.vertical},
        bytes:0,storedBytes:0,estimated:0,unknown:0,assets:[]});
      if(!selectedIds.has(asset.id))continue;
      const group=groups.get(id);
      group.assets.push(asset);
      const size=contentSize(asset);
      if(size.bytes!==null)group.bytes+=size.bytes;
      else group.unknown++;
      if(size.estimated)group.estimated++;
      if(Number.isFinite(asset.size_bytes)&&asset.size_bytes>=0)group.storedBytes+=asset.size_bytes;
    }
    for(const group of groups.values())group.assets.sort((a,b)=>(contentSize(b).bytes||0)-(contentSize(a).bytes||0)||a.id.localeCompare(b.id));
    return [...groups.values()].sort((a,b)=>b.bytes-a.bytes||a.title.localeCompare(b.title));
  }
  function layout(model, scope={}) {
    const verticals=scope.vertical ? model.topic_verticals.filter(v=>v.id===scope.vertical).map(v=>({...v,x:475,y:425,radius:390})) : model.topic_verticals;
    const records=model.assets.filter(row=>matches(row,model.topic_verticals,scope));
    const groups=new Map(verticals.map(v=>[v.id,new Map()]));
    for (const row of records) {
      const topic=primary(row,verticals);
      if(!topic)throw new Error('No topic vertical for ' + row.id);
      const {vertical}=topic, domain=subtopic(row,verticals).id, group=groups.get(vertical);
      if (!group.has(domain)) group.set(domain,[]);
      group.get(domain).push(row);
    }
    const nodes=[],clusters=[];
    for (const vertical of verticals) {
      const groupsHere=[...groups.get(vertical.id)].map(([domain,rows])=>({id:domain, rows:rows.sort((a,b)=>a.id.localeCompare(b.id)),r:Math.max(scope.vertical?34:13,Math.sqrt(rows.length)*8)}));
      const packed=pack(groupsHere), extent=Math.max(1,...packed.map(p=>Math.hypot(p.x,p.y)+p.r));
      const scale=(vertical.radius-30)/extent;
      for (const group of packed) {
        const cx=vertical.x+group.x*scale,cy=vertical.y+group.y*scale+8,r=group.r*scale;
        clusters.push({vertical:vertical.id,domain:group.id,x:cx,y:cy,r});
        group.rows.forEach((record,i)=>{
          const distance=group.rows.length===1 ? 0 : Math.sqrt((i+.4)/group.rows.length)*Math.max(0,r-(scope.vertical&&!scope.domain?48:6));
          const theta=i*Math.PI*(3-Math.sqrt(5));
          nodes.push({id:record.id, record, vertical:vertical.id, domain:primary(record,verticals).domain,
            x:cx+distance*Math.cos(theta),y:cy+distance*Math.sin(theta)+(scope.vertical&&!scope.domain?12:0),r:Math.max(2.5,Math.min(5.5,scale*3.5))});
        });
      }
    }
    return {nodes,clusters,verticals};
  }
  function mount(container, model, onInspect, onScope) {
    const ns='http://www.w3.org/2000/svg';
    let drawn, current=null, scope={}, filter=()=>true;
    function svgEl(tag,attrs,content) {const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(content)e.textContent=content;return e;}
    const svg=svgEl('svg',{viewBox:'0 0 950 850',role:'group','aria-label':'Knowledge topic map. Arrow keys move among visible items; Enter inspects an item.'});
    container.replaceChildren(svg);
    let elements=[], topicElements=[];
    function draw() {
      drawn=layout(model,{vertical:scope.vertical});svg.replaceChildren();elements=[];topicElements=[];
      function drillGroup(shape,label,attrs,next) {
        const group=svgEl('g',{role:'button',tabindex:0,'aria-label':label,...attrs,class:'map-drill'});
        group.append(shape);
        const activate=()=>onScope(next.domain&&scope.domain===next.domain?{vertical:next.vertical}:next);
        group.addEventListener('click',activate);
        group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activate();}});
        svg.append(group);return group;
      }
      for(const v of drawn.verticals) {
        const shape=svgEl('circle',{cx:v.x,cy:v.y,r:v.radius,fill:'#f2f4eb',stroke:'#c5ccbc','stroke-width':1.5});
        const group=scope.vertical ? svgEl('g',{}) : drillGroup(shape,'Explore '+v.title,{'data-map-theme':v.id},{vertical:v.id});
        if(scope.vertical){group.append(shape);svg.append(group);}
        group.append(svgEl('text',{x:v.x,y:v.y-v.radius+23,'text-anchor':'middle',class:'map-theme'},v.title));
      }
      for(const g of drawn.clusters) {
        const shape=svgEl('circle',{cx:g.x,cy:g.y,r:g.r,fill:scope.vertical?'#fffdf7':'none',stroke:'#bfcbb3','stroke-dasharray':scope.vertical?'none':'3 4','stroke-width':1.5});
        if(scope.vertical) {
          const group=drillGroup(shape,'Explore '+topicTitle(model,g.domain),{'data-map-subtopic':g.domain},{vertical:g.vertical,domain:g.domain});
          topicElements.push({group,domain:g.domain});
          const label=svgEl('text',{x:g.x,y:g.y-g.r+22,'text-anchor':'middle',class:'map-subtopic'});
          const lines=[''],limit=Math.max(9,Math.floor((g.r*1.6)/7));
          for(const word of topicTitle(model,g.domain).split(' ')) {
            if(lines.at(-1).length && (lines.at(-1)+' '+word).length>limit)lines.push(word);
            else lines[lines.length-1]+=(lines.at(-1)?' ':'')+word;
          }
          for(const [i,line] of lines.entries())label.append(svgEl('tspan',{x:g.x,dy:i?14:0},line));
          group.append(label);
        } else svg.append(shape);
      }
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
    function highlightScope() {
      for(const {group,domain} of topicElements) {
        const active=domain===scope.domain;
        group.classList.toggle('map-topic-selected',active);
        group.setAttribute('aria-pressed',String(active));
      }
    }
    function inspect(node,e){current=node.id;elements.forEach(item=>item.e.classList.toggle('map-focused',item.node.id===current));onInspect(node.record);}
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
    return {setScope(value){const changed=scope.vertical!==value.vertical;scope={...value};current=null;if(changed)draw();highlightScope();},update};
  }
  root.OWLTopicMap={layout,primary,subtopic,searchText,topicTitle,matches,contentSize,storageGroups,available,mount};
})(typeof globalThis!=='undefined'?globalThis:this);
