"""Portable PhET evidence must prove the current reviewed interaction."""
from copy import deepcopy
import hashlib
import json
import unittest

from scripts.summarize_phet import EvidenceError, summarize


class PhetSummaryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"assets": [{"id": "phet_fixture", "sha256": "a" * 64, "version": "1.0",
                                    "expected_changed_keys": ["chargeProperty"]}],
                         "viewports": [{"width": 390, "height": 844}]}
        self.manifest_bytes = json.dumps(self.manifest).encode()
        self.check = {"id": "phet_fixture", "sha256": "a" * 64, "version": "1.0",
                      "viewport": {"width": 390, "height": 844}, "success": True, "errors": [],
                      "blocked_remote_requests": [], "changed_keys": ["chargeProperty"],
                      "restored_keys": ["chargeProperty"], "before": {"chargeProperty": 0},
                      "after": {"chargeProperty": 1}, "reset": {"chargeProperty": 0},
                      "layout": {"viewport_width": 390, "scroll_width": 390, "visible_rendering_surfaces": 1}}
        self.report = {"checks": [self.check], "success": True, "offline": True, "downloads": False,
                       "scope": "local Chromium browser", "browser_version": "test fixture",
                       "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest()}

    def summary(self, report=None, manifest_bytes=None):
        return summarize(json.dumps(report or self.report).encode(), manifest_bytes or self.manifest_bytes,
                         manifest_name="/temporary/checks.json", report_name="/temporary/report.json")

    def test_bound_values_prove_browser_success_without_device_certification(self):
        result = self.summary()
        self.assertTrue(result["success"])
        self.assertEqual(result["physical_device_certification"], "pending")
        self.assertEqual(result["manifest"], "checks.json")
        self.assertEqual(result["raw_report"]["filename"], "report.json")
        self.assertEqual(result["checks"][0]["reviewed_state_checks"],
                         [{"key": "chargeProperty", "before": 0, "after": 1, "reset": 0}])

    def test_missing_or_changed_manifest_binding_cannot_promote_old_report(self):
        del self.report["manifest_sha256"]
        result = self.summary()
        self.assertFalse(result["success"])
        self.assertTrue(any("manifest bytes" in item for item in result["blockers"]))
        self.report["manifest_sha256"] = hashlib.sha256(self.manifest_bytes).hexdigest()
        self.assertFalse(self.summary(manifest_bytes=self.manifest_bytes + b"\n")["success"])

    def test_missing_check_is_pending_and_duplicate_or_changed_check_rejected(self):
        missing = deepcopy(self.report)
        missing["checks"] = []
        result = self.summary(missing)
        self.assertFalse(result["success"])
        self.assertEqual(result["total_checks"], 0)
        self.assertTrue(any("1 required" in item for item in result["blockers"]))
        duplicate = deepcopy(self.report)
        duplicate["checks"].append(deepcopy(self.check))
        with self.assertRaises(EvidenceError):
            self.summary(duplicate)
        for field, value in [("sha256", "b" * 64), ("version", "2.0"), ("id", "unselected")]:
            with self.subTest(field=field):
                changed = deepcopy(self.report)
                changed["checks"][0][field] = value
                with self.assertRaisesRegex(EvidenceError, "changed or unselected"):
                    self.summary(changed)

    def test_duplicate_manifest_ids_viewports_and_missing_required_keys_rejected(self):
        for changed in [dict(self.manifest, assets=self.manifest["assets"] * 2),
                        dict(self.manifest, viewports=self.manifest["viewports"] * 2),
                        dict(self.manifest, assets=[dict(self.manifest["assets"][0], expected_changed_keys=[])])]:
            with self.subTest(changed=changed), self.assertRaises(EvidenceError):
                self.summary(manifest_bytes=json.dumps(changed).encode())

    def test_claimed_key_lists_cannot_replace_actual_changed_and_restored_values(self):
        for phase, value in [("before", {}), ("after", {"chargeProperty": 0}),
                             ("reset", {"chargeProperty": 1}), ("after", {"chargeProperty": None})]:
            with self.subTest(phase=phase, value=value):
                changed = deepcopy(self.report)
                changed["checks"][0][phase] = value
                with self.assertRaisesRegex(EvidenceError, "observed reviewed"):
                    self.summary(changed)

    def test_overflow_missing_rendering_and_non_boolean_success_rejected(self):
        for key, value in [("scroll_width", 800), ("visible_rendering_surfaces", 0), ("viewport_width", 1280)]:
            with self.subTest(layout=key):
                changed = deepcopy(self.report)
                changed["checks"][0]["layout"][key] = value
                with self.assertRaisesRegex(EvidenceError, "valid layout"):
                    self.summary(changed)
        self.check["success"] = "yes"
        with self.assertRaisesRegex(EvidenceError, "boolean"):
            self.summary()

    def test_overall_failure_network_or_unidentified_execution_never_promotes(self):
        for key, value in [("success", False), ("offline", False), ("downloads", True),
                           ("scope", "source-integrity-only"), ("browser_version", "")]:
            with self.subTest(key=key):
                changed = deepcopy(self.report)
                changed[key] = value
                self.assertFalse(self.summary(changed)["success"])

    def test_failed_detail_export_is_bounded_and_omits_machine_paths(self):
        self.check["success"] = self.report["success"] = False
        self.check["errors"] = ["Failed file:///Users/person/private/sim.html " + "long " * 10000]
        self.check["failure"] = "Read /private/tmp/secret/file.html " + "large " * 10000
        self.check["layout"]["unused"] = "large " * 10000
        self.check["viewport"]["unused"] = "large " * 10000
        self.check["before"]["chargeProperty"] = "/Users/person/private/file"
        result = json.dumps(self.summary())
        self.assertLess(len(result), 4000)
        self.assertNotIn("/Users/person", result)
        self.assertNotIn("/private/tmp", result)
        self.assertNotIn("unused", result)


if __name__ == "__main__":
    unittest.main()
