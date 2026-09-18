"""Compact indexing and crash-safe reclamation never require source deletion."""
from pathlib import Path
import hashlib
import errno
import io
import json
import os
import random
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

import owl.search as search
from owl.search_pack import read_chunk


class CompactSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name).resolve()
        (self.target / 'source.txt').write_text('Water purification and practical first aid. ' * 1000, encoding='utf-8')
        self.assets = [{'destination': 'source.txt', 'format': 'txt', 'title': 'Practical guide'}]

    def retained_raw(self):
        with patch('owl.search_pack.publish_pack', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            search.build_search(self.target, self.assets)
        job, raw, _ = search._job_paths(self.target, None)
        self.assertTrue((job / 'serialized.json').is_file())
        self.assertEqual(search.checkpoint_usage(self.target)['scratch_bytes'], 0)
        return job, raw

    def test_whitespace_normalization_preserves_tokens_across_arbitrary_chunks(self):
        source = ('  Leading\n\nindentation\t café\u2003𐐀  a_word  中文\r\n' * 400) + 'lastword'
        expected = search.tokens(source)
        for width in (1, 2, 7, 127, 8191):
            with self.subTest(width=width):
                passages = list(search._passages(source[n:n + width] for n in range(0, len(source), width)))
                self.assertEqual(search.tokens(' '.join(passages)), expected)
                self.assertTrue(all(len(p) <= search.PASSAGE_CHARS for p in passages))
                self.assertTrue(all('  ' not in p and '\n' not in p and '\t' not in p for p in passages))

    def test_varint_unsigned_boundaries_and_invalid_values(self):
        for value in (0, 1, 127, 128, 16383, 16384, 2**21, 2**28, 2**32 - 1):
            encoded = search._uvarint(value)
            decoded = sum((byte & 127) << (7 * n) for n, byte in enumerate(encoded))
            self.assertEqual(decoded, value)
            self.assertLessEqual(len(encoded), 5)
            self.assertFalse(encoded[-1] & 128)
        for invalid in (-1, True, 2**32, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(search.SearchError):
                search._uvarint(invalid)

    def test_documents_are_compressed_and_posting_lengths_match_varints(self):
        report = search.build_search(self.target, self.assets)
        manifest = report['transport']
        data = b''.join(read_chunk(self.target, manifest, n)[0] for n in range(manifest['chunk_count']))
        self.assertEqual(data[:8], b'OWLIDX3\n')
        header = json.loads(data[12:12 + struct.unpack_from('<I', data, 8)[0]])
        self.assertEqual(header['document_encoding'], 'zlib-json-v1')
        self.assertEqual(header['postings_encoding'], 'delta-uvarint-v1')
        first, length = struct.unpack_from('<QI', data, header['docs_offset'])
        record = zlib.decompress(data[first:first + length])
        self.assertLess(length, len(record) / 2)
        for number in range(header['terms']):
            at, size = struct.unpack_from('<QI', data, header['lexicon_offset'] + number * 12)
            _, start, count, byte_length = json.loads(data[at:at + size])
            position = start
            previous = 0
            for posting in range(count):
                values = []
                for _ in range(3):
                    value = shift = 0
                    while True:
                        byte = data[position]; position += 1
                        value |= (byte & 127) << shift; shift += 7
                        if not byte & 128: break
                    values.append(value)
                delta, tf, dl = values
                self.assertGreater(tf, 0); self.assertGreater(dl, 0)
                if posting: self.assertGreater(delta, 0)
                previous += delta
                self.assertLess(previous, header['documents'])
            self.assertEqual(position, start + byte_length)

    def test_compressed_and_uncompressed_record_limits_precede_database_writes(self):
        database = Mock()
        with self.assertRaisesRegex(search.SearchError, 'Search record exceeds'):
            search._add_record(database, io.BytesIO(), {'text': 'x' * (1024 * 1024)}, 0, 0)
        database.execute.assert_not_called()
        with patch('owl.search.zlib.compress', return_value=b'x' * (1024 * 1024 + 1)), \
                self.assertRaisesRegex(search.SearchError, 'Compressed search record exceeds'):
            search._add_record(database, io.BytesIO(), {'text': 'small'}, 0, 0)
        database.execute.assert_not_called()

    def test_interrupt_before_raw_marker_preserves_extraction(self):
        with patch('owl.search._save_ready', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            search.build_search(self.target, self.assets)
        usage = search.checkpoint_usage(self.target)
        self.assertGreater(usage['scratch_bytes'], 0)
        self.assertFalse(usage['raw_checkpoint_present'])
        with patch('owl.search._units', side_effect=AssertionError('already extracted')):
            search.build_search(self.target, self.assets)

    def test_raw_and_marker_directories_are_synced_before_reclamation(self):
        events = []
        original_save = search._save_ready
        original_clear = search._clear_extraction
        def sync(path):
            events.append(('sync', path.name))
            return True
        def save(*args):
            result = original_save(*args)
            events.append(('marker-ready', args[0].name))
            return result
        def clear(job):
            events.append(('cleanup', job.name))
            original_clear(job)
        with patch('owl.search._sync_directory', side_effect=sync), \
                patch('owl.search._save_ready', side_effect=save), patch('owl.search._clear_extraction', side_effect=clear):
            search.build_search(self.target, self.assets)
        job, _, _ = search._job_paths(self.target, None)
        self.assertEqual(events, [('sync', 'SEARCH'), ('sync', job.name),
                                  ('marker-ready', job.name), ('cleanup', job.name)])

    def test_directory_io_error_never_reclaims_extraction(self):
        for failed_sync in (1, 2):
            with self.subTest(failed_sync=failed_sync):
                calls = 0
                def sync(_):
                    nonlocal calls
                    calls += 1
                    if calls == failed_sync:
                        raise OSError(errno.EIO, 'directory sync failed')
                    return True
                with patch('owl.search._sync_directory', side_effect=sync), self.assertRaises(OSError):
                    search.build_search(self.target, self.assets)
                job, part, _ = search._job_paths(self.target, None)
                self.assertTrue((job / 'records.bin').is_file())
                self.assertTrue((job / 'build.sqlite3').is_file())
                self.assertTrue(part.is_file())
                # Keep the next iteration on the normal publication branch.
                (job / 'serialized.json').unlink(missing_ok=True)
        with patch('owl.search._units', side_effect=AssertionError('already extracted')):
            search.build_search(self.target, self.assets)

    def test_directory_sync_unsupported_is_narrow_and_warns_once(self):
        if os.name == 'nt':
            with patch('owl.search.os.open') as opened:
                self.assertFalse(search._sync_directory(self.target))
            opened.assert_not_called()
        else:
            with patch('owl.search.os.open', return_value=123), patch('owl.search.os.close') as close:
                for code in (errno.EINVAL, getattr(errno, 'ENOTSUP', errno.EINVAL)):
                    with patch('owl.search.os.fsync', side_effect=OSError(code, 'unsupported')):
                        self.assertFalse(search._sync_directory(self.target))
                for code in (errno.EIO, errno.ENOSPC, errno.EACCES):
                    with patch('owl.search.os.fsync', side_effect=OSError(code, 'failure')), self.assertRaises(OSError):
                        search._sync_directory(self.target)
                self.assertEqual(close.call_count, 5)
        messages = []
        with patch('owl.search._sync_directory', return_value=False):
            search.build_search(self.target, self.assets, progress=messages.append)
        self.assertEqual(sum('DURABILITY NOTICE' in message for message in messages), 1)

    def test_raw_resume_syncs_both_directories_before_repeated_cleanup(self):
        job, _ = self.retained_raw()
        events = []
        original_clear = search._clear_extraction
        def clear(path):
            events.append(('cleanup', path))
            original_clear(path)
        with patch('owl.search._sync_directory', side_effect=lambda path: events.append(('sync', path)) or True), \
                patch('owl.search._clear_extraction', side_effect=clear):
            search.build_search(self.target, self.assets, raw_reuse_only=True)
        self.assertEqual(events, [('sync', self.target / 'SEARCH'), ('sync', job), ('cleanup', job)])

    def test_interrupt_after_raw_marker_and_during_cleanup_resumes_from_verified_raw(self):
        unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path.name == 'records.bin':
                raise KeyboardInterrupt
            return unlink(path, *args, **kwargs)
        # Initial empty-workspace cleanup also calls unlink(records.bin).
        original_clear = search._clear_extraction
        def partial(job):
            with patch.object(Path, 'unlink', interrupt):
                original_clear(job)
        with patch('owl.search._clear_extraction', side_effect=partial), self.assertRaises(KeyboardInterrupt):
            search.build_search(self.target, self.assets)
        job, raw, _ = search._job_paths(self.target, None)
        self.assertTrue((job / 'serialized.json').is_file())
        self.assertTrue((job / 'records.bin').is_file())
        self.assertFalse((job / 'build.sqlite3').exists())
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        proof = search.probe_raw_checkpoint(self.target, self.assets)
        self.assertEqual(proof['index_sha256'], digest)
        with patch('owl.search._units', side_effect=AssertionError('must resume raw')), \
                patch('owl.search._serialize_index', side_effect=AssertionError('must not serialize again')):
            report = search.build_search(self.target, self.assets, raw_reuse_only=True)
        self.assertEqual(report['index_sha256'], digest)
        self.assertFalse(raw.exists())
        self.assertFalse((job / 'serialized.json').exists())

    def test_raw_probe_budget_change_and_partial_chunk_credit(self):
        randomizer = random.Random(31)
        (self.target / 'source.txt').write_text(' '.join(f'term{randomizer.getrandbits(56):014x}' for _ in range(25000)), encoding='utf-8')
        def stop(message):
            if message.startswith('INDEX packaging local chunks:'):
                raise KeyboardInterrupt
        with patch('owl.search.time.monotonic', side_effect=iter(range(0, 100000, 10))), self.assertRaises(KeyboardInterrupt):
            search.build_search(self.target, self.assets, progress=stop)
        job, raw, _ = search._job_paths(self.target, None)
        first = search.probe_raw_checkpoint(self.target, self.assets)
        self.assertGreater(first['retained_transport_bytes'], 0)
        staged = next((self.target / 'SEARCH/chunks').glob('*/*.js.part'))
        staged.write_bytes(b'damaged')
        second = search.probe_raw_checkpoint(self.target, self.assets)
        self.assertEqual(second['retained_transport_bytes'], 0)
        self.assertGreater(second['remaining_pack_allocation_bytes'], 0)
        # Damaged staged bytes receive no credit and are repaired from verified raw.
        with patch('owl.search._units', side_effect=AssertionError('must reuse raw')):
            report = search.build_search(self.target, self.assets, raw_reuse_only=True,
                                         search_budget_bytes=20_000_000, index_scratch_budget_bytes=40_000_000)
        self.assertEqual(report['index_sha256'], second['index_sha256'])
        self.assertFalse(raw.exists())

    def test_changed_source_or_corrupt_raw_rejects_raw_only_and_rebuilds_safely(self):
        _, raw = self.retained_raw()
        self.assertIsNotNone(search.probe_raw_checkpoint(self.target, self.assets))
        (self.target / 'source.txt').write_text('Changed source', encoding='utf-8')
        self.assertIsNone(search.probe_raw_checkpoint(self.target, self.assets))
        with self.assertRaisesRegex(search.SearchError, 'raw checkpoint changed'):
            search.build_search(self.target, self.assets, raw_reuse_only=True)
        with patch('owl.search_pack.publish_pack', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            search.build_search(self.target, self.assets)
        with raw.open('r+b') as handle:
            handle.seek(4100); handle.write(b'corrupt')
        self.assertIsNone(search.probe_raw_checkpoint(self.target, self.assets))
        with self.assertRaisesRegex(search.SearchError, 'raw checkpoint changed'):
            search.build_search(self.target, self.assets, raw_reuse_only=True)
        search.build_search(self.target, self.assets)

    def test_ignored_entries_do_not_trigger_unit_commits_but_time_still_does(self):
        saved = []
        original_save = search._save_checkpoint
        now = [10]
        def save(db, records, state, *args):
            saved.append(state['unit_cursor'])
            return original_save(db, records, state, *args)
        def units(*args):
            yield 0, {}, ['first text']
            for number in range(1, 201):
                if number == 100: now[0] = 20
                yield number, None, ()
            yield 201, {}, ['second text']
        with patch('owl.search._units', side_effect=units), patch('owl.search.CHECKPOINT_UNITS', 2), \
                patch('owl.search.time.monotonic', side_effect=lambda: now[0]), patch('owl.search._save_checkpoint', side_effect=save):
            search.build_search(self.target, self.assets)
        self.assertIn(101, saved)  # Time checkpoint saves the raw cursor on a skipped entry.
        self.assertNotIn(2, saved)
        self.assertLessEqual(len(saved), 5)


if __name__ == '__main__':
    unittest.main()
