"""Exercise header probes, bounded streams and source fallback."""
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_links


class LinkChecksTests(unittest.TestCase):
    @staticmethod
    def response(status, headers):
        response = MagicMock()
        response.__enter__.return_value = SimpleNamespace(
            status=status, headers=headers, url="https://example.test/file"
        )
        return response

    def test_range_total_beats_head_length_and_reports_cors(self):
        head = self.response(200, {"Content-Length": "75"})
        ranged = self.response(206, {"Content-Range": "bytes 0-0/42", "Content-Length": "1",
                                     "Access-Control-Allow-Origin": "*",
                                     "Access-Control-Expose-Headers": "Content-Range"})
        with patch.object(check_links, "urlopen", side_effect=[head, ranged]) as fetch:
            row = check_links.probe("https://example.test/file", 42, check_links.DEFAULT_ORIGIN, 1)
        self.assertTrue(row["ok"])
        self.assertTrue(row["range"])
        self.assertTrue(row["exposes_content_range"])
        self.assertEqual(row["observed_bytes"], 42)
        self.assertEqual(fetch.call_args_list[0].args[0].get_method(), "HEAD")
        self.assertEqual(fetch.call_args_list[1].args[0].get_header("Range"), "bytes=0-0")
        self.assertEqual(fetch.call_args_list[1].args[0].get_header("Origin"), check_links.DEFAULT_ORIGIN)
        head.read.assert_not_called()
        ranged.read.assert_not_called()

    def test_ignored_range_and_wrong_length_report_failure(self):
        head = self.response(200, {"Content-Length": "42"})
        get = self.response(200, {"Content-Length": "75"})
        with patch.object(check_links, "urlopen", side_effect=[head, get]):
            row = check_links.probe("https://example.test/file", 42, check_links.DEFAULT_ORIGIN, 1)
        self.assertFalse(row["ok"])
        self.assertFalse(row["range"])
        self.assertFalse(row["cors"])
        self.assertEqual(row["observed_bytes"], 75)

    def test_missing_size_stream_runs_by_default(self):
        head = self.response(200, {})
        ignored = self.response(200, {})
        limit = 42
        stream_response = MagicMock()
        stream_response.__enter__.return_value = SimpleNamespace(
            status=200, headers={}, url="https://example.test/file", read1=BytesIO(b"a" * limit).read1)
        with patch.object(check_links, "urlopen", side_effect=[head, ignored, stream_response]):
            row = check_links.probe("https://example.test/file", limit, check_links.DEFAULT_ORIGIN, 1)
        self.assertTrue(row["ok"])
        self.assertEqual(row["size_method"], "stream")
        with patch.object(check_links, "urlopen", side_effect=[head, ignored]):
            stream = MagicMock(return_value=(42, {}, "https://example.test/file"))
            row = check_links.probe("https://example.test/file", limit, check_links.DEFAULT_ORIGIN, 1,
                                    stream_size=stream)
        self.assertTrue(row["ok"])
        self.assertEqual(row["size_method"], "stream")
        stream.assert_called_once()

    def test_checker_denials_require_a_matching_browser_probe_without_origin(self):
        for status in (403, 429):
            for browser_status, length, outcome in ((200, 42, "blocked_for_checker"), (200, 40, "size mismatch"),
                                                     (403, 42, "unverified"), (410, 42, "gone")):
                denied = self.response(status, {})
                browser = self.response(browser_status, {"Content-Length": str(length)})
                with self.subTest(status=status, outcome=outcome), patch.object(
                        check_links, "urlopen", side_effect=[denied, denied, browser, browser]) as fetch:
                    row = check_links.probe("https://publisher.test/file", 42, check_links.DEFAULT_ORIGIN, 1)
                    self.assertEqual(row["outcome"], outcome)
                    self.assertFalse(row["ok"])
                    for call in fetch.call_args_list[2:]:
                        request = call.args[0]
                        self.assertIsNone(request.get_header("Origin"))
                        self.assertEqual(request.get_header("User-agent"), check_links.BROWSER_USER_AGENT)

    def test_blocked_only_is_green_and_inconclusive_sources_fail_on_third_distinct_week(self):
        assets = [{"id": name, "source_url": f"https://publisher.test/{name}", "size_bytes": 42}
                  for name in ("blocked", "pending")]
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(check_links, "load_catalog", return_value=assets),
              patch.object(check_links, "probe") as probe,
              patch.object(check_links, "date") as clock,
              patch("sys.stdout"), patch("sys.stderr")):
            history = Path(directory) / "history.json"
            report = Path(directory) / "report.json"
            history.write_text("{}")
            outcomes = {"blocked": "blocked_for_checker", "pending": "unverified"}
            probe.side_effect = lambda url, *_a, **_k: {
                "url": url, "outcome": outcomes[url.rsplit("/", 1)[1]],
                "ok": outcomes[url.rsplit("/", 1)[1]] == "matching"}
            for day, count in ((2, 1), (3, 1), (9, 2), (16, 3)):
                with self.subTest(day=day):
                    clock.today.return_value = date(2026, 11, day)
                    status = check_links.main(["--history", str(history), "--output", str(report)])
                    result = json.loads(report.read_bytes())
                    self.assertEqual(status, int(count == 3))
                    self.assertEqual(result["blocked_assets"], ["blocked"])
                    self.assertEqual(result["failed_assets"], ["pending"] if count == 3 else [])
                    self.assertEqual(result["inconclusive_weeks"]["pending"]["count"], count)
                    history.write_text(json.dumps(result["inconclusive_weeks"]))
            self.assertEqual(check_links.inconclusive_history(
                ["pending"], result["inconclusive_weeks"], date(2026, 11, 30))["pending"]["count"], 1)
            outcomes["pending"] = "matching"
            self.assertEqual(check_links.main(["--history", str(history), "--output", str(report)]), 0)
            self.assertEqual(json.loads(report.read_bytes())["inconclusive_weeks"], {})

    @unittest.skipUnless(shutil.which("node"), "Node is required to exercise the GitHub Script step")
    def test_workflow_closes_the_tracking_issue_with_checker_blocks_reported(self):
        workflow = yaml.safe_load((check_links.ROOT / ".github/workflows/check-links.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["check-links"]["steps"]
        report_script = next(step["with"]["script"] for step in steps if step.get("name") == "Update source check issue")
        harness = """
const calls = [];
const github = {rest: {issues: {update: async data => calls.push(data)}}};
const context = {repo: {owner: 'owl', repo: 'library'}, serverUrl: 'https://github.test', runId: 123, sha: 'pin'};
process.env.PROBE_OUTCOME = 'success';
process.env.ISSUE_NUMBER = '7';
(async () => {
""" + report_script + """
  console.log(JSON.stringify(calls));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "link-check-history.json").write_text("{}")
            (root / "link-checks.json").write_text(json.dumps({
                "failed_assets": [], "failed_routes": [], "blocked_assets": ["guide"], "blocked_routes": [],
                "inconclusive_weeks": {"pending": {"week": "2026-11-16", "count": 2}}, "overdue_assets": [],
            }))
            result = subprocess.run(["node", "--input-type=commonjs"], input=harness, cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        [update] = json.loads(result.stdout)
        self.assertEqual((update["issue_number"], update["state"], update["state_reason"]), (7, "closed", "completed"))
        self.assertIn("## Blocked for this checker\n\n- guide", update["body"])
        self.assertIn("- pending (2 weeks)", update["body"])
        self.assertIn('<!-- owl-inconclusive-weeks: {"pending":{"week":"2026-11-16","count":2}} -->', update["body"])

    def test_head_success_can_use_a_full_get_when_range_request_fails(self):
        head = self.response(200, {"Content-Length": "42"})
        rejected = self.response(403, {})
        stream = MagicMock(return_value=(42, {"Access-Control-Allow-Origin": "*"}, "https://example.test/file"))
        with patch.object(check_links, "urlopen", side_effect=[head, rejected]):
            row = check_links.probe("https://example.test/file", 42, check_links.DEFAULT_ORIGIN, 1,
                                    stream_size=stream)
        self.assertTrue(row["ok"])
        self.assertTrue(row["cors"])
        self.assertFalse(row["range"])
        self.assertEqual(row["size_method"], "stream")

    def test_stream_counts_eof_and_stops_after_first_excess_byte(self):
        for length, expected, counted in ((42, 42, 42), (40, 42, 40), (200, 42, 43)):
            with self.subTest(length=length, expected=expected):
                body = BytesIO(b"a" * length)
                response = SimpleNamespace(status=200, headers={},
                                           url="https://example.test/file", read1=body.read1)
                request = MagicMock()
                request.__enter__.return_value = response
                with patch.object(check_links, "urlopen", return_value=request):
                    size, _, _ = check_links.StreamSize()("https://example.test/file", {}, expected, 1)
                self.assertEqual(size, counted)
                self.assertEqual(body.tell(), counted)
                request.__exit__.assert_called_once()

    def test_large_unknown_size_pin_is_never_fetched(self):
        with patch.object(check_links, "urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "streaming limit"):
                check_links.StreamSize()("https://example.test/file", {}, 10**9, 1)
        fetch.assert_not_called()

    def test_matching_reviewed_mirror_counts_when_primary_fails(self):
        primary, mirror = "https://example.test/file", "https://mirror.test/file"
        catalog = [{"id": "guide", "source_url": primary, "mirrors": [mirror], "size_bytes": 42,
                    "mirror_fetch": {mirror: {"sha256_verified": True, "range": True, "cors": True}}}]
        def probe(url, *_args, **_kwargs):
            ok = url == mirror
            return {"url": url, "ok": ok, "range": ok, "cors": ok}
        with patch.object(check_links, "load_catalog", return_value=catalog), patch.object(
                check_links, "probe", side_effect=probe) as mocked, patch("sys.stdout"), patch("sys.stderr"):
            self.assertEqual(check_links.main([]), 0)
            self.assertTrue(all(call.args[2] is None for call in mocked.call_args_list))
            with patch.object(check_links, "probe", side_effect=lambda url, *_a, **_k:
                              {"url": url, "ok": False, "range": False, "cors": True}):
                self.assertEqual(check_links.main([]), 1)

    def test_sampling_browser_routes_keeps_every_publisher_source_in_the_run(self):
        assets = [{"id": str(i), "source_url": f"https://example.test/{i}", "size_bytes": 42}
                  for i in range(3)]
        with (patch.object(check_links, "load_catalog", return_value=assets),
              patch.object(check_links, "deployed_routes", return_value=[]) as routes,
              patch.object(check_links, "probe", side_effect=lambda url, *_a, **_k:
                           {"url": url, "ok": True}) as probe,
              patch("sys.stdout")):
            self.assertEqual(check_links.main(["--route-sample", "1", "--pages-base", "https://pages.test"]), 0)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(routes.call_args.args[3], 1)

    def test_final_browser_origin_must_be_in_connect_src(self):
        primary = "https://source.test/guide"
        allowed = "https://other.test/guide"
        outside = "https://outside.test/guide"
        assets = [
            {"id": name, "source_url": url, "size_bytes": 42, "format": "pdf", "browser_fetch": {"cors": True}}
            for name, url in (("guide", primary), ("another", allowed))
        ]
        for final_url, status, expected in ((allowed, 200, 0), (outside, 200, 1), (outside, 403, 1),
                                            ("https://source.test:8443/guide", 200, 1),
                                            ("http://source.test/guide", 200, 1),
                                            ("ftp://source.test/guide", 200, 1)):
            with self.subTest(final_url=final_url, status=status):
                def probe(url, _size, origin, *_args, **_kwargs):
                    redirected = origin and url == primary
                    code = status if redirected else 200
                    return {"url": url, "final_url": final_url if redirected else url, "ok": code == 200,
                            "cors": code == 200, "outcome": "matching" if code == 200 else "blocked_for_checker"}

                with (tempfile.TemporaryDirectory() as directory,
                      patch.object(check_links, "load_catalog", return_value=assets),
                      patch.object(check_links, "probe", side_effect=probe),
                      patch("sys.stdout"), patch("sys.stderr")):
                    output = Path(directory) / "report.json"
                    self.assertEqual(check_links.main(["--pages-base", "https://pages.test/", "--output", str(output)]),
                                     expected)
                    failed = json.loads(output.read_bytes())["failed_routes"]
                    if expected:
                        self.assertEqual(len(failed), 1)
                        self.assertEqual(failed[0]["outcome"], "outside page CSP")
                        self.assertIn("connect-src", failed[0]["browser_drift"])

    def test_publisher_uses_builder_agent_without_origin(self):
        response = self.response(200, {"Content-Length": "42"})
        with patch.object(check_links, "urlopen", return_value=response) as fetch:
            self.assertTrue(check_links.probe("https://publisher.test/guide", 42, None, 1)["ok"])
        for call in fetch.call_args_list:
            self.assertIsNone(call.args[0].get_header("Origin"))
            self.assertEqual(call.args[0].get_header("User-agent"), check_links.USER_AGENT)

    def test_standard_identifier_can_recover_a_publisher_403(self):
        forbidden = self.response(403, {})
        body = self.response(200, {"Content-Length": "42"})
        with patch.object(check_links, "urlopen", side_effect=[forbidden, forbidden, body]) as fetch:
            row = check_links.probe("https://publisher.test/file", 42, None, 1, whole_get=True)
        self.assertTrue(row["ok"])
        self.assertEqual(row["outcome"], "matching")
        self.assertIsNone(fetch.call_args.args[0].get_header("User-agent"))

    def test_checks_published_mirror_parts_and_relay_with_pages_origin(self):
        url = "https://publisher.test/guide"
        asset = {"id": "guide", "source_url": url, "size_bytes": 80_000_010, "format": "pdf"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "web").mkdir()
            (root / "relay").mkdir()
            (root / "web/pages-mirrors.json").write_text(json.dumps({"guide": "pinned"}))
            (root / "relay/allowlist.json").write_text(json.dumps({
                "guide": {"url": url, "bytes": asset["size_bytes"]},
                "archive--peer": {"url": url, "bytes": 200, "archive": "archive"}}))
            output = root / "report.json"
            def response(route, size, origin, _timeout, *, whole_get=False, **_kwargs):
                self.assertEqual(origin, None if route == url else check_links.DEFAULT_ORIGIN)
                if route.endswith("/assets/guide"):
                    self.assertTrue(whole_get)
                if route.endswith("/assets/archive--peer"):
                    self.assertFalse(whole_get)
                return {"url": route, "observed_bytes": size, "ok": True, "cors": True, "range": True,
                        "exposes_content_range": not route.endswith("archive--peer")}
            with patch.object(check_links, "ROOT", root), patch.object(check_links, "load_catalog", return_value=[asset]), \
                    patch.object(check_links, "probe", side_effect=response), patch("sys.stdout"), patch("sys.stderr"):
                result = check_links.main(["--pages-base", "https://pages.test/owl/", "--relay-base", "https://relay.test",
                                           "--archive-relay", "--output", str(output)])
            self.assertEqual(result, 1)
            report = json.loads(output.read_bytes())
            parts = [(row["url"], row["observed_bytes"]) for row in report["responses"] if row["route"] == "pages-mirror"]
            self.assertEqual(parts, [("https://pages.test/owl/mirrors/guide-0.bin", 80_000_000),
                                     ("https://pages.test/owl/mirrors/guide-1.bin", 10)])
            self.assertEqual(report["failed_routes"][0]["browser_drift"], ["exposes_content_range"])
