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

// Manage is shared by the hosted builder and the standalone planner.
(function (root) {
  "use strict";
  const sizes = [16, 32, 64, 128, 256, 512, 1000];
  const byId = id => document.getElementById(id);
  const bytes = value => {
    const units = [[1e12, "TB"], [1e9, "GB"], [1e6, "MB"], [1e3, "kB"], [1, "B"]];
    const rounded = Number(value.toPrecision(3));
    const [scale, unit] = units.find(([scale]) => rounded >= scale) || units.at(-1);
    return (rounded / scale).toLocaleString(undefined, {maximumSignificantDigits: 3}) + " " + unit;
  };
  const title = (model, row) => (model.collection_copy?.[row.id]?.title || row.title || row.id)
    .replace(/\s+(?:\(ZIM\)|ZIM)$/i, "");
  const profileCapacity = profile => profile.nominal_capacity_bytes ?? profile.capacity_bytes;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (text, action, className) => {
    const node = element("button", className, text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  };
  const link = (text, action, className) => {
    const node = element("a", className, text);
    node.href = "#";
    node.addEventListener("click", event => { event.preventDefault(); action(); });
    return node;
  };
  const sizesInto = (node, selected, choose) => {
    node.replaceChildren(...sizes.map(size => {
      const chip = button(size === 1000 ? "1 TB" : size + " GB", () => choose(size));
      chip.dataset.size = size;
      chip.setAttribute("aria-pressed", String(size === selected));
      return chip;
    }));
  };
  const sum = rows => rows.reduce((total, row) => total + (row?.size_bytes || 0), 0);
  const themeOf = (model, resource) => model.collection_copy?.[resource.id]?.theme ||
    root.OWLTopicMap.primary(resource, model.topic_verticals || [])?.vertical || "other";

  function meter(track, legend, categories, amounts, capacity, over = 0) {
    const bars = [], labels = [];
    const used = amounts.reduce((total, row) => total + row.ready + row.pending, 0);
    const total = Math.max(used, capacity, 1);
    const available = Math.max(0, capacity - used);
    const shown = [...amounts, {id: "free", ready: available, pending: 0}];
    let budget = over ? used - over : used;
    for (const {id, ready, pending} of shown) {
      if (!ready && !pending && id !== "free") continue;
      const category = categories.find(row => row.id === id);
      for (const [raw, pale] of [[ready, false], [pending, true]]) {
        const value = id === "free" ? raw : Math.min(raw, Math.max(0, budget));
        if (id !== "free") budget -= value;
        if (!value) continue;
        const part = element("i", id === "free" ? "free" : pale ? "pending" : "");
        part.style.flex = String(100 * value / total);
        part.style.setProperty("--c", "var(--c-" + id + ")");
        bars.push(part);
      }
      if (legend) {
        const label = element("li", id === "free" ? "free" : "", (category?.name || "Free") + " " + bytes(ready + pending));
        label.style.setProperty("--c", "var(--c-" + id + ")");
        labels.push(label);
      }
    }
    if (over) {
      const part = element("i", "over");
      part.style.flex = String(100 * over / total);
      bars.push(part);
      if (legend) labels.push(element("li", "over", bytes(over) + " over"));
    }
    track.replaceChildren(...bars);
    legend?.replaceChildren(...labels);
  }

  function create(model, {browser = false, download = () => true, recommend = state => state, stops, useful,
      select, onChange = () => {}, onSize, onDiagnostics = () => byId("technical").showModal()} = {}) {
    const assetsById = new Map(model.assets.map(asset => [asset.id, asset]));
    select ??= (profile, _state, result) => {
      const assets = result.selectedAssetIds.map(id => assetsById.get(id));
      const reserve = profile.reserve_bytes + profile.discovery_budget_bytes + 16 * 2 ** 20;
      const limit = profile.capacity_bytes - reserve;
      const used = sum(assets);
      return {assets, used, limit, reserve, over: Math.max(0, used - limit), errors: result.errors};
    };
    const resources = model.resources.filter(row => row.id !== "archive-readers");
    const {categories, other} = model.categories;
    const groups = [...categories, other];
    const listCategories = resources.some(row => themeOf(model, row) === other.id) ? groups : categories;
    const baseTheme = new Map();
    for (const resource of resources) {
      for (const member of [...resource.asset_ids, ...Object.values(resource.editions || {}).flatMap(row => row.asset_ids)]) {
        if (!baseTheme.has(member)) baseTheme.set(member, themeOf(model, resource));
      }
    }
    const cards = new Map(), groupNodes = new Map(), open = new Set(), showFiles = new Set();
    let state, baseline, plan, capacity, choice, splitDefault, requiresSplit, chosenSize, enabled = false;
    let allowed = false, query = "", attention = [];
    const slider = byId("manage-limit");
    const edited = new Set();
    let presetId, ceiling, limitStops = [], savedLimit, shrink, limitChanged = false;

    function members(resource, item) {
      return (resource.editions?.[item.edition] || resource).asset_ids;
    }

    function selectionOf(candidate) {
      const profile = root.OWLPlanner.profileFor(model, candidate.profile, candidate.capacityBytes, candidate);
      const result = root.OWLPlanner.resolve(model, candidate, {ignoreNativeCapacity: browser});
      return {...select(profile, candidate, result), result, profile};
    }

    function fits(candidate) {
      const selection = selectionOf(candidate);
      return !selection.over && !selection.errors.length && useful(selection);
    }

    function measure() {
      const selected = selectionOf(state);
      const theme = new Map();
      const selectedIds = new Set(selected.assets.map(asset => asset.id));
      for (const row of selected.result.rows) {
        if (!row.included && !row.autoIncluded) continue;
        const resource = model.resources.find(resource => resource.id === row.id);
        if (resource.id === "archive-readers") continue;
        for (const id of members(resource, state.items[resource.id])) {
          if (selectedIds.has(id) && !theme.has(id)) theme.set(id, themeOf(model, resource));
        }
      }
      return {...selected, theme, capacity, budget: state.capacityBytes ?? capacity, choice};
    }

    function amounts(current, present = new Map()) {
      const parts = new Map(groups.map(({id}) => [id, {id, ready: 0, pending: 0}]));
      for (const asset of current.assets) {
        const id = asset.destination.startsWith("SOFTWARE/") ? "other" : current.theme.get(asset.id) || baseTheme.get(asset.id);
        const group = parts.get(id) || parts.get("other");
        const ready = Math.min(asset.size_bytes, present.get(asset.id) || 0);
        group.ready += ready;
        group.pending += asset.size_bytes - ready;
      }
      return [...parts.values()];
    }

    function apply(resource, patch) {
      edited.add(resource.id);
      const item = state.items[resource.id];
      Object.assign(item, patch);
      if (patch.edition !== undefined) {
        item.included = true;
        delete item.assetIds;
      }
    }

    function setFile(resource, id, included) {
      edited.add(resource.id);
      const item = state.items[resource.id];
      const all = members(resource, item);
      const chosen = new Set(item.included ? item.assetIds || all : []);
      if (included) chosen.add(id); else chosen.delete(id);
      item.included = chosen.size > 0;
      item.assetIds = all.filter(id => chosen.has(id));
    }

    function readChoice() {
      const edits = {...choice.edits};
      for (const resource of resources) {
        const {id} = resource;
        if (!edited.has(id)) continue;
        delete edits[id];
        const item = state.items[id], expected = baseline.items[id];
        const chosen = new Set((item.assetIds || members(resource, item)).filter(download));
        const defaults = (expected.assetIds || members(resource, expected)).filter(download);
        if (item.included && (!expected.included || item.edition !== expected.edition ||
            chosen.size !== defaults.length || defaults.some(id => !chosen.has(id)))) {
          const excluded = members(resource, item).filter(id => download(id) && !chosen.has(id));
          edits[id] = {included: true, edition: item.edition, ...(excluded.length ? {excluded} : {})};
        } else if (!item.included && expected.included) {
          edits[id] = {included: false};
        }
      }
      edited.clear();
      const custom = Object.keys(edits).length || choice.split !== splitDefault;
      const {split, limitBytes, retainedFiles} = choice;
      return {kind: custom ? "custom" : "recommended", ...(custom ? {edits} : {}), split,
        ...(limitBytes ? {limitBytes} : {}), ...(retainedFiles ? {retainedFiles} : {})};
    }

    function refresh({changed = false} = {}) {
      if (changed) choice = readChoice();
      plan = measure();
      if (enabled) render();
      if (changed) onChange(plan);
      return plan;
    }

    function recommended(budget, retainedFiles) {
      return recommend(root.OWLPlanner.preset(model, presetId, model.capacity_policy ? Math.max(1, budget) : undefined,
        {browser}), retainedFiles);
    }

    function currentBudget() {
      return ceiling === undefined ? capacity : Math.min(choice.limitBytes || ceiling, ceiling);
    }

    function retainedAt(budget) {
      if (budget === currentBudget()) return choice.retainedFiles;
      if (budget === savedLimit.budget) return savedLimit.retainedFiles;
      return budget < shrink?.budget ? shrink.files : undefined;
    }

    function restoreSelection() {
      baseline = recommended(currentBudget(), choice.retainedFiles);
      state = structuredClone(baseline);
      state.allowIncomplete = allowed;
      if (choice.kind === "custom") {
        for (const resource of resources) {
          const edit = choice.edits?.[resource.id];
          if (!edit) continue;
          const item = state.items[resource.id];
          if (typeof edit.included === "boolean") item.included = edit.included;
          else if (edit.edition || edit.excluded?.length) item.included = true;
          if (edit.edition === "published" || resource.editions?.[edit.edition]) {
            item.edition = edit.edition;
            delete item.assetIds;
          }
          if (edit.excluded?.length) item.assetIds = members(resource, item).filter(id => !edit.excluded.includes(id));
        }
      } else if (choice.kind === "legacy") {
        const keep = new Set(choice.files);
        for (const resource of resources) {
          const item = state.items[resource.id];
          const variants = [item.edition, "published", ...Object.keys(resource.editions || {})];
          const [edition, ids] = variants.map(edition => [edition,
            members(resource, {edition}).filter(id => keep.has(id))]).sort((a, b) => b[1].length - a[1].length)[0];
          item.included = Boolean(ids.length);
          item.edition = edition;
          item.assetIds = ids;
          edited.add(resource.id);
        }
        choice = readChoice();
      }
    }

    function configure({capacityBytes, size, savedChoice, split = false, forceSplit = false, connected = false,
        installed}) {
      capacity = capacityBytes;
      chosenSize = size;
      splitDefault = split;
      requiresSplit = forceSplit;
      ceiling = connected && model.capacity_policy ? Math.min(capacity, model.capacity_policy.limit) : undefined;
      const preset = model.capacity_policy ? model.profiles[0] : model.profiles.reduce((best, row) =>
        Math.abs(profileCapacity(row) - capacity) < Math.abs(profileCapacity(best) - capacity) ? row : best);
      presetId = preset.id;
      choice = savedChoice || {kind: "recommended", split};
      if (requiresSplit) choice = {...choice, split: true};
      savedLimit = {budget: currentBudget(), limitBytes: choice.limitBytes, retainedFiles: choice.retainedFiles};
      shrink = installed;
      limitChanged = false;
      edited.clear();
      restoreSelection();
      limitStops = ceiling === undefined ? [] : stops(ceiling, budget => budget > 0 &&
        fits(budget === currentBudget() ? baseline : recommended(budget, retainedAt(budget))));
      return refresh();
    }

    function changeLimit(budget) {
      if (budget === currentBudget() && (budget !== ceiling || !choice.limitBytes)) {
        slider.value = String(budget);
        return;
      }
      const retainedFiles = budget === ceiling ? undefined : retainedAt(budget);
      const limitBytes = budget === ceiling ? undefined :
        budget === savedLimit.budget ? savedLimit.limitBytes : budget;
      const {kind, edits, split} = choice;
      choice = {kind, ...(edits ? {edits} : {}), split,
        ...(limitBytes ? {limitBytes} : {}), ...(retainedFiles ? {retainedFiles} : {})};
      restoreSelection();
      refresh();
      limitChanged = true;
      onChange(plan, {live: true});
    }

    function commitLimit() {
      if (!limitChanged) return;
      limitChanged = false;
      onChange(plan);
    }

    function matching(resource) {
      const item = state.items[resource.id];
      const ids = members(resource, item);
      const copy = model.collection_copy?.[resource.id];
      if (!query || [resource.id, title(model, resource), copy?.blurb || ""].some(text => text.toLowerCase().includes(query))) return ids;
      return ids.filter(id => {
        const file = assetsById.get(id);
        return file && (id.includes(query) || root.OWLTopicMap.searchText(file).includes(query));
      });
    }

    function makeCard(resource) {
      const {id} = resource, heading = title(model, resource);
      const card = element("div", "col");
      card.dataset.resourceId = id;
      const toggle = element("input", "switch");
      toggle.type = "checkbox";
      toggle.setAttribute("role", "switch");
      toggle.setAttribute("aria-label", heading);
      toggle.addEventListener("change", () => {
        apply(resource, {included: toggle.checked});
        if (toggle.checked) delete state.items[id].assetIds;
        refresh({changed: true});
      });
      const label = element("label", "switch-label");
      label.append(toggle);
      const content = element("div");
      content.append(element("b", "", heading));
      if (resource.utility_tier === "CRITICAL") content.append(element("span", "tag", "Essential"));
      const description = model.collection_copy?.[id]?.blurb || "";
      if (description) content.append(element("p", "", description));
      const editions = element("div", "editions"), files = element("ul", "file-list");
      const choose = link("Choose files", () => {
        if (showFiles.has(id)) showFiles.delete(id); else showFiles.add(id);
        renderCard(resource, cards.get(id));
      }, "files");
      choose.setAttribute("aria-controls", "files-" + id);
      files.id = "files-" + id;
      const note = element("p");
      const size = element("span", "size");
      content.append(editions, document.createElement("br"), choose, files, note);
      card.append(label, content, size);
      return {card, toggle, editions, choose, files, note, size};
    }

    function renderCard(resource, nodes) {
      const {id} = resource, item = state.items[id];
      const {card, toggle, editions, choose, files, note, size} = nodes;
      const ids = members(resource, item);
      const visible = matching(resource);
      card.hidden = !visible.length;
      const canChoose = ids.some(download);
      card.classList.toggle("off", !item.included);
      toggle.checked = item.included && canChoose;
      toggle.disabled = !canChoose;
      note.textContent = canChoose ? "" : "This collection has no files available here.";
      const chosen = (item.assetIds || ids).filter(download);
      size.textContent = bytes(sum((item.included ? chosen : ids.filter(download)).map(id => assetsById.get(id))));
      const variants = Object.entries(resource.editions || {}).filter(([, variant]) => variant.asset_ids.some(download));
      const recommended = baseline.items[id].edition;
      const names = {published: "With pictures", nopic: "Text only", mini: "Intro only",
        top: "50,000 article introductions", direct: "Opens directly", compact: "Compact edition"};
      editions.hidden = !variants.length;
      const previous = document.activeElement?.dataset.edition;
      editions.replaceChildren(...(!variants.length ? [] : [["published", resource], ...variants]
        .filter(([value]) => value !== "published" || resource.asset_ids.some(download))
        .map(([value, variant]) => {
          const option = button((names[value] || variant.label || value) + " · " +
            bytes(sum(variant.asset_ids.filter(download).map(id => assetsById.get(id)))) +
            (value === recommended ? " (recommended)" : ""), () => {
            apply(resource, {edition: value});
            refresh({changed: true});
          }, value === item.edition ? "on" : "");
          option.dataset.edition = value;
          option.setAttribute("aria-pressed", String(value === item.edition));
          return option;
        })));
      if (previous && document.activeElement === document.body && editions.querySelector) {
        [...editions.children].find(child => child.dataset.edition === previous)?.focus();
      }
      const expanded = showFiles.has(id);
      choose.hidden = ids.length < 2 || !canChoose;
      choose.setAttribute("aria-expanded", String(expanded));
      files.hidden = !expanded;
      const focusId = files.contains(document.activeElement) && document.activeElement?.dataset.file;
      if (expanded) files.replaceChildren(...visible.map(id => {
        const asset = assetsById.get(id);
        const row = element("li");
        const label = element("label");
        const check = element("input");
        check.type = "checkbox";
        check.dataset.file = id;
        check.checked = item.included && chosen.includes(id);
        check.disabled = !download(id);
        check.addEventListener("change", () => { setFile(resource, id, check.checked); refresh({changed: true}); });
        label.append(check, element("span", "", title(model, asset)), element("span", "size", download(id) ? bytes(asset.size_bytes) : "Unavailable"));
        row.append(label);
        return row;
      }));
      if (focusId) [...files.querySelectorAll("input")].find(input => input.dataset.file === focusId)?.focus();
    }

    function render() {
      const solid = new Map(plan.assets.map(asset => [asset.id, asset.size_bytes]));
      const parts = amounts(plan, solid);
      const limited = limitStops.length > 0;
      byId("manage-track").hidden = limited;
      if (slider) {
        byId("manage-limit-control").hidden = !limited;
        const kept = byId("manage-kept-free");
        kept.hidden = !limited || plan.budget >= capacity;
        if (limited) {
          const budget = currentBudget();
          const all = budget === ceiling;
          const track = byId("manage-limit-budget");
          meter(track, null, groups, parts, budget, plan.over);
          track.style.width = (100 * budget / capacity) + "%";
          byId("manage-limit-kept").hidden = budget === capacity;
          slider.max = String(capacity);
          slider.value = String(budget);
          slider.setAttribute("aria-valuetext", all && budget === capacity ? "All " + bytes(budget) :
            bytes(budget) + " of " + bytes(capacity));
          byId("manage-limit-value").value = (all ? "All " : "") + bytes(budget);
          byId("manage-use-all").hidden = all || !limitStops.includes(ceiling);
          byId("manage-all").textContent = "Use all " + bytes(ceiling);
          byId("manage-limit-min").textContent = bytes(limitStops[0]);
          byId("manage-limit-max").textContent = bytes(capacity) + " free on this drive";
          kept.textContent = bytes(capacity - budget) + " stays free";
        }
      }
      if (!limited) meter(byId("manage-track"), null, groups, parts, capacity, plan.over);
      const used = bytes(plan.used), available = bytes(limited ? plan.budget : capacity);
      const unit = available.split(" ").at(-1);
      const total = byId("manage-total");
      total.replaceChildren(element("b", "", used.endsWith(" " + unit) ? used.slice(0, -unit.length - 1) : used),
        " of " + available, ...(plan.over ? [" · ", element("span", "over", bytes(plan.over) + " over")] :
          choice.kind === "recommended" ? [" · the recommended library"] : []));
      byId("reset-recommended").hidden = choice.kind === "recommended" && choice.split === splitDefault;
      byId("make-fit").hidden = !plan.over;
      byId("split-files").checked = choice.split;
      byId("split-files").disabled = requiresSplit;
      byId("split-note").hidden = !requiresSplit;
      let count = 0;
      for (const category of listCategories) {
        const nodes = groupNodes.get(category.id);
        const rows = resources.filter(resource => themeOf(model, resource) === category.id);
        const visible = rows.filter(row => matching(row).length);
        count += visible.length;
        nodes.details.hidden = Boolean(query) && !visible.length;
        nodes.details.open = query ? Boolean(visible.length) : open.has(category.id);
        const included = rows.filter(row => state.items[row.id].included).length;
        const used = plan.assets.filter(asset => (plan.theme.get(asset.id) || baseTheme.get(asset.id)) === category.id);
        nodes.size.textContent = bytes(sum(used)) + " · " + included + " of " + rows.length;
        for (const resource of rows) renderCard(resource, cards.get(resource.id));
      }
      byId("no-collections").hidden = count > 0;
      byId("include-filtered").disabled = count === 0;
      byId("exclude-filtered").disabled = count === 0;
      byId("storage-lines").replaceChildren(...[
        ["Selected files", bytes(plan.used)], ["Space for search and the reader", bytes(plan.reserve)],
        ["Space available for files", bytes(Math.max(0, plan.limit))],
        ...plan.errors.map(message => ["Selection", message]),
        ...plan.result.incomplete.map(row => [title(model, row), row.reason])
      ].map(([key, text]) => {
        const row = element("tr"), label = element("th", "", key);
        label.scope = "row";
        row.append(label, element("td", "", text));
        return row;
      }));
      const held = byId("held-updates");
      held.hidden = attention.length === 0;
      held.replaceChildren(...attention.map(({name, replace}) => {
        const row = element("p", "", name + " needs room for a second copy. ");
        if (replace) row.append(button("Replace in place", replace));
        return row;
      }));
      renderCommands();
    }

    function renderCommands() {
      if (browser || !byId("target-path")) return;
      const target = byId("target-path").value, shell = byId("shell").value;
      for (const id of ["plan", "build"]) {
        let command = "";
        if (target.trim()) {
          try { command = root.OWLPlanner.command(model, state, {target, shell, plan: id === "plan"}); }
          catch (error) { byId("copy-feedback").textContent = error.message; }
        }
        byId(id + "-command").value = command;
        byId("copy-" + id).disabled = !command;
      }
      byId("build-help").textContent = !target.trim() ? "Enter the library folder to get the commands." :
        byId("build-command").value ? "Keep this computer awake and the drive connected while the command runs." :
          "See storage accounting under Advanced or choose to build with the files available now.";
    }

    function fit() {
      const weakest = resources.filter(resource => state.items[resource.id].included).map(resource => {
        const chosen = members(resource, state.items[resource.id]).map(id => assetsById.get(id));
        const tier = ["CRITICAL", "USEFUL", "NONESSENTIAL"].indexOf(resource.utility_tier);
        return {resource, priority: tier < 0 ? 3 : tier, level: Math.min(...chosen.map(asset => asset?.selection?.level ?? Infinity)),
          rank: Math.min(...chosen.map(asset => asset?.selection?.rank ?? Infinity))};
      }).sort((a, b) => b.priority - a.priority || b.level - a.level || b.rank - a.rank);
      for (const {resource} of weakest) {
        if (!plan.over) break;
        apply(resource, {included: false});
        plan = measure();
      }
      refresh({changed: true});
    }

    function bulk(included) {
      let count = 0;
      for (const resource of resources) {
        for (const id of matching(resource).filter(download)) { setFile(resource, id, included); count++; }
      }
      byId("bulk-feedback").textContent = (included ? "Included " : "Excluded ") + count + " matching files.";
      refresh({changed: true});
    }

    for (const category of listCategories) {
      const details = element("details", "cat");
      details.dataset.category = category.id;
      details.style.setProperty("--c", "var(--c-" + category.id + ")");
      const summary = element("summary");
      const name = element("span", "name");
      name.append(element("b", "", category.name), element("span", "", category.blurb));
      const size = element("span", "size");
      summary.append(element("span", "dot"), name, size);
      summary.addEventListener("click", () => {
        if (details.open) open.delete(category.id); else open.add(category.id);
      });
      details.append(summary);
      for (const resource of resources.filter(row => themeOf(model, row) === category.id)) {
        const card = makeCard(resource);
        cards.set(resource.id, card);
        details.append(card.card);
      }
      groupNodes.set(category.id, {details, size});
      byId("categories").append(details);
    }

    byId("collection-search").addEventListener("input", event => {
      query = event.target.value.trim().toLowerCase();
      render();
    });
    byId("split-files").addEventListener("change", event => {
      choice = {...choice, split: event.target.checked};
      refresh({changed: true});
    });
    byId("reset-recommended").addEventListener("click", event => {
      event.preventDefault();
      state = structuredClone(baseline);
      state.allowIncomplete = allowed;
      const {limitBytes, retainedFiles} = choice;
      choice = {kind: "recommended", split: splitDefault,
        ...(limitBytes ? {limitBytes} : {}), ...(retainedFiles ? {retainedFiles} : {})};
      refresh({changed: true});
    });
    if (slider) {
      slider.addEventListener("input", () => {
        const value = slider.valueAsNumber;
        const nearest = limitStops.reduce((best, stop) => Math.abs(stop - value) < Math.abs(best - value) ? stop : best);
        changeLimit(nearest);
      });
      slider.addEventListener("change", commitLimit);
      slider.addEventListener("keydown", event => {
        const steps = {ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -5, PageUp: 5};
        const last = limitStops.length - 1;
        const current = limitStops.indexOf(currentBudget());
        let next = event.key === "Home" ? 0 : event.key === "End" ? last : undefined;
        if (Object.hasOwn(steps, event.key)) {
          if (current >= 0) next = current + steps[event.key];
          else {
            const higher = limitStops.findIndex(stop => stop > currentBudget());
            const insertion = higher === -1 ? limitStops.length : higher;
            next = insertion + steps[event.key] - Number(steps[event.key] > 0);
          }
        }
        if (next === undefined) return;
        event.preventDefault();
        changeLimit(limitStops[Math.max(0, Math.min(last, next))]);
        commitLimit();
      });
      byId("manage-all").addEventListener("click", event => {
        event.preventDefault();
        changeLimit(ceiling);
        commitLimit();
        slider.focus({preventScroll: true});
      });
    }
    byId("make-fit").addEventListener("click", fit);
    byId("include-filtered").addEventListener("click", () => bulk(true));
    byId("exclude-filtered").addEventListener("click", () => bulk(false));
    byId("diagnostics-link").addEventListener("click", onDiagnostics);
    if (!browser) {
      for (const id of ["target-path", "shell"]) byId(id).addEventListener("input", renderCommands);
      byId("allow-incomplete").addEventListener("change", event => {
        allowed = state.allowIncomplete = event.target.checked;
        refresh();
      });
      for (const id of ["plan", "build"]) byId("copy-" + id).addEventListener("click", async () => {
        const command = byId(id + "-command");
        try {
          await navigator.clipboard.writeText(command.value);
          byId("copy-feedback").textContent = "Command copied.";
        } catch {
          command.select();
          byId("copy-feedback").textContent = "The command is selected. Use your keyboard to copy it.";
        }
      });
    }

    return {configure, amounts, groups, commitLimit,
      get hasRecommendation() { return fits(baseline); },
      minimumCapacity() {
        let low = 1, high = model.capacity_policy.min;
        while (low < high) {
          const mid = Math.floor((low + high) / 2);
          if (fits(recommended(mid))) high = mid;
          else low = mid + 1;
        }
        return high;
      },
      held(rows) { attention = rows; if (enabled) render(); },
      show({name, onBack, onDone, changes}) {
        enabled = true;
        const drive = Boolean(name);
        const back = byId("manage-back");
        back.hidden = !onBack;
        back.textContent = drive ? "‹ " + name : "‹ Back";
        back.onclick = onBack ? event => { event.preventDefault(); onBack(); } : null;
        document.querySelector(".brand").hidden = Boolean(onBack);
        byId("manage-heading").textContent = drive ? "What goes on " + name : "What goes on a drive";
        const sizes = byId("preview-sizes");
        sizes.hidden = drive || !model.capacity_policy;
        if (!sizes.hidden) sizesInto(sizes, chosenSize, size => {
          if (onSize) onSize(size);
          else {
            configure({capacityBytes: size * 1e9, size});
            [...sizes.children].forEach(chip => chip.setAttribute("aria-pressed",
              String(Number(chip.dataset.size) === size)));
          }
        });
        byId("manage").hidden = false;
        byId("manage-done").hidden = !drive;
        byId("manage-return").onclick = onDone;
        byId("manage-changes").textContent = changes || "No changes";
        render();
        if (onBack) byId("manage-heading").focus({preventScroll: true});
      },
      hide() {
        enabled = false;
        byId("manage").hidden = true;
        byId("manage-done").hidden = true;
        byId("manage-back").hidden = true;
        document.querySelector(".brand").hidden = false;
      }
    };
  }

  function how() {
    const opener = byId("how-link"), sheet = byId("how");
    opener.addEventListener("click", event => {
      event.preventDefault();
      sheet.showModal();
    });
    sheet.addEventListener("click", event => {
      if (event.target !== sheet) return;
      const {left, right, top, bottom} = sheet.getBoundingClientRect();
      if (event.clientX < left || event.clientX >= right || event.clientY < top || event.clientY >= bottom) sheet.close();
    });
    sheet.addEventListener("close", () => opener.focus({preventScroll: true}));
  }

  function offline(model) {
    how();
    const manage = create(model);
    manage.configure({capacityBytes: model.capacity_policy ? 64e9 : profileCapacity(model.profiles[0]), size: 64});
    manage.show({});
  }

  root.OWLManage = {create, offline, how, bytes, meter, element, sizesInto, title, link};
})(globalThis);
