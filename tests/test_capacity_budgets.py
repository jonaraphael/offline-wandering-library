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
from owl.search import SearchError, build_search, checkpoint_usage, probe_raw_checkpoint
from owl.search_pack import packed_size, publish_pack


class CapacityBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile = {'id': 'test', 'capacity_bytes': 1_000_000_000,
                        'search_budget_bytes': 1_000_000, 'reserve_bytes': 100_000}
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

    def test_explicit_scratch_retains_the_default_and_reports_filesystem_split(self):
        default = capacity_plan([self.asset], self.profile)
        self.assertEqual(default['index_scratch_budget_bytes'], 2_000_000)
        explicit = capacity_plan([self.asset], {**self.profile, 'index_scratch_budget_bytes': 3_000_000})
        self.assertEqual(explicit['index_serialization_budget_bytes'], 750_000)
        self.assertEqual(explicit['index_extraction_budget_bytes'], 2_250_000)
        self.assertEqual(explicit['estimated_final_bytes'], default['estimated_final_bytes'])

    def test_invalid_scratch_allowances_are_rejected(self):
        for value in (True, -1, '3000000', 749_999):
            with self.subTest(value=value):
                self.profile_path.write_text(yaml.safe_dump({**self.profile, 'index_scratch_budget_bytes': value}), encoding='utf-8')
                with self.assertRaises(CatalogError):
                    load_profiles(self.profiles)

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

    def test_preflight_assigns_raw_to_target_and_database_to_work(self):
        self.profile_path.write_text(yaml.safe_dump({**self.profile, 'index_scratch_budget_bytes': 3_000_000}), encoding='utf-8')
        target, work = self.root / 'drive', self.root / 'external-work'
        with patch('owl.build.check_space_phases', return_value=[]) as check:
            build(target, catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                  allow_local=True, plan_only=True, work_dir=work, progress=lambda _: None)
        phases = check.call_args.args[0]
        allocations = {}
        for path, amount in phases['extraction']:
            allocations[path] = allocations.get(path, 0) + amount
        self.assertEqual(allocations[work], 2_250_000)
        self.assertEqual(allocations[target / "LIBRARY"], self.asset['size_bytes'] + 750_000 + 100_000 + 16 * 1024 * 1024)
        self.assertEqual(sum(amount for _, amount in phases['packaging']),
                         self.asset['size_bytes'] + 1_000_000 + 750_000 + 100_000 + 16 * 1024 * 1024)
        self.assertFalse(target.exists())

    def test_phase_peaks_do_not_add_nonconcurrent_extraction_and_packaging(self):
        target, work = self.root / 'drive', self.root / 'work'
        with patch('owl.build.check_space') as check:
            groups = check_space_phases({
                'extraction': [(target, 400), (work, 600)],
                'packaging': [(target, 900), (work, -200)]})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['required_bytes'], 1000)
        self.assertEqual(groups[0]['phases'], {'extraction': 1000, 'packaging': 700})
        self.assertEqual(check.call_args_list[0].args[1], 1000)
        self.assertEqual(check.call_args_list[1].args[1], 700)

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

    def test_verified_rebuild_fits_without_space_for_a_second_index(self):
        target = self.root / 'drive'
        arguments = dict(catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                         allow_local=True, progress=lambda _: None)
        build(target, **arguments)
        # Enough for UI/metadata and reserve, but not the default 3 MB
        # combined replacement-index and extraction allowance.
        free = 16 * 1024 * 1024 + self.profile['reserve_bytes'] + 300_000
        with patch('owl.build.shutil.disk_usage', return_value=type('Usage', (), {'free': free})()), \
                patch('owl.search._units', side_effect=AssertionError('reuse must not extract')):
            result = build(target, **arguments)
        self.assertTrue(result['plan']['search_reuse_verified'])
        self.assertEqual(result['plan']['remaining_index_scratch_allocation_bytes'], 0)
        self.assertEqual(result['plan']['remaining_index_serialization_allocation_bytes'], 0)
        self.assertLess(result['plan']['remaining_search_output_allocation_bytes'], 300_000)

    def test_changed_metadata_does_not_receive_verified_reuse_space_credit(self):
        from owl.safety import SafetyError
        target = self.root / 'drive'
        arguments = dict(catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                         allow_local=True, progress=lambda _: None)
        build(target, **arguments)
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': [{**self.asset, 'title': 'Changed book'}]}), encoding='utf-8')
        free = 16 * 1024 * 1024 + self.profile['reserve_bytes'] + 300_000
        with patch('owl.build.shutil.disk_usage', return_value=type('Usage', (), {'free': free})()), \
                self.assertRaisesRegex(SafetyError, 'Insufficient disk space'):
            build(target, plan_only=True, **arguments)

    def test_raw_ready_resume_does_not_require_a_second_extraction_workspace(self):
        target = self.root / 'drive'
        arguments = dict(catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                         allow_local=True, progress=lambda _: None)
        with patch('owl.search_pack.publish_pack', side_effect=RuntimeError('pause before packaging')), \
                self.assertRaisesRegex(RuntimeError, 'pause before packaging'):
            build(target, **arguments)
        self.assertEqual(checkpoint_usage(target / 'LIBRARY')['scratch_bytes'], 0)
        from owl.catalog import load_catalog
        inputs = [{**asset, 'verification': 'pinned'} for asset in load_catalog(self.catalog, allow_local=True)]
        proof = probe_raw_checkpoint(target / 'LIBRARY', inputs)
        self.assertIsNotNone(proof)
        free = 16 * 1024 * 1024 + self.profile['reserve_bytes'] + proof['remaining_pack_allocation_bytes'] + 1000
        self.assertLess(free, 16 * 1024 * 1024 + self.profile['reserve_bytes'] + 1_250_000)
        with patch('owl.build.shutil.disk_usage', return_value=type('Usage', (), {'free': free})()), \
                patch('owl.search._units', side_effect=AssertionError('raw-ready must not extract')):
            result = build(target, **arguments)
        self.assertTrue(result['plan']['raw_search_reuse_verified'])
        self.assertEqual(result['plan']['remaining_index_scratch_allocation_bytes'], 0)
        self.assertEqual(result['plan']['remaining_index_serialization_allocation_bytes'], 0)

    def test_lost_reuse_proof_cannot_start_unbudgeted_replacement_extraction(self):
        target = self.search_target()
        report = build_search(target, [self.asset])
        chunk = next(name for name in report['generated_files'] if name.endswith('/00000000.js'))
        (target / chunk).write_bytes(b'damaged')
        with patch('owl.search._units', side_effect=AssertionError('credited reuse must not extract')), \
                self.assertRaisesRegex(SearchError, 'changed after space preflight'):
            build_search(target, [self.asset], reuse_only=True)

    def test_changed_source_pin_does_not_receive_verified_reuse_space_credit(self):
        from owl.safety import SafetyError
        target = self.root / 'drive'
        arguments = dict(catalog=self.catalog, profiles_dir=self.profiles, profile_name='test',
                         allow_local=True, progress=lambda _: None)
        build(target, **arguments)
        self.source.write_bytes(b'Changed source contents.\n' * 1000)
        changed = {**self.asset, 'size_bytes': self.source.stat().st_size,
                   'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}
        self.catalog.write_text(yaml.safe_dump({'schema_version': 1, 'assets': [changed]}), encoding='utf-8')
        free = 16 * 1024 * 1024 + self.profile['reserve_bytes'] + 300_000
        with patch('owl.build.shutil.disk_usage', return_value=type('Usage', (), {'free': free})()), \
                patch('owl.search.probe_completed_search', side_effect=AssertionError('changed input is not reusable')), \
                self.assertRaisesRegex(SafetyError, 'Insufficient disk space'):
            build(target, plan_only=True, **arguments)

    def test_package_quota_is_exact_and_checked_before_publication(self):
        raw = self.root / 'index.part'
        raw.write_bytes(b'x' * 1_048_579)
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        limit = packed_size(raw.stat().st_size, digest)
        with self.assertRaisesRegex(ValueError, 'search_budget_bytes'):
            publish_pack(self.root, raw, digest, max_bytes=limit - 1)
        self.assertFalse((self.root / 'SEARCH').exists())
        report = publish_pack(self.root, raw, digest, max_bytes=limit)
        self.assertEqual(report['transport_bytes'], limit)

    def test_raw_quota_stop_resumes_without_reextracting(self):
        target = self.search_target()
        with self.assertRaisesRegex(SearchError, 'serialization allowance'):
            build_search(target, [self.asset], search_budget_bytes=8192, index_scratch_budget_bytes=2_000_000)
        self.assertFalse((target / 'SEARCH/coverage.json').exists())
        self.assertGreater(checkpoint_usage(target)['scratch_bytes'], 0)
        with patch('owl.search._units', side_effect=AssertionError('durable extraction must be reused')):
            report = build_search(target, [self.asset], search_budget_bytes=1_000_000, index_scratch_budget_bytes=2_000_000)
        self.assertGreater(report['documents'], 0)
        self.assertEqual(checkpoint_usage(target)['scratch_bytes'], 0)

    def test_scratch_quota_stop_retains_checkpoint_and_can_resume(self):
        target = self.search_target()
        with self.assertRaisesRegex(SearchError, 'extraction workspace'):
            build_search(target, [self.asset], search_budget_bytes=1_000_000, index_scratch_budget_bytes=751_000)
        self.assertFalse((target / 'SEARCH/coverage.json').exists())
        self.assertGreater(checkpoint_usage(target)['scratch_bytes'], 0)
        build_search(target, [self.asset], search_budget_bytes=1_000_000, index_scratch_budget_bytes=2_000_000)

    def test_total_output_quota_does_not_publish_completion_or_accept_reuse(self):
        first = self.search_target('first')
        report = build_search(first, [self.asset])
        budget = report['transport_bytes'] + 10  # Fits chunks, but not UI and coverage.
        second = self.search_target('second')
        with self.assertRaisesRegex(SearchError, 'Search outputs require'):
            build_search(second, [self.asset], search_budget_bytes=budget, index_scratch_budget_bytes=2_000_000)
        self.assertFalse((second / 'SEARCH/coverage.json').exists())
        with self.assertRaisesRegex(SearchError, 'Search outputs require'):
            build_search(first, [self.asset], search_budget_bytes=budget, index_scratch_budget_bytes=2_000_000)

    def test_budgeted_reuse_repairs_missing_and_oversized_ui_without_reextracting(self):
        target = self.search_target()
        report = build_search(target, [self.asset], search_budget_bytes=1_000_000, index_scratch_budget_bytes=2_000_000)
        original_ui = {name: (target / name).read_bytes() for name in ('SEARCH.html', 'SEARCH/search.js')}
        (target / 'SEARCH.html').unlink()
        (target / 'SEARCH/search.js').write_bytes(b'x' * 2_000_000)
        with patch('owl.search._units', side_effect=AssertionError('verified chunks must be reused')):
            reused = build_search(target, [self.asset], search_budget_bytes=1_000_000, index_scratch_budget_bytes=2_000_000)
        self.assertEqual(reused['index_sha256'], report['index_sha256'])
        for name, data in original_ui.items():
            self.assertEqual((target / name).read_bytes(), data)

    def test_reuse_over_budget_does_not_overwrite_ui_or_coverage(self):
        target = self.search_target()
        report = build_search(target, [self.asset])
        (target / 'SEARCH.html').write_bytes(b'Existing owned page')
        before = {name: (target / name).read_bytes() for name in ('SEARCH.html', 'SEARCH/search.js', 'SEARCH/coverage.json')}
        with self.assertRaisesRegex(SearchError, 'Search outputs require'):
            build_search(target, [self.asset], search_budget_bytes=report['transport_bytes'] + 10,
                         index_scratch_budget_bytes=2_000_000)
        for name, data in before.items():
            self.assertEqual((target / name).read_bytes(), data)

    def test_free_reserve_is_checked_during_extraction_and_failure_is_resumable(self):
        target = self.search_target()
        low = False
        def progress(message):
            nonlocal low
            if message.startswith('INDEX 1/1 '):
                low = True
        def usage(_):
            return type('Usage', (), {'free': 99 if low else 1_000_000})()
        with patch('owl.search.shutil.disk_usage', side_effect=usage), self.assertRaisesRegex(SearchError, 'free-space reserve'):
            build_search(target, [self.asset], reserve_bytes=100, progress=progress)
        self.assertFalse((target / 'SEARCH/coverage.json').exists())
        build_search(target, [self.asset], reserve_bytes=100)


if __name__ == '__main__':
    unittest.main()
