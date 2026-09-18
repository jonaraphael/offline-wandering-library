"""Link validation retains only requested anchors from streamed source HTML."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.atlas_build import _SourceAnchors, validate_links
from owl.safety import SafetyError


class AtlasLinkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name).resolve()
        (self.target / 'BOOKS').mkdir()

    def test_large_source_is_scanned_once_without_retaining_other_ids_or_links(self):
        source = self.target / 'BOOKS/large.html'
        with source.open('w', encoding='utf-8') as handle:
            handle.write('<h1 id="first">First</h1>')
            for number in range(20_000):
                handle.write(f'<div id="unused-{number}"><a href="https://example.invalid/{number}">other</a></div>')
            handle.write('<h2 id="last">Last</h2>')
        pages = {
            'INDEX/topics/one.html': '<a href="../../BOOKS/large.html#first">First</a>',
            'INDEX/topics/two.html': '<a href="../../BOOKS/large.html#last">Last</a>'
                                       '<a href="../../BOOKS/large.html#first">Repeated</a>',
        }
        parsers, reads, opens = [], [], []
        class Observed(_SourceAnchors):
            def __init__(self, wanted):
                super().__init__(wanted)
                parsers.append(self)
            def feed(self, data):
                reads.append(len(data))
                super().feed(data)
        original_open = Path.open
        def opened(path, *args, **kwargs):
            if path == source:
                opens.append(path)
            return original_open(path, *args, **kwargs)
        with patch('owl.atlas_build._SourceAnchors', Observed), patch.object(Path, 'open', opened):
            validate_links(self.target, pages)
        self.assertEqual(opens, [source])
        self.assertEqual(len(parsers), 1)
        self.assertEqual(parsers[0].wanted, {'first', 'last'})
        self.assertEqual(parsers[0].found, {'first', 'last'})
        self.assertFalse(hasattr(parsers[0], 'links'))
        self.assertFalse(hasattr(parsers[0], 'ids'))
        self.assertGreater(len(reads), 2)
        self.assertLessEqual(max(reads), 65536)

    def test_requested_source_fragments_honor_declared_encoding_and_url_decoding(self):
        (self.target / 'BOOKS/guide.html').write_bytes('<h1 id="café:water">Water</h1>'.encode('utf-16'))
        validate_links(self.target,
            {'INDEX/topics/water.html': '<a href="../../BOOKS/guide.html#caf%C3%A9%3Awater">Water</a>'},
            [{'destination': 'BOOKS/guide.html', 'text_encoding': 'utf-16'}])

    def test_missing_source_fragment_keeps_the_generated_link_context(self):
        (self.target / 'BOOKS/guide.html').write_text('<h1 id="present">Present</h1>', encoding='utf-8')
        with self.assertRaisesRegex(SafetyError, 'Missing HTML fragment in INDEX/topics/water.html'):
            validate_links(self.target,
                {'INDEX/topics/water.html': '<a href="../../BOOKS/guide.html#missing">Missing</a>'})

    def test_generated_pages_still_check_fragments_scripts_and_nonlocal_links(self):
        valid = {'INDEX/topics/one.html': '<a href="two.html#section">Next</a>',
                 'INDEX/topics/two.html': '<h1 id="section">Section</h1>'}
        validate_links(self.target, valid)
        for replacement, error in (
                ('<h1>No matching section</h1>', 'Missing HTML fragment'),
                ('<script>anything</script>', 'must not require scripts'),
                ('<a href="https://example.invalid/">External</a><h1 id="section">Section</h1>', 'Nonlocal generated link')):
            with self.subTest(error=error), self.assertRaisesRegex(SafetyError, error):
                validate_links(self.target, {**valid, 'INDEX/topics/two.html': replacement})


if __name__ == '__main__':
    unittest.main()
