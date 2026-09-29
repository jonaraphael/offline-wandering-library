"""Missing-source CLI and job boundaries, without network or detached workers."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl import jobs
from owl.acquisition import capture as capture_module
from owl.acquisition.cli import main


class MissingSourceJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.staging = self.root / "capture"
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "kind": "acquisition", "id": "missing-fixture",
            "sources": [{"id": "missing", "resource_ids": ["reference"],
                         "source_url": "https://publisher.test/missing.pdf", "version": "1",
                         "size_bytes": 10, "sha256": "a" * 64,
                         "metadata_evidence": [{"url": "https://publisher.test/metadata",
                                                "sha256": "b" * 64}]}],
            "budget": {"download_bytes": 10, "expanded_bytes": 0, "preview_bytes": 0,
                       "scratch_bytes": 0, "cache_bytes": 0},
        }), encoding="utf-8")
        # Exercise the real snapshotter against a tiny, independent source tree.
        repo = self.root / "repo"
        source = repo / "src/owl/fixture.py"
        source.parent.mkdir(parents=True)
        source.write_text("# Captured test source.\n", encoding="utf-8")
        for target, options in (
            ("owl.jobs.REPO_ROOT", {"new": repo}),
            ("owl.download.urlopen", {"side_effect": AssertionError("Unexpected network access")}),
            ("owl.jobs.subprocess.Popen", {"side_effect": AssertionError("Unexpected detached worker")}),
        ):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)

    def incomplete_report(self):
        return {"operation": "capture", "status": "incomplete", "complete": False,
                "content_ready": False, "source_count": 101, "captured_source_count": 1,
                "missing_source_count": 100, "staging": str(self.staging),
                "exceptions": [{"source_id": f"missing-{number}", "http_status": 404,
                                "detail": "Publisher diagnostic " + "x" * 450}
                               for number in range(100)]}

    def cli(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["build", "--candidate-manifest", str(self.manifest),
                           "--staging-root", str(self.staging), "--reserve-bytes", "0",
                           "--cache-dir", str(self.root / "cache"), *extra])
        return result, stdout.getvalue(), stderr.getvalue()

    def prepare_job(self, name, **options):
        job = self.root / name
        with patch.object(jobs, "_launch", return_value={"state": "starting"}) as launch:
            result = jobs.start_acquisition_job(self.manifest, self.staging, job_dir=job,
                                                reserve_bytes=0, **options)
        self.assertEqual(result["state"], "starting")
        launch.assert_called_once()
        self.assertFalse(self.staging.exists(), "Planning a job must not acquire any source")
        return job, json.loads((job / "recipe.json").read_text())

    def test_foreground_incomplete_is_nonzero_with_bounded_diagnostic(self):
        report = self.incomplete_report()
        with patch.object(capture_module, "capture",
                          side_effect=capture_module.IncompleteCaptureError(report)) as capture:
            code, stdout, stderr = self.cli("--continue-missing-sources")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertLessEqual(len(stderr.encode()), 2048)
        diagnostic = json.loads(stderr)
        self.assertIn("100 required source(s)", diagnostic["error"])
        self.assertIn(str(self.staging / "capture-report.json"), diagnostic["error"])
        self.assertNotIn("Publisher diagnostic", stderr)
        capture.assert_called_once()
        self.assertIs(capture.call_args.kwargs["continue_missing_sources"], True)
        self.assertIs(capture.call_args.kwargs["plan_only"], False)

    def test_detached_cli_forwards_opt_in(self):
        job = self.root / "detached"
        with patch.object(jobs, "start_acquisition_job", return_value={
                "state": "starting", "job_dir": str(job), "job_id": "fixture"}) as start:
            code, stdout, stderr = self.cli("--detach", "--job-dir", str(job),
                                           "--continue-missing-sources")
        self.assertEqual(code, 0, stderr)
        self.assertLessEqual(len(stdout.encode()), 2048)
        start.assert_called_once()
        self.assertIs(start.call_args.kwargs["continue_missing_sources"], True)
        self.assertEqual(start.call_args.kwargs["job_dir"], job)

    def test_job_snapshot_preserves_opt_in_and_default(self):
        for name, options, expected in (("opt-in", {"continue_missing_sources": True}, True),
                                        ("default", {}, False)):
            with self.subTest(name=name):
                job, recipe = self.prepare_job(name, **options)
                self.assertIs(recipe["acquisition"]["kwargs"]["continue_missing_sources"], expected)
                captured = Path(recipe["acquisition"]["manifest"])
                self.assertTrue(captured.is_relative_to(job / "snapshot"))
                self.assertIn(str(captured.relative_to(job / "snapshot")), recipe["snapshot_files"])
                self.assertEqual(captured.read_bytes(), self.manifest.read_bytes())
                self.assertEqual(recipe["kind"], "acquisition")

    def test_incomplete_worker_saves_failed_result_without_retry(self):
        job, recipe = self.prepare_job("worker", continue_missing_sources=True,
                                       max_attempts=3, retry_delay=0)
        run_id = "fixture-run"
        owner = json.loads((job / "owner.json").read_text())
        (job / "status.json").write_text(json.dumps({
            "schema_version": 1, "job_id": owner["job_id"], "run_id": run_id,
            "state": "starting", "phase": "starting", "attempt": 0,
            "started_at": jobs._now(), "heartbeat_at": jobs._now(),
        }), encoding="utf-8")
        report = self.incomplete_report()
        with patch.object(capture_module, "capture",
                          side_effect=capture_module.IncompleteCaptureError(report)) as capture, \
                patch("owl.jobs.threading.Thread") as thread, \
                patch("owl.build.main", side_effect=AssertionError("Unexpected production build")):
            thread.return_value.is_alive.return_value = False
            code = jobs._run_worker(str(job), run_id)
        self.assertEqual(code, 1)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args[0], Path(recipe["acquisition"]["manifest"]))
        self.assertIs(capture.call_args.kwargs["continue_missing_sources"], True)
        state = json.loads((job / "status.json").read_text())
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["exit_code"], 1)
        self.assertEqual(state["attempt"], 1)
        self.assertEqual(state["error_type"], "IncompleteCaptureError")
        self.assertEqual(state["result_file"], "result.json")
        self.assertNotIn("retry_seconds", state)
        self.assertLessEqual((job / "status.json").stat().st_size, 2048)
        saved = json.loads((job / "result.json").read_text())
        self.assertEqual(saved, report)
        self.assertEqual(saved["status"], "incomplete")
        self.assertIs(saved["complete"], False)
        self.assertIs(saved["content_ready"], False)
        self.assertNotIn("candidate_fragment", saved)


if __name__ == "__main__":
    unittest.main()
