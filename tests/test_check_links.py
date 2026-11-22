"""Exercise header probes, bounded streams and source fallback."""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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

    def test_missing_size_stream_is_opt_in(self):
        head = self.response(200, {})
        ignored = self.response(200, {})
        limit = 42
        with patch.object(check_links, "urlopen", side_effect=[head, ignored]):
            row = check_links.probe("https://example.test/file", limit, check_links.DEFAULT_ORIGIN, 1)
        self.assertFalse(row["ok"])
        self.assertIsNone(row["size_method"])
        with patch.object(check_links, "urlopen", side_effect=[head, ignored]):
            stream = MagicMock(return_value=(42, {}, "https://example.test/file"))
            row = check_links.probe("https://example.test/file", limit, check_links.DEFAULT_ORIGIN, 1,
                                    stream_size=stream)
        self.assertTrue(row["ok"])
        self.assertEqual(row["size_method"], "stream")
        stream.assert_called_once()

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

    def test_publisher_uses_builder_agent_without_origin(self):
        response = self.response(200, {"Content-Length": "42"})
        with patch.object(check_links, "urlopen", return_value=response) as fetch:
            self.assertTrue(check_links.probe("https://publisher.test/guide", 42, None, 1)["ok"])
        for call in fetch.call_args_list:
            self.assertIsNone(call.args[0].get_header("Origin"))
            self.assertEqual(call.args[0].get_header("User-agent"), check_links.USER_AGENT)

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
