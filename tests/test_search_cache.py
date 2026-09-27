"""Per-asset cache tests use local fixtures; no real archive downloads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from owl import search
from owl.search_cache import IndexCache, NAMESPACE, cache_usage
from owl.search_pack import read_chunk
from owl.safety import SafetyError


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cache = self.root / 'cache'
        self.bodies = {
            'a.txt': ('water boiling café 𐐀 sanitation ' * 1600 + '\n') * 25,
            'b.html': '<h1>Garden plants</h1><script>hiddenword</script>' + '<p>water soil crops</p>' * 700,
            'c.bin': '\0opaque',
        }
        self.assets = [
            {'id': 'a', 'destination': 'a.txt', 'format': 'txt', 'title': 'Water',
             'resource_type': 'textbook', 'illustrated': True, 'license': 'fixture', 'tags': ['safe']},
            {'id': 'b', 'destination': 'b.html', 'format': 'html', 'title': 'Plants', 'category': 'garden'},
            {'id': 'c', 'destination': 'c.bin', 'format': 'bin', 'title': 'Opaque', 'description': 'water metadata'},
        ]

    def target(self, name):
        target = self.root / name
        target.mkdir()
        for name, body in self.bodies.items():
            (target / name).write_text(body, encoding='utf-8')
        return target

    def build(self, target, assets=None, **kwargs):
        return search.build_search(target, self.assets if assets is None else assets,
                                   index_cache_dir=self.cache, **kwargs)

    @staticmethod
    def binary(target):
        report = json.loads((target / 'SEARCH/coverage.json').read_text())
        manifest = report['transport']
        return b''.join(read_chunk(target, manifest, number)[0] for number in range(manifest['chunk_count']))

    def clean(self, assets=None):
        target = self.target('clean-' + str(len(list(self.root.iterdir()))))
        search.build_search(target, self.assets if assets is None else assets)
        return self.binary(target)

    def test_shards_equal_clean_bytes_and_warm_cross_target_needs_no_postings_database(self):
        first = self.target('first')
        result = self.build(first)
        self.assertEqual(result['cache'], {'mode': 'shards', 'hits': 0, 'misses': 3, 'metadata_reuses': 0})
        expected = self.clean()
        self.assertEqual(self.binary(first), expected)
        second = self.target('second')
        with patch('owl.search._units', side_effect=AssertionError('warm extraction')), \
             patch('owl.search._database', side_effect=AssertionError('warm SQLite')), \
             patch('owl.search._add_record', side_effect=AssertionError('warm tokenization')):
            result = self.build(second)
        self.assertEqual(self.binary(second), expected)
        self.assertEqual(result['cache']['hits'], 3)
        self.assertGreater(cache_usage(self.cache), 0)
        self.assertEqual(search.checkpoint_usage(second)['scratch_bytes'], 0)

    def test_more_shards_than_open_file_limit_preserve_unicode_term_order(self):
        assets = [{'destination': f'part-{number:02d}.txt', 'format': 'txt', 'title': f'Part {number}'}
                  for number in range(30)]
        targets = [self.target(name) for name in ('many-cold', 'many-warm', 'many-clean')]
        for target in targets:
            for number, asset in enumerate(assets):
                (target / asset['destination']).write_text(f'共同 café 𐐀 common unique{number} ' * 20, encoding='utf-8')
        self.build(targets[0], assets)
        with patch('owl.search._database', side_effect=AssertionError('warm SQLite')):
            report = self.build(targets[1], assets)
        search.build_search(targets[2], assets)
        self.assertEqual(report['cache']['hits'], 30)
        self.assertEqual(self.binary(targets[0]), self.binary(targets[2]))
        self.assertEqual(self.binary(targets[1]), self.binary(targets[2]))

    def test_subsets_additions_removals_reuse_only_matching_assets(self):
        self.build(self.target('first'), self.assets[:2])
        calls = []
        original = search._units
        def units(path, asset, coverage, start=0):
            calls.append(asset['destination'])
            yield from original(path, asset, coverage, start)
        added = self.target('added')
        with patch('owl.search._units', side_effect=units):
            report = self.build(added)
        self.assertEqual(calls, ['c.bin'])
        self.assertEqual(report['cache']['hits'], 2)
        self.assertEqual(self.binary(added), self.clean())
        subset = [self.assets[2], self.assets[0]]
        removed = self.target('removed')
        with patch('owl.search._database', side_effect=AssertionError('must stream')):
            report = self.build(removed, subset)
        self.assertEqual(report['cache']['hits'], 2)
        self.assertEqual(self.binary(removed), self.clean(subset))

    def test_metadata_reuses_parsed_passages_and_matches_clean_index(self):
        self.build(self.target('first'))
        changed = [dict(asset) for asset in self.assets]
        changed[0].update(title='New water title', attribution='New credit', resource_type='guide', illustrated=False)
        changed[2]['description'] = 'changed searchable opaque description'
        target = self.target('changed')
        with patch('owl.search._units', side_effect=AssertionError('metadata must reuse body')):
            report = self.build(target, changed)
        self.assertEqual(report['cache'], {'mode': 'shards', 'hits': 1, 'misses': 2, 'metadata_reuses': 2})
        self.assertEqual(self.binary(target), self.clean(changed))
        self.assertEqual(len(list((self.cache / NAMESPACE).glob('*.owl'))), 5)

    def test_metadata_reweighting_resumes_committed_passages(self):
        self.build(self.target('first'), self.assets[:1])
        changed = [{**self.assets[0], 'title': 'Changed metadata title'}]
        target = self.target('metadata-resume')
        original_save = search._save_checkpoint
        clock = 0
        def monotonic():
            nonlocal clock
            clock += 6
            return clock
        def save(db, records, state, check_budget):
            original_save(db, records, state, check_budget)
            if state.get('fingerprint', '').startswith('metadata:') and state.get('documents') == 3:
                raise KeyboardInterrupt
        with patch('owl.search_cache.time.monotonic', side_effect=monotonic), \
             patch('owl.search._save_checkpoint', side_effect=save), self.assertRaises(KeyboardInterrupt):
            self.build(target, changed)
        seen = []
        original_add = search._add_record
        def add(db, output, record, document, flags):
            seen.append(document)
            return original_add(db, output, record, document, flags)
        with patch('owl.search._units', side_effect=AssertionError('metadata resume reparsed source')), \
             patch('owl.search._add_record', side_effect=add):
            self.build(target, changed)
        self.assertEqual(seen[0], 3)
        self.assertEqual(self.binary(target), self.clean(changed))

    def test_destination_changes_reuse_body_and_rewrite_links_and_coverage(self):
        self.build(self.target('first'), self.assets[1:2])
        changed = [{**self.assets[1], 'destination': 'renamed.html', 'id': 'new-id'}]
        target = self.target('renamed')
        (target / 'renamed.html').write_text(self.bodies['b.html'])
        with patch('owl.search._units', side_effect=AssertionError('must reuse renamed body')):
            report = self.build(target, changed)
        self.assertEqual(report['assets'][0]['destination'], 'renamed.html')
        self.assertEqual(report['assets'][0]['id'], 'new-id')
        clean = self.target('renamed-clean')
        (clean / 'renamed.html').write_text(self.bodies['b.html'])
        search.build_search(clean, changed)
        self.assertEqual(self.binary(target), self.binary(clean))

    def test_operational_changes_and_irrelevant_catalog_fields_preserve_identity(self):
        first = self.build(self.target('first'), self.assets[1:2])
        irrelevant = [{**self.assets[1], 'profiles': ['other'], 'version': 'editorial note', 'size_estimate': 900}]
        with patch.object(search, 'CHECKPOINT_UNITS', 7), patch.object(search, 'CHECKPOINT_SECONDS', 123), \
             patch('owl.search.importlib.metadata.version', return_value='unrelated-new-library'), \
             patch('owl.search._database', side_effect=AssertionError('operational edit rebuilt index')):
            second = self.build(self.target('second'), irrelevant)
        self.assertEqual(first['build_fingerprint'], second['build_fingerprint'])
        self.assertEqual(second['cache']['hits'], 1)

    def test_source_and_extraction_semantics_invalidate_only_affected_shard(self):
        self.build(self.target('first'), self.assets[1:2])
        calls = []
        original = search._units
        def units(path, asset, coverage, start=0):
            calls.append(asset['destination'])
            yield from original(path, asset, coverage, start)
        with patch.object(search, 'EXTRACTION_VERSION', search.EXTRACTION_VERSION + 1), \
             patch('owl.search._units', side_effect=units):
            report = self.build(self.target('semantics'), self.assets[1:2])
        self.assertEqual(calls, ['b.html'])
        changed = self.target('source-changed')
        (changed / 'b.html').write_text('Entirely new source text')
        with patch('owl.search._units', side_effect=units):
            report = self.build(changed, self.assets[1:2])
        self.assertEqual(calls, ['b.html', 'b.html'])
        self.assertEqual(report['cache']['metadata_reuses'], 0)

    def test_index_semantics_reweight_cached_text_without_reextracting(self):
        self.build(self.target('first'), self.assets[1:2])
        with patch.object(search, 'INDEX_SEMANTICS_VERSION', search.INDEX_SEMANTICS_VERSION + 1), \
             patch('owl.search._units', side_effect=AssertionError('tokenizer change reparsed source')):
            report = self.build(self.target('second'), self.assets[1:2])
        self.assertEqual(report['cache']['metadata_reuses'], 1)

    def test_recipe_includes_only_dependencies_used_by_the_format(self):
        pdf = {**self.assets[0], 'format': 'pdf'}
        zim = {**self.assets[0], 'format': 'zim'}
        with patch('owl.search.importlib.metadata.version', side_effect=lambda name: 'old-' + name):
            old_pdf = search._asset_recipe(pdf, '0' * 64)
            old_zim = search._asset_recipe(zim, '0' * 64)
        with patch('owl.search.importlib.metadata.version', side_effect=lambda name: 'new-' + name):
            new_pdf = search._asset_recipe(pdf, '0' * 64)
        self.assertNotEqual(old_pdf, new_pdf)
        self.assertEqual(set(old_pdf['semantics']['dependencies']), {'pypdf', 'fonttools'})
        self.assertEqual(set(old_zim['semantics']['dependencies']), {'libzim'})
        self.assertEqual(search._asset_recipe(self.assets[0], '0' * 64)['semantics']['dependencies'], {})

    def test_corrupt_completed_shard_fails_before_extraction_or_publication(self):
        self.build(self.target('first'), self.assets[1:2])
        raw = next((self.cache / NAMESPACE).glob('*.owl'))
        with raw.open('r+b') as handle:
            handle.seek(-1, 2)
            byte = handle.read(1)
            handle.seek(-1, 2)
            handle.write(bytes([byte[0] ^ 255]))
        target = self.target('second')
        with patch('owl.search._units', side_effect=AssertionError('silently rebuilding corrupt cache')), \
             self.assertRaisesRegex(search.SearchError, 'Invalid completed search-cache shard'):
            self.build(target, self.assets[1:2])
        self.assertFalse((target / 'SEARCH/manifest.js').exists())

    def test_publication_interruption_recovers_copied_shard_without_extraction(self):
        target = self.target('first')
        original_replace = os.replace
        def replace(source, destination):
            if str(source).endswith('.json.part') and str(destination).endswith('.json'):
                raise KeyboardInterrupt
            return original_replace(source, destination)
        with patch('owl.search_cache.os.replace', side_effect=replace), self.assertRaises(KeyboardInterrupt):
            self.build(target, self.assets[1:2])
        self.assertEqual(len(list((self.cache / NAMESPACE).glob('*.json.part'))), 1)
        with patch('owl.search._units', side_effect=AssertionError('recovery reparsed')), \
             patch('owl.search._database', side_effect=AssertionError('recovery reopened SQLite')):
            report = self.build(target, self.assets[1:2])
        self.assertEqual(report['cache']['hits'], 1)
        self.assertFalse(list((self.cache / NAMESPACE).glob('*.part')))
        self.assertEqual(self.binary(target), self.clean(self.assets[1:2]))

    def test_cache_budget_failure_retains_extraction_and_existing_shards(self):
        target = self.target('first')
        with self.assertRaisesRegex(search.SearchError, 'index_cache_budget_bytes'):
            self.build(target, self.assets[1:2], index_cache_budget_bytes=1000)
        self.assertLessEqual(cache_usage(self.cache), 1000)
        self.assertGreater(search.checkpoint_usage(target)['scratch_bytes'], 0)
        with patch('owl.search._units', side_effect=AssertionError('budget retry reparsed')):
            self.build(target, self.assets[1:2], index_cache_budget_bytes=10_000_000)
        self.assertGreater(cache_usage(self.cache), 1000)
        with self.assertRaisesRegex(search.SearchError, 'index_cache_budget_bytes'):
            self.build(self.target('second'), self.assets[1:2], index_cache_budget_bytes=1000)
        self.assertEqual(len(list((self.cache / NAMESPACE).glob('*.owl'))), 1)

    def test_cache_lock_and_unowned_directory_fail_closed(self):
        with IndexCache(self.cache, None).locked():
            with self.assertRaisesRegex(SafetyError, 'Another OWL process'):
                self.build(self.target('locked'), self.assets[1:2])
        foreign = self.root / 'foreign'
        (foreign / NAMESPACE).mkdir(parents=True)
        (foreign / NAMESPACE / 'important.txt').write_text('preserve')
        with self.assertRaises((SafetyError, ValueError)):
            search.build_search(self.target('unowned'), self.assets[1:2], index_cache_dir=foreign)
        self.assertEqual((foreign / NAMESPACE / 'important.txt').read_text(), 'preserve')

    def test_cache_symlink_is_rejected_and_usage_counts_partial_files(self):
        self.build(self.target('first'), self.assets[1:2])
        namespace = self.cache / NAMESPACE
        before = cache_usage(self.cache)
        (namespace / ('0' * 64 + '.owl.part')).write_bytes(b'x' * 123)
        self.assertEqual(cache_usage(self.cache), before + 123)
        try:
            (namespace / 'unexpected-link').symlink_to(self.root / 'first')
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(SafetyError):
            cache_usage(self.cache)

    def test_progress_and_completed_reuse_reset_cache_counters(self):
        class Progress:
            def __init__(self): self.events = []
            def __call__(self, _): pass
            def event(self, **fields): self.events.append(fields)
        progress = Progress()
        target = self.target('first')
        self.build(target, self.assets[1:2], progress=progress)
        self.assertTrue(any(e.get('cache_misses') == 1 for e in progress.events))
        self.assertTrue(any(e.get('checkpoint_at') for e in progress.events))
        progress.events.clear()
        report = self.build(target, self.assets[1:2], progress=progress)
        self.assertEqual(report['cache'], {'mode': 'completed-index', 'hits': 0, 'misses': 0, 'metadata_reuses': 0})
        self.assertEqual(progress.events[0]['cache_misses'], 0)
        self.assertTrue(all(e['phase'] == 'search' for e in progress.events))

    def test_zim_native_titles_and_entries_survive_metadata_reweighting(self):
        assets = [{**self.assets[1], 'format': 'zim', 'destination': 'b.html'}]
        def units(_path, _asset, _coverage, start=0):
            if start == 0:
                yield 0, {'entry': 'A/water', 'title': 'Archive native title'}, ['clean water']
        with patch('owl.search.check_extractors'), patch('owl.search._units', side_effect=units):
            self.build(self.target('first'), assets)
        changed = [{**assets[0], 'title': 'New catalog title', 'attribution': 'New attribution'}]
        target = self.target('second')
        with patch('owl.search.check_extractors'), patch('owl.search._units', side_effect=AssertionError('reparsed ZIM')):
            self.build(target, changed)
        clean = self.target('zim-clean')
        with patch('owl.search.check_extractors'), patch('owl.search._units', side_effect=units):
            search.build_search(clean, changed)
        self.assertEqual(self.binary(target), self.binary(clean))
