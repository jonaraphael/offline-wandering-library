"""Atlas metadata must be structural, reproducible, and true of selected bytes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml

from owl.atlas_model import AtlasError, load_navigation, validate_sources
from owl.safety import SafetyError


class AtlasModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / "navigation"
        (self.directory / "sections").mkdir(parents=True)
        self.target = self.root / "drive"
        self.target.mkdir()
        self.assets = []
        self.asset = self.add_asset("book", "txt", b"First line\nSecond line\nThird line")
        self.topics = [self.topic("subject"), self.topic("task"),
                       self.topic("shared", parents=["subject", "task"])]
        self.entrances = {"subjects": ["subject"], "tasks": ["task"], "learn": ["subject"]}
        self.assignments = [{"topic_id": "shared", "asset_id": "book", "section_id": "chapter", "purpose": "practical"}]
        self.maps = {"book": self.section_map(self.asset, [{"type": "text-lines", "start": 2, "end": 3}])}

    @staticmethod
    def topic(identity, **values):
        return {"id": identity, "title": identity.title(), "description": "Plain subject scope.", **values}

    def add_asset(self, identity, fmt, data):
        path = self.target / f"{identity}.{fmt}"
        path.write_bytes(data)
        asset = {"id": identity, "format": fmt, "destination": path.name,
                 "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        self.assets.append(asset)
        return asset

    @staticmethod
    def section_map(asset, locators):
        return {"schema_version": 1, "asset_id": asset["id"], "source_sha256": asset["sha256"],
                "sections": [{"id": "chapter" if index == 0 else f"part-{index}",
                              "title": f"Publisher section {index + 1}", "locator": locator,
                              "provenance": "manual", "review": {"by": "Fixture curator", "date": "2026-09-18"}}
                             for index, locator in enumerate(locators)]}

    def write(self):
        topics = {"schema_version": 1, "topics": self.topics, "entrances": self.entrances}
        (self.directory / "topics.yaml").write_text(yaml.safe_dump(topics), encoding="utf-8")
        (self.directory / "assignments.yaml").write_text(yaml.safe_dump({"schema_version": 1,
                                                                       "assignments": self.assignments}), encoding="utf-8")
        for path in (self.directory / "sections").glob("*.yaml"):
            path.unlink()
        for name, section_map in self.maps.items():
            (self.directory / "sections" / (name + ".yaml")).write_text(yaml.safe_dump(section_map), encoding="utf-8")

    def load(self):
        self.write()
        return load_navigation(self.directory, self.assets)

    def test_multiple_parents_related_cycles_and_duplicate_assignments(self):
        self.topics[0]["related"] = ["task"]
        self.topics[1]["related"] = ["subject"]
        self.topics[2]["aliases"] = ["Common label", "common label", "<script>literal label</script>"]
        self.assignments.append(dict(self.assignments[0]))
        navigation = self.load()
        self.assertEqual(navigation["topics"]["shared"]["parents"], ["subject", "task"])
        self.assertEqual(len(navigation["assignments"]), 1)
        self.assertEqual(len(navigation["topics"]["shared"]["aliases"]), 2)
        self.assertEqual(navigation["topics"]["shared"]["aliases"][1], "<script>literal label</script>")
        self.assertEqual(validate_sources(self.target, self.assets, navigation)["book"]["sections"][0]["id"], "chapter")

    def test_input_hashes_cover_exact_raw_metadata_bytes(self):
        navigation = self.load()
        self.assertEqual(set(navigation["input_hashes"]), {"topics.yaml", "assignments.yaml", "sections/book.yaml"})
        for relative, digest in navigation["input_hashes"].items():
            self.assertEqual(digest, hashlib.sha256((self.directory / relative).read_bytes()).hexdigest())

    def test_topic_cycles_and_related_only_orphans_fail(self):
        self.topics[0]["parents"] = ["shared"]
        with self.assertRaisesRegex(AtlasError, "cycle"):
            self.load()
        self.topics[0].pop("parents")
        self.topics.append(self.topic("orphan", related=["subject"]))
        self.topics[0]["related"] = ["orphan"]
        with self.assertRaisesRegex(AtlasError, "unreachable"):
            self.load()

    def test_unknown_parent_related_and_entrance_fail(self):
        for field in ("parents", "related"):
            with self.subTest(field=field):
                self.topics[0][field] = ["missing"]
                with self.assertRaisesRegex(AtlasError, "unknown"):
                    self.load()
                self.topics[0].pop(field)
        self.entrances["subjects"] = ["missing"]
        with self.assertRaisesRegex(AtlasError, "Unknown entrance"):
            self.load()

    def test_duplicate_unsafe_ids_unknown_fields_and_yaml_keys_fail(self):
        self.topics.append(deepcopy(self.topics[0]))
        with self.assertRaisesRegex(AtlasError, "Duplicate topic"):
            self.load()
        self.topics.pop()
        for identity in ("../unsafe", "UPPER", "a/b", "a b", "con"):
            with self.subTest(identity=identity):
                self.topics[0]["id"] = identity
                with self.assertRaises((AtlasError, SafetyError)):
                    self.load()
        self.topics[0]["id"] = "subject"
        self.topics[0]["url"] = "https://example.org/not-a-locator"
        with self.assertRaisesRegex(AtlasError, "unknown fields"):
            self.load()
        self.topics[0].pop("url")
        self.write()
        with (self.directory / "topics.yaml").open("a") as handle:
            handle.write("\nschema_version: 1\n")
        with self.assertRaisesRegex(AtlasError, "Duplicate YAML key"):
            load_navigation(self.directory, self.assets)

    def test_unknown_assets_sections_and_unsafe_assignment_fields_fail_globally(self):
        for change in ({"asset_id": "missing"}, {"section_id": "missing"}, {"topic_id": "missing"},
                       {"url": "https://example.org"}, {"purpose": "medical-advice"}):
            with self.subTest(change=change):
                old = dict(self.assignments[0])
                self.assignments[0].update(change)
                with self.assertRaises(AtlasError):
                    self.load()
                self.assignments[0] = old

    def test_section_hierarchy_cycle_and_duplicate_ids_fail(self):
        sections = self.maps["book"]["sections"]
        sections[0]["parent"] = "chapter"
        with self.assertRaisesRegex(AtlasError, "cycle"):
            self.load()
        sections[0]["parent"] = "missing"
        with self.assertRaisesRegex(AtlasError, "unknown parent"):
            self.load()
        sections[0].pop("parent")
        sections.append(deepcopy(sections[0]))
        with self.assertRaisesRegex(AtlasError, "duplicate section"):
            self.load()

    def test_manual_illustrations_and_media_require_real_review_metadata(self):
        section = self.maps["book"]["sections"][0]
        section.pop("review")
        with self.assertRaisesRegex(AtlasError, "require review"):
            self.load()
        section["provenance"] = "publisher-outline"
        self.load()  # Publisher structure may be imported without manual review.
        section["illustrations"] = [{"kind": "diagram", "label": "Labeled apparatus"}]
        with self.assertRaisesRegex(AtlasError, "require review"):
            self.load()
        section["review"] = {"by": "Curator", "date": "2026-02-30"}
        with self.assertRaisesRegex(AtlasError, "calendar date"):
            self.load()
        section["review"]["date"] = "2026-09-18"
        self.assertEqual(self.load()["sections"]["book"]["sections"][0]["illustrations"][0]["kind"], "diagram")

    def test_selected_stale_map_fails_but_excluded_sources_are_never_opened(self):
        self.maps["book"]["source_sha256"] = "0" * 64
        navigation = self.load()
        with self.assertRaisesRegex(AtlasError, "stale section map"):
            validate_sources(self.target, self.assets, navigation)
        (self.target / self.asset["destination"]).unlink()
        with patch("owl.atlas_model.sha256_file", side_effect=AssertionError("excluded source opened")):
            self.assertEqual(validate_sources(self.target, [], navigation), {})
        self.maps["book"]["sections"][0]["locator"]["start"] = 0
        with self.assertRaises(AtlasError):
            self.load()  # Exclusion does not excuse malformed metadata.

    def test_selected_corruption_and_missing_source_fail(self):
        navigation = self.load()
        source = self.target / self.asset["destination"]
        source.write_bytes(b"x" * self.asset["size_bytes"])
        with self.assertRaisesRegex(AtlasError, "SHA-256 differs"):
            validate_sources(self.target, self.assets, navigation)
        source.write_bytes(b"short")
        with self.assertRaisesRegex(AtlasError, "size differs"):
            validate_sources(self.target, self.assets, navigation)
        source.unlink()
        with self.assertRaisesRegex(AtlasError, "missing"):
            validate_sources(self.target, self.assets, navigation)

    def test_whole_document_assignments_are_verified_without_section_maps(self):
        self.maps = {}
        self.assignments[0].pop("section_id")
        navigation = self.load()
        self.assertEqual(validate_sources(self.target, self.assets, navigation), {})
        (self.target / self.asset["destination"]).write_bytes(b"changed")
        with self.assertRaisesRegex(AtlasError, "size differs"):
            validate_sources(self.target, self.assets, navigation)

    def test_unreferenced_selected_asset_is_not_rehashed(self):
        unreferenced = self.add_asset("unused", "txt", b"not in atlas")
        (self.target / unreferenced["destination"]).unlink()
        self.assertEqual(set(validate_sources(self.target, self.assets, self.load())), {"book"})

    def test_text_lines_are_counted_with_unterminated_final_line(self):
        navigation = self.load()
        validate_sources(self.target, self.assets, navigation)
        self.maps["book"]["sections"][0]["locator"]["end"] = 4
        with self.assertRaisesRegex(AtlasError, "text line is outside"):
            validate_sources(self.target, self.assets, self.load())

    def test_pdf_uses_one_based_physical_page_bounds(self):
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        asset = self.add_asset("manual", "pdf", stream.getvalue())
        self.maps["manual"] = self.section_map(asset, [{"type": "pdf-page", "page": 1, "end_page": 2, "printed_label": "iv–1"}])
        self.assertIn("manual", validate_sources(self.target, self.assets, self.load()))
        self.maps["manual"]["sections"][0]["locator"]["end_page"] = 3
        with self.assertRaisesRegex(AtlasError, "PDF page is outside"):
            validate_sources(self.target, self.assets, self.load())
        self.maps["manual"]["sections"][0]["locator"]["page"] = 0
        with self.assertRaises(AtlasError):
            self.load()

    def test_html_anchors_exist_uniquely_and_allow_escaped_fragment_characters(self):
        asset = self.add_asset("web", "html", b'<h1 id="part:1&amp;two">A source heading</h1>')
        self.maps["web"] = self.section_map(asset, [{"type": "html-anchor", "id": "part:1&two"}])
        validate_sources(self.target, self.assets, self.load())
        self.maps["web"]["sections"][0]["locator"]["id"] = "absent"
        with self.assertRaisesRegex(AtlasError, "found 0"):
            validate_sources(self.target, self.assets, self.load())
        data = b'<h1 id="duplicate">One</h1><p id="duplicate">Two</p>'
        (self.target / asset["destination"]).write_bytes(data)
        asset.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.maps["web"] = self.section_map(asset, [{"type": "html-anchor", "id": "duplicate"}])
        with self.assertRaisesRegex(AtlasError, "found 2"):
            validate_sources(self.target, self.assets, self.load())

    def test_source_text_encoding_is_respected_without_replacing_bad_bytes(self):
        asset = self.add_asset("web", "html", '<h1 id="café">Café</h1>'.encode("windows-1252"))
        self.maps["web"] = self.section_map(asset, [{"type": "html-anchor", "id": "café"}])
        with self.assertRaisesRegex(AtlasError, "could not validate source locators"):
            validate_sources(self.target, self.assets, self.load())
        asset["text_encoding"] = "windows-1252"
        self.assertIn("web", validate_sources(self.target, self.assets, self.load()))
        text_asset = self.add_asset("lines", "txt", "One\nTwo\nThree".encode("utf-16"))
        text_asset["text_encoding"] = "utf-16"
        self.maps["lines"] = self.section_map(text_asset, [{"type": "text-lines", "start": 3}])
        self.assertIn("lines", validate_sources(self.target, self.assets, self.load()))

    def test_unterminated_html_tokens_fail_with_bounded_parser_state(self):
        asset = self.add_asset("web", "html", b'<h1 id="valid">Heading</h1><!--' + b"x" * (2 * 1024 * 1024))
        self.maps["web"] = self.section_map(asset, [{"type": "html-anchor", "id": "valid"}])
        with self.assertRaisesRegex(AtlasError, "unterminated token"):
            validate_sources(self.target, self.assets, self.load())

    def test_epub_members_are_checked_without_extracting(self):
        import io
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("OEBPS/chapter.xhtml", "<h1>Chapter</h1>")
        asset = self.add_asset("ebook", "epub", stream.getvalue())
        self.maps["ebook"] = self.section_map(asset, [{"type": "epub-entry", "path": "OEBPS/chapter.xhtml"}])
        validate_sources(self.target, self.assets, self.load())
        self.assertFalse((self.target / "OEBPS").exists())
        self.maps["ebook"]["sections"][0]["locator"]["path"] = "OEBPS/absent.xhtml"
        with self.assertRaisesRegex(AtlasError, "entry missing"):
            validate_sources(self.target, self.assets, self.load())
        for unsafe in ("../bad", "/absolute", "https://example.org/entry", "A/%2e%2e/bad", "a\\b", "a?remote=1"):
            self.maps["ebook"]["sections"][0]["locator"]["path"] = unsafe
            with self.subTest(path=unsafe), self.assertRaises(AtlasError):
                self.load()

    @unittest.skipUnless(importlib.util.find_spec("libzim"), "optional libzim not installed")
    def test_real_zim_entry_existence(self):
        from libzim.writer import Creator, Item, StringProvider, Hint
        class Article(Item):
            def get_path(self): return "chapter"
            def get_title(self): return "Chapter"
            def get_mimetype(self): return "text/html"
            def get_contentprovider(self): return StringProvider("<h1>Chapter</h1>")
            def get_hints(self): return {Hint.FRONT_ARTICLE: True}
        path = self.root / "fixture.zim"
        with Creator(path) as creator:
            creator.add_item(Article())
            creator.set_mainpath("chapter")
        asset = self.add_asset("archive", "zim", path.read_bytes())
        self.maps["archive"] = self.section_map(asset, [{"type": "zim-entry", "path": "chapter"}])
        validate_sources(self.target, self.assets, self.load())
        self.maps["archive"]["sections"][0]["locator"]["path"] = "absent"
        with self.assertRaisesRegex(AtlasError, "ZIM entry does not exist"):
            validate_sources(self.target, self.assets, self.load())

    def test_media_timestamps_require_review_and_do_not_claim_duration_detection(self):
        asset = self.add_asset("lesson", "mp4", b"reviewed media fixture; decoder is not executed")
        self.maps["lesson"] = self.section_map(asset, [{"type": "media-time", "seconds": 2.5, "end_seconds": 10}])
        self.assertIn("lesson", validate_sources(self.target, self.assets, self.load()))
        row = self.maps["lesson"]["sections"][0]
        row["provenance"] = "publisher-outline"
        row.pop("review")
        with self.assertRaisesRegex(AtlasError, "require review"):
            self.load()
        row["review"] = {"by": "Curator", "date": "2026-09-18"}
        for value in (float("inf"), -1, True):
            row["locator"]["seconds"] = value
            with self.subTest(value=value), self.assertRaises(AtlasError):
                self.load()

    def test_images_link_to_verified_source_and_reject_arbitrary_locator_urls(self):
        asset = self.add_asset("figure", "png", b"\x89PNG\r\n\x1a\n")
        self.maps["figure"] = self.section_map(asset, [{"type": "image"}])
        self.assertIn("figure", validate_sources(self.target, self.assets, self.load()))
        self.maps["figure"]["sections"][0]["locator"]["url"] = "https://example.org/image.png"
        with self.assertRaisesRegex(AtlasError, "unknown fields"):
            self.load()

    def test_metadata_symlinks_are_rejected(self):
        self.write()
        path = self.directory / "topics.yaml"
        original = self.root / "outside.yaml"
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            self.skipTest("symlink privilege not available")
        with self.assertRaises(SafetyError):
            load_navigation(self.directory, self.assets)

    def test_deep_hierarchy_uses_iterative_validation(self):
        self.topics = [self.topic(f"topic-{i}", parents=[f"topic-{i-1}"] if i else []) for i in range(1500)]
        self.entrances = {"subjects": ["topic-0"], "tasks": [], "learn": []}
        self.assignments[0]["topic_id"] = "topic-1499"
        self.assertEqual(len(self.load()["topics"]), 1500)


if __name__ == "__main__":
    unittest.main()
