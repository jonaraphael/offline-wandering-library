"""Repository policy: every production drive includes the core learning library.

These checks read the real recipe without downloading content. Fixed policy
floors deliberately remain independent of configurable profile minima, so
reducing a profile's declared floor cannot silently remove the core collection.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from owl.catalog import (
    CatalogError,
    capacity_plan,
    learning_coverage,
    learning_shelves,
    load_catalog,
    load_profiles,
    select_profile,
)


REPOSITORY = Path(__file__).resolve().parents[1]
PRODUCTION_PROFILES = ("critical-64gb", "compact-256gb", "standard-512gb", "full-1tb")
POLICY_FLOORS = {"textbooks": 7, "illustrated-guides": 8}
CORE_SUBJECTS = {
    "mathematics": {"openstax_prealgebra_2e"},
    "physics": {"openstax_college_physics_2e"},
    "chemistry": {"openstax_chemistry_2e"},
    "biology": {"openstax_biology_2e"},
    "anatomy": {"openstax_anatomy_and_physiology_2e"},
    "electrical": {"electrical_dc", "electrical_ac"},
}
ORDINARY_FORMATS = {"html", "htm", "pdf", "txt", "md", "png", "jpg", "jpeg"}


class ProductionLearningCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(REPOSITORY / "profiles")
        cls.assets = load_catalog(REPOSITORY / "catalog/library.yaml", cls.profiles)

    def test_every_production_profile_preserves_fixed_core_coverage(self):
        for name in PRODUCTION_PROFILES:
            with self.subTest(profile=name):
                profile = self.profiles[name]
                selected, _ = select_profile(self.assets, profile)
                coverage = learning_coverage(selected)
                for shelf, floor in POLICY_FLOORS.items():
                    self.assertGreaterEqual(profile.get("minimum_coverage", {}).get(shelf, 0), floor)
                    self.assertGreaterEqual(coverage[shelf]["required_critical_count"], floor)
                plan = capacity_plan(selected, profile)
                self.assertEqual(plan["learning_coverage"], coverage)
                self.assertLessEqual(
                    plan["estimated_final_bytes"] + plan["reserve_bytes"],
                    profile["capacity_bytes"],
                )

    def test_core_subject_textbooks_are_present_direct_illustrated_and_required(self):
        for name in PRODUCTION_PROFILES:
            selected, _ = select_profile(self.assets, self.profiles[name])
            by_id = {asset["id"]: asset for asset in selected}
            for subject, identities in CORE_SUBJECTS.items():
                for identity in identities:
                    with self.subTest(profile=name, subject=subject, textbook=identity):
                        self.assertIn(identity, by_id)
                        textbook = by_id[identity]
                        self.assertEqual(textbook["category"], subject)
                        self.assertEqual(textbook["resource_type"], "textbook")
                        self.assertEqual(textbook["status"], "resolved")
                        self.assertTrue(textbook["required"])
                        self.assertTrue(textbook["critical"])
                        self.assertTrue(textbook["illustrated"])
                        self.assertIn(textbook["format"].lower(), ORDINARY_FORMATS)
                        self.assertFalse(textbook.get("reader_required"))
                        self.assertNotIn(textbook["destination"].split("/")[0], {"ZIM", "SOFTWARE"})
                        self.assertEqual(learning_shelves(textbook), {"textbooks", "illustrated-guides"})

    def test_core_learning_downloads_precede_every_large_archive(self):
        for name in PRODUCTION_PROFILES:
            with self.subTest(profile=name):
                profile = self.profiles[name]
                selected, _ = select_profile(self.assets, profile)
                core_positions = [
                    index for index, asset in enumerate(selected)
                    if asset.get("required") and asset.get("critical") and learning_shelves(asset)
                ]
                archive_positions = [
                    index for index, asset in enumerate(selected) if asset["format"].lower() == "zim"
                ]
                self.assertTrue(core_positions)
                if archive_positions:
                    self.assertLess(max(core_positions), min(archive_positions))
                # Editing the catalog's physical order must not change priority.
                reversed_selection, _ = select_profile(list(reversed(self.assets)), profile)
                self.assertEqual(
                    [asset["id"] for asset in selected],
                    [asset["id"] for asset in reversed_selection],
                )

    def test_profile_selection_rejects_loss_of_required_critical_textbooks(self):
        for name in PRODUCTION_PROFILES:
            for field in ("required", "critical"):
                with self.subTest(profile=name, removed_flag=field):
                    changed = [
                        {**asset, field: False} if asset.get("resource_type") == "textbook" else dict(asset)
                        for asset in self.assets
                    ]
                    with self.assertRaisesRegex(CatalogError, "required critical textbooks"):
                        select_profile(changed, self.profiles[name])

    def test_optional_critical_textbook_cannot_displace_required_core_downloads(self):
        template = next(asset for asset in self.assets if asset["id"] == "openstax_prealgebra_2e")
        for name in PRODUCTION_PROFILES:
            with self.subTest(profile=name):
                # Selection-only fixture: making the optional book tiny checks
                # that size ordering cannot put it before the required core.
                optional = {**template, "id": "optional_priority_fixture", "required": False,
                            "size_bytes": 1, "destination": "BOOKS/TEXTBOOKS/optional.txt",
                            "profiles": [name]}
                selected, _ = select_profile([optional, *self.assets], self.profiles[name])
                optional_position = next(index for index, asset in enumerate(selected) if asset["id"] == optional["id"])
                core_positions = [
                    index for index, asset in enumerate(selected)
                    if asset.get("required") and asset.get("critical") and learning_shelves(asset)
                ]
                self.assertLess(max(core_positions), optional_position)

    def test_archive_and_software_metadata_never_count_as_direct_learning(self):
        for asset in self.assets:
            if (asset["format"].lower() not in ORDINARY_FORMATS or asset.get("reader_required")
                    or asset["destination"].split("/")[0] in {"ZIM", "SOFTWARE"}):
                with self.subTest(asset=asset["id"]):
                    self.assertEqual(learning_shelves(asset), set())


if __name__ == "__main__":
    unittest.main()
