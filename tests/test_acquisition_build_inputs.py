"""Temporary pinned inputs participate in real builds without becoming books."""
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
        self.profile=dict(id='test',capacity_bytes=100_000_000,search_budget_bytes=100_000,reserve_bytes=100_000)
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

    def test_plan_separates_inputs_from_content_and_never_downloads(self):
        with patch('owl.build.download',side_effect=AssertionError('plan download')):
            plan=self.run_build(plan_only=True)
        self.assertEqual(plan['content_bytes'],self.output['size_bytes'])
        self.assertEqual(plan['pinned_knowledge_bytes'],self.output['size_bytes'])
        self.assertEqual(plan['download_bytes'],self.source['size_bytes'])
        self.assertEqual(plan['build_input_work_bytes'],self.source['size_bytes'])
        self.assertFalse(self.target.exists())

    def test_default_content_ceiling_blocks_completion_before_source_download(self):
        self.profile.update(content_target_min_bytes=1,
                            content_target_max_bytes=self.output['size_bytes']-1)
        self.write()
        plan=self.run_build(plan_only=True)
        self.assertEqual(plan['target_overflow_bytes'],1)
        self.assertTrue(plan['content_floor_met'])
        self.assertFalse(plan['content_ceiling_met'])
        self.assertFalse(plan['content_complete'])
        with patch('owl.build.download',side_effect=AssertionError('ceiling must precede download')), \
                self.assertRaisesRegex(CatalogError,'default profile content maximum'):
            self.run_build()
        self.assertFalse(self.target.exists())
        result=self.run_build(allow_incomplete=True)
        inventory=json.loads((self.target/'LIBRARY/INVENTORY.json').read_text())
        self.assertFalse(inventory['content_complete'])
        self.assertEqual(result['plan']['target_overflow_bytes'],1)

    def test_complete_build_cleans_work_sources_and_reuses_outputs(self):
        self.run_build()
        self.assertFalse(self.staged.exists())
        inventory=json.loads((self.target/'LIBRARY/INVENTORY.json').read_text())
        self.assertEqual([a['id'] for a in inventory['assets']],['guide'])
        locked=json.loads((self.target/'LIBRARY/LOCKED_CATALOG.yaml').read_text())
        self.assertEqual([a['id'] for a in locked['assets']],['guide'])
        self.assertEqual(locked['acquisition_recipes'][0]['build_inputs'][0]['sha256'],self.source['sha256'])
        self.assertEqual(verify_drive(self.target,emit=lambda _:None)['FAILED'],0)
        with patch('owl.build.download',side_effect=AssertionError('must reuse')), \
                patch.object(Generator,'_render',side_effect=AssertionError('must reuse')):
            self.run_build()

    def test_generation_interruption_keeps_verified_source_and_resumes(self):
        with patch.object(Generator,'_render',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.assertTrue(self.staged.is_file())
        with patch('owl.build.download',side_effect=AssertionError('verified input must resume')):
            self.run_build()
        self.assertFalse(self.staged.exists())

    def test_download_interruption_resumes_owned_partial(self):
        def interrupted(asset,destination,**kwargs):
            destination.with_name(destination.name+'.part').write_bytes(self.original.read_bytes()[:20])
            raise KeyboardInterrupt
        with patch('owl.build.download',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.assertTrue(self.staged.with_name(self.staged.name+'.part').exists())
        self.run_build()
        self.assertFalse(self.staged.exists())

    def test_changed_source_and_changed_retained_work_are_rejected(self):
        self.original.write_text('changed')
        with self.assertRaises((SafetyError,DownloadError)):
            self.run_build()
        self.assertFalse((self.target/'LIBRARY/REFERENCE/guide.html').exists())

    def test_corrupt_work_input_does_not_reach_renderer(self):
        with patch.object(Generator,'_render',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.staged.write_bytes(b'x'*self.source['size_bytes'])
        with patch.object(Generator,'_render',side_effect=AssertionError('corrupt input')),self.assertRaisesRegex(SafetyError,'changed or cache is corrupt'):
            self.run_build()

    def test_missing_pin_and_namespace_collision_are_rejected(self):
        self.source['sha256']=None;self.write()
        with self.assertRaisesRegex(CatalogError,'SHA-256 pin'):self.run_build(plan_only=True)
        self.source['sha256']='0'*64
        extra={**self.output,'id':'original','generation':None}
        extra.pop('generation');extra['destination']='REFERENCE/source.html'
        self.write([extra])
        with self.assertRaisesRegex(CatalogError,'retained catalog asset'):self.run_build(plan_only=True)

    def test_source_notice_dependency_is_required_and_preserved(self):
        self.source['notice_asset_ids']=['notice'];self.write()
        with self.assertRaisesRegex(CatalogError,'notice.*not resolved and pinned'):self.run_build(plan_only=True)
        notice={**self.output,'id':'notice','title':'Publisher notice','format':'txt',
            'destination':'REFERENCE/NOTICE.txt','supporting_file':True,'size_bytes':self.original.stat().st_size,
            'sha256':hashlib.sha256(self.original.read_bytes()).hexdigest()}
        notice.pop('generation');self.write([notice])
        self.run_build()
        self.assertTrue((self.target/'LIBRARY/REFERENCE/NOTICE.txt').is_file())
        notice['profiles']=[];self.write([notice])
        with self.assertRaisesRegex(CatalogError,'select all pinned generation sources'):self.run_build(plan_only=True)

    def test_input_pins_affect_recipe_identity(self):
        first=recipe_digest(self.recipe,[self.output])
        changed=deepcopy(self.recipe);changed['build_inputs'][0]['sha256']='0'*64
        self.assertNotEqual(first,recipe_digest(changed,[self.output]))

    def test_cache_retains_inputs_separately_and_peak_is_checked(self):
        cache=self.root/'cache'
        info=self.run_build(cache_dir=cache)
        self.assertTrue((cache/'owl-v1'/self.source['sha256']).is_file())
        self.assertEqual(info['plan']['build_input_cache_bytes'],self.source['size_bytes'])
        self.assertEqual(info['plan']['build_input_work_bytes'],0)
        self.source['size_bytes']=200_000_000;self.write()
        plan=self.run_build(plan_only=True)
        self.assertFalse(plan['in_place_target_budget_fits'])
        (self.target/'LIBRARY/REFERENCE/guide.html').unlink()
        with patch('owl.build.download',side_effect=AssertionError('capacity must precede download')),self.assertRaisesRegex(SafetyError,'profile peak capacity'):
            self.run_build()

    def test_aliases_of_one_cached_source_are_counted_once(self):
        self.recipe['source_asset_ids'].append('same-original')
        self.recipe['build_inputs'].append({**self.source,'id':'same-original'})
        self.write()
        cache=self.root/'shared-cache'
        with patch.object(Generator,'_render',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            self.run_build(cache_dir=cache)
        plan=self.run_build(plan_only=True,cache_dir=cache)
        self.assertEqual(plan['build_input_download_bytes'],self.source['size_bytes'])
        self.assertEqual(plan['remaining_build_input_allocation_bytes'],0)
        self.assertEqual(plan['retained_build_input_bytes'],self.source['size_bytes'])
        self.assertEqual(plan['pinned_knowledge_bytes'],self.output['size_bytes'])
        self.run_build(cache_dir=cache)
        complete=self.run_build(plan_only=True,cache_dir=cache)
        self.assertEqual(complete['retained_build_input_bytes'],self.source['size_bytes'])

    def sevenzip_recipe(self):
        from tests.test_acquisition_sevenzip import fixture_tool
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
        return patch.object(sevenzip,'preflight',return_value=executable),member

    def test_sevenzip_members_are_temporary_pinned_inputs_and_resume(self):
        tool,member=self.sevenzip_recipe()
        with tool:
            plan=self.run_build(plan_only=True)
            self.assertEqual(plan['build_input_download_bytes'],self.source['size_bytes'])
            self.assertEqual(plan['build_input_expanded_bytes'],member['size_bytes'])
            self.assertEqual(plan['build_input_work_bytes'],self.source['size_bytes']+member['size_bytes'])
            with patch.object(Generator,'_render',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
                self.run_build()
            expanded=list((self.target/'LIBRARY/.owl/work/acquisition-inputs').rglob('original.html'))
            self.assertEqual(len(expanded),1)
            self.assertEqual(hashlib.sha256(expanded[0].read_bytes()).hexdigest(),member['sha256'])
            with patch('owl.build.download',side_effect=AssertionError('verified compressed input must reuse')):
                self.run_build()
            self.assertFalse(expanded[0].exists())
            self.assertFalse(self.staged.exists())
            self.assertEqual(verify_drive(self.target,emit=lambda _:None)['FAILED'],0)

    def test_unpinned_extracted_member_cannot_approve_recipe(self):
        _,member=self.sevenzip_recipe()
        member['sha256']=None;self.write()
        with self.assertRaisesRegex(CatalogError,'whole-file SHA-256'):
            self.run_build(plan_only=True)

    def test_archive_timeout_is_explicit_bounded_and_reaches_real_build(self):
        from owl.acquisition import sevenzip
        tool,_=self.sevenzip_recipe()
        extraction=self.recipe['build_input_extractions'][0]
        extraction['timeout_seconds']=3601;self.write()
        with self.assertRaisesRegex(CatalogError,'timeout_seconds'):
            self.run_build(plan_only=True)
        extraction['timeout_seconds']=1800;self.write()
        with tool,patch.object(sevenzip,'extract',wraps=sevenzip.extract) as call:
            self.run_build()
        self.assertEqual(call.call_args.kwargs['timeout'],1800)

    def test_shared_archive_keeps_one_extraction_identity_after_one_recipe_finishes(self):
        from owl.acquisition import sevenzip
        from tests.test_acquisition_sevenzip import fixture_tool
        _,first_member=self.sevenzip_recipe()
        second_original=self.root/'second.html'
        second_original.write_text('<article><h1>Second complete source</h1><p>'+('More useful preserved statements. '*10)+'</p></article>')
        member=dict(id='second-original',path='second.html',size_bytes=second_original.stat().st_size,
                    sha256=hashlib.sha256(second_original.read_bytes()).hexdigest())
        second_recipe=deepcopy(self.recipe)
        second_recipe.update(id='second-recipe',source_asset_ids=['second-original'],output_asset_ids=['second-guide'])
        second_recipe['build_input_extractions'][0]['members']=[member]
        second_recipe['selection']['outputs']=[{'asset_id':'second-guide','sections':[{
            'source_asset_id':'second-original','tag':'article','expected_count':1}]}]
        second_output={**self.output,'id':'second-guide','title':'Second complete guide',
            'destination':'REFERENCE/second.html','generation':{'recipe_id':'second-recipe'}}
        metadata={**build_input_assets([second_recipe]),'second-guide':second_output}
        result=render(second_recipe,{'second-original':second_original},metadata,self.root/'expected-second')['second-guide']
        second_output.update(size_bytes=result.stat().st_size,sha256=hashlib.sha256(result.read_bytes()).hexdigest())
        self.catalog.write_text(yaml.safe_dump(dict(schema_version=1,assets=[self.output,second_output],
            acquisition_recipes=[self.recipe,second_recipe])))
        executable=fixture_tool(self.root,{'original.html':self.original.read_text(),'second.html':second_original.read_text()})
        materialize=Generator.materialize
        def interrupted(generator,asset,destination):
            if asset['id']=='second-guide':raise KeyboardInterrupt
            return materialize(generator,asset,destination)
        with patch.object(sevenzip,'preflight',return_value=executable):
            with patch.object(Generator,'materialize',interrupted),self.assertRaises(KeyboardInterrupt):self.run_build()
            self.assertTrue((self.target/'LIBRARY/REFERENCE/guide.html').is_file())
            work=self.target/'LIBRARY/.owl/work/acquisition-inputs'
            self.assertEqual(len(list(work.glob('extract-*'))),1)
            with patch('owl.build.download',side_effect=AssertionError('shared source must resume')):
                self.run_build()
            self.assertEqual(len(list(work.glob('extract-*'))),1)
            self.assertFalse(list(work.glob('extract-*/files/*.html')))
            self.assertEqual(verify_drive(self.target,emit=lambda _:None)['FAILED'],0)

    def test_on_drive_cache_stays_in_peak_after_generation(self):
        self.source['size_bytes']=20_000_000;self.write()
        default=self.run_build(plan_only=True)
        cached=self.run_build(plan_only=True,cache_dir=self.target/'LIBRARY/.owl/source-cache')
        self.assertTrue(cached['build_input_cache_on_drive'])
        self.assertEqual(cached['build_input_cache_bytes'],20_000_000)
        self.assertEqual(cached['in_place_peak_budget_bytes']-default['in_place_peak_budget_bytes'],cached['index_working_peak_bytes'])

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
