"""Build integration for background launch, structured postflight and cache budgets."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_core import Fixture
from owl.build import main
from owl.safety import SafetyError


class UnattendedBuildTests(Fixture):
    def test_detach_passes_exact_arguments_without_recursive_launch(self):
        argv = [str(self.root / "Drive with spaces"), "--profile", "test", "--detach",
                "--job-dir", str(self.root / "job"), "--catalog", str(self.catalog),
                "--profiles-dir", str(self.profiles), "--allow-local"]
        with patch("owl.jobs.start_job", return_value={"status": "starting"}) as start:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 0)
        passed = start.call_args.args[0]
        self.assertEqual(passed[0], argv[0])
        self.assertNotIn("--detach", passed)
        self.assertNotIn("--job-dir", passed)
        self.assertIn(str(self.catalog), passed)
        self.assertEqual(start.call_args.kwargs["job_dir"], self.root / "job")

    def test_postflight_result_is_saved_before_build_complete(self):
        result = self.run_build()
        state = json.loads((self.root / "drive/LIBRARY/.owl/state.json").read_text())
        self.assertEqual(state["phase"], "complete")
        self.assertTrue(state["complete"])
        self.assertEqual(state["result"], result["result"])
        self.assertEqual(state["result"]["status"], "passed")

    def test_postflight_failure_prevents_completion(self):
        with patch("owl.postflight.audit_build", side_effect=SafetyError("smoke failed")):
            with self.assertRaisesRegex(SafetyError, "smoke failed"):
                self.run_build()
        state = json.loads((self.root / "drive/LIBRARY/.owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["phase"], "postflight")

    def test_external_cache_is_budgeted_and_reused_by_another_target(self):
        from owl.build import build
        cache = self.root / "index-cache"
        plan = self.run_build(plan_only=True, index_cache_dir=cache,
                              index_cache_budget_bytes=2_000_000)
        self.assertEqual(plan["index_cache_budget_bytes"], 2_000_000)
        self.assertEqual(plan["remaining_index_cache_allocation_bytes"], 2_000_000)
        self.assertFalse(cache.exists())
        self.run_build(index_cache_dir=cache, index_cache_budget_bytes=2_000_000)
        with patch("owl.search._units", side_effect=AssertionError("cache should avoid extraction")):
            result = build(self.root / "second-drive", catalog=self.catalog,
                           profiles_dir=self.profiles, profile_name="test", allow_local=True,
                           index_cache_dir=cache, index_cache_budget_bytes=2_000_000,
                           progress=lambda _: None)
        self.assertEqual(result["result"]["status"], "passed")

    def test_inside_drive_cache_requires_private_location_and_capacity(self):
        with self.assertRaisesRegex(SafetyError, "LIBRARY/.owl"):
            self.run_build(plan_only=True, index_cache_dir=self.root / "drive/cache")
        with self.assertRaisesRegex(SafetyError, "capacity"):
            self.run_build(plan_only=True, index_cache_dir=self.root / "drive/LIBRARY/.owl/index-cache",
                           index_cache_budget_bytes=self.profile["capacity_bytes"])
