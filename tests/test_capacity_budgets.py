"""Honest content accounting, explicit working space, and resumable quota stops."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.build import build, check_space_phases
from owl.catalog import CatalogError, capacity_plan, load_profiles


class CapacityBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile = {'id': 'test', 'capacity_bytes': 1_000_000_000,
                        'discovery_budget_bytes': 1_000_000, 'reserve_bytes': 100_000}
        self.profile_path = self.profiles / 'test.yaml'
        self.profile_path.write_text(yaml.safe_dump(self.profile), encoding='utf-8')
        data = b'Practical water filtration and compass navigation.\n' * 1000
        self.source = self.root / 'source.txt'
        self.source.write_bytes(data)
        self.asset = {'id': 'book', 'title': 'Book', 'destination': 'BOOKS/book.txt',
                      'source_url': self.source.as_uri(), 'format': 'txt', 'size_bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest(), 'category': 'reference',
                      'version': '1', 'license': 'CC0', 'redistributable': True,
                      'required': True, 'profiles': ['test']}
        self.catalog = self.root / 'catalog.yaml'
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': [self.asset]}), encoding='utf-8')

    def search_target(self, name='search-drive'):
        target = self.root / name
        (target / 'BOOKS').mkdir(parents=True)
        (target / self.asset['destination']).write_bytes(self.source.read_bytes())
        return target



    def test_metrics_exclude_readers_and_distinguish_plans_from_known_content(self):
        assets = [self.asset, {**self.asset, 'destination': 'SOFTWARE/reader.zip', 'format': 'zip', 'size_bytes': 5000},
                  {**self.asset, 'destination': 'ZIM/book.zim', 'format': 'zim', 'size_bytes': 10_000, 'reader_required': True}]
        minimum = self.asset['size_bytes'] + 20_000
        profile = {**self.profile, 'content_target_min_bytes': minimum, 'content_target_max_bytes': minimum + 100_000}
        selection = {'planned_total_bytes': minimum + 5000, 'content_target_bytes': minimum,
                     'incomplete_resources': [], 'customized': False}
        plan = capacity_plan(assets, profile, selection)
        self.assertEqual(plan['pinned_knowledge_bytes'], self.asset['size_bytes'] + 10_000)
        self.assertEqual(plan['pinned_reader_bytes'], 5000)
        self.assertEqual(plan['direct_readable_bytes'], self.asset['size_bytes'])
        self.assertEqual(plan['target_shortfall_bytes'], 10_000)
        self.assertEqual(plan['target_window_status'], 'in-range')
        self.assertEqual(plan['actual_target_window_status'], 'below-target')
        self.assertFalse(plan['content_floor_met'])
        self.assertTrue(capacity_plan(assets, profile, {**selection, 'customized': True})['content_floor_met'])

    def test_default_underfilled_build_requires_explicit_partial_content(self):
        self.profile_path.write_text(yaml.safe_dump({**self.profile, 'content_target_min_bytes': 100_000,
                                                    'content_target_max_bytes': 200_000}), encoding='utf-8')
        target = self.root / 'drive'
        arguments = dict(catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                         allow_local=True, progress=lambda _: None)
        with self.assertRaisesRegex(CatalogError, 'content minimum'):
            build(target, **arguments)
        self.assertFalse(target.exists())
        plan = build(target, plan_only=True, **arguments)
        self.assertFalse(plan['content_floor_met'])
        info = build(target, allow_incomplete=True, **arguments)
        self.assertFalse(info['content_complete'])



    def test_phase_reclamation_cannot_credit_another_filesystem(self):
        target, work = self.root / 'drive', self.root / 'work'
        # Simulate the already-grouped observations for two distinct devices.
        groups = [
            [{'path': str(target), 'required_bytes': 400, 'uses': [str(target)]},
             {'path': str(work), 'required_bytes': 600, 'uses': [str(work)]}],
            [{'path': str(target), 'required_bytes': 900, 'uses': [str(target)]},
             {'path': str(work), 'required_bytes': 0, 'uses': [str(work)]}]]
        class Device:
            def __init__(self, dev): self.dev = dev
            def stat(self): return type('Stat', (), {'st_dev': self.dev})()
        with patch('owl.build.check_space_groups', side_effect=groups), \
                patch('owl.build._directory_anchor', side_effect=lambda p: (Device(1 if p == target else 2), None)):
            result = check_space_phases({'extraction': [], 'packaging': []})
        self.assertEqual([g['required_bytes'] for g in result], [900, 600])














if __name__ == '__main__':
    unittest.main()
