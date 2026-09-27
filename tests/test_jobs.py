"""Real detached-worker lifecycle tests against tiny deterministic build fixtures."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from owl import jobs
from owl.download import DownloadError, TransientDownloadError, download
from owl.safety import SafetyError


BUILD_FIXTURE = '''from pathlib import Path
import json
import time
from .download import TransientDownloadError
def main(argv=None, *, raise_errors=False, progress=print):
    target = Path(argv[0])
    count = target / "attempts"
    attempt = int(count.read_text()) + 1 if count.exists() else 1
    count.write_text(str(attempt))
    progress.event(phase="content", active_asset="fixture", total_assets=1)
    progress("fixture started")
    mode = (target / "mode").read_text()
    if mode == "transient" and attempt == 1:
        raise TransientDownloadError("connection temporarily unavailable")
    if mode == "late_transient" and attempt == 1:
        from . import jobs
        monotonic = jobs.time.monotonic
        jobs.time.monotonic = lambda: monotonic() + 7200
        raise TransientDownloadError("outage after two hours of successful build work")
    if mode == "permanent":
        raise ValueError("pinned bytes changed")
    if mode == "always_transient":
        raise TransientDownloadError("still offline")
    if mode == "wait":
        while not (target / "release").exists():
            time.sleep(0.02)
    (target / "finished").write_text("captured source")
    state = target / "LIBRARY/.owl/state.json"
    if mode != "missing_state":
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"complete": True, "phase": "complete", "result": {"status": "passed"}}))
    progress.event(phase="complete", completed_assets=1, active_asset=None)
    return 0
'''


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        shutil.copytree(jobs.REPO_ROOT / "src/owl", self.repo / "src/owl", ignore=shutil.ignore_patterns("__pycache__"))
        (self.repo / "src/owl/build.py").write_text(BUILD_FIXTURE)
        self.target = self.root / "target"
        self.target.mkdir()
        (self.target / "mode").write_text("complete")
        self.job = self.root / "job"
        self.patch = patch.object(jobs, "REPO_ROOT", self.repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.stop_worker)

    def stop_worker(self):
        if (self.job / "status.json").exists():
            state = jobs.status_job(self.job)
            if state["worker_active"] or state["state"] == "starting":
                jobs.cancel_job(self.job)
                self.wait_for(lambda s: s["state"] in jobs.TERMINAL and not s["worker_active"])

    def wait_for(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = jobs.status_job(self.job)
            if predicate(state):
                return state
            time.sleep(.04)
        self.fail(f"Worker did not reach expected state: {state}; {jobs.logs_job(self.job)}")

    def start(self, **kwargs):
        return jobs.start_job([str(self.target)], job_dir=self.job, **kwargs)

    def test_detached_build_finishes_after_launcher_exits(self):
        script = ("from pathlib import Path; from owl import jobs; import json,sys; "
                  "jobs.REPO_ROOT=Path(sys.argv[1]); "
                  "print(json.dumps(jobs.start_job([sys.argv[2]],job_dir=Path(sys.argv[3]))))")
        launcher = subprocess.run([sys.executable, "-c", script, str(self.repo), str(self.target), str(self.job)],
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(launcher.returncode, 0, launcher.stderr)
        launched = json.loads(launcher.stdout)
        self.assertEqual(launched["state"], "starting")
        state = self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        self.assertEqual(state["exit_code"], 0)
        self.assertEqual((self.target / "finished").read_text(), "captured source")
        self.assertLess(len(json.dumps(state).encode()), 2048)
        self.assertIn("fixture started", jobs.logs_job(self.job))
        with self.assertRaisesRegex(SafetyError, "already completed"):
            jobs.resume_job(self.job)

    def test_trial_script_pauses_resumes_frozen_code_and_remains_pending_review(self):
        scripts = self.repo / 'scripts'; scripts.mkdir()
        script = scripts / 'prepare_review_packets.py'
        script.write_text('import sys,time\nfrom pathlib import Path\n'
            'target=Path(sys.argv[1])\n(target/"started").touch()\n'
            'while not (target/"release").exists():time.sleep(.02)\n'
            '(target/"trial-output").write_text("frozen")\n')
        control = self.repo / 'control.json'; control.write_text('{}')
        jobs.start_trial_step(script.name, [str(self.target)], job_dir=self.job,
            target=self.target, inputs=[control], working_directory=self.repo)
        self.wait_for(lambda s: (self.target/'started').exists())
        jobs.cancel_job(self.job)
        self.wait_for(lambda s: s['state']=='cancelled' and not s['worker_active'])
        script.write_text('raise RuntimeError("mutable code executed")')
        (self.target/'release').touch(); jobs.resume_job(self.job)
        self.wait_for(lambda s: s['state']=='awaiting_review' and not s['worker_active'])
        self.assertEqual((self.target/'trial-output').read_text(),'frozen')
        self.assertFalse(json.loads((self.job/'result.json').read_text())['content_ready'])

    def test_trial_script_rejects_changed_control_and_production_action(self):
        scripts = self.repo / 'scripts'; scripts.mkdir()
        script = scripts / 'prepare_review_packets.py'
        script.write_text('import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text("changed")\n')
        control = self.repo / 'control.json'; control.write_text('{}')
        with self.assertRaises(SafetyError):
            jobs.start_trial_step('acquire_content.py',['stage'],job_dir=self.job,target=self.target)
        jobs.start_trial_step(script.name,[str(control)],job_dir=self.job,target=self.target,inputs=[control])
        state=self.wait_for(lambda s: s['state']=='failed' and not s['worker_active'])
        self.assertIn('control input changed',state['error'])
        self.assertFalse((self.job/'result.json').exists())

    def test_heartbeat_cancellation_and_resume_use_captured_source(self):
        (self.target / "mode").write_text("wait")
        launched = self.start()
        state = self.wait_for(lambda s: s.get("active_asset") == "fixture")
        before = state["heartbeat_at"]
        state = self.wait_for(lambda s: s["heartbeat_at"] != before)
        self.assertTrue(state["worker_active"])
        if os.name != "nt":
            self.assertEqual(os.getsid(launched["pid"]), launched["pid"])
        with self.assertRaisesRegex(SafetyError, "already active"):
            jobs.resume_job(self.job)
        jobs.cancel_job(self.job)
        cancelled = self.wait_for(lambda s: s["state"] == "cancelled" and not s["worker_active"])
        self.assertEqual(cancelled["exit_code"], 130)
        (self.repo / "src/owl/build.py").write_text("raise RuntimeError('changed editable source')")
        (self.target / "release").touch()
        resumed = jobs.resume_job(self.job)
        self.assertNotEqual(resumed["run_id"], cancelled["run_id"])
        self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        self.assertEqual((self.target / "finished").read_text(), "captured source")
        self.assertEqual((self.target / "attempts").read_text(), "2")

    def test_only_transient_failures_retry(self):
        (self.target / "mode").write_text("transient")
        self.start(retry_delay=.01)
        state = self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        self.assertEqual(state["attempt"], 2)
        self.assertEqual((self.target / "attempts").read_text(), "2")

    def test_retry_attempts_are_bounded(self):
        (self.target / "mode").write_text("always_transient")
        self.start(max_attempts=2, retry_delay=.01)
        state = self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["error_type"], "TransientDownloadError")

    def test_retry_window_starts_at_first_outage_after_hours_of_work(self):
        (self.target / "mode").write_text("late_transient")
        self.start(retry_delay=.01, retry_deadline=1)
        state = self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        self.assertEqual(state["attempt"], 2)

    def test_startup_failure_gets_terminal_status(self):
        # Construct a real stopped job, then simulate an unsafe startup log.
        (self.target / "mode").write_text("permanent")
        self.start()
        state = self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        log = self.job / "build.log"
        log.unlink()
        log.mkdir()
        self.assertEqual(jobs._worker(str(self.job), state["run_id"]), 1)
        self.assertEqual(jobs.status_job(self.job)["phase"], "startup")

    def test_retry_deadline_prevents_another_attempt(self):
        (self.target / "mode").write_text("always_transient")
        self.start(retry_delay=2, retry_deadline=1)
        state = self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        self.assertEqual(state["attempt"], 1)

    def test_successful_exit_without_verified_postflight_is_failure(self):
        (self.target / "mode").write_text("missing_state")
        self.start()
        state = self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        self.assertNotEqual(state["exit_code"], 0)
        self.assertFalse((self.job / "result.json").exists())

    def test_permanent_failure_and_captured_input_tampering(self):
        (self.target / "mode").write_text("permanent")
        self.start(retry_delay=.01)
        state = self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        self.assertEqual(state["attempt"], 1)
        self.assertEqual(state["error_type"], "ValueError")
        self.assertIn("pinned bytes changed", state["error"])
        (self.job / "snapshot/src/owl/build.py").write_text("print('tampered')")
        with self.assertRaisesRegex(SafetyError, "source/input changed"):
            jobs.resume_job(self.job)

    def test_dependency_drift_refuses_resume(self):
        (self.target / "mode").write_text("permanent")
        self.start()
        self.wait_for(lambda s: s["state"] == "failed" and not s["worker_active"])
        with patch.object(jobs, "_dependencies", return_value={}):
            with self.assertRaisesRegex(SafetyError, "dependencies changed"):
                jobs.resume_job(self.job)

    def test_duplicate_start_and_symlink_refused(self):
        self.start()
        with self.assertRaisesRegex(SafetyError, "not empty"):
            self.start()
        self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        link = self.root / "linked-job"
        try:
            link.symlink_to(self.job, target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        with self.assertRaises(SafetyError):
            jobs.status_job(link)

    def test_log_rotation_and_tail_are_bounded(self):
        self.start()
        self.wait_for(lambda s: s["state"] == "complete" and not s["worker_active"])
        with patch.object(jobs, "LOG_BYTES", 5000):
            stream = jobs._Log(self.job)
            try:
                stream.write("x" * 100000)
            finally:
                stream.close()
        self.assertLessEqual(len(list(self.job.glob("build.log*"))), 3)
        self.assertLess(sum(p.stat().st_size for p in self.job.glob("build.log*")), 15000)
        self.assertLessEqual(len(jobs.logs_job(self.job, tail_bytes=300).encode()), 300)
        with self.assertRaises(ValueError):
            jobs.logs_job(self.job, tail_bytes=100000)

    def test_snapshot_remaps_inputs_and_resolves_output_paths(self):
        catalog = self.root / "external/catalog.yaml"
        catalog.parent.mkdir()
        catalog.write_text("schema_version: 1\nassets: []\n")
        catalog.with_name("resources.yaml").write_text("resources: []\n")
        snapshot_job = self.root / "snapshot-test"
        snapshot_job.mkdir()
        recipe = jobs._snapshot(snapshot_job, ["--index-cache-budget-bytes", "123", str(self.target),
            "--catalog=" + str(catalog), "--index-cache-dir", "relative-cache"])
        argv = recipe["build_argv"]
        self.assertEqual(argv[2], str(self.target))
        captured = Path(argv[argv.index("--catalog") + 1])
        self.assertTrue(captured.is_relative_to(snapshot_job))
        self.assertTrue(captured.with_name("resources.yaml").exists())
        self.assertTrue(Path(argv[argv.index("--index-cache-dir") + 1]).is_absolute())


class DownloadRetryClassificationTests(unittest.TestCase):
    def fetch(self, error, retries=3):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            asset = {"id": "fixture", "source_url": "https://example.org/fixture", "size_bytes": 10, "sha256": "a" * 64}
            with patch("owl.download.urlopen", side_effect=error) as opened:
                try:
                    download(asset, root / "asset", repo_root=root, retries=retries, progress=lambda _: None, sleep=lambda _: None)
                except DownloadError as failure:
                    return failure, opened.call_count
        self.fail("Expected failure")

    def test_timeout_is_typed_transient_and_bounded(self):
        failure, calls = self.fetch(URLError(TimeoutError("offline")))
        self.assertIsInstance(failure, TransientDownloadError)
        self.assertEqual(calls, 4)

    def test_missing_source_and_rejected_identifier_are_permanent(self):
        for code, expected_calls in ((404, 1), (403, 2)):
            failure, calls = self.fetch(HTTPError("https://example.org/fixture", code, "rejected", {}, None))
            self.assertIsInstance(failure, DownloadError)
            self.assertNotIsInstance(failure, TransientDownloadError)
            self.assertEqual(calls, expected_calls)

    def test_local_disk_error_is_not_retried(self):
        import errno
        failure, calls = self.fetch(OSError(errno.ENOSPC, "disk full"))
        self.assertNotIsInstance(failure, TransientDownloadError)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
