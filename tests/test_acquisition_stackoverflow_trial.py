"""Shared source expansion remains owned, pinned and separate from content approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition import capture, sevenzip, stackoverflow_trial as trial
from owl.safety import SafetyError
from tests.process_fixtures import python_script_tool


class SharedStackOverflowTests(unittest.TestCase):
    def setUp(self):
        from tests.test_acquisition_corpus import CorpusTests
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.staging=self.root/'capture'
        corpus=CorpusTests();corpus.setUp();self.addCleanup(corpus.doCleanups);self.corpus=corpus
        payloads={}
        sources=[]
        for role,name in trial.ROLES.items():
            identity='dump_'+role;source=self.root/(identity+'.7z')
            if getattr(self,'real_executable',None):
                xml=self.root/name;xml.write_bytes(corpus.sources[role].read_bytes())
                sevenzip._run([str(self.real_executable),'a','-t7z','-mx=1','-mmt=1','-bd','-y','--',str(source),str(xml)],
                    limit=65536,timeout=20)
            else:source.write_bytes(b'7z\xbc\xaf\x27\x1c'+role.encode())
            payloads[identity]={'path':name,'data':corpus.sources[role].read_text(encoding='utf-8')}
            sources.append(dict(id=identity,input_role=role,expected_member=name,resource_ids=['stackoverflow-durable','stackoverflow-legacy'],
                source_url=source.as_uri(),version='synthetic-1',size_bytes=source.stat().st_size,sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                metadata_evidence=[{'url':'https://publisher.invalid/metadata','sha256':'a'*64}]))
        manifest={'schema_version':1,'kind':'acquisition','id':'shared-fixture','profile':'full-1tb','sources':sources,
            'budget':{'download_bytes':sum(s['size_bytes'] for s in sources),'expanded_bytes':0,'preview_bytes':0,'scratch_bytes':0,'cache_bytes':0}}
        self.manifest=self.root/'manifest.json';self.manifest.write_text(json.dumps(manifest))
        capture.capture(self.manifest,self.staging,allow_local=True,reserve_bytes=0,progress=lambda _:None)
        executable=self.root/'fixture7z'
        executable.write_text('#!'+sys.executable+'\nimport sys,pathlib\npayloads='+repr(payloads)+'\n'+
            'row=payloads[pathlib.Path(sys.argv[-1] if sys.argv[1]=="l" else sys.argv[-2]).name]\n'+
            'if sys.argv[1]=="l": print("Path = "+row["path"]+"\\nSize = "+str(len(row["data"].encode()))+"\\nEncrypted = -\\n")\n'+
            'else: sys.stdout.buffer.write(row["data"].encode())\n', encoding='utf-8')
        executable.chmod(0o700)
        self.tool=patch.object(sevenzip,'preflight',return_value=str(getattr(self,'real_executable',None) or executable))
        self.tool.start();self.addCleanup(self.tool.stop)
        if not getattr(self,'real_executable',None):
            self.enterContext(python_script_tool(executable))
        self.inspection=trial.inspect(self.staging,progress=lambda _:None)
        self.inspection_path=self.root/'inspection.json';self.inspection_path.write_text(json.dumps(self.inspection))
        self.options=dict(expanded_bytes=self.inspection['expanded_bytes'],scratch_bytes=8_000_000,
                          preview_bytes=100_000,budget_bytes=20_000_000,reserve_bytes=0,progress=lambda _:None)

    def expand(self):
        return trial.expand(self.staging,self.inspection_path,**self.options)

    def templates(self,identity='durable'):
        shared=capture._read(Path(self.expand()['receipt']))
        recipe=deepcopy(self.corpus.recipe)
        recipe.update(id=identity,resource_id='stackoverflow-durable',version='2',source_asset_ids=list(shared['input_roles'].values()),
                      output_asset_ids=['question_10'],build_input_extractions=shared['build_input_extractions'])
        recipe['selection']['input_roles']=shared['input_roles']
        recipe['review']={'status':'pending','evidence':[]};recipe['blockers']=[]
        output={**self.corpus.output,'generation':{'recipe_id':identity,'question_id':10},'format':'html','size_bytes':None,'sha256':None}
        rp=self.root/(identity+'-recipe.json');rp.write_text(json.dumps(recipe))
        ap=self.root/(identity+'-assets.json');ap.write_text(json.dumps({'assets':[output]}))
        return rp,ap,Path(self.expand()['receipt'])

    def test_measured_shared_inputs_reuse_full_pins_and_reject_changed_xml(self):
        result=self.expand();receipt=Path(result['receipt'])
        self.assertFalse(result['content_ready'])
        manifest,receipts=capture.load_capture_sources(self.staging)
        shared=trial.verified_shared(self.staging,receipt,manifest,receipts)
        self.assertEqual(len(shared['expanded_sources']),4)
        with patch.object(sevenzip,'_run',wraps=sevenzip._run) as run:self.expand()
        self.assertEqual(run.call_count,4) # listings only; completed XML is reused
        row=shared['expanded_sources'][0];(self.staging/row['relative_path']).write_text('changed')
        with self.assertRaisesRegex(SafetyError,'whole-file pin'):
            trial.verified_shared(self.staging,receipt,manifest,receipts)

    def test_candidate_selection_is_cached_and_not_content_approval(self):
        receipt=Path(self.expand()['receipt'])
        first=trial.select(self.staging,receipt,cache_dir=self.root/'candidate-cache',limit=10)
        self.assertFalse(first['content_ready'])
        self.assertEqual(first['corpus_version'],2)
        self.assertEqual([row['id'] for row in first['candidates']],[10])
        from owl.acquisition import corpus
        with patch.object(corpus,'xml_rows',side_effect=AssertionError('must reuse cached metadata')):
            self.assertTrue(trial.select(self.staging,receipt,cache_dir=self.root/'candidate-cache',limit=10)['cache_hit'])

    def test_shared_phase_rejects_underbudget_before_expansion(self):
        with patch.object(sevenzip,'observe_members',side_effect=AssertionError('must not extract')),self.assertRaisesRegex(SafetyError,'measured allowance'):
            trial.expand(self.staging,self.inspection_path,**{**self.options,'expanded_bytes':1})
        changed=deepcopy(self.inspection);changed['xml_bytes']=0;self.inspection_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(SafetyError,'accounting changed'):self.expand()

    def test_two_previews_share_one_expansion_and_review_reverifies_it(self):
        first=None
        for identity in ('durable','legacy-preview'):
            recipe,assets,receipt=self.templates(identity)
            with patch.object(sevenzip,'observe_members',side_effect=AssertionError('preview must reuse XML')):
                report=capture.preview(self.staging,recipe,assets,shared_expansion=receipt,
                    expanded_bytes=self.options['expanded_bytes'],scratch_bytes=8_000_000,preview_bytes=100_000,
                    reserve_bytes=0,budget_bytes=20_000_000,progress=lambda _:None)
            first=first or report
        self.assertEqual(len(list((self.staging/'previews').glob('*/expanded'))),1)
        result=capture.review(self.staging,Path(first['candidate_fragment']),evidence=['Synthetic full source/output inspection'])
        self.assertFalse(result['content_ready'])

    def test_shared_preview_rejects_unbound_allowlist_and_changed_source_receipt(self):
        recipe,assets,receipt=self.templates()
        changed=json.loads(recipe.read_text());changed['build_input_extractions'][0]['members'][0]['sha256']='0'*64
        recipe.write_text(json.dumps(changed))
        with self.assertRaisesRegex(SafetyError,'complete pinned archive allowlist'):
            capture.preview(self.staging,recipe,assets,shared_expansion=receipt,
                expanded_bytes=self.options['expanded_bytes'],scratch_bytes=8_000_000,preview_bytes=100_000,
                reserve_bytes=0,budget_bytes=20_000_000,progress=lambda _:None)
        manifest,receipts=capture.load_capture_sources(self.staging)
        altered=deepcopy(receipts);altered[0]['sha256']='0'*64
        with self.assertRaisesRegex(SafetyError,'source binding changed'):
            trial.verified_shared(self.staging,receipt,manifest,altered)


if __name__=='__main__':unittest.main()
