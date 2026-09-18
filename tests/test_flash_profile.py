"""The small flash-drive preset is a real, bounded direct-reading selection."""
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
        cls.profiles = load_profiles(ROOT / "profiles")
        cls.assets = load_catalog(ROOT / "catalog/library.yaml", cls.profiles)
        cls.profile = cls.profiles["flash-16gb"]

    def selection(self, profile=None):
        return resolve_content(self.assets, profile or self.profile,
                               resources_path=ROOT / "catalog/resources.yaml")

    def test_complete_fixed_selection_retains_verified_critical_library(self):
        assets, unresolved, resources = self.selection()
        critical, _, _ = self.selection(self.profiles["critical-64gb"])
        self.assertEqual(len(assets), 25)
        self.assertEqual({asset["id"] for asset in assets}, {asset["id"] for asset in critical})
        self.assertEqual(unresolved, [])
        self.assertIsNone(resources)
        for asset in assets:
            with self.subTest(asset=asset["id"]):
                self.assertEqual(asset["status"], "resolved")
                self.assertTrue(asset["required"] and asset["critical"])
                self.assertEqual(asset["format"], "pdf")
                self.assertFalse(asset.get("reader_required"))
                self.assertFalse(asset["destination"].startswith(("SOFTWARE/", "ZIM/")))
                self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")

    def test_textbooks_illustrations_and_emergency_subjects_survive(self):
        assets, _, _ = self.selection()
        coverage = learning_coverage(assets)
        self.assertEqual(coverage["textbooks"]["required_critical_count"], 7)
        self.assertEqual(coverage["illustrated-guides"]["required_critical_count"], 13)
        self.assertTrue({"cert", "medical_bec", "water", "sanitation", "food", "agriculture",
                         "electrical_dc", "electrical_ac", "mechanical", "shelter",
                         "survival_shelter", "navigation", "reference"} <= {asset["id"] for asset in assets})

    def test_final_index_scratch_and_reserve_fit_nominal_16gb(self):
        assets, _, _ = self.selection()
        plan = capacity_plan(assets, self.profile)
        self.assertEqual(plan["capacity_bytes"], 16_000_000_000)
        self.assertGreaterEqual(plan["search_budget_bytes"], 2_000_000_000)
        self.assertGreaterEqual(plan["reserve_bytes"], 2_000_000_000)
        peak = plan["estimated_final_bytes"] + plan["index_scratch_budget_bytes"] + plan["reserve_bytes"]
        self.assertLessEqual(peak, plan["capacity_bytes"])
        # There is no fabricated content target to fill an otherwise useful
        # small drive. Final corpus bytes are the sum of verified asset pins.
        self.assertEqual(plan["content_bytes"], sum(asset["size_bytes"] for asset in assets))
        self.assertNotIn("content_target_min_bytes", self.profile)
        self.assertNotIn("default_resources", self.profile)

    def test_real_plan_needs_no_download_or_zim_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "FLASH"
            with patch("owl.build.download", side_effect=AssertionError("plan must not download")), \
                    patch("owl.download.urlopen", side_effect=AssertionError("plan must not use the network")):
                plan = build(target, catalog=ROOT / "catalog/library.yaml", profiles_dir=ROOT / "profiles",
                             profile_name="flash-16gb", plan_only=True, progress=lambda message: None)
            self.assertTrue(plan["in_place_target_budget_fits"])
            self.assertLessEqual(plan["in_place_peak_budget_bytes"], 16_000_000_000)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
