"""Static navigation remains useful without JavaScript or network requests."""

from __future__ import annotations

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from owl.navigation import GENERATED_PATHS, generate_navigation
from owl.search_ui import render_search_widget
from owl.layout import logical_name, managed_path


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "href" in attrs:
            self.hrefs.append(attrs["href"])
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "script":
            self.scripts.append(attrs)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.outer = Path(self.temporary.name).resolve()
        self.target = self.outer / "LIBRARY"
        self.target.mkdir()
        self.assets = [
            {
                "id": "aid",
                "title": '<First aid & safety> "manual"',
                "category": "first_aid",
                "destination": "CRITICAL/FIRST_AID/first aid #1.txt",
                "format": "txt",
                "critical": True,
                "resource_type": "guide",
                "illustrated": True,
                "license": "Public domain",
            },
            {
                "id": "book",
                "title": "Électricité",
                "category": "books",
                "destination": "BOOKS/electricity.pdf",
                "format": "pdf",
                "size_bytes": 1024,
                "resource_type": "textbook",
                "illustrated": True,
                "critical": True,
                "attribution": "Textbook author & publisher. Access for free at example.org.",
            },
            {
                "id": "wiki",
                "title": "Wikipedia",
                "category": "encyclopedia",
                "destination": "ZIM/WIKIPEDIA/wiki.zim",
                "format": "zim",
                "reader_required": True,
                "resource_type": "archive",
                "illustrated": True,
            },
            {
                "id": "reference",
                "title": "123 reference",
                "category": "reference",
                "destination": "REFERENCE/numbers.txt",
                "format": "txt",
                "resource_type": "reference",
                "critical": True,
            },
            {
                "id": "textbook_plain",
                "title": "Mathematics textbook",
                "category": "books",
                "destination": "BOOKS/TEXTBOOKS/math.html",
                "format": "html",
                "resource_type": "textbook",
                "illustrated": False,
            },
            {
                "id": "guide_archive",
                "title": "Archived illustrated guide",
                "category": "education",
                "destination": "ZIM/OTHER/guide.zim",
                "format": "zim",
                "reader_required": True,
                "resource_type": "guide",
                "illustrated": True,
            },
            {
                "id": "textbook_epub",
                "title": "Textbook requiring an EPUB viewer",
                "category": "books",
                "destination": "BOOKS/reader-required.epub",
                "format": "epub",
                "reader_required": True,
                "resource_type": "textbook",
                "illustrated": True,
            },
            {
                "id": "software_guide",
                "title": "Reader installation guide",
                "category": "software",
                "destination": "SOFTWARE/LINUX/install.pdf",
                "format": "pdf",
                "resource_type": "guide",
                "illustrated": True,
            },
            {
                "id": "gutenberg_fixture",
                "title": "Classic reading collection",
                "category": "books",
                "destination": "BOOKS/GUTENBERG/classic #1.html",
                "format": "html",
                "resource_ids": ["gutenberg-core", "gutenberg-multilingual", "gutenberg-core"],
            },
            {
                "id": "children_fixture",
                "title": "Children’s reading archive",
                "category": "books",
                "destination": "ZIM/OTHER/children.zim",
                "format": "zim",
                "reader_required": True,
                "resource_ids": ["childrens-library"],
            },
            {
                "id": "unrelated_title",
                "title": "Gutenberg and children in a reference title",
                "category": "reference",
                "destination": "REFERENCE/unrelated.txt",
                "format": "txt",
            },
        ]
        for asset in self.assets:
            path = self.target / asset["destination"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        for relative in ("SEARCH.html", "BUILD_INFO.json", "INVENTORY.json", "SHA256SUMS.txt", "VERIFY.py", "SOURCE_NOTES.txt"):
            managed_path(self.target, relative).write_text("fixture", encoding="utf-8")
        (self.target / "SEARCH").mkdir()
        (self.target / "SEARCH/coverage.json").write_text("{}", encoding="utf-8")
        (self.target / "SEARCH/manifest.js").write_text("fixture", encoding="utf-8")
        (self.target / "SEARCH/search.js").write_text("fixture", encoding="utf-8")

    def generate(self, **inventory_fields):
        inventory = {"assets": [{**self.assets[0], "verification": "pinned", "size_bytes": 2048}]}
        inventory.update(inventory_fields)
        return generate_navigation(self.target, self.assets, inventory,
                                   {"documents": 4, "generated_files": ["SEARCH/manifest.js", "SEARCH/search.js"]})

    def test_all_generated_links_resolve_without_javascript(self):
        paths = self.generate()
        self.assertEqual(set(paths), set(GENERATED_PATHS))
        self.assertEqual({path.name for path in self.outer.iterdir()}, {"START_HERE.html", "LIBRARY"})
        self.assertFalse((self.target / "START_HERE.html").exists())
        parsed = {}
        for relative in paths:
            if relative.endswith(".html"):
                parser = Links()
                parser.feed(managed_path(self.target, relative).read_text(encoding="utf-8"))
                if relative == "START_HERE.html":
                    self.assertEqual(parser.scripts, [{"defer": None, "src": "LIBRARY/SEARCH/search.js"}])
                    self.assertTrue((self.outer / parser.scripts[0]["src"]).is_file())
                else:
                    self.assertFalse(parser.scripts)
                parsed[relative] = parser
        for relative, parser in parsed.items():
            for href in parser.hrefs:
                components = urlsplit(href)
                self.assertFalse(components.scheme, href)
                destination = managed_path(self.target, relative).parent / unquote(components.path)
                self.assertTrue(destination.exists(), f"{relative}: {href}")
                self.assertTrue(destination.resolve().is_relative_to(self.outer.resolve()))
                if components.fragment:
                    linked = logical_name(destination.resolve().relative_to(self.outer.resolve()).as_posix())
                    self.assertIn(components.fragment, parsed[linked].ids)

    def test_start_page_has_shared_automatic_search_before_browsing(self):
        self.generate()
        landing = (self.outer / "START_HERE.html").read_text(encoding="utf-8")
        self.assertIn(render_search_widget("LIBRARY/"), landing)
        for identity in ("searchForm", "query", "shelf", "searchButton", "cancelButton", "retryButton", "status", "results"):
            self.assertEqual(landing.count(f'id="{identity}"'), 1, identity)
        self.assertLess(landing.index('id="searchForm"'), landing.index('<h2>Books and learning collections</h2>'))
        self.assertNotIn('type="file"', landing)
        self.assertIn("Static navigation works without JavaScript; search requires it", landing)
        self.assertIn("Content-Security-Policy", landing)
        self.assertIn("connect-src", landing)
        self.assertIn('data-library-root="LIBRARY/"', landing)
        self.assertIn('href="LIBRARY/SEARCH.html"', landing)
        self.assertIn('href="../../START_HERE.html"',
                      (self.target / "INDEX/categories.html").read_text(encoding="utf-8"))
        self.assertIn('href="../START_HERE.html"',
                      (self.target / "INVENTORY.html").read_text(encoding="utf-8"))
        readme = (self.target / "README.txt").read_text(encoding="utf-8")
        self.assertIn("loads its index automatically", readme)
        self.assertNotIn("file-picker", readme)

    def test_human_index_only_has_no_search_runtime_or_unsupported_search_claim(self):
        for report in ({"status": "not-built"}, {}, {"generated_files": ["SEARCH/manifest.js"]}):
            with self.subTest(report=report):
                pages = generate_navigation(self.target, self.assets, {"assets": []}, report, write=False)
                landing = pages["START_HERE.html"]
                parser = Links(); parser.feed(landing)
                self.assertFalse(parser.scripts)
                self.assertNotIn('id="searchForm"', landing)
                self.assertNotIn("SEARCH/search.js", landing)
                self.assertIn("Full-text search", pages["README.txt"])
                self.assertNotIn("loads its index automatically", pages["README.txt"])
                self.assertIn('href="LIBRARY/INDEX/critical.html"', landing)

    def test_escaping_categories_reader_labels_and_critical_subset(self):
        self.generate()
        critical = (self.target / "INDEX/critical.html").read_text(encoding="utf-8")
        self.assertIn("&lt;First aid &amp; safety&gt; &quot;manual&quot;", critical)
        self.assertIn("../CRITICAL/FIRST_AID/first%20aid%20%231.txt", critical)
        self.assertNotIn("wiki.zim", critical)
        categories = (self.target / "INDEX/categories.html").read_text(encoding="utf-8")
        self.assertIn('id="first-aid"', categories)
        self.assertIn("Archive reader required", categories)
        self.assertIn("electricity.pdf", (self.target / "INDEX/E.html").read_text(encoding="utf-8"))
        self.assertIn("numbers.txt", (self.target / "INDEX/0-9.html").read_text(encoding="utf-8"))
        inventory = (self.target / "INVENTORY.html").read_text(encoding="utf-8")
        self.assertIn("2.0 KiB", inventory)
        self.assertIn("pinned", inventory)

    def test_learning_shelves_include_direct_books_and_guides_only(self):
        self.generate()
        textbooks = (self.target / "INDEX/textbooks.html").read_text(encoding="utf-8")
        illustrated = (self.target / "INDEX/illustrated-guides.html").read_text(encoding="utf-8")
        self.assertIn("../BOOKS/electricity.pdf", textbooks)
        self.assertIn("../BOOKS/TEXTBOOKS/math.html", textbooks)
        self.assertIn("2 files · 1 critical", textbooks)
        self.assertIn("../BOOKS/electricity.pdf", illustrated)
        self.assertIn("../CRITICAL/FIRST_AID/first%20aid%20%231.txt", illustrated)
        self.assertIn("2 files · 2 critical", illustrated)
        self.assertNotIn("../BOOKS/TEXTBOOKS/math.html", illustrated)
        self.assertNotIn("../CRITICAL/FIRST_AID/first%20aid%20%231.txt", textbooks)
        for page in (textbooks, illustrated):
            self.assertNotIn("../ZIM/", page)
            self.assertNotIn("../SOFTWARE/", page)
            self.assertNotIn("reader-required.epub", page)
            self.assertNotIn("../REFERENCE/numbers.txt", page)
        critical = (self.target / "INDEX/critical.html").read_text(encoding="utf-8")
        self.assertIn("../BOOKS/electricity.pdf", critical)
        self.assertIn("../REFERENCE/numbers.txt", critical)

    def test_learning_shelves_are_prominent_and_labeled_across_indexes(self):
        self.generate()
        landing = (self.outer / "START_HERE.html").read_text(encoding="utf-8")
        self.assertIn('<strong>Textbooks (2)</strong>', landing)
        self.assertIn('<strong>Illustrated guides (2)</strong>', landing)
        self.assertLess(landing.index('<strong>Textbooks (2)</strong>'), landing.index('<h2>Browse by topic</h2>'))
        for relative in ("INDEX/textbooks.html", "INDEX/illustrated-guides.html", "INDEX/critical.html", "INDEX/categories.html", "INDEX/E.html", "INVENTORY.html"):
            with self.subTest(page=relative):
                self.assertIn(
                    "Textbook · Illustrated · Critical",
                    managed_path(self.target, relative).read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "Textbook author &amp; publisher. Access for free at example.org.",
                    managed_path(self.target, relative).read_text(encoding="utf-8"),
                )
        self.assertIn("open the document to inspect its illustrations", (self.target / "INDEX/illustrated-guides.html").read_text(encoding="utf-8"))

    def test_repeated_generation_is_deterministic_and_preserves_unrelated_files(self):
        unrelated = self.target / "personal-notes.txt"
        unrelated.write_text("Do not change", encoding="utf-8")
        paths = self.generate()
        previous = {relative: managed_path(self.target, relative).read_bytes() for relative in paths}
        self.generate()
        self.assertEqual(previous, {relative: managed_path(self.target, relative).read_bytes() for relative in paths})
        self.assertEqual("Do not change", unrelated.read_text(encoding="utf-8"))

    def test_reading_collections_use_resource_ids_and_show_reader_requirements(self):
        self.generate()
        gutenberg = (self.target / "INDEX/gutenberg.html").read_text(encoding="utf-8")
        children = (self.target / "INDEX/children.html").read_text(encoding="utf-8")
        self.assertEqual(gutenberg.count('href="../BOOKS/GUTENBERG/classic%20%231.html"'), 1)
        self.assertIn("1 selected file available in this build", gutenberg)
        self.assertNotIn("../ZIM/OTHER/children.zim", gutenberg)
        self.assertIn("../ZIM/OTHER/children.zim", children)
        self.assertIn("Archive reader required", children)
        for page in (gutenberg, children):
            self.assertNotIn("../REFERENCE/unrelated.txt", page)
        landing = (self.outer / "START_HERE.html").read_text(encoding="utf-8")
        self.assertIn('<strong>Project Gutenberg</strong>', landing)
        self.assertIn('<strong>Children’s Library</strong>', landing)
        self.assertLess(landing.index('<strong>Project Gutenberg</strong>'), landing.index('<h2>Browse by topic</h2>'))

    def test_partial_selection_notice_and_coverage_are_visible_and_escaped(self):
        resource = {"id": "gutenberg-core", "title": 'Gutenberg <planned>', "status": "partial",
                    "reason": "Awaiting <verified> files & permission", "target_bytes": 1_000_000,
                    "effective_target_bytes": 900_000, "known_bytes": 1024}
        self.generate(content_complete=False, content_selection={"resource_rows": [resource]})
        for relative in ("START_HERE.html", "INVENTORY.html", "INDEX/gutenberg.html", "INDEX/children.html"):
            with self.subTest(page=relative):
                page = managed_path(self.target, relative).read_text(encoding="utf-8")
                self.assertIn("Content selection is incomplete", page)
                self.assertIn("INVENTORY.html#content-selection", page)
        for relative in ("INVENTORY.html", "INDEX/gutenberg.html"):
            page = managed_path(self.target, relative).read_text(encoding="utf-8")
            self.assertIn("Gutenberg &lt;planned&gt;", page)
            self.assertIn("Awaiting &lt;verified&gt; files &amp; permission", page)
        inventory = (self.target / "INVENTORY.html").read_text(encoding="utf-8")
        self.assertIn('id="content-selection"', inventory)
        self.assertIn("Resolved asset bytes", inventory)
        self.assertIn("1.0 KiB", inventory)
        self.assertIn("CONTENT SELECTION IS INCOMPLETE", (self.target / "README.txt").read_text(encoding="utf-8"))

    def test_complete_selection_does_not_get_partial_notice(self):
        self.generate(content_complete=True, content_selection={"resource_rows": []})
        self.assertNotIn("Content selection is incomplete", (self.outer / "START_HERE.html").read_text(encoding="utf-8"))

    def test_empty_library_has_useful_indexes(self):
        generate_navigation(self.target, [], {"assets": []}, {})
        self.assertIn(
            "No material in this section",
            (self.target / "INDEX/categories.html").read_text(encoding="utf-8"),
        )
        for relative in ("INDEX/gutenberg.html", "INDEX/children.html"):
            self.assertIn(
                "No files for this collection are included in this build",
                managed_path(self.target, relative).read_text(encoding="utf-8"),
            )

    def test_untrusted_asset_path_is_rejected(self):
        self.assets[0]["destination"] = "../outside.txt"
        with self.assertRaises(ValueError):
            self.generate()

    def test_symlink_directory_cannot_redirect_output(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.target / "INDEX").symlink_to(outside, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                self.generate()
            self.assertEqual([], list(Path(outside).iterdir()))


if __name__ == "__main__":
    unittest.main()
