import json
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.ocw_expansion import (
    INDEX, SITEMAP, course_id, freeze_packages, immutable_json, load_index, rank_courses,
)
from owl.safety import SafetyError


def row(slug="18-06-linear-algebra-spring-2020", *, number="18.06", title="Linear Algebra", department="18", year=2020, identity=1):
    return {"id": identity, "url": "https://ocw.mit.edu/courses/" + slug + "/",
        "title": title, "published": True, "resource_type": "course", "platform": {"code": "ocw"},
        "departments": [{"department_id": department}], "runs": [{"year": year}],
        "course": {"course_numbers": [{"value": number}]},
        "course_feature": ["Lecture Videos", "Lecture Notes", "Problem Sets"], "languages": None}


class Metadata:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def fetch(self, url, *, kind):
        self.calls.append(url)
        value = self.responses[url]
        return value if isinstance(value, bytes) else json.dumps(value).encode()


class Probe:
    def __init__(self, *, size=1234, blockers=None):
        self.size, self.calls = size, []
        self.blockers = blockers if blockers is not None else [
            "Publisher metadata supplies no whole-file SHA-256; ETag/MD5/SHA-1 are not pins"]

    def probe(self, request):
        self.calls.append(request)
        return {"size_bytes": self.size, "sha256": None, "blockers": self.blockers,
            "evidence": [{"url": request["url"], "final_url": request["url"], "method": "HEAD",
                "body_read": False, "status": 200, "headers": {"content-length": str(self.size)},
                "checked_at": "2026-09-27", "cached": False}]}


class OcwExpansionTests(unittest.TestCase):
    def test_index_requires_complete_pagination_and_official_sitemap(self):
        course = row()
        xml = f'<sitemapindex><sitemap><loc>{course["url"]}sitemap.xml</loc></sitemap></sitemapindex>'.encode()
        url = INDEX + "?platform=ocw&course_feature=Lecture%20Videos&limit=100&offset=0"
        metadata = Metadata({SITEMAP: xml, url: {"count": 1, "results": [course], "next": None}})
        rows, evidence = load_index(metadata)
        self.assertEqual(rows, [course])
        self.assertEqual(len(evidence), 2)
        metadata.responses[url]["count"] = 101
        with self.assertRaisesRegex(SafetyError, "incomplete"):
            load_index(metadata)

    def test_untrusted_course_host_and_xml_entities_are_rejected(self):
        with self.assertRaises(SafetyError):
            course_id("https://example.com/courses/course/")
        with self.assertRaises(SafetyError):
            course_id("https://ocw.mit.edu/courses/../")
        with self.assertRaisesRegex(SafetyError, "entity"):
            load_index(Metadata({SITEMAP: b'<!DOCTYPE foo [<!ENTITY xx "bad">]><sitemapindex/>'}))

    def test_deduplicates_editions_titles_and_cross_listings_against_existing(self):
        existing = row("18-06sc-linear-algebra-fall-2011", number="18.06SC", year=2011)
        same_title = row("18-new-linear-algebra-fall-2024", number="18.NEW", year=2024, identity=3)
        other = row("6-100-algorithms-fall-2023", number="6.100", title="Algorithms", department="6", identity=4)
        selected, available = rank_courses([existing, row(identity=2), same_title, other], excluded_ids=[course_id(existing["url"])])
        self.assertEqual([r["title"] for r in selected], ["Algorithms"])
        self.assertEqual(available, 1)
        self.assertIsNone(selected[0]["expected_useful_bytes"])

    def test_deterministic_diverse_ranking_and_explicit_language_rejection(self):
        courses = [row(), row("18-01-calculus-fall-2021", number="18.01", title="Calculus", identity=2),
            row("6-100-algorithms-fall-2023", number="6.100", title="Algorithms", department="6", identity=3)]
        selected, _ = rank_courses(courses)
        reversed_selection, _ = rank_courses(list(reversed(courses)))
        self.assertEqual(selected, reversed_selection)
        self.assertEqual([c["subject"] for c in selected], ["mathematics", "computing", "mathematics"])
        courses[2]["languages"] = ["fr"]
        self.assertEqual(len(rank_courses(courses)[0]), 2)

    def capture_inputs(self):
        candidate = rank_courses([row()])[0][0]
        base = candidate["course_url"]
        metadata = Metadata({base + "data.json": {"site_url_path": "courses/" + candidate["id"],
            "site_uid": "course-work-id", "course_title": candidate["title"]},
            base + "download/": f'<a href="{base}18.06-spring-2020.zip">Download course</a><a href="https://archive.org/download/item/first.mp4">Video</a>'.encode()})
        return candidate, metadata

    def test_package_capture_is_exact_size_build_input_not_partial_video_selection(self):
        candidate, metadata = self.capture_inputs()
        probe = Probe()
        candidates, manifest = freeze_packages([candidate], metadata, probe)
        self.assertEqual(manifest["budget"]["download_bytes"], 1234)
        self.assertEqual(len(manifest["sources"]), 1)
        self.assertNotIn("fullasset_metadata", manifest["sources"][0])
        self.assertFalse(manifest["content_ready"])
        self.assertIsNone(candidates[0]["expected_useful_bytes"])
        self.assertIsNone(manifest["sources"][0]["sha256"])
        self.assertIn("incomplete evidence", candidates[0]["media_inventory"])
        self.assertTrue(all(not u.endswith((".zip", ".mp4")) for u in metadata.calls))
        self.assertTrue(probe.calls[0]["url"].endswith(".zip"))

    def test_missing_size_overlaps_and_non_hash_probe_failures_are_explicit(self):
        for probe, kwargs in [(Probe(size=None), {}), (Probe(size=600_000_000), {}), (Probe(blockers=["Source HEAD returned HTTP 404"]), {}),
                              (Probe(), {"max_source_bytes": 1}), (Probe(), {"excluded_urls": [
                                  "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2020/18.06-spring-2020.zip"]})]:
            with self.subTest(kwargs=kwargs, size=probe.size):
                candidate, metadata = self.capture_inputs()
                candidates, manifest = freeze_packages([candidate], metadata, probe, **kwargs)
                self.assertIsNone(manifest)
                self.assertIsNone(candidates[0]["capture_source_id"])
                self.assertGreater(len(candidates[0]["blockers"]), 5)

    def test_same_cached_pins_are_deterministic_and_frozen_files_are_immutable(self):
        candidate, metadata = self.capture_inputs()
        a = freeze_packages([candidate], metadata, Probe())
        b = freeze_packages([candidate], metadata, Probe())
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "proposal.json"
            immutable_json(path, a[1])
            immutable_json(path, b[1])
            with self.assertRaisesRegex(SafetyError, "differs"):
                immutable_json(path, {"different": True})


if __name__ == "__main__":
    unittest.main()
