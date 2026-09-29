import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for browser fragment checks')
class ManualLinkTests(unittest.TestCase):
    def test_image_decode_wait_preserves_lazy_attributes_and_never_hides_failures(self):
        script=Path(__file__).resolve().parents[1]/'scripts/manual_link_checks.cjs'
        code='const {settleImages}=require('+json.dumps(str(script))+');'+'''
        const assert=require('node:assert/strict');
        function image(loading,behavior){return {loading,complete:false,naturalWidth:0,
          getAttribute(){return this.loading},setAttribute(k,v){this.loading=v},removeAttribute(){this.loading=null},
          async decode(){assert.equal(this.loading,'eager');await behavior(this);}};}
        (async()=>{
          const delayed=image('lazy',async i=>{await new Promise(r=>setTimeout(r,5));i.complete=true;i.naturalWidth=20;});
          const broken=image(null,async i=>{i.complete=true;throw Error('bad bytes');});
          assert.deepEqual(await settleImages({images:[delayed,broken]},100),{images:2,timed_out:false,failed:1});
          assert.equal(delayed.loading,'lazy');assert.equal(broken.loading,null);
          const stalled=image('lazy',()=>new Promise(()=>{}));
          assert.deepEqual(await settleImages({images:[stalled]},5),{images:1,timed_out:true,failed:1});
          assert.equal(stalled.loading,'lazy');
        })().catch(e=>{console.error(e);process.exitCode=1});
        '''
        result=subprocess.run([shutil.which('node'),'-e',code],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_empty_top_named_and_encoded_targets_but_not_missing_or_invalid(self):
        script=Path(__file__).resolve().parents[1]/'scripts/manual_link_checks.cjs'
        code='const {brokenAnchors,hasReadableContent}=require('+json.dumps(str(script))+');'+'''
        const assert=require('node:assert/strict');
        const hrefs=['#','#top','#TOP','#a%20b','#legacy','#missing','#%zz','#form-name'];
        const document={
          querySelectorAll:()=>hrefs.map(href=>({getAttribute:()=>href})),
          getElementById:value=>value==='a b'?{}:null,
          getElementsByName:value=>value==='legacy'?[{tagName:'A'}]:value==='form-name'?[{tagName:'INPUT'}]:[]
        };
        assert.deepEqual(brokenAnchors(document),['#missing','#%zz','#form-name']);
        assert.equal(hasReadableContent({title:'Complete short API',textLength:24,visibleGraphicCount:0}),true);
        assert.equal(hasReadableContent({title:'Empty page',textLength:0,visibleGraphicCount:0}),false);
        assert.equal(hasReadableContent({title:'Syntax diagram',textLength:0,visibleGraphicCount:1}),true);
        '''
        result=subprocess.run([shutil.which('node'),'-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
