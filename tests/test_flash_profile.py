"""Production presets carry useful content, not merely large planning targets."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.build import build
from owl.catalog import capacity_plan, learning_coverage, load_catalog, load_profiles, resolve_content

ROOT = Path(__file__).resolve().parents[1]


class FlashProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(ROOT / 'profiles')
        cls.assets = load_catalog(ROOT / 'catalog/library.yaml', cls.profiles)
        cls.profile = cls.profiles['flash-16gb']

    def selection(self, profile=None, **kwargs):
        return resolve_content(self.assets, profile or self.profile,
                               resources_path=ROOT / 'catalog/resources.yaml', **kwargs)

    def test_small_presets_are_pinned_substantial_and_nested(self):
        flash, unresolved, resources = self.selection()
        critical, _, _ = self.selection(self.profiles['critical-64gb'])
        self.assertGreaterEqual(len(flash), 400)
        self.assertLess({a['id'] for a in flash}, {a['id'] for a in critical})
        self.assertEqual(unresolved, [])
        self.assertFalse(resources["incomplete_resources"])
        for selected in (flash, critical):
            knowledge = [a for a in selected if not a['destination'].startswith('SOFTWARE/')]
            self.assertTrue(knowledge)
            for asset in selected:
                self.assertEqual(asset['status'], 'resolved')
                self.assertRegex(asset['sha256'], r'^[0-9a-f]{64}$')
                if asset.get('critical'):
                    self.assertEqual(asset['format'], 'pdf')
                    self.assertFalse(asset.get('reader_required'))

    def test_direct_medical_textbooks_illustrations_and_repair_are_first_class(self):
        assets, _, _ = self.selection()
        coverage = learning_coverage(assets)
        self.assertTrue(any(a['id']=='openstax_physics' for a in assets))
        self.assertTrue(any(a['id']=='usfs_ax_manual' and a['illustrated'] for a in assets))
        self.assertGreaterEqual(sum(a['format'] == 'pdf' for a in assets), 350)
        ids = {a['id'] for a in assets}
        self.assertTrue({'cert', 'medical_bec', 'water', 'sanitation', 'food', 'agriculture',
                         'electrical_dc', 'electrical_ac', 'mechanical', 'shelter',
                         'survival_shelter', 'navigation', 'reference', 'wikem_en',
                         'ifixit_en', 'appropedia_en', 'cd3wd_en', 'lowtech_magazine'} <= ids)
        self.assertTrue({'kiwix_windows', 'kiwix_linux', 'kiwix_macos', 'kiwix_android'} <= ids)
        # Direct emergency documents precede specialized archives during acquisition.
        self.assertLess(max(i for i,a in enumerate(assets) if a.get('critical')),
                        min(i for i,a in enumerate(assets) if a['format'] == 'zim'))

    def test_discovery_and_reserve_fit_nominal_devices(self):
        limits = {'flash-16gb': (16_000_000_000, 125_000_000),
                  'critical-64gb': (64_000_000_000, 320_000_000)}
        for name, (nominal_bytes, margin_bytes) in limits.items():
            profile = self.profiles[name]
            assets, _, selection = self.selection(profile)
            plan = capacity_plan(assets, profile, selection)
            peak = plan['in_place_peak_budget_bytes']
            self.assertLessEqual(peak, plan['capacity_bytes'])
            self.assertEqual(plan['reserve_bytes'], margin_bytes)
            self.assertEqual(plan['capacity_bytes'] + margin_bytes, nominal_bytes)
            self.assertEqual(selection['readers_budget_bytes'], 1_000_000_000)
            self.assertEqual(plan['content_bytes'], sum(a['size_bytes'] for a in assets))
            self.assertNotIn('content_target_min_bytes', profile)

    def test_every_size_retains_the_expanded_direct_foundation(self):
        flash, _, _ = self.selection()
        direct_ids = {a['id'] for a in flash if a['format'] != 'zim' and not a['destination'].startswith('SOFTWARE/')}
        for name in ('critical-64gb', 'compact-256gb', 'standard-512gb', 'full-1tb'):
            selected, _, _ = self.selection(self.profiles[name])
            self.assertTrue(direct_ids <= {a['id'] for a in selected}, name)

    def test_exclusions_still_allow_a_deliberately_smaller_custom_library(self):
        original, _, _ = self.selection()
        selected, _, report = self.selection(exclude=['ifixit', 'school-education'])
        self.assertTrue(report['customized'])
        self.assertNotIn('ifixit_en', {a['id'] for a in selected})
        self.assertFalse(any(a['id'].startswith('openstax_') for a in selected))
        self.assertLess(sum(a['size_bytes'] for a in selected), sum(a['size_bytes'] for a in original))

    def test_real_plan_does_not_download_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / 'FLASH'
            with patch('owl.build.download', side_effect=AssertionError('plan must not download')), \
                    patch('owl.download.urlopen', side_effect=AssertionError('plan must not use the network')):
                plan = build(target, catalog=ROOT / 'catalog/library.yaml', profiles_dir=ROOT / 'profiles',
                             profile_name='flash-16gb', plan_only=True, progress=lambda message: None)
            self.assertTrue(plan['in_place_target_budget_fits'])
            self.assertLessEqual(plan['in_place_peak_budget_bytes'], 16_000_000_000)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
