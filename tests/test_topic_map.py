"""Offline topic layout covers all selectable content and stays within its themes."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from owl.selector import make_model, render_selector
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'),'Node required for offline topic layout')
class TopicMapTests(unittest.TestCase):
    def test_every_asset_and_collection_has_a_bounded_deterministic_topic_position(self):
        model=make_model(ROOT/'catalog/library.yaml',ROOT/'profiles',ROOT/'catalog/resources.yaml')
        code='''const fs=require('fs');eval(fs.readFileSync(process.argv[1],'utf8'));
const model=JSON.parse(fs.readFileSync(0,'utf8'));
if(!OWLTopicMap.available(model))throw Error('Production topic map unavailable');
for(const mode of ['assets','collections']) {
 const layout=OWLTopicMap.layout(model,mode), again=OWLTopicMap.layout(model,mode);
 if(JSON.stringify(layout)!==JSON.stringify(again))throw Error('Unstable layout');
 const records=mode==='assets'?model.assets:model.resources;
 if(new Set(layout.nodes.map(n=>n.id)).size!==records.length)throw Error('Missing or duplicate dots');
 for(const node of layout.nodes) {
  const theme=model.topic_verticals.find(v=>v.id===node.vertical);
  if(!theme||!theme.domains.includes(node.domain))throw Error('Incorrect theme');
  if(Math.hypot(node.x-theme.x,node.y-theme.y)+node.r>theme.radius)throw Error('Outside theme: '+node.id);
 }
}
for(const theme of model.topic_verticals) {
 const focused=OWLTopicMap.layout(model,'assets',{vertical:theme.id});
 const expected=model.assets.filter(a=>OWLTopicMap.primary(a,model.topic_verticals).vertical===theme.id);
 if(focused.nodes.length!==expected.length)throw Error('Theme membership mismatch');
 for(const cluster of focused.clusters) {
  const scope={vertical:theme.id,domain:cluster.domain},leaf=OWLTopicMap.layout(model,'assets',scope);
  if(!leaf.nodes.length||leaf.nodes.some(n=>!OWLTopicMap.matches(n.record,model.topic_verticals,scope)))throw Error('Leaf leaked another topic');
 }
 for(const n of focused.nodes)if(Math.hypot(n.x-475,n.y-425)+n.r>390)throw Error('Outside zoomed theme');
}
const asset=id=>model.assets.find(a=>a.id===id);
if(OWLTopicMap.primary(asset('usfs_ax_manual'),model.topic_verticals).vertical!=='trades')throw Error('Ax manual misplaced');
if(OWLTopicMap.primary(asset('openstax_physics'),model.topic_verticals).vertical!==OWLTopicMap.primary(asset('openstax_university_physics_volume_1'),model.topic_verticals).vertical)throw Error('Related school/college physics separated by priority');
for(const collection of ['assets','resources']) {
 for(const metadata of [{knowledge_domains:[]},{knowledge_domains:['unknown-domain']},{utility_tier:undefined}]) {
  const custom=JSON.parse(JSON.stringify(model));
  Object.assign(custom[collection][0],metadata);
  if(OWLTopicMap.available(custom))throw Error('Map enabled with incomplete '+collection+' metadata');
 }
}
'''
        result=subprocess.run([shutil.which('node'),'-e',code,str(ROOT/'src/owl/templates/selector-map.js')],input=json.dumps(model),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_custom_catalog_without_topic_tags_keeps_list_and_commands_usable(self):
        from test_core import Fixture
        fixture = Fixture()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        resources = fixture.root / 'resources.yaml'
        resources.write_text(json.dumps({'schema_version': 1, 'resources': [
            {'id': 'core', 'title': 'Core', 'status': 'ready', 'target_bytes': len(fixture.data),
             'asset_ids': ['fixture']}]}))
        model = make_model(fixture.catalog, fixture.profiles, resources, allow_local=True)
        # Run the generated UI and its real click handlers with a small DOM
        # double. This checks the view transition as well as the layout gate.
        code = r'''
const fs=require('fs'), html=fs.readFileSync(0,'utf8'), nodes=new Map();
function node() {
 return {children:[],dataset:{},style:{},attributes:{},handlers:{},value:'',hidden:false,disabled:false,
  classList:{toggle(){}},append(...items){this.children.push(...items);},
  replaceChildren(...items){this.children=items;},
  setAttribute(key,value){this.attributes[key]=value;},
  addEventListener(event,handler){this.handlers[event]=handler;}};
}
for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
 const item=node(), tag=match[0];
 item.hidden=/\bhidden\b/.test(tag);
 item.value=(tag.match(/\bvalue="([^"]*)"/)||[])[1]||'';
 nodes.set(match[1],item);
}
const get=id=>{if(!nodes.has(id))throw Error('Unknown element '+id);return nodes.get(id);};
get('owl-model').textContent=html.match(/<script id="owl-model"[^>]*>([\s\S]*?)<\/script>/)[1];
get('shell').value='posix';get('map-level').value='assets';
globalThis.document={getElementById:get,createElement:node,createTextNode:text=>({textContent:text})};
for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g))eval(script[1]);
if(!get('fatal').hidden)throw Error(get('fatal').textContent);
if(!get('map-view').disabled||get('map-unavailable').hidden)throw Error('Missing map explanation');
if(get('resources').hidden||get('resources').children.length!==1)throw Error('List unavailable');
get('map-view').handlers.click();
if(get('resources').hidden||!get('map-panel').hidden)throw Error('Unsupported map hid the list');
if(!get('plan-command').value||!get('build-command').value)throw Error('Commands unavailable');
const card=get('resources').children[0], checkbox=card.children[0].children[0];
checkbox.checked=false;checkbox.handlers.change();
if(!get('fatal').hidden)throw Error(get('fatal').textContent);
if(card.dataset.included!=='false'||!get('plan-command').value)throw Error('List cannot change selection');
'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=render_selector(model),
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
