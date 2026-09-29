"""Metadata and transformation fixtures never contact publishers or fetch books."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.documents import DocumentError, render
from owl.acquisition.maps import MapError, coverage_holes, select_maps
from owl.acquisition.providers import ProviderError, discover, select_survivor, survivor_records


class Fetcher:
    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        return self.bodies(url) if callable(self.bodies) else self.bodies[url]


def recipe(adapter, **selection):
    return {"id": "fixture", "resource_id": "fixture", "adapter": adapter, "selection": selection,
            "source_asset_ids": [], "output_asset_ids": [], "metadata_sources": [], "blockers": []}


def polygon(west=0, south=0, east=2, north=2):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north],
                                                [west, north], [west, south]]]}


def sheet(identity, bbox, *, size=10, scale=24000, edition="2026"):
    return {"sheet_id": identity, "bbox": bbox, "size_bytes": size, "scale": scale,
            "edition": edition, "source_url": "https://example.org/" + identity + ".pdf"}


class ProviderTests(unittest.TestCase):
    def test_survivor_table_titles_bind_to_pdfs_and_enforce_exclusions(self):
        body = b'''<table><thead><tr><th>DateAdded</th><th>Title</th><th>Size</th><th>Link</th></tr></thead>
        <tr><td>2026-07-01</td><td>Practical_<em>Carpentry</em>_1912</td><td>12 mb</td><td><a href="/library/carpentry.pdf">PDF 12 mb</a></td></tr>
        <tr><td>2026-07-01</td><td>Old_Surgery_1898</td><td>12 mb</td><td><a href="/library/surgery.pdf">PDF 12 mb</a></td></tr></table>'''
        rows=survivor_records(body)
        self.assertEqual([r['title'] for r in rows],['Practical Carpentry 1912','Old Surgery 1898'])
        self.assertEqual(rows[0]['publisher_size_label'],'12 mb')
        self.assertNotIn('size_bytes',rows[0])
        url='https://www.survivorlibrary.com/index.php/library-carpentry/'
        r=recipe('survivor',required_topics=['carpentry'],exclude_title_patterns=[r'\bsurgery\b'])
        r['metadata_sources']=[{'url':url,'topics':['carpentry']}]
        result=discover(r,Fetcher({url:body}))['selection_report']
        self.assertEqual(len(result['pending']),1);self.assertEqual(len(result['rejected']),1)
        self.assertFalse(result['complete'])

    def test_survivor_old_labels_are_explicitly_inferred_not_book_identity(self):
        rows=survivor_records(b'<a href="/books/foundry_1905.pdf">PDF 9 mb</a><a href="b.pdf">Complete Practical Workshop</a>')
        self.assertEqual(rows[0]['title'],'foundry 1905')
        self.assertEqual(rows[0]['title_source'],'filename-pending-review')
        self.assertEqual(rows[1]['title_source'],'publisher-link-title')

    def test_hesperian_discovers_only_exact_edition_without_fetching_pdf(self):
        url = "https://languages.hesperian.org/pages/en/pdf.html"
        r = recipe("hesperian", edition="2026", expected_filename="en_midw_2026_bm.pdf")
        r["metadata_sources"] = [{"url": url, "kind": "html"}]
        fetcher = Fetcher({url: b'<a href="https://hesperian.org/en_midw_2025_bm.pdf">Old</a>'
                          b'<a href="https://hesperian.org/en_midw_2026_bm.pdf">Other resources</a>'})
        result = discover(r, fetcher)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(fetcher.calls, [url])
        self.assertFalse(result["candidates"][0]["body_verified"])
        self.assertTrue(result["blockers"])

    def test_survivor_dedup_does_not_promote_keyword_matches(self):
        rows = [{"title": "Practical carpentry", "source_url": "https://example.org/a.pdf", "topics": ["wood"]},
                {"title": "Practical carpentry", "source_url": "https://example.org/a.pdf", "topics": ["carpentry"]},
                {"title": "Old surgery", "source_url": "https://example.org/surgery.pdf", "topics": ["medicine"]}]
        policy = {"required_topics": ["wood", "carpentry"], "exclude_title_patterns": [r"\bsurgery\b"]}
        report = select_survivor(rows, policy)
        self.assertEqual(len(report["pending"]), 1)
        self.assertEqual(len(report["rejected"]), 1)
        self.assertFalse(report["complete"])
        policy["approved_titles"] = [{"source_url": rows[0]["source_url"], "reviewed": True,
                                     "topics": ["wood", "carpentry"], "evidence": ["review.json"]}]
        self.assertTrue(select_survivor(rows, policy)["complete"])

    def test_survivor_duplicate_edition_needs_written_reason(self):
        rows = [{"title": "Practical carpentry", "source_url": "https://example.org/" + name + ".pdf"}
                for name in ("a", "b")]
        policy = {"required_topics": ["carpentry"], "approved_titles": [dict(row, reviewed=True,
                  topics=["carpentry"], evidence=["review.json"]) for row in rows]}
        self.assertFalse(select_survivor(rows, policy)["complete"])
        for row in policy["approved_titles"]:
            row["complementary_reason"] = "Distinct joinery drawings reviewed"
        self.assertTrue(select_survivor(rows, policy)["complete"])

    def test_direct_inventory_does_not_request_archive(self):
        fetcher = Fetcher({})
        result = discover(recipe("zim_direct", entries=["A/Water", "A/Water"]), fetcher)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(fetcher.calls, [])
        self.assertTrue(result["blockers"])

    def test_lesson_metadata_rejects_unsupported_required_dependency(self):
        r = recipe("lessons", course_ids=["algebra"])
        url = "https://example.org/lessons.json"
        r["metadata_sources"] = [{"url": url, "kind": "json", "role": "lesson_manifest"}]
        body = {"revision": "1", "lessons": [{"id": "l1", "title": "Equations", "course_id": "algebra",
                "language": "en", "license": "CC-BY", "files": [{"format": "kolibri"}]}]}
        result = discover(r, Fetcher({url: json.dumps(body).encode()}))
        self.assertEqual(result["candidates"], [])
        self.assertTrue(any("Unsupported" in b for b in result["blockers"]))

    def test_map_pagination_repetition_fails(self):
        r = recipe("usgs_maps", max_pages=3)
        r["metadata_sources"] = [{"url": "https://example.org/products", "kind": "json"}]
        body = json.dumps({"total": 2, "items": [{}]}).encode()
        with self.assertRaisesRegex(ProviderError, "repeated"):
            discover(r, Fetcher(lambda url: body))

    def test_truncated_inventory_never_publishes_complete_map_selection(self):
        r = recipe("usgs_maps", max_pages=1, states=["CT"], allowances={"fixture": 100},
                   overview=[{"source_url": "https://example.org/usa.pdf", "size_bytes": 1}])
        r["metadata_sources"] = [{"url": "https://example.org/boundaries", "kind": "json", "role": "boundaries"},
                                 {"url": "https://example.org/products", "kind": "json", "scale": 24000}]
        def fetch(url):
            if "boundaries" in url:
                return json.dumps({"features": [{"properties": {"STUSPS": "CT"}, "geometry": polygon()}]}).encode()
            return json.dumps({"total": 2, "items": [{"sheet_id": "one", "size_bytes": 10,
                              "edition": "2026", "bbox": [0, 0, 2, 2], "source_url": "https://example.org/one.pdf"}]}).encode()
        result = discover(r, Fetcher(fetch))
        self.assertFalse(result["inventory_complete"])
        self.assertFalse(result["plans"]["fixture"]["complete"])
        self.assertEqual(result["plans"]["fixture"]["selected"], [])

    def test_pending_overview_reserves_bytes_but_cannot_complete_selection(self):
        candidate = {"id": "usa-pending", "source_url": "https://example.org/pending.pdf", "size_bytes": 20,
                     "scale": 5000000, "version_date": "2001-01-01", "candidate_manifest": "overview.json",
                     "sha256": None, "pin_status": "pending"}
        r = recipe("usgs_maps", states=["CT"], allowances={"fixture": 50}, overview_candidates=[candidate],
                   overview=[{"source_url": "https://example.org/other-overview.pdf", "size_bytes": 1}])
        r["metadata_sources"] = [{"url": "https://example.org/boundaries", "kind": "json", "role": "boundaries"},
                                 {"url": "https://example.org/products", "kind": "json", "scale": 24000}]
        def fetch(url):
            if "boundaries" in url:
                return json.dumps({"features": [{"properties": {"STUSPS": "CT"}, "geometry": polygon()}]}).encode()
            return json.dumps({"total": 1, "items": [{"sheet_id": "one", "size_bytes": 10,
                              "edition": "2026", "bbox": [0, 0, 2, 2], "source_url": "https://example.org/one.pdf"}]}).encode()
        result = discover(r, Fetcher(fetch))
        plan = result["plans"]["fixture"]
        self.assertFalse(plan["complete"])
        self.assertEqual(plan["selected"], [])
        self.assertEqual(plan["sheet_budget_bytes"], 30)
        self.assertEqual(plan["candidate_total_bytes"], 31)
        self.assertEqual(plan["budget_bytes"], 50)
        self.assertTrue(any("identity selected" in reason for reason in plan["blockers"]))
        candidate["sha256"] = "a" * 64
        with self.assertRaisesRegex(ProviderError, "pending content pin"):
            discover(r, Fetcher(fetch))


class MapTests(unittest.TestCase):
    def test_holes_detect_thin_gap_not_just_corner_coverage(self):
        gaps = coverage_holes(polygon(), [[0, 0, 0.999, 2], [1.001, 0, 2, 2]])
        self.assertAlmostEqual(sum(row["area_square_degrees"] for row in gaps), .004)

    def test_polygon_interior_hole_and_disconnected_island(self):
        geo = polygon()
        geo["coordinates"].append([[.5, .5], [.5, 1.5], [1.5, 1.5], [1.5, .5], [.5, .5]])
        footprints = [[0, 0, .5, 2], [1.5, 0, 2, 2], [.5, 0, 1.5, .5], [.5, 1.5, 1.5, 2]]
        self.assertEqual(coverage_holes(geo, footprints), [])
        geo = {"type": "MultiPolygon", "coordinates": [polygon()["coordinates"], polygon(3, 3, 4, 4)["coordinates"]]}
        gaps = coverage_holes(geo, [[0, 0, 2, 2]])
        self.assertAlmostEqual(sum(row["area_square_degrees"] for row in gaps), 1)

    def test_finest_complete_scale_within_budget_and_no_filler(self):
        rows = [sheet("fine-left", [0, 0, 1, 2], size=30), sheet("fine-right", [1, 0, 2, 2], size=30),
                sheet("coarse", [0, 0, 2, 2], scale=100000, size=20),
                sheet("irrelevant", [3, 3, 4, 4], size=1000)]
        overview = [{"source_url": "https://example.org/usa.pdf", "size_bytes": 1}]
        result = select_maps(rows, {"CT": polygon()}, 70, overview=overview, states=["CT"])
        self.assertEqual(result["scale"], 24000)
        self.assertEqual(result["size_bytes"], 61)
        self.assertNotIn("irrelevant", [r.get("sheet_id") for r in result["selected"]])
        self.assertEqual(select_maps(rows, {"CT": polygon()}, 50, overview=overview, states=["CT"])["scale"], 100000)
        self.assertFalse(select_maps(rows, {"CT": polygon()}, 10, overview=overview, states=["CT"])["complete"])

    def test_fine_gap_uses_complete_coarser_scale(self):
        rows = [sheet("half", [0, 0, 1, 2]), sheet("whole", [0, 0, 2, 2], scale=100000)]
        result = select_maps(rows, {"CT": polygon()}, 100, states=["CT"],
                             overview=[{"source_url": "https://example.org/usa.pdf", "size_bytes": 1}])
        self.assertEqual(result["scale"], 100000)
        self.assertIn("CT", result["attempts"][0]["holes"])

    def test_missing_region_and_overview_never_claim_complete(self):
        self.assertFalse(select_maps([], {}, 100)["complete"])
        self.assertFalse(select_maps([sheet("whole", [0, 0, 2, 2])], {"CT": polygon()}, 100, states=["CT"])["complete"])

    def test_latest_sheet_edition_wins_without_duplicate_bytes(self):
        old = sheet("same", [0, 0, 2, 2], edition="2023", size=90)
        new = sheet("same", [0, 0, 2, 2], edition="2026", size=10)
        result = select_maps([old, new], {"CT": polygon()}, 20, states=["CT"],
                            overview=[{"source_url": "https://example.org/usa.pdf", "size_bytes": 1}])
        self.assertTrue(result["complete"])
        self.assertEqual(result["size_bytes"], 11)

    def test_unknown_sizes_and_invalid_geometries_fail(self):
        with self.assertRaises(MapError):
            select_maps([sheet("bad", [0, 0, 2, 2], size=None)], {"CT": polygon()}, 100, states=["CT"])
        with self.assertRaises(MapError):
            coverage_holes({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 2]]]}, [])


class DocumentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.assets = {"output": {"title": "Fixture", "destination": "REFERENCE/output.html"},
                       "other": {"destination": "REFERENCE/other.pdf"}}
        self.sources = {}
        self.add_source("source", b'<html><body><article class="guide"><h2 id="title">Complete guide</h2>'
                        b'<p>Follow the complete procedure.</p><table><tr><td>12 minutes</td></tr></table>'
                        b'<img src="diagram.png" alt="Diagram"><a href="#title">Heading</a>'
                        b'<a href="other.pdf">Companion</a><script>remote()</script></article></body></html>',
                        "https://example.org/guide.html")
        self.add_source("image", b"\x89PNG\r\n\x1a\nfixture", "https://example.org/diagram.png")
        self.recipe = recipe("html_snapshot", dependencies={"https://example.org/diagram.png": "image"},
            links={"https://example.org/other.pdf": "other"}, outputs=[{"asset_id": "output", "title": "Guide",
            "sections": [{"source_asset_id": "source", "tag": "article", "attribute": "class", "value": "guide", "expected_count": 1}]}])
        self.recipe.update(source_asset_ids=["source", "image"], output_asset_ids=["output"])

    def add_source(self, identity, body, url):
        path = self.root / identity
        path.write_bytes(body)
        self.sources[identity] = path
        self.assets[identity] = {"source_url": url, "size_bytes": len(body), "sha256": sha256(body).hexdigest()}

    def test_preserves_text_tables_illustrations_and_local_links_deterministically(self):
        first = render(self.recipe, self.sources, self.assets, self.root / "first")["output"].read_bytes()
        second = render(self.recipe, self.sources, self.assets, self.root / "second")["output"].read_bytes()
        self.assertEqual(first, second)
        self.assertIn(b"12 minutes", first)
        self.assertIn(b'class="table-scroll"', first)
        self.assertIn(b'data:image/png;base64,', first)
        self.assertIn(b'href="#s0-title"', first)
        self.assertIn(b'href="other.pdf"', first)
        self.assertNotIn(b"remote()", first)

    def test_missing_dependency_or_changed_source_fails_before_outputs(self):
        changed = deepcopy(self.recipe)
        changed["selection"]["dependencies"] = {}
        with self.assertRaisesRegex(DocumentError, "Undeclared illustration"):
            render(changed, self.sources, self.assets, self.root / "out")
        self.assertFalse((self.root / "out").exists())
        self.sources["source"].write_bytes(b"changed")
        with self.assertRaisesRegex(DocumentError, "differs from its pin"):
            render(self.recipe, self.sources, self.assets, self.root / "out")

    def test_selector_count_class_exact_and_explicit_index_are_frozen(self):
        self.add_source("source", b'<div class="guide">First</div><div class="guide more">Second</div>'
                        b'<div class="guide">Footer</div>', "https://example.org/guide.html")
        section = self.recipe["selection"]["outputs"][0]["sections"][0]
        section["tag"] = "div"
        with self.assertRaisesRegex(DocumentError, "found 3"):
            render(self.recipe, self.sources, self.assets, self.root / "bad")
        section.update(class_exact=True, expected_count=2, match_index=0, expected_text_sha256=sha256(b"First").hexdigest())
        text = render(self.recipe, self.sources, self.assets, self.root / "good")["output"].read_text()
        self.assertIn("First", text)
        self.assertNotIn("Second", text)
        self.assertNotIn("Footer", text)
        section["match_index"] = 2
        with self.assertRaisesRegex(DocumentError, "outside"):
            render(self.recipe, self.sources, self.assets, self.root / "bad")

    def test_unknown_interactive_content_and_fragments_fail(self):
        for body, message in [(b'<article class="guide"><canvas>Chart</canvas></article>', "Unsupported selected content"),
                              (b'<article class="guide"><a href="#missing">Link</a></article>', "Missing selected fragment")]:
            with self.subTest(message=message):
                self.add_source("source", body, "https://example.org/guide.html")
                with self.assertRaisesRegex(DocumentError, message):
                    render(self.recipe, self.sources, self.assets, self.root / "out")

    def test_publisher_ftp_citation_remains_explicitly_online(self):
        self.add_source('source',b'<article class="guide"><a href="ftp://ftp.gnu.org/pub/gnu/bash/">Original download citation</a></article>', 'https://example.org/guide.html')
        result=render(self.recipe,self.sources,self.assets,self.root/'ftp')['output'].read_text()
        self.assertIn('href="ftp://ftp.gnu.org/pub/gnu/bash/"',result)
        self.assertIn('class="online"',result);self.assertIn('Internet required',result)
        self.add_source('source',b'<article class="guide"><a href="javascript:alert(1)">Unsafe</a></article>', 'https://example.org/guide.html')
        with self.assertRaisesRegex(DocumentError,'Unsupported link'):render(self.recipe,self.sources,self.assets,self.root/'unsafe')

    def test_encoded_fragment_and_counted_missing_index_link_keep_valid_local_targets(self):
        self.add_source('source',b'<article class="guide"><h2 id="See Also">All instructions</h2>'
                        b'<a href="#See%20Also">Encoded title</a><a href="#missing-option">Option index</a>'
                        b'<a id="" href="#">Top of document</a></article>', 'https://example.org/guide.html')
        section=self.recipe['selection']['outputs'][0]['sections'][0]
        section['fragment_repairs']=[{'from':'#missing-option','to':'#See%20Also','expected_count':1}]
        result=render(self.recipe,self.sources,self.assets,self.root/'encoded')['output'].read_text()
        self.assertEqual(result.count('href="#s0-See Also"'),2)
        self.assertIn('href="#">Top of document</a>',result)
        self.assertNotIn('id=""',result)
        self.assertIn('All instructions',result);self.assertIn('Option index',result)
        section['fragment_repairs'][0]['expected_count']=2
        with self.assertRaisesRegex(DocumentError,'occurrence count'):render(self.recipe,self.sources,self.assets,self.root/'changed')
        section['fragment_repairs'][0].update(expected_count=1,to='#absent')
        with self.assertRaisesRegex(DocumentError,'existing unique target'):render(self.recipe,self.sources,self.assets,self.root/'absent')

    def test_legacy_named_anchors_rewrite_and_duplicate_names_fail(self):
        self.add_source("source", b'<article class="guide"><a href="#table1">Table</a>'
                        b'<a name="table1"></a><table><tr><td>Complete</td></tr></table></article>',
                        "https://example.org/guide.html")
        result = render(self.recipe, self.sources, self.assets, self.root / "out")["output"].read_text()
        self.assertIn('href="#s0-table1"', result)
        self.assertIn('id="s0-table1"', result)
        self.add_source("source", b'<article class="guide"><a name="same"></a><a id="same">Text</a></article>',
                        "https://example.org/guide.html")
        with self.assertRaisesRegex(DocumentError, "Duplicate"):
            render(self.recipe, self.sources, self.assets, self.root / "bad")

    def test_source_bound_duplicate_anchor_repair_preserves_content_and_first_target(self):
        body=(b'<article class="guide"><a href="#v245">First canonical release badge</a>'
              b'<a id="v245" name="v245">Added in245</a><p>Keep first instructions</p>'
              b'<a id="v245">Added in245</a><p>Keep second instructions</p></article>')
        self.add_source('source',body,'https://example.org/guide.html')
        section=self.recipe['selection']['outputs'][0]['sections'][0]
        with self.assertRaisesRegex(DocumentError,'Duplicate selected'):render(self.recipe,self.sources,self.assets,self.root/'missing-policy')
        section['duplicate_id_counts']={'v245':2}
        output=render(self.recipe,self.sources,self.assets,self.root/'repaired')['output'].read_text()
        self.assertEqual(output.count('id="s0-v245"'),1)
        self.assertIn('id="s0-v245--owl-duplicate-2"',output)
        self.assertIn('href="#s0-v245"',output)
        self.assertEqual(output.count('Added in245'),2)
        self.assertIn('Keep first instructions',output);self.assertIn('Keep second instructions',output)
        section['duplicate_id_counts']={'v245':3}
        with self.assertRaisesRegex(DocumentError,'repair counts'):render(self.recipe,self.sources,self.assets,self.root/'changed-count')
        section['duplicate_id_counts']={'v245':2}
        self.add_source('source',body.replace(b'</article>',b'<span id="v245--owl-duplicate-2">Publisher target</span></article>'),'https://example.org/guide.html')
        with self.assertRaisesRegex(DocumentError,'collides'):render(self.recipe,self.sources,self.assets,self.root/'collision')
        self.assertFalse((self.root/'collision').exists())

    def test_cross_recipe_links_jump_to_selected_section_and_original_fragment(self):
        self.add_source("source", b'<article class="guide"><a href="recipe.html">Whole recipe</a>'
                        b'<a href="recipe.html#table1">Processing table</a></article>',
                        "https://example.org/guide.html")
        self.add_source("recipe", b'<article><h2>Complete recipe</h2><a name="table1"></a>'
                        b'<table><tr><td>Original table</td></tr></table></article>',
                        "https://example.org/recipe.html")
        self.recipe["source_asset_ids"].append("recipe")
        self.recipe["selection"]["links"]["https://example.org/recipe.html"] = "output"
        self.recipe["selection"]["outputs"][0]["sections"].append(
            {"source_asset_id": "recipe", "tag": "article", "expected_count": 1})
        result = render(self.recipe, self.sources, self.assets, self.root / "out")["output"].read_text()
        self.assertIn('href="#section-1"', result)
        self.assertIn('href="#s1-table1"', result)
        self.assertIn('id="section-1"', result)
        self.assertIn('id="s1-table1"', result)
        self.add_source("source", b'<article class="guide"><a href="recipe.html#absent">Bad</a></article>',
                        "https://example.org/guide.html")
        with self.assertRaisesRegex(DocumentError, "Missing cross-document"):
            render(self.recipe, self.sources, self.assets, self.root / "bad")

    def test_manual_body_retains_author_notices_and_removes_remote_styles(self):
        self.add_source("source", b'<html><head><link rel="stylesheet" href="https://x/style.css"></head>'
                        b'<body><h1>SSH</h1><p>Full manual.</p><footer>Author copyright</footer></body></html>',
                        "https://example.org/ssh.html")
        self.recipe["adapter"] = "manual_html"
        self.recipe["selection"]["outputs"][0]["sections"] = [{"source_asset_id": "source", "tag": "body", "expected_count": 1}]
        result = render(self.recipe, self.sources, self.assets, self.root / "out")["output"].read_text()
        self.assertIn("Author copyright", result)
        self.assertNotIn("https://x/style.css", result)


if __name__ == "__main__":
    unittest.main()
