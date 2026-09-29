"""Offline topic layout covers all selectable content and stays within its themes."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from owl.selector import make_model
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'),'Node required for offline topic layout')
class TopicMapTests(unittest.TestCase):
    def test_every_asset_and_collection_has_a_bounded_deterministic_topic_position(self):
        model=make_model(ROOT/'catalog/library.yaml',ROOT/'profiles',ROOT/'catalog/resources.yaml')
        code='''const fs=require('fs');eval(fs.readFileSync(process.argv[1],'utf8'));
const model=JSON.parse(fs.readFileSync(0,'utf8'));
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
const asset=id=>model.assets.find(a=>a.id===id);
if(OWLTopicMap.primary(asset('usfs_ax_manual'),model.topic_verticals).vertical!=='trades')throw Error('Ax manual misplaced');
if(OWLTopicMap.primary(asset('openstax_physics'),model.topic_verticals).vertical!==OWLTopicMap.primary(asset('openstax_university_physics_volume_1'),model.topic_verticals).vertical)throw Error('Related school/college physics separated by priority');
'''
        result=subprocess.run([shutil.which('node'),'-e',code,str(ROOT/'src/owl/templates/selector-map.js')],input=json.dumps(model),text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
