"""Whole-source pins, book context and read-only candidate inspection."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("zim_candidates", Path(__file__).resolve().parents[1] / "scripts/inspect_zim_candidates.py")
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class SelectionTests(unittest.TestCase):
    def test_portable_summary_keeps_language_conflicts_and_separate_derivative_accounting(self):
        rows = [{'entry': str(i), 'entry_sha256': 'a' * 64, 'size_bytes': 10,
                 'structure': {'html_language': 'fr', 'utf8_replacement_characters': 0}} for i in range(2)]
        full = {'sources': [{'topic_coverage': {'repair': ['0', '1']}, 'candidates': rows}]}
        result = candidate.portable_evidence(full)
        source = result['sources'][0]
        self.assertEqual(source['language_tag_conflicts']['count'], 2)
        self.assertEqual(source['unique_candidate_document_bytes'], 10)
        self.assertEqual(len(source['duplicate_entry_bodies']), 1)
        self.assertNotIn('structure', source['candidates'][0])
        self.assertIn('English body-language review required', source['candidates'][0]['language_status'])
        self.assertIn('structure', full['sources'][0]['candidates'][0])

    def test_whole_book_context_keeps_figures_chapters_and_exclusions(self):
        rows = [{'entry': path, 'title': title, 'mime': 'text/html', 'size_bytes': 10}
                for path, title in [('books/water/index.html', 'Water supply'), ('books/water/chapter.html', 'Chapter two'),
                                    ('books/water/french.html', 'French translation'), ('books/other/index.html', 'Other')]]
        policy = {'include_path': '^books/', 'exclude_patterns': ['french'], 'topics': {'water': 'water'},
                  'context_group_patterns': [r'^(books/[^/]+/)'], 'max_candidates': 10}
        result = candidate.choose(rows, policy)
        self.assertEqual([row['entry'] for row in result], ['books/water/chapter.html', 'books/water/index.html'])
        self.assertTrue(all(row['context_group'] == 'books/water/' for row in result))
        self.assertEqual(result, candidate.choose(list(reversed(rows)), policy))
        policy['max_candidates'] = 1
        with self.assertRaisesRegex(ValueError, 'narrow reviewed'):
            candidate.choose(rows, policy)


@unittest.skipUnless(importlib.util.find_spec('libzim'), 'optional libzim extra')
class LocalArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source.zim'
        from libzim.writer import Creator, Item, StringProvider, Hint
        self.body = '<html lang="en"><h1>Water pump</h1><p>Complete original.</p><img src="image.png"><table><tr><td>1</td></tr></table></html>'
        body = self.body
        class Document(Item):
            def get_path(self): return 'pump.html'
            def get_title(self): return 'Water pump'
            def get_mimetype(self): return 'text/html'
            def get_contentprovider(self): return StringProvider(body)
            def get_hints(self): return {Hint.FRONT_ARTICLE: True}
        with Creator(self.source) as archive:
            archive.add_item(Document())
            archive.add_redirection('alias.html', 'Alias', 'pump.html', {})
            archive.set_mainpath('pump.html')
        self.asset = {'id': 'fixture', 'size_bytes': self.source.stat().st_size,
                      'sha256': candidate.sha256_file(self.source), 'source_url': 'https://example.org/source.zim', 'version': '2026'}

    def test_cached_inventory_uses_unchanged_verified_source_and_no_export(self):
        cache = self.root / 'cache.json'
        first = candidate.inventory(self.source, self.asset, cache)
        with patch.object(candidate, 'sha256_file', side_effect=AssertionError('Unchanged evidence should be reused')):
            self.assertEqual(first, candidate.inventory(self.source, self.asset, cache))
        self.assertEqual(len(first['documents']), 1)
        policy = {'resource_id': 'fixture', 'include_path': r'\.html$', 'topics': {'water': 'Water'}}
        result = candidate.inspect_candidates(self.source, self.asset, first, policy)
        self.assertFalse(result['content_ready'])
        row = result['candidates'][0]
        self.assertEqual(row['entry_sha256'], hashlib.sha256(self.body.encode()).hexdigest())
        self.assertEqual(row['structure']['img'], 1)
        self.assertEqual(row['structure']['table'], 1)
        self.assertEqual(row['review_status'], 'pending')
        self.assertEqual({path.name for path in self.root.iterdir()}, {'source.zim', 'cache.json'})

    def test_changed_source_invalidates_inventory_checkpoint(self):
        cache = self.root / 'cache.json'
        original = candidate.inventory(self.source, self.asset, cache)
        with self.source.open('r+b') as handle:
            handle.seek(-1, 2)
            value = handle.read(1)
            handle.seek(-1, 2)
            handle.write(bytes([value[0] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            candidate.inventory(self.source, self.asset, cache)
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            candidate.inspect_candidates(self.source, self.asset, original, {'include_path': '.', 'topics': {'water': 'Water'}})


if __name__ == '__main__':
    unittest.main()
