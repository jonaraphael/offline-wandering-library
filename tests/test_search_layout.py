"""Both search entry points resolve only into the single LIBRARY folder."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from owl.search_ui import render_search_page, render_search_widget


class _Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.scripts, self.forms = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "script":
            self.scripts.append(attrs)
        if tag == "form":
            self.forms.append(attrs)


class SearchLayoutTests(unittest.TestCase):
    def test_widget_has_explicit_prefix_and_standalone_returns_to_outer_start(self):
        outer = _Links(render_search_widget("LIBRARY/"))
        self.assertTrue(all(link.startswith("LIBRARY/") for link in outer.links))
        self.assertEqual(outer.scripts, [{"defer": None, "src": "LIBRARY/SEARCH/search.js"}])
        self.assertEqual(outer.forms[0]["data-library-root"], "LIBRARY/")
        self.assertIn("hidden", outer.forms[0])
        page = render_search_page()
        inner = _Links(page)
        self.assertIn("../START_HERE.html", inner.links)
        self.assertIn("INDEX/categories.html", inner.links)
        self.assertEqual(inner.forms[0]["data-library-root"], "")
        self.assertIn("hidden", inner.forms[0])
        self.assertIn('id="viewerHelp" class="notice"', page)
        self.assertIn("open a document directly", page)
        self.assertEqual(inner.scripts, [{"defer": None, "src": "SEARCH/search.js"}])
        self.assertNotIn("__OWL_", page)
        self.assertNotIn("<base", page)
        self.assertNotIn('type="file"', page)

    def test_widget_rejects_arbitrary_locations(self):
        for prefix in ("../", "/LIBRARY/", "https://example.invalid/", "LIBRARY//", "other/"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                render_search_widget(prefix)



if __name__ == "__main__":
    unittest.main()
