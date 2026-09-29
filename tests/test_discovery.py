"""The pseudoindex must work without source reads and remain useful/safe offline."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.atlas_model import AtlasError, load_navigation
from owl.build import build
from owl.discovery import Annotation, annotate, compile_records, main, plan_discovery
from owl.safety import SafetyError
from owl.verify import verify_drive
from test_core import Fixture
from navigation_fixture import write_assignments

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


class DiscoveryTests(Fixture):
    def nav(self):
        return {'topics': {'water': {'id':'water','title':'Drinking water','description':'Water reference sources',
                 'parents':[],'aliases':['safe drinking water'],'related':[]}},
                'entrances': {'subjects':['water'], 'tasks':['water'], 'learn':[]},
                'assignments':[{'topic_id':'water','asset_id':self.asset['id'], 'purpose':'reference',
                                'aliases':['collect rainwater']}], 'sections':{}}

    def test_catalog_topics_and_aliases_without_any_source_reads(self):
        # Compilation cannot depend on even opening the document once.
        with patch.object(Path, 'open', side_effect=AssertionError('source I/O')):
            records, coverage = compile_records([self.asset], self.nav())
        self.assertEqual(len(records), 2)
        self.assertEqual(coverage[0]['status'], 'catalog')
        self.assertEqual(records[0]['aliases'], ['collect rainwater'])
        self.assertEqual(records[1]['aliases'], ['safe drinking water'])

    def test_excluded_sources_hide_their_topics_and_aliases(self):
        records, coverage = compile_records([], self.nav())
        self.assertEqual(records, [])
        self.assertEqual(coverage, [])

    def test_supporting_files_do_not_become_reading_material(self):
        for change in ({'supporting_file':True}, {'resource_type':'software'}, {'destination':'SOFTWARE/reader.zip'}):
            with self.subTest(change=change):
                records, _ = compile_records([{**self.asset, **change}])
                self.assertEqual(records, [])

    def test_sections_are_pinned_to_exact_edition(self):
        nav = self.nav()
        nav['sections']['fixture'] = {'asset_id':'fixture', 'source_sha256':'f'*64,
                                     'sections':[]}
        with self.assertRaisesRegex(AtlasError, 'Stale'):
            compile_records([self.asset], nav)

    def test_identical_locations_are_deduplicated_and_escaped(self):
        asset = {**self.asset, 'format':'html', 'destination':'BOOKS/a b.html'}
        nav = self.nav()
        nav['sections']['fixture'] = {'asset_id':'fixture', 'source_sha256':asset['sha256'],
            'sections':[{'id':'one','title':'Chapter','locator':{'type':'html-anchor','id':'a&b'}},
                        {'id':'two','title':'Chapter alias','locator':{'type':'html-anchor','id':'a&b'}}]}
        records, coverage = compile_records([asset],nav)
        self.assertEqual(coverage[0]['records'],2)
        self.assertEqual(records[1]['href'],'BOOKS/a%20b.html#a%26b')
        self.assertIn('Chapter alias', records[1]['aliases'])

    def test_compiler_is_deterministic_and_checks_output_budget(self):
        first = plan_discovery([self.asset],self.nav())
        self.assertEqual(first,plan_discovery([self.asset],self.nav()))
        with self.assertRaisesRegex(SafetyError,'allowance'):
            plan_discovery([self.asset],budget=1)
        self.assertEqual(first[1]['source_body_bytes_read'],0)
        self.assertTrue(all('chunks' not in key for key in first[0]))

    def test_invalid_annotation_types_and_references_are_rejected(self):
        good={'asset_id':'fixture','aliases':['rainwater'],'topic_ids':['water'],'basis':'Publisher title'}
        self.assertEqual(Annotation.parse(good,{'fixture'},{'water'}).asset_id,'fixture')
        for changes in ({'asset_id':'missing'},{'topic_ids':['missing']},{'aliases':'wrong'},
                        {'aliases':[True]},{'basis':''},{'basis':'invalid\x00note'},{'extra':'ignored?'},{'aliases':['x'*201]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                Annotation.parse({**good,**changes},{'fixture'},{'water'})

    def test_annotations_write_a_reviewable_draft_without_changing_approved_input(self):
        nav=self.nav(); folder=self.root/'navigation'; folder.mkdir()
        (folder/'topics.yaml').write_text(yaml.safe_dump({'schema_version':1,'topics':list(nav['topics'].values()),'entrances':nav['entrances']}))
        write_assignments(folder, nav['assignments'])
        approved=folder/'assignments/fixture.yaml'
        before=approved.read_bytes()
        proposal=self.root/'annotation.json'
        proposal.write_text(json.dumps({'asset_id':'fixture','aliases':['rainwater tank'], 'topic_ids':['water'],'basis':'Inspected publisher contents'}))
        output=self.root/'draft.yaml'
        annotate(folder,[self.asset],proposal,output)
        self.assertEqual(approved.read_bytes(),before)
        self.assertIn('rainwater tank',output.read_text())
        # Draft uses the production navigation schema, not a parallel format.
        approved.write_bytes(output.read_bytes())
        parsed=load_navigation(folder,[self.asset])
        self.assertIn('rainwater tank',parsed['assignments'][0]['aliases'])

    def test_multi_asset_annotation_cannot_overwrite_one_asset_draft(self):
        nav = self.nav()
        folder = self.root / 'navigation'
        folder.mkdir()
        (folder / 'topics.yaml').write_text(yaml.safe_dump({'schema_version': 1,
            'topics': list(nav['topics'].values()), 'entrances': nav['entrances']}))
        proposal = self.root / 'annotations.json'
        proposal.write_text(json.dumps([{'asset_id': aid, 'aliases': ['Useful phrase'],
            'topic_ids': ['water'], 'basis': 'Catalog title'} for aid in ('fixture', 'second')]))
        output = self.root / 'draft.yaml'
        with self.assertRaisesRegex(ValueError, 'one asset'):
            annotate(folder, [self.asset, {**self.asset, 'id': 'second'}], proposal, output)
        self.assertFalse(output.exists())

    def test_annotation_cli_accepts_partial_inventory_with_full_repository_metadata(self):
        nav = self.nav()
        folder = self.root / 'navigation'
        folder.mkdir()
        (folder / 'topics.yaml').write_text(yaml.safe_dump({'schema_version': 1,
            'topics': list(nav['topics'].values()), 'entrances': nav['entrances']}))
        other = {**self.asset, 'id': 'other', 'destination': 'BOOKS/other.txt'}
        self.write_catalog([self.asset, other])
        write_assignments(folder, [*nav['assignments'], {'topic_id': 'water', 'asset_id': 'other'}])
        inventory = self.root / 'inventory.json'
        inventory.write_text(json.dumps({'assets': [self.asset]}))
        proposal = self.root / 'proposal.json'
        proposal.write_text(json.dumps({'asset_id': 'fixture', 'aliases': ['Useful phrase'],
            'topic_ids': ['water'], 'basis': 'Catalog title'}))
        output = self.root / 'draft.yaml'
        self.assertEqual(main(['annotate', '--inventory', str(inventory), '--catalog', str(self.catalog),
            '--navigation-dir', str(folder), '--annotations', str(proposal), '--output', str(output),
            '--allow-local']), 0)
        self.assertEqual(yaml.safe_load(output.read_text())['asset_id'], 'fixture')

    def test_new_build_and_repeat_build_have_no_source_extraction(self):
        info=self.run_build()
        self.assertEqual(info['search']['format'],'owl-discovery-v1')
        self.assertEqual(info['search']['source_body_bytes_read'],0)
        self.assertNotIn('index_scratch_budget_bytes',info['plan'])
        self.assertEqual(self.run_build()['search'],info['search'])
        self.assertEqual(verify_drive(self.root/'drive',emit=lambda _:None)['FAILED'],0)

    def test_prepare_defaults_to_catalog_metadata_and_does_not_overwrite_edits(self):
        inventory=self.root/'inventory.json'; inventory.write_text(json.dumps({'assets':[self.asset]}))
        output=self.root/'packet.json'
        self.assertEqual(main(['prepare','--inventory',str(inventory),'--asset','fixture','--output',str(output)]),0)
        self.assertFalse(json.loads(output.read_text())['source_inspected'])
        output.write_text('my edits')
        self.assertEqual(main(['prepare','--inventory',str(inventory),'--asset','fixture','--output',str(output)]),1)
        self.assertEqual(output.read_text(),'my edits')

    def test_cli_rejects_retired_index_cache_flags(self):
        from owl.build import main as build_main
        with self.assertRaises(SystemExit):
            build_main([str(self.root/'drive'),'--index-cache-dir','cache'])


class DiscoveryRefreshTests(unittest.TestCase):
    def test_refresh_never_reads_sources_and_keeps_full_verifier(self):
        from owl.atlas_build import build_atlas
        with tempfile.TemporaryDirectory() as td:
            drive=Path(td).resolve()/'drive'
            build(drive,catalog=ROOT/'catalog/demo.yaml',profiles_dir=ROOT/'profiles',profile_name='demo',
                  allow_local=True,navigation_dir=ROOT/'catalog/demo-navigation',progress=lambda _:None)
            library=drive/'LIBRARY'
            inventory=json.loads((library/'INVENTORY.json').read_text())
            sources={(library/a['destination']).resolve() for a in inventory['assets']}
            original=Path.open
            def checked(path,*args,**kwargs):
                if path.resolve() in sources:
                    raise AssertionError('Metadata refresh read a source body')
                return original(path,*args,**kwargs)
            with patch.object(Path,'open',checked):
                build_atlas(drive,catalog=ROOT/'catalog/demo.yaml',navigation_dir=ROOT/'catalog/demo-navigation',
                            allow_local=True,metadata_only=True,progress=lambda _:None)
            self.assertEqual(verify_drive(drive,emit=lambda _:None)['FAILED'],0)
            source=next(iter(sources)); raw=source.read_bytes(); source.write_bytes(b'X'+raw[1:])
            self.assertGreater(verify_drive(drive,emit=lambda _:None)['FAILED'],0)

    def test_default_catalog_build_enables_navigation(self):
        # Main-catalog default resolution is checked without downloading content.
        from owl.catalog import load_catalog
        assets=load_catalog(ROOT/'catalog/library.yaml')
        records,_=compile_records(assets,load_navigation(ROOT/'catalog/navigation',assets))
        self.assertGreater(sum(r['kind']=='topic' for r in records),50)
        self.assertLess(sum(len(json.dumps(r)) for r in records),16*1024*1024)


@unittest.skipUnless(NODE,'Node required')
class DiscoveryJavaScriptTests(unittest.TestCase):
    def js(self,body):
        script='const assert=require("node:assert/strict"); const api=require('+json.dumps(str(ROOT/'src/owl/templates/search.js'))+');\n'+body
        result=subprocess.run([NODE,'-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ranking_aliases_filters_dedup_and_empty_query(self):
        self.js('''
const records=[
{id:'a',title:'Water',aliases:['rainwater'],href:'BOOKS/a.pdf',location:'Complete',shelves:['textbooks'],description:'water'},
{id:'b',title:'Plumbing',href:'BOOKS/b.pdf',location:'Complete',description:'water water water water'},
{id:'c',title:'Water',href:'BOOKS/old.pdf',location:'Complete',legacy:true},
{id:'d',title:'Water duplicate',href:'BOOKS/a.pdf',location:'Complete'}];
const data=api.prepare(records);
assert.equal(api.search(data,'water')[0].record.id,'a');
assert.equal(api.search(data,'rainwater')[0].record.id,'a');
assert.deepEqual(api.search(data,'water','textbooks').map(x=>x.record.id),['a']);
assert.deepEqual(api.search(data,'water','legacy').map(x=>x.record.id),['c']);
assert.equal(api.search(data,'water').filter(x=>x.record.href==='BOOKS/a.pdf').length,1);
assert.equal(api.search(data,'').length,0);
assert.throws(()=>api.search(data,Array.from({length:33},(_,i)=>'word'+i).join(' ')));
''')

    def test_unicode_and_safe_relative_paths(self):
        self.js('''
assert.deepEqual(api.tokens('ＷＡＴＥＲ Eau Électricité'), ['water','eau','électricité']);
for (const href of ['../secret','%2e%2e/secret','https://example.com','//host/x','BOOKS/a%00.pdf','BOOKS/../x']) assert.equal(api.safeHref(href),false,href);
assert.equal(api.safeHref('BOOKS/a%20b.pdf#page=2'),true);
assert.equal(api.safeHref('INDEX/topics/water.html'),true);
''')
