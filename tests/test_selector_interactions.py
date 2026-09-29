"""Selection UI integration: real handlers, offline DOM double, no downloads."""
import shutil
import subprocess
import unittest
from pathlib import Path
from owl.selector import make_model, render_selector

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node required for selector UI checks')
class SelectorInteractionTests(unittest.TestCase):
    def test_drilldown_pseudoindex_search_and_filtered_bulk_selection(self):
        model = make_model(ROOT/'catalog/library.yaml', ROOT/'profiles', ROOT/'catalog/resources.yaml')
        code = r'''
const fs=require('fs'),html=fs.readFileSync(0,'utf8'),nodes=new Map();
function node(){return {children:[],dataset:{},style:{},attributes:{},handlers:{},value:'',hidden:false,disabled:false,
 classList:{toggle(){}},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
 setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,v){this.handlers[k]=v;}};}
for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
 const item=node();item.hidden=/\bhidden\b/.test(match[0]);item.value=(match[0].match(/\bvalue="([^"]*)"/)||[])[1]||'';nodes.set(match[1],item);
}
const get=id=>nodes.get(id),assert=(v,msg)=>{if(!v)throw Error(msg);};
get('owl-model').textContent=html.match(/<script id="owl-model"[^>]*>([\s\S]*?)<\/script>/)[1];
get('shell').value='posix';
globalThis.document={getElementById:get,createElement:node,createElementNS:node,createTextNode:text=>({textContent:text})};
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
 eval(script[1]);
 if(globalThis.OWLPlanner&&!globalThis.savedResolve){globalThis.savedResolve=OWLPlanner.resolve;OWLPlanner.resolve=(...args)=>{globalThis.lastReport=savedResolve(...args);return lastReport;};}
}
assert(get('fatal').hidden,get('fatal').textContent);
const cards=()=>get('resources').children,shown=()=>cards().filter(c=>!c.hidden);
const checked=c=>c.children[0].children[0].checked;
const selections=()=>Object.fromEntries(cards().map(c=>[c.dataset.resourceId,checked(c)]));
const click=id=>get(id).handlers.click(), search=value=>{get('resource-filter').value=value;get('resource-filter').handlers.input();};
const svgItems=()=>get('topic-map').children[0].children;
const clearFilters=()=>{search('');get('priority-filter').value='';get('priority-filter').handlers.change();get('selected-only').checked=false;get('selected-only').handlers.change();if(!get('topic-breadcrumbs').hidden)get('topic-breadcrumbs').children[0].handlers.click();};
const drill=(attr,value,key)=>{const n=svgItems().find(n=>n.attributes[attr]===value);assert(n,'Missing '+value);key?n.handlers.keydown({key,preventDefault(){}}):n.handlers.click();};
// Establish a partial-selection scenario independently of preset membership.
search('seed-processing-quality');click('exclude-shown');
const before=new Set(lastReport.selectedAssetIds);
search('seed drying');
assert(shown().length===1&&shown()[0].dataset.resourceId==='seed-processing-quality','Pseudoindex alias failed');
click('include-shown');
let after=new Set(lastReport.selectedAssetIds);
assert(after.has('fao_seed_processing')&&!after.has('fao_seed_quality'),'Search included an unmatched file');
for(const id of before)assert(after.has(id),'Search removed an unrelated file');
assert(get('build-command').value.includes('--resource-assets seed-processing-quality=fao_seed_processing'),'Exact file selection absent from command');
clearFilters();drill('data-map-theme','school','Enter');
const geometry=()=>svgItems().filter(n=>n.attributes['data-map-subtopic']).map(n=>[n.attributes['data-map-subtopic'],n.children[0].attributes]);
const positions=JSON.stringify(geometry());
drill('data-map-subtopic','topic:mathematics',' ');
assert(JSON.stringify(geometry())===positions,'Subtopic changed geometry');
assert(svgItems().find(n=>n.attributes['data-map-subtopic']==='topic:mathematics').attributes['aria-pressed']==='true','Subtopic not highlighted');
const storageSegments=()=>get('topic-storage-bars').children.flatMap(row=>row.children[1].children[0].children);
assert(get('topic-storage-bars').children.length===1,'Leaf storage chart leaked another subtopic');
const segment=storageSegments()[0];
assert(segment&&segment.handlers.click,'Leaf segments are not interactive');
segment.handlers.click();
const selectedFile=JSON.parse(get('owl-model').textContent).assets.find(a=>a.id===segment.dataset.storageAsset);
assert(get('map-info').children[0].textContent===selectedFile.title,'Segment did not inspect its file');
assert(get('topic-storage-files').children.length===storageSegments().length,'Tiny files inaccessible through key');
search('biology');assert(shown().length===0&&get('include-shown').disabled,'Math topic leaked biology search');
assert(get('topic-storage-bars').children.length===0&&!get('topic-storage-empty').hidden,'Storage ignored empty intersection');
assert(get('visible-count').textContent.startsWith('0 assets'),'Map and list filters disagree');
search('');get('priority-filter').value='USEFUL';get('priority-filter').handlers.change();
get('selected-only').checked=true;get('selected-only').handlers.change();
const previous=new Set(lastReport.selectedAssetIds);
const targets=new Set(shown().flatMap(c=>c.children[1].children.find(n=>n.dataset.role==='matching-assets').children.map(n=>n.dataset.assetId)));
assert(targets.size>0,'No filtered math targets');
click('exclude-shown');after=new Set(lastReport.selectedAssetIds);
for(const id of previous)assert(after.has(id)===!targets.has(id),'Filtered exclusion changed unrelated file '+id);
assert(shown().length===0&&get('include-shown').disabled,'Selected-only snapshot failed');
assert(!get('topic-storage-empty').hidden,'Exclusion left selected data in chart');
get('selected-only').checked=false;get('selected-only').handlers.change();
click('include-shown');after=new Set(lastReport.selectedAssetIds);
for(const id of previous)assert(after.has(id),'Reinclude lost original file '+id);
drill('data-map-subtopic','topic:mathematics');
assert(JSON.stringify(geometry())===positions,'Clearing subtopic changed geometry');
assert(svgItems().find(n=>n.attributes['data-map-subtopic']==='topic:mathematics').attributes['aria-pressed']==='false','Subtopic toggle did not clear');
clearFilters();search('archive-readers');click('exclude-shown');
assert(shown()[0].children[0].children[0].checked&&get('bulk-feedback').textContent.includes('required'),'Required reader removed');
clearFilters();click('exclude-shown');assert(lastReport.selectedAssetIds.length===0,'Unfiltered exclude failed');
click('include-shown');assert(cards().every(checked),'Unfiltered include failed');
search('does-not-match-anything-xyz');assert(shown().length===0&&get('include-shown').disabled,'Empty search failed');
assert(get('fatal').hidden,get('fatal').textContent);
'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=render_selector(model), encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
