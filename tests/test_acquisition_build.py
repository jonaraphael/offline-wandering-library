"""Generated editions are rejected before writes; recipe structure remains inspectable."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch
import yaml

from owl.acquisition.documents import render
from owl.acquisition.runtime import Generator, order_assets, selected_recipes
from owl.build import build
from owl.catalog import CatalogError, validate_catalog, load_catalog, resolve_content
from owl.safety import SafetyError
from owl.verify import verify_drive
from owl.download import DownloadError


class AcquisitionBuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile = dict(id='test', capacity_bytes=100_000_000, discovery_budget_bytes=100_000,
                            reserve_bytes=100_000)
        (self.profiles / 'test.yaml').write_text(yaml.safe_dump(self.profile))
        self.input = self.root / 'publisher.html'
        self.input.write_bytes(b'<html><body><article id="guide"><h2>Useful fixture</h2><p>Water storage guidance fixture.</p><table><tr><td>Preserve this table</td></tr></table></article></body></html>')
        data = self.input.read_bytes()
        self.source = dict(id='publisher',title='Publisher original',category='reference',format='html',
            source_url=self.input.as_uri(),destination='REFERENCE/SOURCES/publisher.html',version='1',
            size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),license='CC0',
            redistributable=True,required=True,profiles=['test'],supporting_file=True)
        self.output = {**self.source, 'id':'guide', 'title':'Useful fixture',
                       'destination':'REFERENCE/guide.html','supporting_file':False,
                       'generation':{'recipe_id':'fixture'}}
        self.recipe = dict(id='fixture',resource_id='reference',adapter='html_snapshot',version='1',
            source_asset_ids=['publisher'],output_asset_ids=['guide'],
            selection={'outputs':[{'asset_id':'guide','sections':[{'source_asset_id':'publisher','tag':'article',
                            'attribute':'id','value':'guide','expected_count':1}]}]},
            review={'status':'approved','evidence':['original fixture']},blockers=[])
        paths = render(self.recipe, {'publisher':self.input}, {'publisher':self.source,'guide':self.output}, self.root / 'expected')
        payload = paths['guide'].read_bytes()
        self.output.update(size_bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
        self.catalog = self.root / 'catalog.yaml'
        self.target = self.root / 'drive'
        self.write()

    def write(self):
        self.catalog.write_text(yaml.safe_dump(dict(schema_version=1,assets=[self.source,self.output],
                                                   acquisition_recipes=[self.recipe])))

    def run_build(self, **options):
        return build(self.target,catalog=self.catalog,profiles_dir=self.profiles,profile_name='test',
                     allow_local=True,progress=lambda _:None,**options)










    def test_generated_content_is_rejected_before_download_or_target_mutation(self):
        for options in ({}, {'plan_only': True}, {'allow_incomplete': True}):
            with self.subTest(options=options), patch('owl.build.download', side_effect=AssertionError('No download before admission')), self.assertRaisesRegex(CatalogError, 'Content policy'):
                self.run_build(**options)
            self.assertFalse(self.target.exists())


    def test_pending_recipe_cannot_be_built_even_with_allow_incomplete(self):
        self.recipe['review']['status'] = 'pending'
        self.write()
        with self.assertRaisesRegex(CatalogError,'approved'):
            self.run_build(allow_incomplete=True)
        self.assertFalse(self.target.exists())

    def test_missing_source_and_cycles_are_rejected_before_writes(self):
        with self.assertRaisesRegex(CatalogError,'sources'):
            selected_recipes([self.output], {'fixture':self.recipe})
        source = {**self.source,'generation':{'recipe_id':'back'}}
        recipes = {'fixture':self.recipe,'back':dict(source_asset_ids=['guide'])}
        with self.assertRaisesRegex(CatalogError,'Cycle'):
            order_assets([source,self.output], recipes)

    def test_generation_cannot_share_asset_with_archive_extraction(self):
        self.output['archive_member'] = {'source_asset_id':'publisher','path':'guide','document':True}
        self.write()
        with self.assertRaises(CatalogError):
            self.run_build()

    def test_excluding_source_collection_omits_its_derived_edition(self):
        registry = self.root / 'resources.yaml'
        registry.write_text(yaml.safe_dump(dict(schema_version=1,resources=[
            dict(id='original',title='Original source',target_bytes=2000,status='ready',asset_ids=['publisher']),
            dict(id='reference',title='Direct edition',target_bytes=3000,status='ready',asset_ids=['guide'])])))
        assets = load_catalog(self.catalog,allow_local=True)
        selected, _, report = resolve_content(assets, {**self.profile,'default_resources':['original','reference']},
                                              resources_path=registry,exclude=['original'])
        self.assertFalse(selected)
        self.assertTrue(report['incomplete_resources'])
        self.assertIn('No selected source',report['incomplete_resources'][0]['reason'])
