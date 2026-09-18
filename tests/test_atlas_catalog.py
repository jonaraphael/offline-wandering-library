"""Structural policy checks for the real starter atlas; no source bytes are mocked.

These tests render metadata into memory against an empty temporary target. They
do not assert that content is downloaded or verified. Actual-file checks belong
to validate_sources and the end-to-end build tests.
"""
from collections import defaultdict, deque
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from owl.atlas import prepare_atlas
from owl.atlas_model import load_navigation
from owl.catalog import learning_shelves, load_catalog, load_profiles, resolve_content


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("critical-64gb", "compact-256gb", "standard-512gb", "full-1tb")


class ProductionAtlasCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(ROOT / "profiles")
        cls.assets = load_catalog(ROOT / "catalog/library.yaml", cls.profiles)
        cls.navigation = load_navigation(ROOT / "catalog/navigation", cls.assets)
        cls.by_id = {asset["id"]: asset for asset in cls.assets}

    def select(self, profile):
        assets, _, _ = resolve_content(self.assets, self.profiles[profile],
                                      resources_path=ROOT / "catalog/resources.yaml")
        return assets

    def reachable(self, entrances):
        children = defaultdict(set)
        for identity, topic in self.navigation["topics"].items():
            for parent in topic["parents"]:
                children[parent].add(identity)
        result = set(entrances)
        pending = deque(result)
        while pending:
            for child in children[pending.popleft()] - result:
                result.add(child)
                pending.append(child)
        return result

    def render(self, assets, navigation=None):
        # The renderer is pure. A nonexistent corpus is intentional here: do
        # not create fake PDFs or label this as byte-integrity validation.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve()
            result = prepare_atlas(target, assets, navigation or self.navigation)
            self.assertEqual(list(target.iterdir()), [])
        return result

    def test_all_resolved_critical_sources_have_subject_routes(self):
        subjects = self.reachable(self.navigation["entrances"]["subjects"])
        mapped = {row["asset_id"] for row in self.navigation["assignments"]
                  if row["topic_id"] in subjects}
        critical = {asset["id"] for asset in self.assets
                    if asset.get("critical") and asset.get("status", "resolved") == "resolved"}
        self.assertTrue(critical)
        self.assertEqual(critical - mapped, set())

    def test_required_textbooks_reachable_from_subjects_and_learning(self):
        books = {asset["id"] for asset in self.assets if asset.get("required")
                 and asset.get("status", "resolved") == "resolved" and "textbooks" in learning_shelves(asset)}
        self.assertGreaterEqual(len(books), 7)
        for entrance in ("subjects", "learn"):
            reachable = self.reachable(self.navigation["entrances"][entrance])
            mapped = {row["asset_id"] for row in self.navigation["assignments"] if row["topic_id"] in reachable}
            self.assertEqual(books - mapped, set(), entrance)

    def test_core_sources_are_mapped_under_relevant_domains(self):
        expected = {
            "cert": "health", "medical_bec": "health", "water": "water-hygiene",
            "sanitation": "water-hygiene", "food": "food-growing", "agriculture": "food-growing",
            "electrical_dc": "electricity", "electrical_ac": "electricity", "mechanical": "repair",
            "shelter": "shelter", "survival_shelter": "shelter", "navigation": "navigation-maps",
            "reference": "reference",
        }
        for asset_id, domain in expected.items():
            topics = {row["topic_id"] for row in self.navigation["assignments"] if row["asset_id"] == asset_id}
            self.assertTrue(topics & self.reachable([domain]), (asset_id, domain))
            self.assertFalse(self.by_id[asset_id].get("reader_required"), asset_id)

    def test_each_profile_reports_only_selected_assets_and_honest_coverage(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                selected = self.select(profile)
                pages, report = self.render(selected)
                ids = {asset["id"] for asset in selected}
                expected = ids & {row["asset_id"] for row in self.navigation["assignments"]}
                self.assertEqual(set(report["mapped_asset_ids"]), expected)
                self.assertEqual(set(report["unmapped_assets"]), ids - expected)
                self.assertEqual(report["unmapped_critical"], [])
                self.assertEqual(report["missing_textbook_subject_routes"], [])
                self.assertEqual(report["missing_textbook_learning_routes"], [])
                expected_sections = sum(len(mapping["sections"]) for identity, mapping
                                        in self.navigation["sections"].items() if identity in ids)
                self.assertEqual(report["included_section_count"], expected_sections)
                # Map archives are now pinned sources. Navigation follows the
                # actual selection, including world-for-regional replacement.
                for asset_id in ("map_osm_world", "map_osm_north_america"):
                    self.assertEqual(asset_id in report["mapped_asset_ids"], asset_id in ids)
                self.assertEqual("regional-maps" in report["included_topic_ids"],
                                 bool(ids & {"map_osm_north_america", "regional_topographic_maps"}))
                self.assertEqual("world-maps" in report["included_topic_ids"], "map_osm_world" in ids)
                self.assertTrue(pages)

    def test_acquired_publisher_documents_have_relevant_whole_file_routes(self):
        families = {
            "hesperian_en_dent_": "dental-care", "hesperian_en_midw_": "midwifery",
            "hesperian_en_dvc_": "disability-support", "hesperian_en_hcwb_": "vision-support",
            "hesperian_en_cgeh_": "community-environment", "hesperian_en_hhwl_": "health-worker-education",
            "hesperian_en_wtnd_": "clinical-medicine", "hesperian_en_wwhnd_": "womens-health",
            "who_emergency_": "emergency-care",
        }
        pairs = {(row["asset_id"], row["topic_id"]) for row in self.navigation["assignments"]}
        for prefix, topic in families.items():
            assets = [asset for asset in self.assets if asset["id"].startswith(prefix)]
            self.assertTrue(assets, prefix)
            self.assertTrue(all((asset["id"], topic) in pairs for asset in assets), prefix)
        for asset_id, topic in {
            "docs_progit": "computing", "openstax_astronomy_2e": "astronomy",
            "openstax_physics": "physics", "openstax_microbiology": "biology",
            "fao_compost_en": "soil-compost", "fao_poultry": "small-livestock",
            "fao_seed_storage": "seed-storage", "fao_aquaponics": "aquaponics",
        }.items():
            self.assertIn((asset_id, topic), pairs)

    def test_starter_whole_document_routes_do_not_invent_sections_or_figures(self):
        self.assertFalse(self.navigation["sections"], "Review this starter-policy test when reviewed maps are published")
        self.assertTrue(all(row["section_id"] is None for row in self.navigation["assignments"]))
        pages, report = self.render(self.select("critical-64gb"))
        self.assertEqual(report["included_section_count"], 0)
        for page in pages.values():
            self.assertNotIn('aria-label="Verified section illustrations"', page)
            self.assertNotIn(">Open this section</a>", page)
            self.assertNotIn("#page=", page)

    def test_missing_editorial_assignment_is_reported_without_automatic_mapping(self):
        navigation = deepcopy(self.navigation)
        navigation["assignments"] = [row for row in navigation["assignments"] if row["asset_id"] != "mechanical"]
        _, report = self.render(self.select("critical-64gb"), navigation)
        self.assertIn("mechanical", report["unmapped_critical"])
        self.assertNotIn("maintenance", report["included_topic_ids"])


if __name__ == "__main__":
    unittest.main()
