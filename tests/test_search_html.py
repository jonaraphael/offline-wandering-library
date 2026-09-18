"""Bounded HTML extraction keeps visible text without retaining script payloads."""
from __future__ import annotations

from html.parser import HTMLParser
import re
import unittest
from unittest.mock import patch

from owl import search


class _ReferenceHTMLText(search._HTMLText):
    """Use the installed stdlib's original feed behavior as a semantic oracle."""

    feed = HTMLParser.feed


class HTMLExtractionTests(unittest.TestCase):
    def extract(self, chunks):
        return "".join(search._html_chunks(chunks))

    def reference(self, html):
        parser = _ReferenceHTMLText()
        parser.feed(html)
        parser.close()
        return "".join(parser.parts)

    def test_large_script_and_style_keep_visible_text_and_bound_feed_buffers(self):
        measurements = []

        class Measured(search._HTMLText):
            def feed(self, data):
                super().feed(data)
                measurements.append((len(data), len(self.rawdata),
                                     getattr(self, "_pending_len", 0)))

        body = "script_secret" * 270_000
        html = ("<title>Electric circuits</title><p>Before &amp; visible.</p>"
                "<script>" + body + "</script><style>" + body + "</style>"
                "<h1>After the simulation</h1><p>Voltage and resistance.</p>")
        with patch.object(search, "_HTMLText", Measured):
            # A caller-provided large chunk must also be subdivided.
            actual = self.extract([html])
        self.assertEqual(actual, self.reference(html))
        self.assertIn("Before & visible.", actual)
        self.assertIn("Voltage and resistance.", actual)
        self.assertNotIn("script_secret", actual)
        self.assertTrue(measurements)
        self.assertLessEqual(max(row[0] for row in measurements), 64 * 1024)
        self.assertLessEqual(max(row[1] for row in measurements), 64 * 1024)
        self.assertEqual(max(row[2] for row in measurements), 0)

    def test_every_end_tag_split_preserves_native_parser_semantics(self):
        # Python releases differ in the malformed closing tags they accept.
        # Retention must support both grammars without inventing new closers.
        endings = ["</script>", "</ScRiPt\n>", "</script \t\r\n>",
                   "</ script>", "</\tSCRIPT\n>", "</script/>",
                   '</script data-note="a < b">']
        for ending in endings:
            for split in range(len(ending) + 1):
                with self.subTest(ending=ending, split=split):
                    prefix = "<p>Before</p><script>hidden_secret"
                    suffix = "<p>After &amp; visible</p>"
                    self.assertEqual(
                        self.extract([prefix, ending[:split], ending[split:], suffix]),
                        self.reference(prefix + ending + suffix))
        for split in range(len("</StYlE\n>") + 1):
            ending = "</StYlE\n>"
            chunks = ["<p>Before</p><style>css_secret", ending[:split],
                      ending[split:], "<p>After</p>"]
            self.assertEqual(self.extract(chunks), self.reference("".join(chunks)))

    def test_partial_names_and_false_closers_do_not_leak_script_text(self):
        chunks = ["<p>Before</p><script>hidden", "<", "/scr", "ipture>",
                  "still_hidden", "<", "/script", " ", ">", "<p>After</p>"]
        actual = self.extract(chunks)
        self.assertEqual(actual, self.reference("".join(chunks)))
        self.assertNotIn("hidden", actual)
        self.assertIn("After", actual)

    def test_long_closing_whitespace_and_legacy_matcher_tail_are_retained(self):
        ending = "</script" + " \n" * 40_000 + ">"
        chunks = ["<p>Before</p><script>ignored", *(
            ending[i:i + 97] for i in range(0, len(ending), 97)), "<p>After</p>"]
        self.assertEqual(self.extract(chunks), self.reference("".join(chunks)))
        # Older stdlib matchers required the entire closing tag before matching.
        # Exercise the retention path directly with that published grammar.
        parser = search._HTMLText()
        parser.feed("<script>")
        parser.interesting = re.compile(r"</\s*script\s*>", re.IGNORECASE)
        parser.rawdata = "discard_body</ \tScRiPt \n"
        parser._discard_hidden_body()
        self.assertEqual(parser.rawdata, "</ \tScRiPt \n")

    def test_unclosed_script_does_not_grow_or_expose_hidden_text(self):
        chunks = ["<p>Before</p><script>", *("secret" * 10_000 for _ in range(60))]
        self.assertEqual(self.extract(chunks), "\nBefore\n")

    def test_unterminated_real_tokens_still_fail_at_the_existing_bound(self):
        for opening in ['<div title="', "<!--", "<script></script "]:
            with self.subTest(opening=opening):
                with self.assertRaisesRegex(search.SearchError, "unterminated token over 1 MiB"):
                    self.extract([opening, " " * (1024 * 1024 + 64 * 1024)])

    def test_entities_templates_and_visible_chunk_boundaries_are_unchanged(self):
        html = ("<title>Pi &amp; π</title><p>alpha&nbsp;beta</p>"
                "<template>hidden<script>more_hidden</script></template>"
                "<h2>Gamma</h2><div>delta &lt; epsilon</div>")
        expected = self.reference(html)
        for width in [1, 2, 3, 7, 64, 65_536]:
            with self.subTest(width=width):
                self.assertEqual(self.extract(html[i:i + width]
                                             for i in range(0, len(html), width)), expected)


if __name__ == "__main__":
    unittest.main()
