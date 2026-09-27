"""Automatic postflight checks real completed output without rehashing sources."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from owl.build import build
from owl.postflight import audit_build
from owl.safety import SafetyError
from owl.verify import verify_drive

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


class PostflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline_temp = tempfile.TemporaryDirectory()
        cls.baseline = Path(cls.baseline_temp.name).resolve() / "drive"
        build(cls.baseline, catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
              profile_name="demo", allow_local=True, navigation_dir=ROOT / "catalog/demo-navigation",
              progress=lambda _: None)

    @classmethod
    def tearDownClass(cls):
        cls.baseline_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "drive"
        shutil.copytree(self.baseline, self.root)
        self.library = self.root / "LIBRARY"

    def rewrite(self, relative, transform):
        path = self.library / relative
        value = json.loads(path.read_text())
        transform(value)
        path.write_text(json.dumps(value))

    def test_summary_reports_actual_bytes_selection_and_preceding_verification(self):
        verified = verify_drive(self.root, emit=lambda _: None)
        info = json.loads((self.library / "BUILD_INFO.json").read_text())
        info["verification"] = verified
        # A build has not yet set complete=True when it invokes this function.
        self.rewrite(".owl/state.json", lambda x: x.update(complete=False, phase="postflight"))
        with patch("owl.safety.sha256_file", side_effect=AssertionError("source rehash")):
            report = audit_build(self.root, info=info, run_smoke=False)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["profile"], "demo")
        self.assertEqual(report["verification"]["preceding_counts"], verified)
        self.assertFalse(report["verification"]["source_hashes_repeated"])
        inventory = json.loads((self.library / "INVENTORY.json").read_text())
        self.assertEqual(report["bytes"]["sources"], sum(a["size_bytes"] for a in inventory["assets"]))
        expected = sum(p.stat().st_size for p in self.root.rglob("*")
                       if p.is_file() and ".owl" not in p.parts)
        self.assertEqual(report["bytes"]["managed"], expected)
        self.assertLess(len(json.dumps(report)), 4000)
        self.assertEqual(report["search_smoke"]["status"], "skipped")

    def test_rejects_mismatched_selection_and_missing_source(self):
        self.rewrite("LOCKED_CATALOG.yaml", lambda x: x["assets"].pop())
        with self.assertRaisesRegex(SafetyError, "locked catalog"):
            audit_build(self.root, run_smoke=False)
        shutil.copy2(self.baseline / "LIBRARY/LOCKED_CATALOG.yaml", self.library / "LOCKED_CATALOG.yaml")
        inventory = json.loads((self.library / "INVENTORY.json").read_text())
        (self.library / inventory["assets"][0]["destination"]).unlink()
        with self.assertRaisesRegex(SafetyError, "missing"):
            audit_build(self.root, run_smoke=False)

    def test_rejects_generated_link_and_published_index_manifest_errors(self):
        entry = self.root / "START_HERE.html"
        original = entry.read_bytes()
        entry.write_bytes(original + b'<a href="LIBRARY/missing.txt">Missing</a>')
        with self.assertRaisesRegex(SafetyError, "Missing generated link"):
            audit_build(self.root, run_smoke=False)
        entry.write_bytes(original)
        manifest = self.library / "SEARCH/manifest.js"
        manifest.write_bytes(manifest.read_bytes().replace(b'"version":1', b'"version":2'))
        with self.assertRaisesRegex(SafetyError, "published search manifest"):
            audit_build(self.root, run_smoke=False)

    def test_rejects_coverage_and_capacity_mismatches(self):
        self.rewrite("SEARCH/coverage.json", lambda x: x.update(documents=x["documents"] + 1))
        with self.assertRaisesRegex(SafetyError, "search coverage"):
            audit_build(self.root, run_smoke=False)
        shutil.copy2(self.baseline / "LIBRARY/SEARCH/coverage.json", self.library / "SEARCH/coverage.json")
        self.rewrite("BUILD_INFO.json", lambda x: x["plan"].update(
            index_cache_on_drive=True, index_cache_budget_bytes=x["profile"]["capacity_bytes"]))
        with self.assertRaisesRegex(SafetyError, "capacity"):
            audit_build(self.root, run_smoke=False)

    def test_missing_node_is_explicitly_skipped_or_required(self):
        with patch("owl.postflight.shutil.which", return_value=None):
            report = audit_build(self.root)
            self.assertEqual(report["search_smoke"], {"status": "skipped", "reason": "Node is unavailable"})
            with self.assertRaisesRegex(SafetyError, "Node is required"):
                audit_build(self.root, run_smoke="required")

    def test_completed_summary_exposes_cold_and_warm_cache_counts(self):
        common = dict(catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
                      profile_name="demo", allow_local=True,
                      index_cache_dir=self.root.parent / "cache", progress=lambda _: None)
        cold = build(self.root.parent / "cold", **common)["result"]
        with patch("owl.search._units", side_effect=AssertionError("cache should prevent extraction")):
            warm = build(self.root.parent / "warm", **common)["result"]
        self.assertEqual(cold["cache"]["mode"], "shards")
        self.assertEqual(cold["cache"]["misses"], cold["selection"]["documents"])
        self.assertEqual(warm["cache"]["hits"], warm["selection"]["documents"])
        self.assertEqual(warm["cache"]["misses"], 0)
        self.assertEqual(set(warm["cache"]), {"mode", "hits", "misses", "metadata_reuses"})

    @unittest.skipUnless(NODE, "Node is required for runtime smoke integration")
    def test_real_runtime_search_and_facets_use_selected_inventory(self):
        report = audit_build(self.root, run_smoke="required")["search_smoke"]
        self.assertEqual(report["status"], "passed")
        self.assertGreater(report["positive_queries"], 0)
        self.assertGreater(report["shelf_queries"], 0)
        self.assertGreater(report["chunk_reads"], 0)
        self.assertLessEqual(report["script_bytes_read"], 256 * 1024 * 1024)

    @unittest.skipUnless(NODE, "Node is required for damaged runtime smoke integration")
    def test_real_runtime_detects_damaged_chunk_without_source_rehash(self):
        coverage = json.loads((self.library / "SEARCH/coverage.json").read_text())
        chunk = self.library / "SEARCH/chunks" / coverage["index_sha256"] / "00000000.js"
        data = bytearray(chunk.read_bytes())
        at = data.index(b',0,"') + 4
        data[at] = ord("A") if data[at] != ord("A") else ord("B")
        chunk.write_bytes(data)
        with self.assertRaisesRegex(SafetyError, "search runtime smoke failed"):
            audit_build(self.root, run_smoke="required")

    @unittest.skipUnless(NODE, "Node is required for timeout behavior")
    def test_child_timeout_is_a_compact_failure(self):
        with patch("owl.postflight.subprocess.run", side_effect=subprocess.TimeoutExpired("node", 60)):
            with self.assertRaisesRegex(SafetyError, "exceeded 60 seconds"):
                audit_build(self.root)


if __name__ == "__main__":
    unittest.main()
