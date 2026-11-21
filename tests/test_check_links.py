"""Exercise header probes, bounded streams and source fallback."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys
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
                check_links, "probe", side_effect=probe), patch("sys.stdout"), patch("sys.stderr"):
            self.assertEqual(check_links.main([]), 0)
            with patch.object(check_links, "probe", side_effect=lambda url, *_a, **_k:
                              {"url": url, "ok": url == mirror, "range": False, "cors": True}):
                self.assertEqual(check_links.main([]), 1)
