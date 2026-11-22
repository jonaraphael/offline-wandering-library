"""Selection UI integration: real handlers, offline DOM double, no downloads."""
import shutil
import subprocess
import unittest
from pathlib import Path
from owl.selector import make_model, render_selector

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node required for selector UI checks')
class SelectorInteractionTests(unittest.TestCase):
    def test_opening_source_template_links_to_generated_selector(self):
        code=r'''
const fs=require('fs'),html=fs.readFileSync(0,'utf8'),nodes=new Map();
const node=()=>({children:[],hidden:true,replaceChildren(...items){this.children=items;}});
globalThis.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:node};
document.getElementById('owl-model').textContent=html.match(/<script id="owl-model"[^>]*>([\s\S]*?)<\/script>/)[1];
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g))eval(script[1]);
const notice=nodes.get('fatal');
if(notice.hidden||notice.children[1].href!=='../../../SELECT.html')throw Error('Missing working-selector link');
if(globalThis.OWLPlanner)throw Error('Unbuilt engine executed');
'''
        result=subprocess.run([shutil.which('node'),'-e',code],
            input=(ROOT/'src/owl/templates/selector.html').read_text(),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_recommendation_view_customizing_search_and_bulk_selection(self):
        model = make_model(ROOT/'catalog/library.yaml', ROOT/'profiles', ROOT/'catalog/resources.yaml')
        code = r"""
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
globalThis.document={body:node(),getElementById:get,createElement:node,createTextNode:text=>({textContent:text})};
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
 eval(script[1]);
 if(globalThis.OWLPlanner&&!globalThis.savedResolve){globalThis.savedResolve=OWLPlanner.resolve;OWLPlanner.resolve=(...args)=>{globalThis.lastReport=savedResolve(...args);return lastReport;};}
}
assert(get('fatal').hidden,get('fatal').textContent);
const catalog=JSON.parse(get('owl-model').textContent);
const themes=()=>get('themes').children, themeOf=id=>themes().find(t=>t.dataset.theme===id);
const cards=()=>themes().flatMap(t=>t.children[1].children), shown=()=>cards().filter(c=>!c.hidden);
const card=id=>cards().find(c=>c.dataset.resourceId===id);
const checkbox=c=>c.children[0].children[0], checked=c=>checkbox(c).checked;
const files=c=>c.children[1].children.find(n=>n.dataset.role==='matching-assets').children;
const click=id=>get(id).handlers.click(), search=value=>{get('resource-filter').value=value;get('resource-filter').handlers.input();};
const selected=()=>new Set(lastReport.selectedAssetIds);

// The first view is the recommendation: only what is on the drive, no reader row.
assert(!get('planner').hidden&&document.body.dataset.stage==='plan','Planner not shown');
assert(themes().length===8,'Expected eight themes');
assert(shown().length>5&&shown().every(c=>c.dataset.included==='true'),'Recommendation view lists collections that are not included');
assert(!card('archive-readers'),'Required reader apps should not be a row');
assert(themes().every(t=>t.children[1].hidden),'Themes should start folded');
assert(get('knowledge-bytes').textContent.endsWith('GB')&&get('capacity').textContent==='of 16 GB drive','Summary total missing: '+get('capacity').textContent);
assert(get('storage-meter').children.length===get('legend').children.length&&get('legend').children.length>=8,'Meter and legend disagree');
assert(get('legend').children.some(li=>li.children[0].children[1].textContent==='Kiwix reader apps'),'Reader apps missing from the legend');
assert(get('reset-preset').hidden,'Reset offered before any change');
// The legend opens its theme.
const health=themeOf('health');
get('legend').children[0].children[0].handlers.click();
assert(!health.children[1].hidden&&health.children[0].children[1].attributes['aria-expanded']==='true','Legend did not open its theme');

// Customizing shows everything, with checkboxes.
click('customize');
const all=cards().length;
assert(shown().length===all&&all===catalog.resources.length-1,'Customize should list every collection');
assert(get('bulk').hidden,'Bulk actions shown without a filter');
// Establish a partial-selection scenario independently of preset membership.
search('seed-processing-quality');
assert(shown().length===1&&!get('bulk').hidden,'Collection id search failed');
click('exclude-shown');
const before=selected();
search('seed drying');
assert(shown().length===1&&shown()[0].dataset.resourceId==='seed-processing-quality','Pseudoindex alias failed');
click('include-shown');
let after=selected();
assert(after.has('fao_seed_processing')&&!after.has('fao_seed_quality'),'Search included an unmatched file');
for(const id of before)assert(after.has(id),'Search removed an unrelated file');
assert(get('build-command').value.includes('--resource-assets seed-processing-quality=fao_seed_processing'),'Exact file selection absent from command');
assert(!get('reset-preset').hidden,'Reset not offered after a change');
search('');

// A row unfolds to its files; one file can be toggled.
const seeds=card('seed-processing-quality');
seeds.children[0].children[3].handlers.click();
assert(!seeds.children[1].hidden&&files(seeds).length===2,'Row did not list its files');
const quality=files(seeds).find(li=>li.dataset.assetId==='fao_seed_quality');
quality.children[0].children[0].checked=true;quality.children[0].children[0].handlers.change();
assert(selected().has('fao_seed_quality'),'File checkbox did not add its file');

// View and priority filters narrow what bulk actions touch.
get('priority-filter').value='USEFUL';get('priority-filter').handlers.change();
click('view-in');
const previous=selected();
const targets=new Set(shown().flatMap(c=>{c.children[0].children[3].handlers.click();return files(card(c.dataset.resourceId)).map(n=>n.dataset.assetId);}));
assert(targets.size>0&&[...targets].every(id=>previous.has(id)),'On-drive view listed files that are not selected');
click('exclude-shown');after=selected();
for(const id of previous)assert(after.has(id)===!targets.has(id),'Filtered removal changed unrelated file '+id);
assert(shown().length===0&&get('include-shown').disabled&&!get('no-results').hidden,'Empty view not reported');
click('view-out');
assert(shown().length>0,'Not-included view is empty');
click('view-all');click('include-shown');after=selected();
for(const id of previous)assert(after.has(id),'Adding back lost original file '+id);
get('priority-filter').value='';get('priority-filter').handlers.change();

// A theme checkbox adds or removes the whole theme.
const culture=themeOf('culture'), cultureIds=new Set(catalog.resources.filter(r=>cards().some(c=>c.dataset.resourceId===r.id&&culture.children[1].children.includes(c))).flatMap(r=>r.asset_ids));
const cultureCheck=culture.children[0].children[0];
cultureCheck.checked=false;cultureCheck.handlers.change();
assert(![...selected()].some(id=>cultureIds.has(id)),'Theme checkbox left files selected');
cultureCheck.checked=true;cultureCheck.handlers.change();
assert(culture.children[1].children.every(checked),'Theme checkbox did not add its collections');

// Bulk actions on the unfiltered list keep the required reader apps.
click('exclude-shown');
assert(lastReport.selectedAssetIds.length===4&&lastReport.selectedAssetIds.every(id=>id.startsWith('kiwix_')),'Unfiltered removal failed');
assert(get('bulk-feedback').textContent.startsWith('Removed '),'No feedback after bulk removal');
click('include-shown');assert(cards().every(checked),'Unfiltered add failed');
search('does-not-match-anything-xyz');assert(shown().length===0&&get('include-shown').disabled,'Empty search failed');
search('');

// Editions name their size and mark the recommended one.
click('reset-preset');
const wikipedia=card('wikipedia-en'), edition=wikipedia.children[1].children[0].children[1];
assert(edition.children.length>=4&&edition.children.some(o=>o.textContent.includes('(recommended)')),'Edition choices missing');
edition.value='nopic';edition.handlers.change();
assert(selected().has('wikipedia_en_nopic')&&get('plan-command').value.includes('--edition wikipedia-en=nopic'),'Edition change missing from command');

// Leaving customize returns to the on-drive view.
click('customize');
assert(shown().every(c=>c.dataset.included==='true'),'Recommendation view kept unselected collections');
assert(get('fatal').hidden,get('fatal').textContent);
const capacity=get('capacity-gb');
capacity.value='78.55';
capacity.checkValidity=()=>true;
get('custom-capacity').handlers.submit({preventDefault(){}});
assert(get('plan-command').value.includes('--capacity-bytes 78550000000'),'Custom capacity missing from CLI handoff');
assert(lastReport.selectedAssetIds.includes('wikimed_en'),'Custom recommendation lost the critical collection');
assert(get('capacity').textContent==='of 78.5 GB drive'||get('capacity').textContent==='of 78.6 GB drive','Custom size not shown: '+get('capacity').textContent);
"""
        result = subprocess.run([shutil.which('node'), '-e', code], input=render_selector(model), encoding='utf-8', capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
