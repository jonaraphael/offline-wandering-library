"""Real synthetic PDFs exercise receipt, render and incomplete-scope safeguards."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import runpy
import unittest
from unittest.mock import patch

from owl.acquisition.capture import _digest, _json, normalize_manifest
from owl.acquisition.map_review import MAX_SOURCE_OUTPUT, inspect_capture, inspect_pdf, review_owner, review_write, verified_payload, wait_for_receipt, worker
from owl.safety import SafetyError


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "Requires optional PyMuPDF")
class MapReviewTests(unittest.TestCase):
    def setUp(self):
        import pymupdf
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.staging = self.root / "capture"
        (self.staging / "sources").mkdir(parents=True)
        (self.staging / "receipts").mkdir()
        self.output = self.root / "review"
        with pymupdf.open() as document:
            page = document.new_page(width=800, height=1000)
            page.insert_text((40, 50), "SCALE 1:24 000\n2024\nMap legend and notice")
            self.data = document.tobytes()
        self.source = {"id": "map-one", "source_url": "https://example.org/map.pdf", "version": "2024-01-01",
            "size_bytes": len(self.data), "resource_ids": ["regional-maps"], "sha256": None,
            "metadata_evidence": [{"url": "https://example.org/metadata", "sha256": "a" * 64}],
            "publisher_checksums": {}, "map_metadata": {"scale": 24000}, "fullasset_metadata": {"format": "pdf"}}
        self.manifest = normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": "map-test", "sources": [self.source],
            "budget": {"download_bytes": len(self.data), "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0},
            "blockers": ["Coastal fine-scale gaps remain"], "coverage": {"required_scale_complete": False}})
        self.digest = _digest(self.manifest)
        self.receipt = {"source_id": "map-one", "source_record_sha256": _digest(self.source), "manifest_sha256": self.digest,
            "source_url": self.source["source_url"], "version": self.source["version"], "relative_path": "sources/map-one",
            "size_bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(),
            "metadata_evidence": self.source["metadata_evidence"], "publisher_checksums_verified": {},
            "content_ready": False, "status": "captured_awaiting_review"}
        (self.staging / "manifest.json").write_bytes(_json(self.manifest))
        (self.staging / "owner.json").write_bytes(_json({"owner": "owl-acquisition-capture", "manifest_sha256": self.digest}))
        (self.staging / "sources/map-one").write_bytes(self.data)
        (self.staging / "receipts/map-one.json").write_bytes(_json(self.receipt))

    def test_source_and_receipt_identity_are_bound(self):
        self.assertEqual(verified_payload(self.staging, self.source, self.receipt, self.digest), self.data)
        for change in ({"source_url": "https://other.org/map.pdf"}, {"relative_path": "../map.pdf"},
                       {"content_ready": True}, {"source_record_sha256": "b" * 64}, {"metadata_evidence": []}):
            with self.subTest(change=change), self.assertRaises(SafetyError):
                verified_payload(self.staging, self.source, {**self.receipt, **change}, self.digest)
        (self.staging / "sources/map-one").write_bytes(self.data[:-1] + b"!")
        with self.assertRaisesRegex(SafetyError, "whole-file receipt"):
            verified_payload(self.staging, self.source, self.receipt, self.digest)

    def test_render_checks_do_not_approve_content_or_geography(self):
        result, images = inspect_pdf(self.data, self.source, render=True)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(len(images), 2)
        self.assertFalse(result["geographic_coverage_approved"])
        self.assertTrue(all(payload.startswith(b"\x89PNG") for _, payload in images))
        wrong = deepcopy(self.source)
        wrong["map_metadata"]["scale"] = 100000
        wrong["version"] = "1984"
        result, _ = inspect_pdf(self.data, wrong)
        self.assertFalse(result["checks"]["scale_label_present"])
        self.assertFalse(result["checks"]["edition_year_in_page_text"])
        self.assertFalse(result["checks"]["every_page_rendered"])

    def test_whole_scope_retains_required_coverage_blockers(self):
        result = inspect_capture(self.staging, self.output, render=True, reserve=0)
        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(result["inspected_sources"], 1)
        self.assertFalse(result["content_ready"])
        self.assertEqual(result["blockers"], self.manifest["blockers"])
        self.assertFalse(result["coverage"]["required_scale_complete"])
        self.assertFalse(result["geographic_coverage_approved"])

    def test_missing_capture_is_incomplete_and_never_opens_unreceipted_file(self):
        (self.staging / "receipts/map-one.json").unlink()
        result = inspect_capture(self.staging, self.output, reserve=0)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["status_counts"], {"pending_capture": 1})
        self.assertEqual(result["inspected_sources"], 0)

    def test_cached_evidence_still_verifies_source_and_repairs_changed_render(self):
        owner = review_owner(self.output, self.digest, 10_000_000_000, 0)
        task = {"staging": str(self.staging), "output": str(self.output / "map-one"), "source": self.source,
            "receipt": self.receipt, "manifest_sha256": self.digest, "render": True,
            "review_root": str(self.output), "review_owner": owner}
        first = worker(task)
        self.assertEqual(worker(task), first)
        image = self.output / "map-one" / first["renders"][0]["path"]
        image.write_bytes(b"bad")
        self.assertEqual(worker(task), first)
        self.assertNotEqual(image.read_bytes(), b"bad")
        (self.staging / "sources/map-one").write_bytes(self.data[:-1] + b"!")
        with self.assertRaises(SafetyError):
            worker(task)

    def test_refuses_capture_writes_and_inadequate_review_budget(self):
        with self.assertRaisesRegex(SafetyError, "separate"):
            inspect_capture(self.staging, self.staging / "preview")
        with self.assertRaisesRegex(SafetyError, "reserve"):
            inspect_capture(self.staging, self.output, output_budget=MAX_SOURCE_OUTPUT, reserve=0)

    def test_follower_stops_when_capture_fails_without_reading_unreceipted_body(self):
        owner = review_owner(self.output, self.digest, 10_000_000_000, 0)
        with patch("owl.jobs.status_job", return_value={"job_id": "test", "state": "failed", "worker_active": False}), \
                patch("owl.acquisition.map_review.time.sleep") as sleep:
            self.assertFalse(wait_for_receipt(self.root / "job", self.root / "missing", self.output, float("inf"), owner))
            sleep.assert_not_called()
        job = self.root / "job"
        job.mkdir()
        (job / "recipe.json").write_bytes(_json({"kind": "acquisition", "target": str(self.root / "other")}))
        with self.assertRaisesRegex(SafetyError, "matching full-scope"):
            inspect_capture(self.staging, self.output, follow_job=job)

    def test_unowned_or_mismatched_directory_and_live_space_are_rejected(self):
        self.output.mkdir()
        (self.output / "unrelated.txt").write_text("Keep me")
        with self.assertRaisesRegex(SafetyError, "no matching owner"):
            inspect_capture(self.staging, self.output, reserve=0)
        owned = self.root / "owned"
        owner = review_owner(owned, self.digest, 10_000_000_000, 100)
        with self.assertRaisesRegex(SafetyError, "ownership"):
            review_owner(owned, "b" * 64, 10_000_000_000, 100)
        with patch("owl.acquisition.map_review.shutil.disk_usage") as usage:
            usage.return_value.free = 101
            with self.assertRaisesRegex(SafetyError, "reserve"):
                review_write(owned, owned / "new.json", b"{}\n", owner)
        self.assertFalse((owned / "new.json").exists())

    def test_relocation_preserves_evidence_bytes_and_only_removes_verified_old_copies(self):
        result = inspect_capture(self.staging, self.output, render=True, reserve=0)
        previous = {str(p.relative_to(self.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.output.rglob("*") if p.is_file()}
        relocate = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/relocate_map_review.py"))["relocate"]
        destination = self.root / "staged-review"
        moved = relocate(self.output, destination, self.staging, budget=10_000_000_000, reserve=0)
        preserved = destination / moved["preserved_directory"]
        self.assertEqual({name: hashlib.sha256((preserved / name).read_bytes()).hexdigest() for name in previous}, previous)
        self.assertEqual([p.name for p in self.output.iterdir()], ["relocation.json"])
        self.assertEqual((self.staging / "sources/map-one").read_bytes(), self.data)
        self.assertEqual(json.loads((preserved / "report.json").read_text())["manifest_sha256"], result["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
