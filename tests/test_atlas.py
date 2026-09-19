"""Pure topic rendering: shared routes, accurate coverage, bounded static pages."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from owl.atlas import MAX_PAGE_BYTES, prepare_atlas
from owl.layout import checksum_name, logical_name
from owl.safety import SafetyError


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.ids, self.entries = [], set(), 0
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "a":
            self.links.append(attributes["href"])
        if attributes.get("class") == "entry":
            self.entries += 1


class AtlasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name).resolve() / "LIBRARY"
        self.asset = self.make_asset("book", "pdf", textbook=True, critical=True)
        self.topics = {"science": self.topic("science", "Science"),
                       "repair": self.topic("repair", "Repair"),
                       "learning": self.topic("learning", "Learning"),
                       "measurements": self.topic("measurements", "Measurements", ["science", "repair", "learning"],
                                                   aliases=["Meter reading"]),
                       "voltage": self.topic("voltage", "Voltage", ["measurements"]),
                       "empty": self.topic("empty", "Excluded branch", ["science"])}
        self.navigation = {"topics": self.topics,
                           "entrances": {"subjects": ["science"], "tasks": ["repair"], "learn": ["learning"]},
                           "assignments": [self.assignment("measurements", "book", "intro", "start-here"),
                                           self.assignment("voltage", "book", "voltage", "explanation")],
                           "sections": {"book": self.mapping(self.asset, [self.section("intro", 1),
                               self.section("voltage", 2, parent="intro")])},
                           "input_hashes": {"topics.yaml": "a" * 64, "assignments.yaml": "b" * 64}}

    def make_asset(self, identity, format, *, textbook=False, critical=False, illustrated=False):
        relative = f"BOOKS/{identity}.{format}"
        data = b"Local renderer fixture; file verification belongs to the caller."
        path = self.target / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(data)
        return {"id": identity, "title": "Book " + identity, "destination": relative, "format": format,
                "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "version": "Fixture edition 1",
                "publisher": "Fixture publisher", "license": "CC-BY-4.0", "attribution": "Fixture Author & Contributors",
                "resource_type": "textbook" if textbook else "reference", "critical": critical, "required": True,
                "illustrated": illustrated, "reader_required": format in {"zim", "epub"}}

    def topic(self, identity, title, parents=(), *, aliases=(), related=()):
        return {"id": identity, "title": title, "description": f"Coverage for {title}", "parents": list(parents),
                "related": list(related), "aliases": list(aliases), "order": None}

    def section(self, identity, page, parent=None, **extra):
        return {"id": identity, "title": "Section " + identity, "parent": parent,
                "locator": {"type": "pdf-page", "page": page}, "provenance": "publisher-outline", **extra}

    def mapping(self, asset, sections):
        return {"schema_version": 1, "asset_id": asset["id"], "source_sha256": asset["sha256"], "sections": sections}

    def assignment(self, topic, asset, section=None, purpose="reference", **extra):
        return {"topic_id": topic, "asset_id": asset, "section_id": section, "purpose": purpose, "order": None, **extra}

    def render(self, assets=None):
        return prepare_atlas(self.target, assets if assets is not None else [self.asset], self.navigation)

    def test_shared_topic_has_one_page_three_routes_and_deduplicated_counts(self):
        self.navigation["assignments"].append(self.assignment("measurements", "book", "intro"))
        self.navigation["assignments"].append(self.assignment("science", "book", "voltage"))
        pages, report = self.render()
        self.assertEqual(report["topics"]["science"]["asset_count"], 1)
        self.assertEqual(report["topics"]["science"]["location_count"], 2)
        self.assertEqual(pages["INDEX/topics/measurements.html"].count("Open this section"), 1)
        shared = pages["INDEX/topics/measurements.html"]
        self.assertIn('href="science.html"', shared)
        self.assertIn('href="repair.html"', shared)
        self.assertIn('href="learning.html"', shared)
        self.assertIn("Canonical topic breadcrumb", shared)
        self.assertTrue(report["textbook_route_coverage"]["book"]["subjects"])
        self.assertTrue(report["textbook_route_coverage"]["book"]["learn"])
        self.assertEqual(report["omitted_topic_ids"], ["empty"])
        self.assertNotIn("INDEX/topics/empty.html", pages)
        self.assertFalse((self.target / "INDEX").exists(), "Renderer must not write output")

    def test_related_wrong_turn_links_and_filtered_empty_branch(self):
        self.topics["science"]["related"] = ["repair", "empty"]
        self.navigation["assignments"].append(self.assignment("empty", "excluded"))
        pages, report = self.render()
        self.assertIn("Related topics and other routes", pages["INDEX/topics/science.html"])
        self.assertIn('href="repair.html"', pages["INDEX/topics/science.html"])
        self.assertNotIn("empty.html", pages["INDEX/topics/science.html"])
        self.assertEqual(report["unmapped_critical"], [])

    def test_ambiguous_alias_is_a_choice_list_and_duplicate_alias_merges(self):
        self.topics["voltage"]["aliases"] = ["Charge", "charge", " Charge "]
        self.topics["measurements"]["aliases"] = ["CHARGE"]
        pages, _ = self.render()
        page = pages["INDEX/topic-a-z/C.html"]
        self.assertEqual(page.count("This label has several meanings"), 1)
        self.assertIn("../topics/measurements.html", page)
        self.assertIn("../topics/voltage.html", page)

    def test_reader_only_requirements_visible_before_opening_topic(self):
        archive = self.make_asset("archive", "zim")
        self.topics["archives"] = self.topic("archives", "Archive material", ["science"])
        section = {"id": "article", "title": "Archive article", "parent": None,
                   "locator": {"type": "zim-entry", "path": "A/article"}, "provenance": "manual",
                   "review": {"by": "Editor", "date": "2026-09-18"}}
        self.navigation["sections"]["archive"] = self.mapping(archive, [section])
        self.navigation["assignments"].append(self.assignment("archives", "archive", "article"))
        pages, report = self.render([self.asset, archive])
        self.assertIn("Reader required for all material", pages["INDEX/topics/science.html"])
        self.assertIn("Reader required for all material in this topic", pages["INDEX/topics/archives.html"])
        self.assertIn("Archive article: A/article", pages["INDEX/topics/archives.html"])
        self.assertNotIn(".zim#", pages["INDEX/topics/archives.html"])
        self.assertNotIn("Open this section", pages["INDEX/topics/archives.html"])
        self.assertTrue(report["topics"]["archives"]["reader_only"])
        self.assertEqual(report["topics"]["science"]["direct_asset_count"], 1)
        self.assertEqual(report["topics"]["science"]["reader_asset_count"], 1)

    def test_locations_notices_escaping_and_verified_figures(self):
        self.asset.update(title='Book <script>alert(1)</script>', illustrated=True,
                          attribution='Access for free at openstax.org. <b>Credit</b>')
        introduction = self.navigation["sections"]["book"]["sections"][0]
        introduction["locator"].update(end_page=3, printed_label="ix–xi")
        introduction["review"] = {"by": "Editor", "date": "2026-09-18"}
        introduction["illustrations"] = [{"kind": "diagram", "label": "Checked circuit & symbols",
                                           "figure_id": "Figure 1", "caption": "<figure>"}]
        pages, _ = self.render()
        page = pages["INDEX/topics/measurements.html"]
        self.assertIn("book.pdf#page=1", page)
        self.assertIn("Physical PDF page 1–3; printed label: ix–xi", page)
        self.assertIn("Open complete document", page)
        self.assertIn("Version / edition: Fixture edition 1", page)
        self.assertIn("License: CC-BY-4.0", page)
        self.assertIn("Access for free at openstax.org.", page)
        self.assertIn("Verified diagram", page)
        self.assertNotIn("Verified diagram", pages["INDEX/topics/voltage.html"])
        self.assertIn("Illustrated document (whole work)", pages["INDEX/topics/voltage.html"])
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;figure&gt;", page)

    def test_html_anchor_encoded_text_line_and_media_locations_visible(self):
        html = self.make_asset("heading", "html")
        text = self.make_asset("lines", "txt")
        media = self.make_asset("clip", "mp4")
        for asset, locator in [(html, {"type": "html-anchor", "id": "a&b"}),
                               (text, {"type": "text-lines", "start": 10, "end": 20}),
                               (media, {"type": "media-time", "seconds": 12, "end_seconds": 20})]:
            section = {"id": "location", "title": "Location", "parent": None,
                       "locator": locator, "provenance": "manual", "review": {"by": "Editor", "date": "2026-09-18"}}
            self.navigation["sections"][asset["id"]] = self.mapping(asset, [section])
            self.navigation["assignments"].append(self.assignment("measurements", asset["id"], "location"))
        pages, _ = self.render([self.asset, html, text, media])
        page = pages["INDEX/topics/measurements.html"]
        self.assertIn("heading.html#a%26b", page)
        self.assertIn("Line 10–20", page)
        self.assertIn("Time 12 seconds–20 seconds", page)
        self.assertNotIn("clip.mp4#", page)

    def test_imported_contents_paginate_and_parent_links_resolve(self):
        sections = [self.section("chapter", 1)]
        sections += [self.section(f"section-{number}", number + 1, parent="chapter") for number in range(101)]
        self.navigation["sections"]["book"]["sections"] = sections
        self.navigation["assignments"] = [self.assignment("measurements", "book", section["id"]) for section in sections]
        pages, report = self.render()
        self.assertIn("INDEX/books/book/2.html", pages)
        self.assertIn("INDEX/books/book/3.html", pages)
        self.assertIn("INDEX/topics/measurements/3.html", pages)
        self.assertIn("Imported publisher headings are not reviewed", pages["INDEX/books/book.html"])
        self.assertEqual(report["included_section_count"], 102)
        for path, text in pages.items():
            if path.startswith("INDEX/books/book") or path.startswith("INDEX/topics/measurements"):
                self.assertLessEqual(Links(text).entries, 50, path)
        self.assert_links_resolve(pages)

    def assert_links_resolve(self, pages):
        baseline = {"START_HERE.html", "SEARCH.html", "INDEX/critical.html", "INDEX/textbooks.html",
                    "INDEX/illustrated-guides.html", "INDEX/categories.html"}
        for current, content in pages.items():
            self.assertNotIn("<script", content.lower())
            for link in Links(content).links:
                url = urlsplit(link)
                self.assertFalse(url.scheme, link)
                self.assertFalse(url.netloc, link)
                outer_destination = posixpath.normpath(posixpath.join(posixpath.dirname(checksum_name(current)), unquote(url.path))) if url.path else checksum_name(current)
                destination = logical_name(outer_destination)
                self.assertTrue(destination in pages or destination in baseline or (self.target / destination).is_file(), (current, link))
                if url.fragment and destination in pages:
                    self.assertIn(unquote(url.fragment), Links(pages[destination]).ids, (current, link))

    def test_large_broad_lists_are_bounded_and_all_choices_reachable(self):
        for number in range(42):
            identity = f"child-{number}"
            self.topics[identity] = self.topic(identity, "Child " + str(number), ["science"])
            self.navigation["assignments"].append(self.assignment(identity, "book"))
        pages, _ = self.render()
        self.assertIn("INDEX/topics/science/children.html", pages)
        self.assertIn("INDEX/topics/science/children/2.html", pages)
        self.assertIn("More: narrower topics", pages["INDEX/topics/science.html"])
        self.assert_links_resolve(pages)

    def test_actual_byte_limit_splits_before_entry_limit_and_rejects_giant_single_item(self):
        sections = [self.section(f"s-{number}", number + 1) for number in range(30)]
        self.navigation["sections"]["book"]["sections"] = sections
        self.navigation["assignments"] = [self.assignment("measurements", "book", section["id"],
                                                          description="Long source description. " * 120) for section in sections]
        with patch("owl.atlas.MAX_PAGE_BYTES", 16000):
            pages, _ = self.render()
        self.assertTrue(all(len(text.encode()) <= 16000 for text in pages.values()))
        self.assertIn("INDEX/topics/measurements/2.html", pages)
        self.navigation["assignments"][0]["description"] = "x" * MAX_PAGE_BYTES
        with self.assertRaisesRegex(SafetyError, "cannot fit"):
            self.render()

    def test_unmapped_critical_textbook_reported_and_whole_book_fallback_available(self):
        self.navigation["assignments"] = []
        self.navigation["sections"] = {}
        pages, report = self.render()
        self.assertEqual(report["unmapped_critical"], ["book"])
        self.assertEqual(report["unmapped_required_textbooks"], ["book"])
        self.assertEqual(report["missing_textbook_subject_routes"], ["book"])
        self.assertEqual(report["missing_textbook_learning_routes"], ["book"])
        self.assertIn("No verified source contents", pages["INDEX/books/book.html"])
        self.assertIn("No topics for this entrance", pages["INDEX/topics.html"])
        self.assertTrue({"subjects", "tasks", "learn"}.issubset(Links(pages["INDEX/topics.html"]).ids))

    def test_stale_source_maps_and_cycles_fail_instead_of_silent_fallback(self):
        self.navigation["sections"]["book"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(SafetyError, "Stale reviewed"):
            self.render()
        self.navigation["sections"]["book"]["source_sha256"] = self.asset["sha256"]
        self.topics["science"]["parents"] = ["voltage"]
        with self.assertRaisesRegex(SafetyError, "hierarchy contains a cycle"):
            self.render()

    def test_layered_dag_output_is_linear_in_topics_not_number_of_routes(self):
        self.topics.clear()
        self.topics["root"] = self.topic("root", "Root")
        previous = ["root"]
        for layer in range(12):
            current = [f"layer-{layer}-a", f"layer-{layer}-b"]
            for identity in current:
                self.topics[identity] = self.topic(identity, identity, previous)
            previous = current
        self.navigation["entrances"] = {"subjects": ["root"], "tasks": [], "learn": []}
        self.navigation["assignments"] = [self.assignment(identity, "book") for identity in previous]
        pages, report = self.render()
        topic_pages = [path for path in pages if path.startswith("INDEX/topics/")]
        self.assertEqual(len(topic_pages), len(self.topics))
        self.assertEqual(report["topics"]["root"]["location_count"], 1)
        self.assertEqual(report["topics"]["root"]["asset_count"], 1)

    def test_identical_inputs_produce_identical_pages_and_reports(self):
        first = self.render()
        self.assertEqual(first, self.render())
        pages, report = first
        self.assertEqual(report["html_bytes"], sum(len(value.encode()) for value in pages.values()))
        self.assertTrue(all(len(value.encode()) <= MAX_PAGE_BYTES for value in pages.values()))
        self.assertEqual(report["input_hashes"], self.navigation["input_hashes"])
        self.assert_links_resolve(pages)


if __name__ == "__main__":
    unittest.main()
