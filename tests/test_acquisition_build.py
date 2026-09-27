"""Pinned generated editions use the real build pipeline, including restart/locks."""
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
        self.profile = dict(id='test', capacity_bytes=100_000_000, search_budget_bytes=100_000,
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

    def test_plan_never_downloads_and_accounts_generated_bytes(self):
        with patch('owl.build.download',side_effect=AssertionError('plan download')):
            report = self.run_build(plan_only=True)
        self.assertFalse(self.target.exists())
        self.assertEqual(report['download_bytes'], self.source['size_bytes'])
        self.assertEqual(report['generated_output_bytes'], self.output['size_bytes'])
        self.assertEqual(report['acquisition_workspace_budget_bytes'], 65536 + self.output['size_bytes'])

    def test_manual_plan_needs_no_renderer(self):
        self.recipe['adapter'] = 'mdoc'
        self.recipe['selection'] = {'edition':'Fixture 1','renderer_probe_sha256':'0' * 64}
        self.write()
        with patch('owl.acquisition.mdoc.preflight',side_effect=AssertionError('plan must not probe mandoc')), \
                patch('owl.build.download',side_effect=AssertionError('plan download')):
            self.run_build(plan_only=True)
        self.assertFalse(self.target.exists())

    def test_manual_build_checks_renderer_before_download_or_target_mutation(self):
        self.recipe['adapter'] = 'mdoc'
        self.recipe['selection'] = {'edition':'Fixture 1','renderer_probe_sha256':'0' * 64}
        self.write()
        with patch('owl.acquisition.mdoc.shutil.which',return_value=None), \
                patch('owl.build.download',side_effect=AssertionError('download before renderer dependency')), \
                self.assertRaisesRegex(SafetyError,'mandoc on PATH'):
            self.run_build()
        self.assertFalse(self.target.exists())
        with patch('owl.acquisition.mdoc._mandoc',return_value=b'different renderer'), \
                patch('owl.build.download',side_effect=AssertionError('download before renderer fingerprint')), \
                self.assertRaisesRegex(SafetyError,'renderer differs'):
            self.run_build()
        self.assertFalse(self.target.exists())

    def test_build_verifies_generated_output_and_locked_rebuild_reuses_it(self):
        self.run_build()
        self.assertEqual(verify_drive(self.target, emit=lambda _:None)['FAILED'],0)
        locked = self.target / 'LIBRARY/LOCKED_CATALOG.yaml'
        document = json.loads(locked.read_text())
        self.assertEqual(document['acquisition_recipes'][0]['id'],'fixture')
        with patch('owl.build.download',side_effect=AssertionError('already downloaded')), \
                patch.object(Generator,'_render',side_effect=AssertionError('already generated')):
            self.run_build()
            build(self.target,catalog=locked,profiles_dir=self.profiles,profile_name='test',
                  allow_local=True,progress=lambda _:None)

    def test_interrupted_generation_retains_inputs_and_recovers(self):
        with patch.object(Generator,'_render',side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.assertFalse(json.loads((self.target/'LIBRARY/.owl/state.json').read_text())['complete'])
        with patch('owl.build.download',side_effect=AssertionError('input is reusable')):
            self.run_build()
        self.assertTrue(json.loads((self.target/'LIBRARY/.owl/state.json').read_text())['complete'])

    def test_bad_generated_pin_does_not_publish_or_complete(self):
        self.output['sha256'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(SafetyError,'Generated output SHA-256/size'):
            self.run_build()
        self.assertFalse((self.target / 'LIBRARY/REFERENCE/guide.html').exists())

    def test_changed_original_rejected_before_generation(self):
        self.input.write_bytes(self.input.read_bytes().replace(b'Water', b'Wrong'))
        with patch.object(Generator, '_render', side_effect=AssertionError('unverified input rendered')):
            with self.assertRaises((SafetyError, DownloadError)):
                self.run_build()
        self.assertFalse((self.target / 'LIBRARY/REFERENCE/guide.html').exists())

    def test_legacy_only_edition_passes_explicit_shelf_postflight(self):
        self.output['legacy'] = True
        self.write()
        self.run_build()
        state = json.loads((self.target/'LIBRARY/.owl/state.json').read_text())
        self.assertTrue(state['complete'])

    def test_interrupt_after_one_output_reuses_staged_sibling(self):
        sibling = deepcopy(self.output)
        sibling.update(id='second', destination='REFERENCE/second.html')
        self.recipe['output_asset_ids'].append('second')
        selected = deepcopy(self.recipe['selection']['outputs'][0])
        selected['asset_id'] = 'second'
        selected['sections'][0]['value'] = 'other'
        self.recipe['selection']['outputs'].append(selected)
        data = self.input.read_bytes().replace(b'</body>', b'<article id="other"><p>Separate complete instructions.</p></article></body>')
        self.input.write_bytes(data)
        self.source.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        outputs = render(self.recipe, {'publisher':self.input},
                         {a['id']:a for a in [self.source,self.output,sibling]}, self.root/'expected-pair')
        for asset in [self.output,sibling]:
            data = outputs[asset['id']].read_bytes()
            asset.update(size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        self.catalog.write_text(yaml.safe_dump(dict(schema_version=1,
            assets=[self.source,self.output,sibling],acquisition_recipes=[self.recipe])))
        original = Generator.materialize
        published = []
        def interrupt(generator, asset, destination):
            if published:
                raise KeyboardInterrupt
            result = original(generator,asset,destination)
            published.append(destination)
            return result
        with patch.object(Generator,'materialize',interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.assertTrue(published[0].is_file())
        with patch.object(Generator,'_render',side_effect=AssertionError('staged output is reusable')):
            self.run_build()
        self.assertEqual(verify_drive(self.target, emit=lambda _:None)['FAILED'],0)

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

    def test_retained_workspace_is_included_in_capacity(self):
        self.recipe['workspace_bytes'] = self.profile['capacity_bytes']
        self.write()
        with self.assertRaisesRegex(CatalogError,'workspace exceeds'):
            self.run_build(plan_only=True)
