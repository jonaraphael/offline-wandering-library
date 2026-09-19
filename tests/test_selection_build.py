"""Build and CLI integration for explicit resource choices and incomplete recipes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

from owl.build import build
from owl.catalog import CatalogError
from owl.verify import verify_drive

ROOT = Path(__file__).resolve().parents[1]


class ResourceBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.profiles = self.root/'profiles'; self.profiles.mkdir()
        self.catalog = self.root/'library.yaml'
        self.registry = self.root/'resources.yaml'
        self.target = self.root/'drive'
        self.profile = dict(id='test', title='Test', capacity_bytes=100_000_000,
            search_budget_bytes=1_000_000, reserve_bytes=1_000_000, default_resources=['core','pending'])
        self.assets=[]
        for number in (1,2):
            data=f'Illustrated textbook fixture {number}: independent resource selection.\n'.encode()
            source=self.root/f'{number}.txt';source.write_bytes(data)
            self.assets.append(dict(id=f'file{number}',title=f'Fixture {number}',category='reference',
                format='txt',source_url=source.as_uri(),destination=f'BOOKS/file{number}.txt',
                version='1',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                license='CC0-1.0',redistributable=True,required=True,critical=True,
                profiles=[],resource_type='textbook',illustrated=True))
        self.resources=[dict(id='core',number=1,title='Core',target_bytes=1000,status='ready',asset_ids=['file1']),
            dict(id='extra',number=2,title='Extra',target_bytes=1000,status='ready',asset_ids=['file2']),
            dict(id='pending',number=3,title='Pending collection',target_bytes=2_000_000,status='unresolved',
                 reason='Curation and exact source pins needed',asset_ids=[])]
        self.save()

    def save(self):
        (self.profiles/'test.yaml').write_text(yaml.safe_dump(self.profile),encoding='utf-8')
        self.catalog.write_text(yaml.safe_dump(dict(schema_version=1,resource_catalog='resources.yaml',assets=self.assets)),encoding='utf-8')
        self.registry.write_text(yaml.safe_dump(dict(schema_version=1,resources=self.resources)),encoding='utf-8')

    def run_build(self, target=None, **kwargs):
        return build(target or self.target,catalog=self.catalog,profiles_dir=self.profiles,profile_name='test',
                     allow_local=True,progress=lambda _:None,**kwargs)

    def test_incomplete_default_fails_before_writing(self):
        with self.assertRaisesRegex(CatalogError,'collections are incomplete'):
            self.run_build()
        self.assertFalse(self.target.exists())

    def test_plan_reports_intended_and_available_without_writing(self):
        result=self.run_build(plan_only=True)
        self.assertFalse(result['content_complete'])
        self.assertEqual(result['content_bytes'],self.assets[0]['size_bytes'])
        self.assertEqual(result['content_selection']['content_target_bytes'],2_001_000)
        self.assertFalse(self.target.exists())

    def test_explicit_partial_build_records_and_displays_coverage(self):
        result=self.run_build(allow_incomplete=True)
        self.assertTrue(result['complete'])
        self.assertFalse(result['content_complete'])
        self.assertIn('incomplete',(self.target/'START_HERE.html').read_text(encoding='utf-8').lower())
        selection=json.loads((self.target/'LIBRARY/CONTENT_SELECTION.json').read_text())
        self.assertFalse(selection['content_complete'])
        counts=verify_drive(self.target,emit=lambda _:None)
        self.assertGreater(counts['OK'],0)
        self.assertEqual([counts[k] for k in ('MISSING','FAILED','UNKNOWN')],[0,0,0])

    def test_custom_selection_and_locked_rebuild_need_no_registry(self):
        result=self.run_build(include=['2'],exclude=['1,3'])
        self.assertTrue(result['content_complete'])
        self.assertFalse((self.target/'LIBRARY/BOOKS/file1.txt').exists())
        self.assertTrue((self.target/'LIBRARY/BOOKS/file2.txt').exists())
        self.registry.unlink()
        rebuilt=build(self.root/'second',catalog=self.target/'LIBRARY/LOCKED_CATALOG.yaml',profiles_dir=self.profiles,
            profile_name='test',allow_local=True,progress=lambda _:None)
        self.assertEqual(rebuilt['content_selection'],result['content_selection'])
        self.assertEqual((self.root/'second/LIBRARY/BOOKS/file2.txt').read_bytes(),(self.target/'LIBRARY/BOOKS/file2.txt').read_bytes())
        self.assertEqual(verify_drive(self.root/'second',emit=lambda _:None)['FAILED'],0)
        validated=subprocess.run([sys.executable,str(ROOT/'scripts/validate_catalog.py'),
            str(self.target/'LIBRARY/LOCKED_CATALOG.yaml'),'--profiles-dir',str(self.profiles),'--allow-local'],
            text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(validated.returncode,0,validated.stdout+validated.stderr)

    def test_exclusion_preserves_existing_files_without_listing_them_as_selected(self):
        self.run_build(include=['extra'],exclude=['pending'])
        result=self.run_build(exclude=['extra','pending'])
        self.assertEqual(result['asset_count'],1)
        self.assertTrue((self.target/'LIBRARY/BOOKS/file2.txt').exists())
        assets=json.loads((self.target/'LIBRARY/INVENTORY.json').read_text())['assets']
        self.assertEqual([a['id'] for a in assets],['file1'])
        counts=verify_drive(self.target,emit=lambda _:None)
        self.assertEqual(counts['UNKNOWN'],1)
        self.assertEqual(counts['FAILED'],0)

    def test_malformed_locked_coverage_fails_before_writing(self):
        self.run_build(exclude=['pending'])
        locked=json.loads((self.target/'LIBRARY/LOCKED_CATALOG.yaml').read_text())
        locked['selection_lock']['content_selection']['incomplete_resources']='false'
        self.catalog.write_text(json.dumps(locked),encoding='utf-8')
        with self.assertRaisesRegex(CatalogError,'Invalid locked resource coverage'):
            self.run_build(target=self.root/'second')
        self.assertFalse((self.root/'second').exists())

    def test_lock_cannot_omit_collection_coverage(self):
        self.run_build(exclude=['pending'])
        locked=json.loads((self.target/'LIBRARY/LOCKED_CATALOG.yaml').read_text())
        for coverage in (None, {'status':False}):
            locked['selection_lock']['content_selection']=coverage
            self.catalog.write_text(json.dumps(locked),encoding='utf-8')
            with self.subTest(coverage=coverage),self.assertRaises(CatalogError):
                self.run_build(target=self.root/'second')
        self.assertFalse((self.root/'second').exists())

    def test_existing_verified_selection_reused(self):
        self.run_build(exclude=['pending'])
        with patch('owl.build.download',side_effect=AssertionError('unexpected download')):
            self.run_build(exclude=['pending'])

    def test_bad_selector_never_writes(self):
        for options in [dict(include=['typo']),dict(include=['2'],exclude=['extra'])]:
            with self.subTest(options=options),self.assertRaises(CatalogError):self.run_build(**options)
        self.assertFalse(self.target.exists())

    def test_target_capacity_is_checked_even_for_unresolved_collection(self):
        self.resources[2]['target_bytes']=self.profile['capacity_bytes'];self.save()
        with self.assertRaisesRegex(CatalogError,'targets exceed capacity'):
            self.run_build(plan_only=True)
        self.assertFalse(self.target.exists())

    def test_fixed_profile_can_exclude_required_book_explicitly(self):
        self.profile.pop('default_resources')
        self.profile['minimum_coverage']={'textbooks':2}
        for a in self.assets:a['profiles']=['test']
        self.save()
        result=self.run_build(exclude=['extra'])
        self.assertEqual(result['asset_count'],1)
        self.assertTrue(result['content_selection']['customized'])

    def test_cli_lists_and_builds_without_live_downloads(self):
        base=[sys.executable,str(ROOT/'scripts/build_drive.py'),'--profile','test','--catalog',str(self.catalog),
              '--profiles-dir',str(self.profiles),'--allow-local']
        listed=subprocess.run([*base,'--list-resources'],text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(listed.returncode,0,listed.stderr)
        self.assertIn('pending',listed.stdout)
        built=subprocess.run([*base,str(self.target),'--include','2','--exclude','1,3'],text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(built.returncode,0,built.stderr)
        self.assertTrue((self.target/'LIBRARY/BOOKS/file2.txt').is_file())


if __name__=='__main__':unittest.main()
