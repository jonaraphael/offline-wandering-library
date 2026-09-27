"""Exact mixed-scale coverage and authoritative offshore exclusions."""
import importlib.util
from copy import deepcopy
import unittest

from owl.acquisition.maps import MapError, coverage_holes, exclude_offshore_water, select_mixed_maps
from owl.acquisition.map_manifest import freeze_selection


def polygon(west=0, south=0, east=2, north=2):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north],
                                                [west, north], [west, south]]]}


def sheet(identity, bbox, scale, size=10):
    return {"sheet_id": identity, "bbox": bbox, "size_bytes": size, "scale": scale,
            "edition": "2026", "source_url": "https://example.org/" + identity + ".pdf"}


class PrecisionTests(unittest.TestCase):
    def test_positive_area_gap_is_never_discarded_as_tolerance(self):
        holes = coverage_holes(polygon(), [[0, 0, 1, 2], [1 + 1e-12, 0, 2, 2]])
        self.assertTrue(holes)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        row = sheet("one", [0, 0, 2, 2], 100000)
        self.discovery = {"results": [{"resource_id": "regional-maps", "recipe_id": "maps",
            "recipe_sha256": "a" * 64, "inventory_complete": True, "boundary_states": ["CT"],
            "plans": {"full-1tb": {"geographic_complete": True, "holes": {}, "proposed_sheets": [row],
                                  "base_scale": 100000, "scales": [100000], "budget_bytes": 100}}}]}
        self.probes = {"records": [{"id": "one", "source_url": row["source_url"], "size_bytes": 12,
            "sha256": None, "evidence": [{"method": "HEAD", "status": 200, "url": row["source_url"],
                                           "body_read": False, "headers": {"content-length": "12"}}]}]}

    def test_verified_size_correction_never_becomes_a_content_pin(self):
        manifest = freeze_selection(self.discovery, "full-1tb", self.probes)
        self.assertEqual(manifest["size_bytes"], 12)
        self.assertEqual(len(manifest["metadata_size_discrepancies"]), 1)
        self.assertEqual(manifest["sheets"][0]["size_status"], "verified-by-head")
        self.assertIsNone(manifest["sheets"][0]["sha256"])
        self.assertFalse(manifest["content_ready"])
        self.assertEqual(manifest, freeze_selection(deepcopy(self.discovery), "full-1tb", deepcopy(self.probes)))

    def test_changed_size_capacity_and_duplicate_sources_rejected(self):
        self.probes["records"][0]["size_bytes"] = 101
        self.probes["records"][0]["evidence"][0]["headers"]["content-length"] = "101"
        with self.assertRaisesRegex(MapError, "allowance"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        self.probes["records"].append(deepcopy(self.probes["records"][0]))
        with self.assertRaisesRegex(MapError, "Duplicate"):
            freeze_selection(self.discovery, "full-1tb", self.probes)

    def test_incomplete_inventory_and_hash_substitutes_rejected(self):
        self.discovery["results"][0]["inventory_complete"] = False
        with self.assertRaisesRegex(MapError, "incomplete"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        self.discovery["results"][0]["inventory_complete"] = True
        self.probes["records"][0]["sha256"] = "etag-not-a-sha256"
        with self.assertRaisesRegex(MapError, "SHA256"):
            freeze_selection(self.discovery, "full-1tb", self.probes)

    def test_distinct_sheet_ids_cannot_count_the_same_source_twice(self):
        sheets = self.discovery["results"][0]["plans"]["full-1tb"]["proposed_sheets"]
        duplicate = deepcopy(sheets[0])
        duplicate["sheet_id"] = "different-identifier"
        sheets.append(duplicate)
        with self.assertRaisesRegex(MapError, "Duplicate selected map source URL"):
            freeze_selection(self.discovery, "full-1tb", self.probes)

    def test_pending_or_unbound_source_probe_cannot_supply_pin(self):
        record = self.probes["records"][0]
        record["sha256"], record["status"] = "b" * 64, "pending"
        with self.assertRaisesRegex(MapError, "proposed source probe"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        record["status"] = "proposed"
        record["evidence"][0]["url"] = "https://example.org/unrelated.pdf"
        with self.assertRaisesRegex(MapError, "URL-bound HEAD"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        record["evidence"][0]["url"] = record["source_url"]
        record["evidence"][0]["status"] = 404
        with self.assertRaisesRegex(MapError, "URL-bound HEAD"):
            freeze_selection(self.discovery, "full-1tb", self.probes)

    def test_probe_size_must_match_one_unambiguous_response_length(self):
        response = self.probes["records"][0]["evidence"][0]
        response["headers"]["content-length"] = "13"
        with self.assertRaisesRegex(MapError, "differs.*Content-Length"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        response["headers"]["content-length"] = "12"
        conflict = deepcopy(response)
        conflict["headers"]["content-length"] = "13"
        self.probes["records"][0]["evidence"].append(conflict)
        with self.assertRaisesRegex(MapError, "Conflicting"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        self.probes["records"][0]["evidence"] = [response]
        del response["headers"]["content-length"]
        with self.assertRaisesRegex(MapError, "lacks.*Content-Length"):
            freeze_selection(self.discovery, "full-1tb", self.probes)

    def test_partial_or_encoded_head_cannot_verify_whole_file_size(self):
        headers = self.probes["records"][0]["evidence"][0]["headers"]
        for key, value in [("content-range", "bytes 0-11/24"), ("content-encoding", "gzip")]:
            headers[key] = value
            with self.assertRaisesRegex(MapError, "whole identity"):
                freeze_selection(self.discovery, "full-1tb", self.probes)
            del headers[key]

    def test_pending_overview_is_separate_counted_once_and_never_ready(self):
        overview = {"id": "usa", "source_url": "https://example.org/usa.pdf", "size_bytes": 20,
                    "sha256": None, "pin_status": "pending", "scale": 5000000}
        self.discovery["results"][0]["overview_candidates"] = [overview]
        manifest = freeze_selection(self.discovery, "full-1tb", self.probes)
        self.assertEqual(manifest["sheet_count"], 1)
        self.assertEqual(manifest["size_bytes"], 12)
        self.assertEqual(manifest["overview_candidate_bytes"], 20)
        self.assertEqual(manifest["combined_candidate_bytes"], 32)
        self.assertFalse(manifest["content_ready"])
        self.assertIsNone(manifest["overview_candidates"][0]["sha256"])
        self.assertIn("source identity is selected", manifest["blockers"][1])
        self.discovery["results"][0]["plans"]["full-1tb"]["budget_bytes"] = 31
        with self.assertRaisesRegex(MapError, "allowance"):
            freeze_selection(self.discovery, "full-1tb", self.probes)
        self.discovery["results"][0]["plans"]["full-1tb"]["budget_bytes"] = 100
        overview["source_url"] = self.probes["records"][0]["source_url"]
        with self.assertRaisesRegex(MapError, "unique identities"):
            freeze_selection(self.discovery, "full-1tb", self.probes)


@unittest.skipUnless(importlib.util.find_spec("shapely"), "optional Shapely dependency")
class MixedMapTests(unittest.TestCase):
    def test_fine_supplement_closes_actual_gap_without_filler(self):
        rows = [sheet("base", [0, 0, 2, 1.9], 100000), sheet("border", [0, 1.9, 2, 2], 24000),
                sheet("unneeded", [0, 0, 1, 1], 24000, 1000)]
        result = select_mixed_maps(rows, {"CT": polygon()}, 25, states=["CT"])
        self.assertTrue(result["geographic_complete"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["base_scale"], 100000)
        self.assertEqual([row["sheet_id"] for row in result["proposed_sheets"]], ["base", "border"])
        self.assertEqual(result["size_bytes"], 20)
        self.assertFalse(select_mixed_maps(rows, {"CT": polygon()}, 19, states=["CT"])["geographic_complete"])
        self.assertEqual(result, select_mixed_maps(list(reversed(rows)), {"CT": polygon()}, 25, states=["CT"]))

    def test_incomplete_mixed_scale_never_returns_complete_proposal(self):
        rows = [sheet("base", [0, 0, 2, 1.8], 100000), sheet("border", [0, 1.9, 2, 2], 24000)]
        result = select_mixed_maps(rows, {"CT": polygon()}, 25, states=["CT"])
        self.assertFalse(result["geographic_complete"])
        self.assertEqual(result["proposed_sheets"], [])
        self.assertIn("CT", result["attempts"][-1]["holes"])

    def test_water_exclusion_preserves_island_and_rejects_unproven_mask(self):
        ocean = polygon(1, 0, 2, 2)
        ocean["coordinates"].append([[1.2, .2], [1.2, .4], [1.4, .4], [1.4, .2], [1.2, .2]])
        feature = {"properties": {"MTFCC": "H2053", "NAME": "Atlantic Ocean", "AREALAND": 0,
                                  "AREAWATER": 100}, "geometry": ocean}
        regions, evidence = exclude_offshore_water({"CT": polygon()}, [feature])
        holes = coverage_holes(regions["CT"], [[0, 0, 1, 2]])
        self.assertTrue(holes, "The island inside the ocean must remain a coverage gap")
        self.assertEqual(evidence[0]["NAME"], "Atlantic Ocean")
        feature["properties"]["AREALAND"] = 1
        with self.assertRaisesRegex(MapError, "zero-land"):
            exclude_offshore_water({"CT": polygon()}, [feature])
        feature["properties"]["AREALAND"] = False
        with self.assertRaisesRegex(MapError, "zero-land"):
            exclude_offshore_water({"CT": polygon()}, [feature])


if __name__ == "__main__":
    unittest.main()
