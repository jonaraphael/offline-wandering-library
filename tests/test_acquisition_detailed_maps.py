"""Detailed map proposals retain fine sheets and evidence-bound capture inputs."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import unittest

from owl.acquisition.map_capture import capture_candidates
from owl.acquisition.maps import MapError, select_required_scale
from owl.acquisition.providers import _map_row


def polygon():
    return {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def sheet(identity, bbox, scale=24000, size=10, edition="2026"):
    return {"sheet_id": identity, "bbox": bbox, "scale": scale, "size_bytes": size,
            "edition": edition, "source_url": "https://example.org/" + identity + edition + ".pdf"}


@unittest.skipUnless(importlib.util.find_spec("shapely"), "optional Shapely dependency")
class RequiredScaleTests(unittest.TestCase):
    def test_all_latest_fine_sheets_remain_with_explicit_coarse_gap(self):
        rows = [sheet("left", [0, 0, 1, 2]), sheet("left", [0, 0, 1, 2], edition="2025"),
                sheet("right", [1, 0, 1.9, 2]), sheet("coast", [1.9, 0, 2, 2], 100000),
                sheet("unneeded", [0, 0, 1, 2], 100000)]
        result = select_required_scale(rows, {"CT": polygon()}, 31, scale=24000, gap_scales=[100000], states=["CT"])
        self.assertEqual([row["sheet_id"] for row in result["proposed_sheets"]], ["left", "right", "coast"])
        self.assertEqual(result["proposed_sheets"][0]["edition"], "2026")
        self.assertTrue(result["geographic_complete"])
        self.assertFalse(result["required_scale_complete"])
        self.assertIn("CT", result["required_scale_holes"])
        self.assertFalse(result["complete"])
        self.assertEqual(result, select_required_scale(list(reversed(rows)), {"CT": polygon()}, 31,
            scale=24000, gap_scales=[100000], states=["CT"]))

    def test_over_budget_never_truncates_or_substitutes_required_sheets(self):
        rows = [sheet("left", [0, 0, 1, 2]), sheet("right", [1, 0, 2, 2]),
                sheet("cheap", [0, 0, 2, 2], 100000, size=1)]
        result = select_required_scale(rows, {"CT": polygon()}, 10, scale=24000, gap_scales=[100000], states=["CT"])
        self.assertEqual(len(result["proposed_sheets"]), 2)
        self.assertEqual(result["size_bytes"], 20)
        self.assertFalse(result["complete"])
        self.assertTrue(any("exceeds allowance" in row for row in result["blockers"]))
        with self.assertRaisesRegex(MapError, "coarser"):
            select_required_scale(rows, {"CT": polygon()}, 30, scale=24000, gap_scales=[24000], states=["CT"])


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://tnmaccess.nationalmap.gov/api/v1/products?offset=0"
        self.item = {"sourceId": "abc123", "downloadURL": "https://example.org/map.pdf", "title": "Map",
                     "boundingBox": [0, 0, 2, 2], "scale": 24000, "publicationDate": "2026", "sizeInBytes": 10}
        self.body = json.dumps({"items": [self.item]}).encode()
        row = _map_row(self.item, {"url": self.url})
        row.update(size_bytes=12, size_status="verified-by-head", source_probe_id="usgs_abc123", sha256=None)
        self.selection = {"content_ready": False, "geographic_complete": True, "sheet_count": 1,
            "sheets": [row], "metadata_evidence": [{"url": self.url, "sha256": hashlib.sha256(self.body).hexdigest()}],
            "combined_candidate_bytes": 12, "profile": "full-1tb", "recipe_id": "maps", "recipe_sha256": "a" * 64,
            "base_scale": 24000, "coverage": {"required_scale_complete": False}, "blockers": ["Review required"]}

    def fetcher(self):
        class Fetch:
            def fetch(_, url):
                if url != self.url:
                    raise AssertionError("Unexpected metadata request")
                return self.body
        return Fetch()

    def test_pending_capture_keeps_exact_size_and_no_content_approval(self):
        result = capture_candidates(self.selection, self.fetcher())
        self.assertEqual(result["budget"]["download_bytes"], 12)
        self.assertIsNone(result["sources"][0]["sha256"])
        self.assertFalse(result["content_ready"])
        self.assertFalse(result["coverage"]["required_scale_complete"])
        self.assertEqual(result["sources"][0]["map_metadata"]["review_status"], "pending")
        template = result["sources"][0]["fullasset_metadata"]
        self.assertEqual(template["format"], "pdf")
        self.assertTrue(template["destination"].endswith("/usgs_abc123.pdf"))
        self.assertIsNone(template["sha256"])
        self.assertFalse(template["redistributable"])
        self.assertEqual(template["review_status"], "pending")
        self.assertEqual(result, capture_candidates(deepcopy(self.selection), self.fetcher()))

    def test_changed_metadata_or_selected_identity_rejected(self):
        self.body += b" "
        with self.assertRaisesRegex(MapError, "metadata changed"):
            capture_candidates(self.selection, self.fetcher())
        self.body = self.body[:-1]
        self.selection["sheets"][0]["edition"] = "2025"
        with self.assertRaisesRegex(MapError, "edition differs"):
            capture_candidates(self.selection, self.fetcher())

    def test_missing_head_or_publisher_identity_rejected(self):
        self.selection["sheets"][0]["size_status"] = "publisher-inventory-only"
        with self.assertRaisesRegex(MapError, "exact HEAD size"):
            capture_candidates(self.selection, self.fetcher())
        self.selection["sheets"][0]["size_status"] = "verified-by-head"
        self.selection["sheets"][0]["publisher_id"] = "different"
        with self.assertRaisesRegex(MapError, "absent"):
            capture_candidates(self.selection, self.fetcher())

    def test_missing_overview_and_duplicate_metadata_rejected(self):
        self.selection["overview_candidates"] = [{"source_url": "https://example.org/usa.pdf"}]
        with self.assertRaisesRegex(MapError, "Missing frozen national"):
            capture_candidates(self.selection, self.fetcher())
        self.selection["overview_candidates"] = []
        self.body = json.dumps({"items": [self.item, self.item]}).encode()
        self.selection["metadata_evidence"][0]["sha256"] = hashlib.sha256(self.body).hexdigest()
        with self.assertRaisesRegex(MapError, "Duplicate publisher"):
            capture_candidates(self.selection, self.fetcher())


if __name__ == "__main__":
    unittest.main()
