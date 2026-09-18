"""Check the real resource recipe and its profile policies without downloads."""
from pathlib import Path
import unittest

from owl.catalog import capacity_plan, learning_coverage, load_catalog, load_profiles, resolve_content
from owl.resources import load_resources

ROOT = Path(__file__).resolve().parents[1]
LARGE = ('compact-256gb', 'standard-512gb', 'full-1tb')


class ProductionLearningCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(ROOT / 'profiles')
        cls.assets = load_catalog(ROOT / 'catalog/library.yaml', cls.profiles)
        cls.registry = ROOT / 'catalog/resources.yaml'
        cls.resources = load_resources(cls.registry, cls.assets)

    def selection(self, name, **kwargs):
        return resolve_content(self.assets, self.profiles[name], resources_path=self.registry, **kwargs)

    def test_all_numbered_resources_and_defaults_match_acquisition_list(self):
        self.assertEqual({r['number'] for r in self.resources.values() if r['number']}, set(range(1,47)))
        expected = [set(range(1,19)), set(range(1,32)), set(range(1,37)) | {42,43,44,46}]
        for name, numbers in zip(LARGE, expected):
            _, _, report = self.selection(name)
            actual = {self.resources[r]['number'] for r in report['selected_ids'] if self.resources[r]['number']}
            self.assertEqual(actual, numbers)
            self.assertIn('owl-direct-core', report['selected_ids'])
            self.assertIn('archive-readers', report['auto_included_ids'])
            self.assertNotIn('khan-remaining', report['selected_ids'])

    def test_all_large_profiles_keep_full_english_wikipedia_and_readers(self):
        for name in LARGE:
            assets, _, report = self.selection(name)
            ids = {a['id'] for a in assets}
            self.assertIn('wikipedia_en', ids)
            self.assertNotIn('wikipedia_en_nopic', ids)
            self.assertTrue({'kiwix_windows','kiwix_linux','kiwix_macos','kiwix_android'} <= ids)
            self.assertTrue(report['incomplete_resources'])

    def test_books_follow_requested_defaults_and_critical_baseline_survives(self):
        for name, count in [('critical-64gb',7), ('compact-256gb',2), ('standard-512gb',22), ('full-1tb',22)]:
            assets, _, _ = self.selection(name)
            coverage = learning_coverage(assets)
            self.assertEqual(coverage['textbooks']['required_critical_count'], count)
            self.assertGreaterEqual(coverage['illustrated-guides']['required_critical_count'], 8)
            core = [i for i,a in enumerate(assets) if a.get('critical')]
            zim = [i for i,a in enumerate(assets) if a['format']=='zim']
            if zim:self.assertLess(max(core), min(zim))

    def test_map_replacement_and_survivor_budgets(self):
        for name, map_budget, tier in [('compact-256gb',10_000_000_000,None), ('standard-512gb',51_000_000_000,75_000_000_000), ('full-1tb',30_000_000_000,100_000_000_000)]:
            assets, unresolved, report = self.selection(name)
            rows = {r['id']:r for r in report['resource_rows']}
            self.assertEqual(rows['regional-maps']['effective_target_bytes'], map_budget)
            if tier:self.assertEqual(rows['survivor-tier-a']['effective_target_bytes'],tier)
            ids = {a['id'] for a in assets}
            self.assertEqual('map_osm_north_america' in ids,name=='standard-512gb')
            self.assertEqual('map_osm_world' in ids,name=='full-1tb')
            self.assertIn('regional_topographic_maps', {a['id'] for a in unresolved})

    def test_planning_targets_are_not_fabricated_download_bytes(self):
        for name in LARGE:
            assets, _, report = self.selection(name)
            plan = capacity_plan(assets,self.profiles[name],report)
            self.assertLess(plan['content_bytes'], report['content_target_bytes'])
            self.assertFalse(plan['content_complete'])
            self.assertLessEqual(plan['planned_final_bytes']+plan['reserve_bytes'],plan['capacity_bytes'])
        # Remaining 1TB budget funds ordinary directly readable copies, rather
        # than unwanted languages or non-core Khan material.
        assets,_,report=self.selection('full-1tb')
        self.assertEqual(capacity_plan(assets,self.profiles['full-1tb'],report)['target_window_status'],'in-range')
        self.assertIn('direct-reading-expansion',report['selected_ids'])

    def test_personal_selection_can_remove_books_or_replace_language(self):
        assets,_,report=self.selection('full-1tb',include=['37'],exclude=['22,36'])
        self.assertNotIn('wikipedia-es',report['selected_ids'])
        self.assertIn('wikipedia-fr',report['selected_ids'])
        self.assertFalse(any(a['id'].startswith('openstax_') for a in assets))
        assets,_,report=self.selection('critical-64gb',exclude=['22'])
        self.assertEqual(learning_coverage(assets)['textbooks']['count'],2)
        self.assertTrue(report['customized'])


if __name__ == '__main__':
    unittest.main()
