"""Production priorities, real coverage and finished alternatives are enforceable."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from owl.catalog import CatalogError, capacity_plan, load_catalog, load_profiles, resolve_content
from owl.content_policy import audit_assets
from owl.resources import load_resources
from owl.utility_policy import require_utility_policy
ROOT=Path(__file__).resolve().parents[1]

class ProductionLearningCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles=load_profiles(ROOT/'profiles');cls.assets=load_catalog(ROOT/'catalog/library.yaml',cls.profiles)
        cls.path=ROOT/'catalog/resources.yaml';cls.resources=load_resources(cls.path,cls.assets)
    def selection(self,name,**kwargs):return resolve_content(self.assets,self.profiles[name],resources_path=self.path,**kwargs)
    def test_every_selectable_file_and_default_passes_both_policies(self):
        self.assertTrue(audit_assets(self.assets)['compliant'])
        reports=require_utility_policy(self.assets,self.resources,self.profiles,self.path)
        self.assertEqual({r['profile'] for r in reports},{'flash-16gb','critical-64gb','compact-256gb','standard-512gb','full-1tb'})
        self.assertFalse(any(a.get('generation') for a in self.assets))
    def test_missing_classification_and_quotas_fail_closed(self):
        assets=deepcopy(self.assets);assets[0].pop('utility_tier')
        with self.assertRaisesRegex(CatalogError,'utility_tier'):require_utility_policy(assets,self.resources,self.profiles,self.path)
        profiles=deepcopy(self.profiles);profiles['flash-16gb']['minimum_coverage']={'textbooks':62}
        with self.assertRaisesRegex(CatalogError,'quotas'):require_utility_policy(self.assets,self.resources,profiles,self.path)
    def test_college_and_stories_are_opt_in_while_school_and_trades_are_default(self):
        for name in self.profiles:
            if name=='demo':continue
            selected,unresolved,report=self.selection(name);ids={a['id'] for a in selected}
            self.assertFalse(unresolved);self.assertFalse(report['incomplete_resources'])
            self.assertFalse(any(a['utility_tier']=='NONESSENTIAL' for a in selected))
            self.assertTrue({'openstax_physics','openstax_algebra_1','usfs_ax_manual','usfs_crosscut_manual','fao_beekeeping_visual','appropedia_en'}<=ids)
            self.assertNotIn('openstax_calculus_volume_1',ids)
        selected,_,_=self.selection('full-1tb',include=['openstax-core','childrens-library','linux-programming-docs'])
        ids={a['id'] for a in selected};self.assertIn('openstax_calculus_volume_1',ids)
        self.assertTrue({'bookdash_pdf_amazing_daisy','docs_bash_published_pdf'}<=ids)
        self.assertTrue(audit_assets(selected)['compliant'])
    def test_map_packages_are_real_and_larger_sizes_do_not_invent_content(self):
        for name in ['compact-256gb','standard-512gb','full-1tb']:
            selected,_,report=self.selection(name);ids={a['id'] for a in selected}
            self.assertEqual('map_osm_north_america' in ids,name=='compact-256gb')
            self.assertEqual('map_osm_world' in ids,name!='compact-256gb')
            self.assertNotIn('regional_topographic_maps',ids);self.assertIn('wikipedia_en',ids)
            plan=capacity_plan(selected,self.profiles[name],report);self.assertTrue(plan['in_place_target_budget_fits'])
        standard={a['id'] for a in self.selection('standard-512gb')[0]}
        full={a['id']:a for a in self.selection('full-1tb')[0]}
        self.assertTrue(standard <= full.keys())
        # Growth is backed by finished source receipts, not a larger-drive quota.
        batch=json.loads((ROOT/'catalog/acquisition/practical-discovery-20260928.json').read_text())
        for receipt in batch['assets']:
            self.assertIn(receipt['id'], full.keys()-standard)
            self.assertEqual(full[receipt['id']]['sha256'], receipt['sha256'])
            self.assertEqual(full[receipt['id']]['size_bytes'], receipt['size_bytes'])
    def test_review_preserves_rejected_assets_and_coverage_limits(self):
        review=json.loads((ROOT/'catalog/content-review.json').read_text());ids={a['id'] for a in self.assets}
        self.assertEqual(len(review['assets']),review['before']['checked_assets'])
        for row in review['assets']:
            self.assertIn(row['utility_tier'],['CRITICAL','USEFUL','NONESSENTIAL'])
            if row['action']=='retained':self.assertIn(row['asset_id'],ids)
            else:self.assertIsNotNone(row['coverage_limit'])
        for replacements in review['replacement_groups'].values():self.assertTrue(set(replacements)<=ids)
        for evidence in review['new_download_evidence']:
            asset=next(a for a in self.assets if a['id']==evidence['id'])
            self.assertEqual(asset['sha256'],evidence['sha256']);self.assertEqual(asset['size_bytes'],evidence['size_bytes'])
