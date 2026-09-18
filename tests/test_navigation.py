"""Static navigation remains useful without JavaScript or network requests."""

from __future__ import annotations

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from owl.navigation import GENERATED_PATHS, generate_navigation


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
        self.target = Path(self.temporary.name).resolve()
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
        ]
        for asset in self.assets:
            path = self.target / asset["destination"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        for relative in ("SEARCH.html", "BUILD_INFO.json", "INVENTORY.json", "SHA256SUMS.txt", "VERIFY.py", "SOURCE_NOTES.txt"):
            (self.target / relative).write_text("fixture", encoding="utf-8")
        (self.target / "SEARCH").mkdir()
        (self.target / "SEARCH/coverage.json").write_text("{}", encoding="utf-8")

    def generate(self):
        inventory = {"assets": [{**self.assets[0], "verification": "pinned", "size_bytes": 2048}]}
        return generate_navigation(self.target, self.assets, inventory, {"documents": 4})

    def test_all_generated_links_resolve_without_javascript(self):
        paths = self.generate()
        self.assertEqual(set(paths), set(GENERATED_PATHS))
        parsed = {}
        for relative in paths:
            if relative.endswith(".html"):
                parser = Links()
                parser.feed((self.target / relative).read_text(encoding="utf-8"))
                self.assertFalse(parser.scripts)
                parsed[relative] = parser
        for relative, parser in parsed.items():
            for href in parser.hrefs:
                components = urlsplit(href)
                self.assertFalse(components.scheme, href)
                destination = (self.target / relative).parent / unquote(components.path)
                self.assertTrue(destination.exists(), f"{relative}: {href}")
                self.assertTrue(destination.resolve().is_relative_to(self.target.resolve()))
                if components.fragment:
                    linked = destination.resolve().relative_to(self.target.resolve()).as_posix()
                    self.assertIn(components.fragment, parsed[linked].ids)

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
        landing = (self.target / "START_HERE.html").read_text(encoding="utf-8")
        self.assertIn('<strong>Textbooks (2)</strong>', landing)
        self.assertIn('<strong>Illustrated guides (2)</strong>', landing)
        self.assertLess(landing.index('<strong>Textbooks (2)</strong>'), landing.index('<h2>Browse by topic</h2>'))
        for relative in ("INDEX/textbooks.html", "INDEX/illustrated-guides.html", "INDEX/critical.html", "INDEX/categories.html", "INDEX/E.html", "INVENTORY.html"):
            with self.subTest(page=relative):
                self.assertIn(
                    "Textbook · Illustrated · Critical",
                    (self.target / relative).read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "Textbook author &amp; publisher. Access for free at example.org.",
                    (self.target / relative).read_text(encoding="utf-8"),
                )
        self.assertIn("open the document to inspect its illustrations", (self.target / "INDEX/illustrated-guides.html").read_text(encoding="utf-8"))

    def test_repeated_generation_is_deterministic_and_preserves_unrelated_files(self):
        unrelated = self.target / "personal-notes.txt"
        unrelated.write_text("Do not change", encoding="utf-8")
        paths = self.generate()
        previous = {relative: (self.target / relative).read_bytes() for relative in paths}
        self.generate()
        self.assertEqual(previous, {relative: (self.target / relative).read_bytes() for relative in paths})
        self.assertEqual("Do not change", unrelated.read_text(encoding="utf-8"))

    def test_empty_library_has_useful_indexes(self):
        generate_navigation(self.target, [], {"assets": []}, {})
        self.assertIn(
            "No material in this section",
            (self.target / "INDEX/categories.html").read_text(encoding="utf-8"),
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
