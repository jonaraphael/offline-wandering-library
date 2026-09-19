"""A local direct export can join a build without staging another copy."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.build import build
from owl.catalog import CatalogError
from owl.verify import verify_drive


class ExtraCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.target = self.root / 'drive'
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile = dict(id='test', capacity_bytes=100_000_000,
                            reserve_bytes=0, search_budget_bytes=100_000,
                            default_resources=['core'])
        (self.profiles/'test.yaml').write_text(yaml.safe_dump(self.profile))
        self.base = self.asset('source', 'BOOKS/source.txt', b'Original source contents')
        self.extra = self.asset('export', 'REFERENCE/DIRECT/export.txt', b'Illustrated export contents')
        self.extra['derived_from_asset_id'] = 'source'
        self.extra['source_archive_sha256'] = self.base['sha256']
        self.catalog = self.root/'library.yaml'
        self.manifest = self.root/'extra.yaml'
        self.write(self.catalog, [self.base])
        self.write(self.manifest, [self.extra])
        (self.root/'resources.yaml').write_text(yaml.safe_dump(dict(schema_version=1, resources=[
            dict(id='core', title='Source', number=1, target_bytes=1000, status='ready', asset_ids=['source'])])))

    def asset(self, identity, destination, data):
        path = self.target/"LIBRARY"/destination
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return dict(id=identity, title=identity, category='reference', format='txt',
                    source_url=path.as_uri(), destination=destination, version='1',
                    size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), license='CC0-1.0',
                    redistributable=True, required=True, profiles=[])

    def write(self, path, assets):
        path.write_text(yaml.safe_dump(dict(schema_version=1, assets=assets)))

    def run_build(self, **kwargs):
        return build(self.target, catalog=self.catalog, profiles_dir=self.profiles,
                     profile_name='test', allow_local=True, extra_catalogs=[self.manifest],
                     progress=lambda _:None, **kwargs)

    def test_in_place_export_is_reused_and_verified_and_locked(self):
        with patch('owl.build.download', side_effect=AssertionError('must reuse in-place files')):
            result = self.run_build()
            self.run_build()
        self.assertEqual(result['asset_count'], 2)
        self.assertEqual(result['content_selection']['additional_asset_ids'], ['export'])
        self.assertEqual(verify_drive(self.target, emit=lambda _:None)['FAILED'], 0)
        self.assertEqual(len(result['extra_catalogs']), 1)
        rebuilt = build(self.root/'second', catalog=self.target/'LIBRARY/LOCKED_CATALOG.yaml',
                        profiles_dir=self.profiles, profile_name='test', allow_local=True,
                        progress=lambda _:None)
        self.assertEqual(rebuilt['asset_count'], 2)
        self.assertEqual((self.root/'second/LIBRARY'/self.extra['destination']).read_bytes(),
                         (self.target/'LIBRARY'/self.extra['destination']).read_bytes())

    def test_cross_manifest_collisions_rejected_before_build_state(self):
        for field, value in [('id', 'source'), ('destination', 'books/SOURCE.txt'),
                             ('destination', 'BOOKS/source.txt/child')]:
            with self.subTest(field=field, value=value):
                self.write(self.manifest, [{**self.extra, field:value}])
                with self.assertRaises((CatalogError, ValueError)):
                    self.run_build(plan_only=True)
        self.assertFalse((self.target/'LIBRARY/.owl').exists())

    def test_excluded_parent_does_not_import_derivative(self):
        result = self.run_build(exclude=['core'], plan_only=True)
        self.assertEqual(result['content_bytes'], 0)
        self.assertEqual(result['content_selection']['additional_asset_ids'], [])
        self.assertTrue((self.target/'LIBRARY'/self.extra['destination']).exists())

    def test_unknown_parent_or_missing_hash_rejected(self):
        for changes in [dict(derived_from_asset_id='missing'), dict(sha256=None),
                        dict(source_archive_sha256='0'*64), dict(source_archive_sha256=None)]:
            self.write(self.manifest, [{**self.extra, **changes}])
            with self.assertRaises(CatalogError):
                self.run_build(plan_only=True)
        self.assertFalse((self.target/'LIBRARY/.owl').exists())

    def test_independent_addition_increases_planning_budget(self):
        self.extra.pop('derived_from_asset_id')
        self.write(self.manifest, [self.extra])
        result = self.run_build(plan_only=True)
        self.assertEqual(result['content_selection']['content_target_bytes'], 1000+self.extra['size_bytes'])

    def test_derivative_cannot_consume_other_collections_planning_allowance(self):
        result = self.run_build(plan_only=True)
        self.assertEqual(result['content_selection']['content_target_bytes'], 1000+self.extra['size_bytes'])

    def test_additional_archive_cannot_bypass_reader_requirement(self):
        self.extra.update(format='zim', reader_required=True)
        self.write(self.manifest, [self.extra])
        with self.assertRaisesRegex(CatalogError, 'pinned bundled reader'):
            self.run_build(plan_only=True)
        self.assertFalse((self.target/'LIBRARY/.owl').exists())


if __name__ == '__main__':
    unittest.main()
