"""Pure topic rendering: shared routes, accurate coverage, bounded static pages."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from owl.atlas import prepare_atlas
from owl.safety import SafetyError


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
                           "input_hashes": {"topics.yaml": "a" * 64, "assignments/book.yaml": "b" * 64}}

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

    def render(self, navigation=None):
        return prepare_atlas(self.target, [self.asset], navigation or self.navigation)

    def test_shared_topic_labels_have_each_parent_and_counts_are_deduplicated(self):
        pages, report = self.render()
        self.assertEqual(pages, {})
        self.assertEqual(set(report["included_topic_ids"]), {"science", "repair", "learning", "measurements", "voltage"})
        self.assertEqual({label[0] for label in report["reader_topics"][self.asset["id"]]},
                         {"science", "repair", "learning", "measurements", "voltage"})
        self.assertEqual(report["topics"]["measurements"]["asset_count"], 1)
        self.assertEqual(report["topics"]["science"]["location_count"], 2)

    def test_no_assignments_leaves_reader_topics_empty_and_reports_coverage_gap(self):
        navigation = {**self.navigation, "assignments": []}
        pages, report = self.render(navigation)
        self.assertEqual(pages, {})
        self.assertEqual(report["reader_topics"], {})
        self.assertEqual(report["included_topic_ids"], [])
        self.assertEqual(report["unmapped_critical"], [self.asset["id"]])

    def test_stale_source_maps_and_cycles_fail_instead_of_silent_fallback(self):
        self.navigation["sections"]["book"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(SafetyError, "Stale reviewed"):
            self.render()
        self.navigation["sections"]["book"]["source_sha256"] = self.asset["sha256"]
        self.topics["science"]["parents"] = ["voltage"]
        with self.assertRaisesRegex(SafetyError, "hierarchy contains a cycle"):
            self.render()

    def test_identical_inputs_produce_identical_pages_and_reports(self):
        first = self.render()
        self.assertEqual(first, self.render())
        pages, report = first
        self.assertEqual(report["html_bytes"], sum(len(value.encode()) for value in pages.values()))
        self.assertEqual(pages, {})
        self.assertEqual(report["input_hashes"], self.navigation["input_hashes"])


if __name__ == "__main__":
    unittest.main()
