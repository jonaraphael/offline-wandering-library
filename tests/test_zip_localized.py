from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from owl.acquisition.zip_localized import render, rewrite_member, validate_recipe
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
        with self.assertRaisesRegex(SafetyError,'count changed'):rewrite_member(self.body,member)
        member['rewrites'][0]['expected_count']=1
        with self.assertRaisesRegex(SafetyError,'unquoted'):
            rewrite_member(b'<a href=/license.html#Terms>License</a>',member)
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

    def test_fixed_stylesheet_append_retains_original_bytes_and_rejects_other_targets(self):
        from owl.acquisition.zip_localized import STYLESHEET_PATCHES
        original=b'/* Publisher notice */\nbody { color: black; }'
        member={'path':'manual/_static/pydoctheme.css','stylesheet_patch':'python-index-wrap-v1'}
        result=rewrite_member(original,member)
        self.assertEqual(result,original+STYLESHEET_PATCHES['python-index-wrap-v1'])
        with self.assertRaisesRegex(SafetyError,'already contains'):rewrite_member(result,member)
        for wrong in ['manual/guide.html','manual/_static/other.css']:
            with self.assertRaisesRegex(SafetyError,'Invalid fixed'):rewrite_member(original,{**member,'path':wrong})
        with self.assertRaisesRegex(SafetyError,'Invalid fixed'):
            rewrite_member(original,{**member,'stylesheet_patch':'arbitrary-css'})
        recipe=deepcopy(self.recipe)
        recipe['selection']['members'][0]['stylesheet_patch']='python-index-wrap-v1'
        with self.assertRaisesRegex(SafetyError,'Invalid fixed'):validate_recipe(recipe,self.assets)

    def test_relative_reference_and_explicit_existing_fragment_are_counted(self):
        member={'path':'manual/guide.html','rewrites':[{'attribute':'href','from':'the_merge_command',
            'target_member':'manual/guide.html','target_fragment':'the_merge_command','expected_count':1}]}
        data=b'<a href="the_merge_command">merge</a><h2 id="the_merge_command">Full instructions</h2>'
        self.assertEqual(rewrite_member(data,member),data.replace(b'href="the_merge_command"',b'href="guide.html#the_merge_command"'))
        with self.assertRaisesRegex(SafetyError,'count changed'):rewrite_member(data.replace(b'the_merge_command',b'changed',1),member)

    def test_obsolete_reference_annotation_preserves_context_and_is_source_bound(self):
        from owl.acquisition.zip_localized import REFERENCE_ANNOTATIONS, STYLESHEET_PATCHES
        _,old,new=REFERENCE_ANNOTATIONS['sqlite-obsolete-asyncvfs-v1']
        member={'path':'manual/docs.html','reference_annotation':'sqlite-obsolete-asyncvfs-v1'}
        context='<h2>Obsolete Documents</h2>'+old+'<p>Extension deprecated. Read <a href="wal.html">WAL</a>.</p>'
        self.assertEqual(rewrite_member(context.encode(),member),context.replace(old,new).encode())
        for changed in [context.replace(old,'<a href="async-v2.html">Updated</a>'),context+old]:
            with self.assertRaisesRegex(SafetyError,'source span changed'):rewrite_member(changed.encode(),member)
        for invalid in [{**member,'path':'manual/current.html'},{**member,'reference_annotation':{}}]:
            with self.assertRaisesRegex(SafetyError,'Invalid source-bound'):rewrite_member(context.encode(),invalid)
        original=b'/* notice */ body { color: #123; }'
        self.assertEqual(rewrite_member(original,{'path':'manual/sqlite.css','stylesheet_patch':'sqlite-responsive-v1'}),
            original+STYLESHEET_PATCHES['sqlite-responsive-v1'])

    def test_historical_page_title_preserves_body_and_rejects_changed_source(self):
        original=b'<html>\n<body bgcolor="white"><h2>Historical statement</h2><p>Complete dated body.</p></body></html>'
        record={'path':'manual/pressrelease-20071212.html','reference_annotation':'sqlite-press-release-title-v1'}
        result=rewrite_member(original,record)
        self.assertIn(b'<title>SQLite Consortium Launches With Mozilla And Symbian As Charter Members</title>',result)
        self.assertEqual(result[result.index(b'<body'):],original[original.index(b'<body'):])
        with self.assertRaisesRegex(SafetyError,'source span changed'):
            rewrite_member(original.replace(b'bgcolor="white"',b'bgcolor="gray"'),record)
        with self.assertRaisesRegex(SafetyError,'Invalid source-bound'):
            rewrite_member(original,{**record,'path':'manual/unreviewed.html'})

    def test_pinned_companion_dependency_keeps_package_paths_and_rejects_changes(self):
        recipe=deepcopy(self.recipe);assets=deepcopy(self.assets)
        companion=self.root/'illustration.gif';companion.write_bytes(b'original GIF bytes')
        assets['illustration']={'id':'illustration','destination':'REFERENCE/manual/images/illustration.gif','supporting_file':True,
            'size_bytes':companion.stat().st_size,'sha256':hashlib.sha256(companion.read_bytes()).hexdigest()}
        recipe['source_asset_ids'].append('illustration')
        recipe['selection']['dependencies']={'manual/images/illustration.gif':'illustration'}
        sources={'source':self.source,'illustration':companion}
        render(recipe,sources,assets,self.root/'with-companion')
        companion.write_bytes(b'changed GIF bytes')
        with self.assertRaisesRegex(SafetyError,'dependency changed'):render(recipe,sources,assets,self.root/'changed')
        assets['illustration']['destination']='REFERENCE/elsewhere/illustration.gif'
        with self.assertRaisesRegex(SafetyError,'exact pins and package destination'):validate_recipe(recipe,assets)
        recipe['selection']['dependencies']={'manual/pic.png':'illustration'}
        with self.assertRaisesRegex(SafetyError,'collides'):validate_recipe(recipe,assets)

    def test_supplemental_notice_preserves_body_and_localizes_its_pinned_image(self):
        recipe=deepcopy(self.recipe);assets=deepcopy(self.assets)
        notice=self.root/'notice.html';raw=b'<h1>Full rights notice</h1><img src="https://publisher.test/badge"><p>Complete terms</p>'
        notice.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
        assets['notice']={'id':'notice','size_bytes':len(raw),'sha256':digest}
        assets['notice_local']={'id':'notice_local','destination':'REFERENCE/manual/notice.html'}
        recipe['source_asset_ids'].append('notice');recipe['output_asset_ids'].append('notice_local')
        recipe['selection']['additional_source_ids']=['notice']
        recipe['selection']['members'].append({'asset_id':'notice_local','source_asset_id':'notice','path':'manual/notice.html',
            'size_bytes':len(raw),'sha256':digest,'rewrites':[{'attribute':'src','from':'https://publisher.test/badge',
                'target_member':'manual/pic.png','expected_count':1}]})
        outputs=render(recipe,{'source':self.source,'notice':notice},assets,self.root/'notice-output')
        self.assertEqual(outputs['notice_local'].read_bytes(),raw.replace(b'https://publisher.test/badge',b'pic.png'))
        self.assertEqual(len(outputs),4)
        notice.write_bytes(b'changed')
        with self.assertRaisesRegex(SafetyError,'Supplemental document source changed'):
            render(recipe,{'source':self.source,'notice':notice},assets,self.root/'changed-notice')

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
        (profiles/'test.yaml').write_text(json.dumps({'id':'test','capacity_bytes':100000000,'reserve_bytes':100000,'discovery_budget_bytes':1000000}))
        target=self.root/'drive'
        from owl.catalog import CatalogError
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            build(target,catalog=catalog,profiles_dir=profiles,profile_name='test',allow_local=True,progress=lambda _:None)
        self.assertFalse(target.exists())
