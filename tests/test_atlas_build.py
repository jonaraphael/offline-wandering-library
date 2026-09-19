"""Offline atlas publication, ownership, integrity, and interruption recovery."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import yaml

from test_core import Fixture
from owl.atlas_build import build_atlas, validate_links
from owl.safety import SafetyError, atomic_write
from owl.verify import verify_drive


class AtlasBuildTests(Fixture):
    def setUp(self):
        super().setUp()
        self.asset.update(resource_type="textbook", illustrated=True)
        self.write_catalog()
        self.nav = self.root / "navigation"
        self.nav.mkdir()
        self.topic_data = {"schema_version": 1, "entrances": {"subjects": ["subject"], "tasks": ["shared"], "learn": ["learn"]},
            "topics": [{"id": "subject", "title": "Science", "description": "A broad subject.", "parents": [], "related": [], "aliases": []},
                       {"id": "learn", "title": "Learning", "description": "Foundations.", "parents": [], "related": [], "aliases": []},
                       {"id": "shared", "title": "Shared topic", "description": "One source, several routes.", "parents": ["subject", "learn"], "related": [], "aliases": ["Test topic"]}]}
        (self.nav / "topics.yaml").write_text(yaml.safe_dump(self.topic_data), encoding="utf-8")
        self.assignments = {"schema_version": 1, "assignments": [{"topic_id": "shared", "asset_id": "fixture", "purpose": "explanation"}]}
        self.write_assignments()
        self.drive = self.root / "drive"
        self.library = self.drive / "LIBRARY"

    def write_assignments(self):
        (self.nav / "assignments.yaml").write_text(yaml.safe_dump(self.assignments), encoding="utf-8")

    def atlas(self, **kwargs):
        return build_atlas(self.drive, navigation_dir=self.nav, catalog=self.catalog,
                           profiles_dir=self.profiles, allow_local=True, progress=lambda _: None, **kwargs)

    def check_verified(self):
        counts = verify_drive(self.drive, emit=lambda _: None)
        self.assertEqual(counts["FAILED"] + counts["MISSING"] + counts["UNKNOWN"], 0, counts)
        self.assertEqual({p.name for p in self.drive.iterdir()}, {"START_HERE.html", "LIBRARY"})
        checksum_paths = [line.split("  ", 1)[1] for line in
                          (self.library / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()]
        self.assertIn("START_HERE.html", checksum_paths)
        self.assertIn("LIBRARY/INVENTORY.json", checksum_paths)
        self.assertNotIn("LIBRARY/START_HERE.html", checksum_paths)
        self.assertTrue(all(p == "START_HERE.html" or p.startswith("LIBRARY/") for p in checksum_paths))

    def put_downloaded_files(self):
        destination = self.library / self.asset["destination"]
        destination.parent.mkdir(parents=True)
        destination.write_bytes(self.data)

    def test_post_download_atlas_preserves_search_and_is_deterministic(self):
        self.run_build()
        inventory = json.loads((self.library / "INVENTORY.json").read_text(encoding="utf-8"))
        search_files = inventory["search"]["generated_files"]
        before = {p: ((self.library / p).read_bytes(), (self.library / p).stat().st_mtime_ns) for p in search_files}
        with patch("owl.build.download", side_effect=AssertionError("no downloads")), patch("owl.search.build_search", side_effect=AssertionError("no search rebuild")):
            report = self.atlas(strict_coverage=True)
        self.assertEqual(report["unmapped_critical"], [])
        self.assertIn("INDEX/topics/shared.html", report["generated_files"])
        self.assertIn("LIBRARY/INDEX/topics.html#subjects", (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        self.assertIn('id="searchForm"', (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        self.assertIn('src="LIBRARY/SEARCH/search.js"', (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        first = {p: (self.library / p).read_bytes() for p in report["generated_files"]}
        self.atlas()
        self.assertEqual(first, {p: (self.library / p).read_bytes() for p in first})
        self.assertEqual({p: ((self.library / p).read_bytes(), (self.library / p).stat().st_mtime_ns) for p in search_files}, before)
        self.check_verified()

    def test_full_builder_integrates_atlas_and_disabling_retires_pages(self):
        self.run_build(navigation_dir=self.nav, strict_coverage=True)
        info = json.loads((self.library / "BUILD_INFO.json").read_text(encoding="utf-8"))
        paths = info["navigation"]["generated_files"]
        self.assertIn("INDEX/books.html", paths)
        self.check_verified()
        self.run_build()
        self.assertNotIn("topic-atlas", (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        for relative in paths:
            if relative.endswith(".html"):
                self.assertIn("Unavailable in this build", (self.library / relative).read_text(encoding="utf-8"))
        self.check_verified()

    def test_removed_mapping_retires_old_pages_and_preserves_unrelated_files(self):
        self.run_build()
        self.atlas()
        personal = self.library / "INDEX/topics/personal.txt"
        personal.write_text("keep", encoding="utf-8")
        self.assignments["assignments"] = []
        self.write_assignments()
        report = self.atlas()
        self.assertIn("shared", report["omitted_topic_ids"])
        self.assertIn("Unavailable in this build", (self.library / "INDEX/topics/shared.html").read_text(encoding="utf-8"))
        self.assertEqual(personal.read_text(encoding="utf-8"), "keep")
        counts = verify_drive(self.drive, emit=lambda _: None)
        self.assertEqual((counts["FAILED"], counts["MISSING"], counts["UNKNOWN"]), (0, 0, 1))

    def test_unowned_atlas_collision_is_not_overwritten(self):
        self.run_build()
        destination = self.library / "INDEX/topics/shared.html"
        destination.parent.mkdir()
        destination.write_text("personal", encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "unowned"):
            self.atlas()
        self.assertEqual(destination.read_text(encoding="utf-8"), "personal")

    def test_catalog_only_generation_requires_no_search_or_network(self):
        self.put_downloaded_files()
        self.atlas(profile="test", strict_coverage=True)
        self.assertFalse((self.library / "SEARCH/manifest.js").exists())
        self.assertFalse((self.library / "SEARCH/search.js").exists())
        self.assertIn("has not been built", (self.library / "SEARCH.html").read_text(encoding="utf-8"))
        self.assertIn("Human index only", (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        self.assertNotIn('id="searchForm"', (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        self.assertNotIn("<script", (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        info = json.loads((self.library / "BUILD_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(info["build_kind"], "human-index-only")
        self.check_verified()
        with patch("owl.build.download", side_effect=AssertionError("already downloaded")):
            self.run_build(navigation_dir=self.nav)
        self.assertTrue((self.library / "SEARCH/manifest.js").is_file())
        self.assertTrue((self.library / "SEARCH/search.js").is_file())
        self.assertIn('id="searchForm"', (self.drive / "START_HERE.html").read_text(encoding="utf-8"))
        self.check_verified()

    def test_catalog_only_interruption_retains_support_files_in_manifest(self):
        from owl.atlas_build import write_outputs
        self.put_downloaded_files()
        def interrupted(*args):
            write_outputs(*args)
            raise KeyboardInterrupt
        with patch("owl.atlas_build.write_outputs", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.atlas(profile="test")
        self.assertFalse(json.loads((self.library / ".owl/state.json").read_text(encoding="utf-8"))["complete"])
        self.assertGreater(verify_drive(self.drive, emit=lambda _: None)["FAILED"], 0)
        self.atlas(profile="test")
        self.check_verified()
        self.assertFalse((self.library / ".owl/atlas-job.json").exists())

    def test_catalog_only_rejects_unowned_support_files(self):
        self.put_downloaded_files()
        destination = self.library / "SEARCH.html"
        destination.write_text("personal page", encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "unowned"):
            self.atlas(profile="test")
        self.assertEqual(destination.read_text(encoding="utf-8"), "personal page")

    def test_catalog_only_rejects_unowned_outer_homepage(self):
        self.put_downloaded_files()
        home = self.drive / "START_HERE.html"
        home.write_text("personal homepage", encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "unowned"):
            self.atlas(profile="test")
        self.assertEqual(home.read_text(encoding="utf-8"), "personal homepage")
        self.assertFalse((self.library / "INVENTORY.json").exists())

    def test_interruption_while_adopting_checksum_verified_drive_can_resume(self):
        self.run_build()
        shutil.rmtree(self.library / ".owl")  # Simulate a finished SSD copied without private build state.
        def interrupted(path, data):
            atomic_write(path, data)
            if path.name == "atlas-job.json":
                raise KeyboardInterrupt
        with patch("owl.atlas_build.atomic_write", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.atlas()
        self.atlas()
        self.check_verified()

    def test_incomplete_drive_stays_incomplete_after_usable_human_index(self):
        with patch("owl.search.build_search", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_build()
        self.atlas(profile="test")
        self.assertTrue((self.library / "INDEX/topics.html").is_file())
        self.assertFalse(json.loads((self.library / ".owl/state.json").read_text(encoding="utf-8"))["complete"])
        self.assertEqual(verify_drive(self.drive, emit=lambda _: None)["FAILED"], 1)
        self.run_build(navigation_dir=self.nav)
        self.check_verified()

    def test_adoption_without_private_state_retires_verified_old_atlas_pages(self):
        self.run_build(navigation_dir=self.nav)
        shutil.rmtree(self.library / ".owl")
        self.assignments["assignments"] = []
        self.write_assignments()
        self.atlas()
        self.assertIn("Unavailable in this build", (self.library / "INDEX/topics/shared.html").read_text(encoding="utf-8"))
        self.check_verified()

    def test_changed_source_and_stale_map_fail_before_publication(self):
        self.run_build()
        (self.library / self.asset["destination"]).write_bytes(b"x" * len(self.data))
        with self.assertRaisesRegex(SafetyError, "integrity"):
            self.atlas()
        self.assertFalse((self.library / "INDEX/topics.html").exists())

    def test_strict_coverage_reports_missing_routes(self):
        self.run_build()
        self.assignments["assignments"] = []
        self.write_assignments()
        with self.assertRaisesRegex(SafetyError, "coverage is incomplete"):
            self.atlas(strict_coverage=True)
        self.assertFalse((self.library / "INDEX/topics.html").exists())

    def test_interrupted_job_cannot_name_generated_output_as_source(self):
        self.put_downloaded_files()
        with patch("owl.atlas_build.write_outputs", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.atlas(profile="test")
        path = self.library / ".owl/atlas-job.json"
        job = json.loads(path.read_text(encoding="utf-8"))
        job["inventory"]["assets"][0]["destination"] = "README.txt"
        path.write_text(json.dumps(job), encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "content path"):
            self.atlas(profile="test")

    def test_declared_html_encoding_is_used_for_source_fragment_checks(self):
        self.library.mkdir(parents=True)
        source = self.library / "REFERENCE/utf16.html"
        source.parent.mkdir()
        source.write_text('<h1 id="caf\u00e9">Title</h1>', encoding="utf-16")
        validate_links(self.library, {"INDEX/topics/test.html": '<a href="../../REFERENCE/utf16.html#caf%C3%A9">Section</a>'},
                       [{"destination": "REFERENCE/utf16.html", "text_encoding": "utf-16"}])

    def test_navigation_scripts_allow_only_the_complete_homepage_search_dependency(self):
        runtime = self.library / "SEARCH/search.js"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("/* fixture */", encoding="utf-8")
        manifest = self.library / "SEARCH/manifest.js"
        manifest.write_text("/* fixture */", encoding="utf-8")
        allowed = '<script defer src="LIBRARY/SEARCH/search.js"></script>'
        validate_links(self.library, {"START_HERE.html": allowed})
        for relative, markup in (
            ("INDEX/topics/test.html", allowed),
            ("INDEX/categories.html", allowed),
            ("START_HERE.html", '<script>alert(1)</script>'),
            ("START_HERE.html", '<script defer src="https://example.invalid/a.js"></script>'),
            ("START_HERE.html", '<script defer src="SEARCH/other.js"></script>'),
            ("START_HERE.html", '<script defer type="module" src="LIBRARY/SEARCH/search.js"></script>'),
            ("START_HERE.html", '<script defer src="LIBRARY/SEARCH/search.js">alert(1)</script>'),
            ("START_HERE.html", allowed + allowed),
        ):
            with self.subTest(relative=relative, markup=markup), self.assertRaisesRegex(SafetyError, "Unexpected generated script"):
                validate_links(self.library, {relative: markup})
        manifest.unlink()
        with self.assertRaisesRegex(SafetyError, "Missing automatic search dependency"):
            validate_links(self.library, {"START_HERE.html": allowed})


if __name__ == "__main__":
    unittest.main()
