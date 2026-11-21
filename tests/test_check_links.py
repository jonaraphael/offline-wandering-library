"""Check pinned sizes and browser headers without reading source bodies."""
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
