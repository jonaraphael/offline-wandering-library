"""Honest content accounting, explicit working space, and resumable quota stops."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

import yaml

from owl.build import build, check_space_phases, main
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

    def test_flash_command_fits_a_153_gb_drive_and_builds(self):
        profile = {**self.profile, 'id': 'flash-16gb', 'capacity_bytes': 15_875_000_000,
                   'nominal_capacity_bytes': 16_000_000_000, 'discovery_budget_bytes': 200_000_000,
                   'reserve_bytes': 125_000_000, 'default_resources': ['core', 'optional', 'archive-readers']}
        (self.profiles / 'flash-16gb.yaml').write_text(yaml.safe_dump(profile), encoding='utf-8')
        assets = [{**self.asset, 'profiles': [], 'utility_tier': 'CRITICAL'},
                  {**self.asset, 'id': 'optional', 'profiles': [], 'destination': 'BOOKS/optional.txt',
                   'size_bytes': 15_000_000_000, 'utility_tier': 'NONESSENTIAL'},
                  {**self.asset, 'id': 'reader', 'profiles': [], 'destination': 'SOFTWARE/reader.zip',
                   'format': 'zip', 'utility_tier': 'USEFUL'}]
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': assets}), encoding='utf-8')
        resources = [{'id': identity, 'title': identity, 'status': 'ready', 'target_bytes': asset['size_bytes'],
                      'asset_ids': [asset['id']]} for identity, asset in zip(profile['default_resources'], assets)]
        self.catalog.with_name('resources.yaml').write_text(yaml.safe_dump({'schema_version': 1, 'resources': resources}),
                                                          encoding='utf-8')
        self.catalog.with_name('capacity-ladder.json').write_text(json.dumps({
            'schema_version': 2, 'transitions': [[16_000_000_000, identity, 'published'] for identity in ('core', 'optional')],
            'filler_placements': [], 'fillers': [[16_000_000_000, []]]}), encoding='utf-8')
        target = self.root / 'drive'
        target.mkdir()
        argv = [str(target), '--catalog', str(self.catalog), '--profiles-dir', str(self.profiles),
                '--profile', 'flash-16gb', '--allow-local']
        with patch('owl.build.shutil.disk_usage', return_value=SimpleNamespace(free=15_300_000_000)), \
                patch('sys.stdout') as stdout, patch('sys.stderr') as stderr:
            self.assertEqual(main([*argv, '--plan', '--capacity-bytes', '16000000000']), 1)
            diagnostic = ''.join(call.args[0] for call in stderr.write.call_args_list)
            self.assertIn('Largest capacity available for this library: 15,300,000,000 bytes.', diagnostic)
            self.assertIn("python scripts/build_drive.py", diagnostic)
            self.assertRegex(diagnostic, r"--capacity-bytes[' ]+15300000000")
            self.assertEqual(main([*argv, '--plan', '--capacity-bytes=15300000000']), 0)
            self.assertEqual(main([*argv, '--plan']), 0)
            self.assertFalse((target / 'START_HERE.html').exists())
            self.assertEqual(main(argv), 0)
        self.assertIn('Fitting the flash-16gb recommendation to 15,300,000,000 free bytes',
                      ''.join(call.args[0] for call in stdout.write.call_args_list))
        info = json.loads((target / 'LIBRARY/BUILD_INFO.json').read_bytes())
        self.assertTrue(info['content_complete'])
        self.assertEqual(info['profile']['nominal_capacity_bytes'], 15_300_000_000)
        self.assertTrue((target / 'LIBRARY/BOOKS/book.txt').is_file())
        self.assertFalse((target / 'LIBRARY/BOOKS/optional.txt').exists())
        tiny = self.root / 'small-drive'
        tiny.mkdir()
        with patch('owl.build.shutil.disk_usage', return_value=SimpleNamespace(free=7_000_000_000)), \
                patch('sys.stdout'), patch('sys.stderr') as stderr:
            self.assertEqual(main([str(tiny), *argv[1:], '--plan']), 1)
        self.assertIn('Free at least 1,000,000,000 more bytes for the 8 GB plan',
                      ''.join(call.args[0] for call in stderr.write.call_args_list))


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
