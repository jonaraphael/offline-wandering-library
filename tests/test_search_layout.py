"""The old search address leads directly to Search in the drive reader."""
from html.parser import HTMLParser
import unittest

from owl.search_ui import render_search_page


class SearchLayoutTests(unittest.TestCase):
    def test_search_redirect_and_static_fallback_resolve_at_the_drive_root(self):
        class Tags(HTMLParser):
            entries = []

            def handle_starttag(self, tag, attrs):
                self.entries.append((tag, dict(attrs)))

        tags = Tags()
        tags.feed(render_search_page())
        self.assertIn(('meta', {'http-equiv': 'refresh', 'content': '0; url=../START_HERE.html#/search'}), tags.entries)
        self.assertIn(('a', {'href': '../START_HERE.html'}), tags.entries)
        self.assertFalse(any(tag in {'script', 'form'} for tag, _ in tags.entries))
