"""Temporary conversion inputs cannot bypass finished-content admission."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.acquisition.documents import render
from owl.acquisition.runtime import Generator, recipe_digest
from owl.acquisition.model import build_input_assets
from owl.build import build
from owl.catalog import CatalogError, load_catalog, resolve_content
from owl.download import DownloadError
from owl.safety import SafetyError
from owl.verify import verify_drive


class BuildInputTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        self.original=self.root/'original.html'
        self.original.write_text('<article><h1>Useful source</h1><p>Preserve every complete statement.</p></article>')
        payload=self.original.read_bytes()
        self.source=dict(id='original',title='Pinned original',format='html',source_url=self.original.as_uri(),
            version='1',size_bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),license='CC0',notice_asset_ids=[])
        self.output=dict(id='guide',title='Complete useful guide',category='reference',format='html',
            source_url=self.original.as_uri(),destination='REFERENCE/guide.html',version='1',size_bytes=1,
            sha256='0'*64,license='CC0',redistributable=True,required=True,profiles=['test'],
            generation={'recipe_id':'temporary-source'})
        self.recipe=dict(id='temporary-source',resource_id='reference',adapter='html_snapshot',version='1',
            source_asset_ids=['original'],build_inputs=[self.source],output_asset_ids=['guide'],
            selection={'outputs':[{'asset_id':'guide','sections':[{'source_asset_id':'original','tag':'article','expected_count':1}]}]},
            review={'status':'approved','evidence':['Synthetic complete original review']},blockers=[])
        result=render(self.recipe,{'original':self.original},{'original':self.source,'guide':self.output},self.root/'expected')['guide']
        self.output.update(size_bytes=result.stat().st_size,sha256=hashlib.sha256(result.read_bytes()).hexdigest())
        self.profile=dict(id='test',capacity_bytes=100_000_000,discovery_budget_bytes=100_000,reserve_bytes=100_000)
        self.profiles=self.root/'profiles';self.profiles.mkdir()
        self.catalog=self.root/'catalog.yaml';self.target=self.root/'drive'
        self.write()

    def write(self,extra=()):
        self.catalog.write_text(yaml.safe_dump(dict(schema_version=1,assets=[self.output,*extra],acquisition_recipes=[self.recipe])))
        (self.profiles/'test.yaml').write_text(yaml.safe_dump(self.profile))

    def run_build(self,**options):
        return build(self.target,catalog=self.catalog,profiles_dir=self.profiles,profile_name='test',
                     allow_local=True,progress=lambda _:None,**options)

    @property
    def staged(self):
        return self.target/'LIBRARY/.owl/work/acquisition-inputs'/self.source['sha256']








    def test_generated_content_is_rejected_before_download_or_target_mutation(self):
        for options in ({}, {'plan_only': True}, {'allow_incomplete': True}):
            with self.subTest(options=options), patch('owl.build.download', side_effect=AssertionError('No download before admission')), self.assertRaisesRegex(CatalogError, 'Content policy'):
                self.run_build(**options)
            self.assertFalse(self.target.exists())


    def test_missing_pin_and_namespace_collision_are_rejected(self):
        self.source['sha256']=None;self.write()
        with self.assertRaisesRegex(CatalogError,'SHA-256 pin'):self.run_build(plan_only=True)
        self.source['sha256']='0'*64
        extra={**self.output,'id':'original','generation':None}
        extra.pop('generation');extra['destination']='REFERENCE/source.html'
        self.write([extra])
        with self.assertRaisesRegex(CatalogError,'retained catalog asset'):self.run_build(plan_only=True)


    def test_input_pins_affect_recipe_identity(self):
        first=recipe_digest(self.recipe,[self.output])
        changed=deepcopy(self.recipe);changed['build_inputs'][0]['sha256']='0'*64
        self.assertNotEqual(first,recipe_digest(changed,[self.output]))



    def sevenzip_recipe(self):
        from tests.test_acquisition_sevenzip import fixture_tool, fixture_preflight
        from owl.acquisition import sevenzip
        archive=self.root/'original.7z'
        archive.write_bytes(b'7z\xbc\xaf\x27\x1cSYNTHETIC PIPELINE FIXTURE')
        member=dict(id='original',path='original.html',size_bytes=self.source['size_bytes'],sha256=self.source['sha256'])
        self.source=dict(id='compressed',title='Pinned 7z fixture',format='7z',source_url=archive.as_uri(),
            version='1',size_bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),license='CC0',notice_asset_ids=[])
        self.recipe['build_inputs']=[self.source]
        self.recipe['build_input_extractions']=[dict(source_id='compressed',format='7z',max_bytes=10000,max_files=10,members=[member])]
        self.output['source_url']=archive.as_uri()
        metadata={**build_input_assets([self.recipe]),'guide':self.output}
        result=render(self.recipe,{'original':self.original},metadata,self.root/'expected-sevenzip')['guide']
        self.output.update(size_bytes=result.stat().st_size,sha256=hashlib.sha256(result.read_bytes()).hexdigest())
        self.write()
        executable=fixture_tool(self.root,{'original.html':self.original.read_text()})
        return fixture_preflight(executable),member


    def test_unpinned_extracted_member_cannot_approve_recipe(self):
        _,member=self.sevenzip_recipe()
        member['sha256']=None;self.write()
        with self.assertRaisesRegex(CatalogError,'whole-file SHA-256'):
            self.run_build(plan_only=True)




    def test_excluded_source_resource_removes_build_only_derivative(self):
        self.source['source_resource_ids']=['original-collection'];self.write()
        registry=self.root/'resources.yaml'
        registry.write_text(yaml.safe_dump(dict(schema_version=1,resources=[
            dict(id='original-collection',title='Original collection',target_bytes=1000,status='partial',reason='Pinned source only',asset_ids=[]),
            dict(id='reference',title='Derived edition',target_bytes=2000,status='ready',asset_ids=['guide'])])))
        assets=load_catalog(self.catalog,allow_local=True)
        selected,_,selection=resolve_content(assets,{**self.profile,'default_resources':['original-collection','reference']},
            resources_path=registry,exclude=['original-collection'])
        self.assertFalse(selected)
        self.assertTrue(selection['incomplete_resources'])


if __name__=='__main__':unittest.main()
