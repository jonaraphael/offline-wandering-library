from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from owl.acquisition.zip_localized import render, rewrite_html, validate_recipe
from owl.safety import SafetyError


class LocalizedZipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'source.zip'
        self.body=(b'<!doctype html>\r\n<html><script>const sample="<a href=\"/license.html#Terms\">";</script>'
            b'<body><h1>Caf\xc3\xa9</h1><table><tr><td>42</td></tr></table><img src="pic.png">'
            b'<a class="credit" href=\'/license.html#Terms\'>Original license</a></body></html>')
        self.files={'manual/guide.html':self.body,'manual/license.html':b'<h1 id="Terms">Full original license</h1>','manual/pic.png':b'original illustration'}
        with ZipFile(self.source,'w') as archive:
            for name,data in self.files.items():archive.writestr(name,data)
        self.assets={'source':{'id':'source','size_bytes':self.source.stat().st_size,'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}}
        members=[]
        for index,(name,data) in enumerate(self.files.items()):
            identity='output'+str(index);self.assets[identity]={'id':identity,'destination':'REFERENCE/'+name}
            members.append({'asset_id':identity,'path':name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'rewrites':[]})
        members[0]['rewrites']=[{'attribute':'href','from':'/license.html#Terms','target_member':'manual/license.html','expected_count':1}]
        self.recipe={'id':'local','source_asset_ids':['source'],'output_asset_ids':['output0','output1','output2'],'selection':{'source_asset_id':'source','members':members}}

    def test_complete_preservation_except_declared_attribute_span(self):
        outputs=render(self.recipe,{'source':self.source},self.assets,self.root/'output')
        expected=self.body.replace(b"href='/license.html#Terms'",b"href='license.html#Terms'")
        self.assertEqual(outputs['output0'].read_bytes(),expected)
        self.assertEqual(outputs['output1'].read_bytes(),self.files['manual/license.html'])
        self.assertEqual(outputs['output2'].read_bytes(),self.files['manual/pic.png'])

    def test_changed_source_and_member_pin_rejected(self):
        self.assets['source']['sha256']='0'*64
        with self.assertRaisesRegex(SafetyError,'SHA-256'):
            render(self.recipe,{'source':self.source},self.assets,self.root/'out')
        self.assets['source']['sha256']=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.recipe['selection']['members'][0]['sha256']='0'*64
        with self.assertRaisesRegex(SafetyError,'member SHA256'):
            render(self.recipe,{'source':self.source},self.assets,self.root/'out')

    def test_changed_count_unquoted_link_and_unlisted_target_rejected(self):
        member=deepcopy(self.recipe['selection']['members'][0]);member['rewrites'][0]['expected_count']=2
        with self.assertRaisesRegex(SafetyError,'count changed'):rewrite_html(self.body,member)
        member['rewrites'][0]['expected_count']=1
        with self.assertRaisesRegex(SafetyError,'unquoted'):
            rewrite_html(b'<a href=/license.html#Terms>License</a>',member)
        member['rewrites'][0]['target_member']='manual/absent.html'
        recipe=deepcopy(self.recipe);recipe['selection']['members'][0]=member
        with self.assertRaisesRegex(SafetyError,'Invalid counted'):validate_recipe(recipe,self.assets)

    def test_partial_package_and_path_relocation_rejected(self):
        recipe=deepcopy(self.recipe);recipe['selection']['members'].pop();recipe['output_asset_ids'].pop()
        with self.assertRaisesRegex(SafetyError,'complete publisher'):
            render(recipe,{'source':self.source},self.assets,self.root/'out')
        self.assets['output2']['destination']='REFERENCE/other/pic.png'
        with self.assertRaisesRegex(SafetyError,'preserve package'):validate_recipe(self.recipe,self.assets)

    def test_output_writer_is_used_before_any_adapter_write(self):
        def denied(path,data):raise SafetyError('budget before write')
        with self.assertRaisesRegex(SafetyError,'budget before write'):
            render(self.recipe,{'source':self.source},self.assets,self.root/'out',output_writer=denied)
        self.assertFalse((self.root/'out').exists())

    def test_normal_build_roundtrip_and_changed_output_never_complete(self):
        from owl.build import build
        from owl.verify import verify_drive
        from owl.acquisition.runtime import Generator
        import json
        rendered=render(self.recipe,{'source':self.source},self.assets,self.root/'expected')
        base=dict(title='Publisher package fixture',category='reference',source_url=self.source.as_uri(),
            version='1',license='CC0',redistributable=True,required=True,profiles=['test'])
        original={**base,**self.assets['source'],'format':'zip','destination':'REFERENCE/source.zip','supporting_file':True}
        outputs=[{**base,**self.assets[identity],'format':'html' if path.suffix=='.html' else 'png',
            'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'supporting_file':path.suffix!='.html','generation':{'recipe_id':'local'}} for identity,path in rendered.items()]
        recipe={**self.recipe,'resource_id':'reference','adapter':'zip_localized','version':'1',
            'review':{'status':'approved','evidence':['complete bounded synthetic original']},'blockers':[],'workspace_bytes':1000000}
        catalog=self.root/'catalog.json'; catalog.write_text(json.dumps({'schema_version':1,'assets':[original,*outputs],'acquisition_recipes':[recipe]}))
        profiles=self.root/'profiles';profiles.mkdir()
        (profiles/'test.yaml').write_text(json.dumps({'id':'test','capacity_bytes':100000000,'reserve_bytes':100000,'search_budget_bytes':1000000}))
        target=self.root/'drive'
        def run():return build(target,catalog=catalog,profiles_dir=profiles,profile_name='test',allow_local=True,progress=lambda _:None)
        with patch.object(Generator,'_render',side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):run()
        self.assertFalse(json.loads((target/'LIBRARY/.owl/state.json').read_text())['complete'])
        with patch('owl.build.download',side_effect=AssertionError('verified source must be reused')):run()
        self.assertEqual(verify_drive(target,emit=lambda _:None)['FAILED'],0)
        self.assertEqual((target/'LIBRARY/REFERENCE/manual/guide.html').read_bytes(),rendered['output0'].read_bytes())
        with patch.object(Generator,'_render',side_effect=AssertionError('completed output must be reused')):run()
        # A wrong transformed pin cannot publish a completion manifest.
        outputs[0]['sha256']='0'*64
        catalog.write_text(json.dumps({'schema_version':1,'assets':[original,*outputs],'acquisition_recipes':[recipe]}))
        with self.assertRaisesRegex(SafetyError,'Generated output SHA-256/size'):
            build(self.root/'bad-drive',catalog=catalog,profiles_dir=profiles,profile_name='test',allow_local=True,progress=lambda _:None)
        self.assertFalse(json.loads((self.root/'bad-drive/LIBRARY/.owl/state.json').read_text())['complete'])


if __name__=='__main__':unittest.main()
