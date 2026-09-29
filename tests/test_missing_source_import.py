"""Import preserved missing-source evidence without requesting publisher bytes."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from owl import jobs
from owl.acquisition import capture as capture_module
from owl.download import DownloadError
from owl.safety import SafetyError


class Response(io.BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url, self.status = url, 200
        self.headers = {"Content-Length": str(len(body))}


class MissingSourceImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.staging = self.root / "capture"
        self.job = self.root / "failed-job"
        self.manifest = self.root / "manifest.json"
        self.evidence_path = self.root / "retry-evidence.json"
        self.body = b"frozen publisher source"
        self.document = {
            "schema_version": 1, "kind": "acquisition", "id": "import-fixture",
            "sources": [{"id": identity, "resource_ids": ["reference"],
                         "source_url": "https://publisher.test/" + identity, "version": "1",
                         "size_bytes": len(self.body), "sha256": hashlib.sha256(self.body).hexdigest(),
                         "metadata_evidence": [{"url": "https://publisher.test/metadata", "sha256": "b" * 64}]}
                        for identity in ("before", "missing", "after")],
            "budget": {"download_bytes": 3 * len(self.body), "expanded_bytes": 0,
                       "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0},
        }
        self.write(self.manifest, self.document)
        repo = self.root / "repo"
        source = repo / "src/owl/fixture.py"
        source.parent.mkdir(parents=True)
        source.write_text("# Independent snapshot fixture.\n", encoding="utf-8")
        for target, options in (
            ("owl.jobs.REPO_ROOT", {"new": repo}),
            ("owl.download.urlopen", {"side_effect": AssertionError("Unexpected network access")}),
            ("owl.jobs.subprocess.Popen", {"side_effect": AssertionError("Unexpected detached worker")}),
        ):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)
        with patch.object(jobs, "_launch", return_value={"state": "starting"}):
            jobs.start_acquisition_job(self.manifest, self.staging, job_dir=self.job, reserve_bytes=0)

        def old_capture(request, **kwargs):
            if request.full_url.endswith("/missing"):
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            return Response(self.body, request.full_url)

        with patch("owl.download.urlopen", side_effect=old_capture):
            with self.assertRaises(DownloadError):
                self.capture()
        self.assertTrue((self.staging / "receipts/before.json").is_file())
        self.assertFalse((self.staging / "exceptions").exists())
        self.assertFalse((self.staging / "sources/after").exists())
        job_id = json.loads((self.job / "owner.json").read_text())["job_id"]
        self.status = {"schema_version": 1, "job_id": job_id, "run_id": "second-failure",
                       "state": "failed", "phase": "acquisition", "exit_code": 1,
                       "active_asset": "missing", "error_type": "DownloadError",
                       "error": "missing: download failed: HTTP Error 404: Not Found",
                       "finished_at": "2026-09-27T12:01:00+00:00"}
        source = self.document["sources"][1]
        self.evidence = {
            "schema_version": 1, "content_ready": False,
            "new_evidence": {key: source[key] for key in ("id", "source_url", "size_bytes")},
            "failed_status": {**self.status, "run_id": "first-failure",
                              "finished_at": "2026-09-27T12:00:00+00:00"},
        }
        self.write(self.job / "status.json", self.status)
        self.write(self.evidence_path, self.evidence)
        # A real failed worker leaves this lock file behind.
        (self.job / "worker.lock").write_bytes(b"\0")

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def capture(self, **kwargs):
        return capture_module.capture(self.manifest, self.staging, reserve_bytes=0,
                                      progress=lambda _: None, **kwargs)

    def import_failure(self, **kwargs):
        return capture_module.import_missing_source_failure(
            self.job, self.evidence_path, source_id="missing", **kwargs)

    def saved_files(self, root):
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def test_default_dry_run_verifies_evidence_without_requests_or_mutation(self):
        before = self.saved_files(self.root)
        with patch("owl.download.urlopen", side_effect=AssertionError("Unexpected request")) as opened:
            report = self.import_failure()
        opened.assert_not_called()
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["body_downloads"], 0)
        self.assertIs(report["content_ready"], False)
        self.assertFalse(Path(report["checkpoint"]).exists())
        self.assertEqual(self.saved_files(self.root), before)

    def test_applied_checkpoint_skips_old_404_and_captures_remaining_source(self):
        receipt = self.staging / "receipts/before.json"
        original_receipt = receipt.read_bytes()
        job_files = self.saved_files(self.job)
        with patch("owl.download.urlopen", side_effect=AssertionError("Unexpected import request")) as opened:
            imported = self.import_failure(plan_only=False)
        opened.assert_not_called()
        self.assertEqual(imported["status"], "checkpointed")
        checkpoint = Path(imported["checkpoint"])
        original_checkpoint = checkpoint.read_bytes()
        record = json.loads(original_checkpoint)
        self.assertEqual(record["failed_at"], self.status["finished_at"])
        self.assertEqual(record["http_status"], 404)
        self.assertEqual(record["import_evidence"]["run_ids"], ["first-failure", "second-failure"])
        for key, path in (("recipe", self.job / "recipe.json"),
                          ("status", self.job / "status.json"), ("evidence", self.evidence_path)):
            self.assertEqual(record["import_evidence"][key + "_sha256"],
                             hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(self.saved_files(self.job), job_files)
        calls = []

        def remaining(request, **kwargs):
            calls.append(request.full_url)
            self.assertEqual(request.full_url, self.document["sources"][2]["source_url"])
            return Response(self.body, request.full_url)

        with patch("owl.download.urlopen", side_effect=remaining):
            with self.assertRaises(capture_module.IncompleteCaptureError) as raised:
                self.capture(continue_missing_sources=True)
        self.assertEqual(calls, [self.document["sources"][2]["source_url"]])
        self.assertEqual(raised.exception.report["status"], "incomplete")
        self.assertEqual(raised.exception.report["missing_source_count"], 1)
        self.assertEqual(raised.exception.report["captured_source_count"], 2)
        self.assertEqual(raised.exception.report["reused_sources"], 1)
        self.assertFalse((self.staging / "candidate-fragment.json").exists())
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertEqual(checkpoint.read_bytes(), original_checkpoint)

    def test_mismatched_source_or_failure_evidence_cannot_create_checkpoint(self):
        changes = (
            ("observation", "id", "other"),
            ("observation", "source_url", "https://publisher.test/different"),
            ("observation", "size_bytes", len(self.body) + 1),
            ("previous", "active_asset", "before"),
            ("previous", "job_id", "different-job"),
            ("previous", "run_id", self.status["run_id"]),
            ("previous", "error", "missing: download failed: HTTP Error 410: Gone"),
            ("current", "error", "missing: download failed: HTTP Error 403: Forbidden"),
            ("current", "state", "running"),
        )
        for group, key, value in changes:
            with self.subTest(group=group, key=key):
                evidence, status = deepcopy(self.evidence), deepcopy(self.status)
                target = (evidence["new_evidence"] if group == "observation" else
                          evidence["failed_status"] if group == "previous" else status)
                target[key] = value
                self.write(self.evidence_path, evidence)
                self.write(self.job / "status.json", status)
                with self.assertRaises(SafetyError):
                    self.import_failure(plan_only=False)
                self.assertFalse((self.staging / "exceptions").exists())

    def test_repeated_apply_keeps_checkpoint_and_job_evidence_immutable(self):
        first = self.import_failure(plan_only=False)
        checkpoint = Path(first["checkpoint"])
        before = self.saved_files(self.root)
        timestamp = checkpoint.stat().st_mtime_ns
        with patch.object(capture_module, "_transport_record",
                          side_effect=AssertionError("Existing checkpoint must not be rewritten")):
            second = self.import_failure(plan_only=False)
        self.assertEqual(second, first)
        self.assertEqual(checkpoint.stat().st_mtime_ns, timestamp)
        self.assertEqual(self.saved_files(self.root), before)
        self.write(self.evidence_path, {**self.evidence, "later_note": "changed evidence"})
        with self.assertRaisesRegex(SafetyError, "immutable"):
            self.import_failure(plan_only=False)
        self.assertEqual(checkpoint.read_bytes(), before[str(checkpoint.relative_to(self.root))])

    def test_changed_snapshot_is_rejected_before_checkpointing(self):
        recipe = json.loads((self.job / "recipe.json").read_text())
        captured = Path(recipe["acquisition"]["manifest"])
        changed = deepcopy(self.document)
        changed["sources"][1]["source_url"] = "https://publisher.test/changed"
        self.write(captured, changed)
        with self.assertRaisesRegex(SafetyError, "source/input changed"):
            self.import_failure(plan_only=False)
        self.assertFalse((self.staging / "exceptions").exists())


if __name__ == "__main__":
    unittest.main()
