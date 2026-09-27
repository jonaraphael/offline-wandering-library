"""Trial status respects filtered identities and cannot create ownership."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.capture import _digest, _json, load_manifest, normalize_manifest


class TrialStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        spec = importlib.util.spec_from_file_location("trial_status", Path(__file__).resolve().parents[1] / "scripts/acquisition_trial_status.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.ROOT = self.root
        self.staging = self.root / "staging"
        self.staging.mkdir()
        source = {"id": "sheet", "source_url": "https://example.org/sheet.pdf", "version": "2024", "size_bytes": 32,
            "resource_ids": ["regional-maps"], "sha256": None,
            "metadata_evidence": [{"url": "https://example.org/meta", "sha256": "a" * 64}]}
        manifest = normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": "map", "profile": "full-1tb",
            "sources": [source], "budget": {"download_bytes": 32, "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0}})
        (self.root / "manifest.json").write_bytes(_json(manifest))
        self.filtered = load_manifest(self.root / "manifest.json", profile="full-1tb", resource_ids=["regional-maps"])
        capture = self.staging / "maps"
        capture.mkdir()
        self.owner = {"owner": "owl-acquisition-capture", "manifest_sha256": _digest(self.filtered)}
        (capture / "owner.json").write_bytes(_json(self.owner))
        (capture / "manifest.json").write_bytes(_json(self.filtered))
        self.batch = {"id": "maps", "staging": "maps", "manifest": "manifest.json", "profile": "full-1tb", "resource_ids": ["regional-maps"]}

    def report(self, batches):
        return self.module.report(self.staging, {"schema_version": 1, "shared_reserve_bytes": 0, "batches": batches})

    def test_filtered_manifest_matches_captured_owner(self):
        result = self.report([self.batch])
        self.assertNotEqual(result["batches"][0]["state"], "exception")
        self.assertTrue(result["combined_declared_phases_fit"])
        unfiltered = {key: value for key, value in self.batch.items() if key not in {"profile", "resource_ids"}}
        self.assertEqual(self.report([unfiltered])["batches"][0]["state"], "exception")

    def test_unowned_existing_directory_is_never_adopted(self):
        marker = self.staging / "maps/owner.json"
        marker.unlink()
        self.assertEqual(self.report([self.batch])["batches"][0]["state"], "exception")
        self.assertFalse(marker.exists())

    def test_review_budget_source_binding_and_pending_report_are_verified(self):
        review = self.staging / "review"
        review.mkdir()
        owner = {"schema_version": 1, "owner": "owl-map-pdf-review", "manifest_sha256": self.owner["manifest_sha256"],
            "output_budget_bytes": 1000000, "reserve_bytes": 0}
        (review / "owner.json").write_bytes(_json(owner))
        (review / "report.json").write_bytes(_json({"manifest_sha256": owner["manifest_sha256"], "content_ready": False,
            "status": "awaiting_review", "inspected_sources": 1, "requested_sources": 1, "failed_check_counts": {},
            "rows": [{"source_id": "sheet", "status": "inspected_awaiting_review"}]}))
        batch = {"id": "map-review", "staging": "review", "review_peak_bytes": 1000000,
            "review_owner": "owl-map-pdf-review", "source_staging": "maps"}
        row = self.report([batch])["batches"][0]
        self.assertEqual(row["inspected_sources"], 1)
        self.assertEqual(row["inspection_state"], "awaiting_review")
        for change in ({"output_budget_bytes": 900000}, {"manifest_sha256": "b" * 64}):
            (review / "owner.json").write_bytes(_json({**owner, **change}))
            self.assertEqual(self.report([batch])["batches"][0]["state"], "exception")


if __name__ == "__main__":
    unittest.main()
