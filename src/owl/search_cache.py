"""Optional immutable per-asset search shards and bounded OWLIDX3 composition.

Only compact records and sorted postings are retained. Extraction SQLite stays in
its explicitly budgeted workspace; warm builds never populate a postings database.
The cache is opt-in, owns one namespaced directory, and never evicts old shards.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import time
import zlib

from .runtime import file_lock
from .safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file

NAMESPACE = 'owl-index-v1'
OWNER = {'owner': 'offline-wandering-library-search-cache', 'schema_version': 1}
BLOCK = 1024 * 1024
MAX_METADATA = 4 * BLOCK


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _read_json(path: Path) -> dict:
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > MAX_METADATA:
        raise ValueError(f'Invalid search-cache metadata: {path}')
    with path.open('rb') as handle:
        data = handle.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        raise ValueError(f'Oversized search-cache metadata: {path}')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f'Invalid search-cache metadata: {path}')
    return value


def _root(directory: Path) -> Path:
    directory = Path(directory).absolute()
    reject_symlinks(directory)
    return safe_path(directory, NAMESPACE)


def cache_usage(directory: Path) -> int:
    """Read-only bytes in the owned namespace, including partials and scaffolding."""
    root = _root(directory)
    if not root.exists():
        return 0
    if not root.is_dir() or _read_json(safe_path(root, 'owner.json')) != OWNER:
        raise SafetyError(f'Refusing unowned search cache: {root}')
    total = 0
    # The namespace is deliberately flat; no unbounded recursive traversal or
    # following user-controlled symlinks. Unknown ordinary files are preserved
    # and counted against the allowance.
    for path in root.iterdir():
        reject_symlinks(path)
        if not path.is_file():
            raise SafetyError(f'Unexpected directory or non-file in search cache: {path}')
        total += path.stat().st_size
    return total


class IndexCache:
    def __init__(self, directory: Path, budget: int | None):
        self.directory, self.root, self.budget = Path(directory), _root(directory), budget
        self._sources = None
        if budget is not None and (type(budget) is not int or budget < 0):
            raise ValueError('index_cache_budget_bytes must be a nonnegative integer')

    def check(self, additional: int = 0) -> None:
        from .search import SearchError
        used = cache_usage(self.directory)
        if self.budget is not None and used + additional > self.budget:
            raise SearchError(f'Search cache needs {used + additional:,} bytes, exceeding '
                              f'index_cache_budget_bytes ({self.budget:,}). Increase the allowance '
                              'or choose another cache directory; existing shards and extraction checkpoints are retained.')

    @contextmanager
    def locked(self):
        from .search import SearchError
        if not self.root.exists() or (self.root.is_dir() and not any(self.root.iterdir())):
            if self.budget is not None and len(_json(OWNER)) + 1 > self.budget:
                raise SearchError('index_cache_budget_bytes is too small for search-cache ownership metadata')
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_write(safe_path(self.root, 'owner.json'), _json(OWNER))
        # Validate before creating the lock, and count that persistent byte.
        cache_usage(self.directory)
        lock = safe_path(self.root, 'lock')
        self.check(0 if lock.exists() else 1)
        with guard_directory(self.root), file_lock(lock):
            self.check()
            yield self

    def paths(self, key: str) -> tuple[Path, Path]:
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('Invalid search shard key')
        return safe_path(self.root, key + '.owl'), safe_path(self.root, key + '.json')

    def source(self, recipe: dict) -> dict | None:
        """Find verified extracted passages whose catalog metadata can be rebuilt."""
        if self._sources is None:
            self._sources = {}
            for path in sorted(self.root.iterdir()):
                if not re.fullmatch('[0-9a-f]{64}\\.json', path.name):
                    continue
                try:
                    candidate = _read_json(path)['recipe']
                    if hashlib.sha256(_json(candidate)).hexdigest() + '.json' != path.name:
                        continue
                    identity = _source_identity(candidate)
                except (OSError, ValueError, KeyError, TypeError):
                    continue  # Unrelated broken metadata is not a reusable source.
                self._sources.setdefault(identity, []).append(candidate)
        for candidate in self._sources.get(_source_identity(recipe), []):
            shard = self.load(candidate)
            if shard is not None:
                return shard
        return None

    def load(self, recipe: dict) -> dict | None:
        """Verify all bytes. Recover a fully copied unpublished shard after a crash."""
        from .search import SearchError, _sync_directory
        key = hashlib.sha256(_json(recipe)).hexdigest()
        index, metadata = self.paths(key)
        pending = safe_path(self.root, key + '.json.part')
        finalized = metadata.exists()
        if not finalized and not pending.exists():
            return None
        try:
            saved = _read_json(metadata if finalized else pending)
            report = saved['report']
            if (saved.get('schema_version') != 1 or saved.get('key') != key or saved.get('recipe') != recipe
                    or not isinstance(report, dict) or report.get('build_fingerprint') != key
                    or report.get('format_version') != 3
                    or type(report.get('documents')) is not int or not 1 <= report['documents'] <= 2**32
                    or type(report.get('total_length')) is not int or report['total_length'] < report['documents']
                    or not isinstance(report.get('assets'), list) or len(report['assets']) != 1
                    or report['assets'][0].get('passages') != report['documents']
                    or report['assets'][0].get('destination') != recipe['metadata']['record']['destination']
                    or report['assets'][0].get('id') != recipe['metadata']['id']
                    or not isinstance(report.get('warnings'), list)
                    or type(report.get('index_bytes')) is not int or report['index_bytes'] < 4096
                    or not isinstance(report.get('index_sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', report['index_sha256'])):
                raise ValueError('Search shard recipe or report differs')
            candidate = index if index.exists() else safe_path(self.root, key + '.owl.part')
            if not candidate.is_file() or candidate.stat().st_size != report['index_bytes']:
                raise ValueError('Search shard is missing or truncated')
            before = _signature(candidate)
            if sha256_file(candidate) != report['index_sha256'] or before != _signature(candidate):
                raise ValueError('Search shard checksum changed')
            header = _header(candidate, report)
            if not finalized:
                if candidate != index:
                    os.replace(candidate, index)
                os.replace(pending, metadata)
                _sync_directory(self.root)
            return {'key': key, 'path': index, 'report': report, 'header': header,
                    'signature': _signature(index)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            if not finalized:
                # An interrupted copy is not a cache hit. Its retained extraction
                # checkpoint can serialize/publish it again without re-extraction.
                return None
            raise SearchError(f'Invalid completed search-cache shard {key}: {error}. '
                              'Restore that shard or choose another cache directory.') from error

    def publish(self, recipe: dict, raw: Path, report: dict) -> dict:
        from .search import SearchError, _sync_directory
        key = hashlib.sha256(_json(recipe)).hexdigest()
        index, metadata = self.paths(key)
        staged = safe_path(self.root, key + '.owl.part')
        pending = safe_path(self.root, key + '.json.part')
        data = _json({'schema_version': 1, 'key': key, 'recipe': recipe, 'report': report})
        if len(data) > MAX_METADATA:
            raise SearchError('Search-cache shard metadata exceeds 4 MiB')
        # Include atomic metadata staging and retain any orphaned final blob in
        # the peak estimate until it has been replaced. No eviction is implicit.
        partial_bytes = staged.stat().st_size if staged.exists() else 0
        pending_bytes = pending.stat().st_size if pending.exists() else 0
        self.check(max(len(data), report['index_bytes'] - partial_bytes + len(data) - pending_bytes))
        atomic_write(pending, data)
        before = _signature(raw)
        digest = hashlib.sha256()
        reject_symlinks(staged)
        with raw.open('rb') as source, staged.open('wb') as destination:
            size = 0
            while block := source.read(BLOCK):
                size += len(block)
                if size > report['index_bytes']:
                    raise SearchError('Raw search shard grew during cache publication')
                digest.update(block)
                destination.write(block)
            destination.flush()
            os.fsync(destination.fileno())
        if (size != report['index_bytes'] or digest.hexdigest() != report['index_sha256']
                or before != _signature(raw)):
            raise SearchError('Raw search shard changed during cache publication')
        os.replace(staged, index)
        os.replace(pending, metadata)
        _sync_directory(self.root)
        self.check()
        if self._sources is not None:
            self._sources.setdefault(_source_identity(recipe), []).append(recipe)
        # The copy was hashed above; avoid rereading this potentially large shard.
        return {'key': key, 'path': index, 'report': report, 'header': _header(index, report),
                'signature': _signature(index)}


def _source_identity(recipe: dict) -> str:
    semantics = recipe['semantics']
    body = {'source_sha256': recipe['source_sha256'],
            'format': recipe['metadata']['record']['format'],
            'text_encoding': recipe['metadata']['text_encoding'],
            'semantics': {key: semantics[key] for key in
                          ('extraction', 'dependencies', 'python', 'unicode', 'passage_chars', 'max_zim_item')}}
    return hashlib.sha256(_json(body)).hexdigest()


def _signature(path: Path) -> tuple:
    from .search import _signature as signature
    reject_symlinks(path)
    return signature(path)


def _header(path: Path, report: dict) -> dict:
    from .search import HEADER_SIZE, MAGIC
    with path.open('rb') as handle:
        data = handle.read(HEADER_SIZE)
    if len(data) != HEADER_SIZE or data[:8] != MAGIC:
        raise ValueError('Invalid search shard header')
    size = struct.unpack_from('<I', data, 8)[0]
    if size > HEADER_SIZE - 12:
        raise ValueError('Oversized search shard header')
    header = json.loads(data[12:12 + size])
    if (header.get('version') != 3 or header.get('document_encoding') != 'zlib-json-v1'
            or header.get('postings_encoding') != 'delta-uvarint-v1'
            or any(type(header.get(key)) is not int or header[key] < 0 for key in
                   ('documents', 'terms', 'size', 'docs_offset', 'flags_offset', 'lexicon_offset'))
            or header['documents'] != report['documents'] or header['size'] != report['index_bytes']
            or header['docs_offset'] < HEADER_SIZE
            or header['docs_offset'] + 12 * header['documents'] != header['flags_offset']
            or header['flags_offset'] + header['documents'] > header['lexicon_offset']
            or header['lexicon_offset'] + 12 * header['terms'] != header['size']
            or header.get('average_length') != report['total_length'] / report['documents']):
        raise ValueError('Invalid search shard bounds or statistics')
    return header


class _Files:
    """Bound open files independently of the number of selected assets."""
    def __init__(self):
        self.handles = OrderedDict()

    def read(self, shard: dict, start: int, size: int) -> bytes:
        from .search import SearchError
        if start < 0 or size < 0 or size > BLOCK or start + size > shard['header']['size']:
            raise SearchError('Invalid search-shard read bounds')
        path = shard['path']
        handle = self.handles.pop(path, None)
        if handle is None:
            if _signature(path) != shard['signature']:
                raise SearchError(f'Search shard changed during composition: {path}')
            handle = path.open('rb')
        self.handles[path] = handle
        while len(self.handles) > 24:
            self.handles.popitem(last=False)[1].close()
        handle.seek(start)
        data = handle.read(size)
        if len(data) != size:
            raise SearchError('Search shard was truncated during composition')
        return data

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()


def _copy(files: _Files, shard: dict, start: int, end: int, output, check_budget) -> None:
    while start < end:
        data = files.read(shard, start, min(BLOCK, end - start))
        output.write(data)
        start += len(data)
        check_budget()


def _term(files: _Files, shard: dict, number: int) -> list:
    from .search import SearchError
    header = shard['header']
    offset, size = struct.unpack('<QI', files.read(shard, header['lexicon_offset'] + number * 12, 12))
    if not 0 < size <= BLOCK or offset < header['flags_offset'] + header['documents'] or offset + size > header['lexicon_offset']:
        raise SearchError('Invalid search-shard lexicon record')
    term = json.loads(files.read(shard, offset, size))
    if (not isinstance(term, list) or len(term) != 4 or not isinstance(term[0], str) or not term[0]
            or any(type(value) is not int or value < 0 for value in term[1:])
            or not 1 <= term[2] <= header['documents'] or term[3] < 3 * term[2]
            or term[1] < header['flags_offset'] + header['documents'] or term[1] + term[3] > offset):
        raise SearchError('Invalid search-shard term bounds')
    return term


def _postings(files: _Files, shard: dict, term: list):
    """Decode one list with a single 64 KiB buffer, validating every varint."""
    from .search import SearchError
    position, end, buffer, at = term[1], term[1] + term[3], b'', 0

    def integer():
        nonlocal position, buffer, at
        value = 0
        for shift in range(0, 35, 7):
            if at == len(buffer):
                if position >= end:
                    raise SearchError('Truncated search-shard posting')
                buffer = files.read(shard, position, min(65536, end - position))
                position += len(buffer)
                at = 0
            byte = buffer[at]
            at += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                if value >= 2**32 or (shift and byte == 0):
                    raise SearchError('Invalid search-shard varint')
                return value
        raise SearchError('Invalid search-shard varint')

    document = 0
    for number in range(term[2]):
        delta, frequency, length = integer(), integer(), integer()
        document += delta
        if (number and not delta) or document >= shard['header']['documents'] or frequency < 1 or length < 1:
            raise SearchError('Invalid search-shard posting')
        yield document, frequency, length
    if position - len(buffer) + at != end:
        raise SearchError('Unexpected trailing search-shard posting bytes')


def compose(shards: list[dict], part: Path, job: Path, *, fingerprint: str,
            maximum: int | None, check_budget, notify) -> dict:
    """Merge precomputed records/postings without a corpus-wide SQLite rebuild."""
    from .search import HEADER_SIZE, MAGIC, PASSAGE_CHARS, SearchError, _BoundedIndexWriter, _uvarint
    lex_path, offsets_path = safe_path(job, 'merge-lexicon.bin'), safe_path(job, 'merge-offsets.bin')
    reject_symlinks(part)
    files = _Files()
    report = {'format_version': 3, 'documents': sum(s['report']['documents'] for s in shards),
              'total_length': sum(s['report']['total_length'] for s in shards),
              'assets': [a for s in shards for a in s['report']['assets']],
              'warnings': [w for s in shards for w in s['report']['warnings']],
              'generated_files': [], 'build_fingerprint': fingerprint}
    if report['documents'] > 2**32:
        raise SearchError('Index exceeds version 3\'s 2^32 passage limit')
    try:
        with part.open('w+b') as raw, lex_path.open('w+b') as lex, offsets_path.open('w+b') as offsets:
            output = _BoundedIndexWriter(raw, maximum)
            output.write(b'\0' * HEADER_SIZE)
            base_doc, bases = 0, []
            notify(f"INDEX composing {len(shards):,} cached assets: compressed records", force=True)
            for shard in shards:
                bases.append((base_doc, output.tell() - HEADER_SIZE))
                _copy(files, shard, HEADER_SIZE, shard['header']['docs_offset'], output, check_budget)
                base_doc += shard['header']['documents']
            docs_offset = output.tell()
            for shard, (_, record_shift) in zip(shards, bases):
                header = shard['header']
                # Read fixed-width tables in blocks, instead of seeking per doc.
                for first in range(0, header['documents'], 4096):
                    count = min(4096, header['documents'] - first)
                    data = files.read(shard, header['docs_offset'] + first * 12, count * 12)
                    for offset, size in struct.iter_unpack('<QI', data):
                        if not 0 < size <= BLOCK or offset < HEADER_SIZE or offset + size > header['docs_offset']:
                            raise SearchError('Invalid search-shard document bounds')
                        output.write(struct.pack('<QI', offset + record_shift, size))
                    check_budget()
            flags_offset = output.tell()
            for shard in shards:
                header = shard['header']
                _copy(files, shard, header['flags_offset'], header['flags_offset'] + header['documents'], output, check_budget)
            heap = []
            for index, shard in enumerate(shards):
                if shard['header']['terms']:
                    term = _term(files, shard, 0)
                    heapq.heappush(heap, (term[0], index, 0, term))
            terms = postings = 0
            notify('INDEX composing cached assets: sorted postings', force=True)
            while heap:
                name = heap[0][0]
                start, count, previous_doc = output.tell(), 0, 0
                while heap and heap[0][0] == name:
                    _, index, term_number, term = heapq.heappop(heap)
                    shard = shards[index]
                    for document, frequency, length in _postings(files, shard, term):
                        document += bases[index][0]
                        delta = document - previous_doc
                        if count and delta <= 0:
                            raise SearchError('Search-shard document order differs')
                        output.write(_uvarint(delta) + _uvarint(frequency) + _uvarint(length))
                        previous_doc = document
                        count += 1
                        postings += 1
                        if postings % 100000 == 0:
                            lex.flush(); offsets.flush()
                            notify(f'INDEX composing: {postings:,} postings, {terms:,} terms')
                    if term_number + 1 < shard['header']['terms']:
                        following = _term(files, shard, term_number + 1)
                        if following[0] <= name:
                            raise SearchError('Search-shard lexicon is not sorted')
                        heapq.heappush(heap, (following[0], index, term_number + 1, following))
                encoded = _json([name, start, count, output.tell() - start])
                offsets.write(struct.pack('<QI', lex.tell(), len(encoded)))
                lex.write(encoded)
                terms += 1
                if terms % 1000 == 0:
                    lex.flush(); offsets.flush()
                    check_budget()
            notify(f'INDEX composing cached assets: lexicon ({terms:,} terms)', force=True)
            lex_start = output.tell()
            lex.seek(0)
            while block := lex.read(BLOCK):
                output.write(block)
                check_budget()
            lexicon_offset = output.tell()
            offsets.seek(0)
            while block := offsets.read(12 * 4096):
                for offset, size in struct.iter_unpack('<QI', block):
                    output.write(struct.pack('<QI', lex_start + offset, size))
                check_budget()
            header = {'version': 3, 'document_encoding': 'zlib-json-v1', 'postings_encoding': 'delta-uvarint-v1',
                      'documents': report['documents'], 'terms': terms,
                      'average_length': report['total_length'] / max(1, report['documents']),
                      'docs_offset': docs_offset, 'flags_offset': flags_offset, 'lexicon_offset': lexicon_offset,
                      'size': output.tell(), 'tokenizer': 'NFKC-lower-unicode-letter-number-v1',
                      'passage_characters': PASSAGE_CHARS}
            encoded = _json(header)
            if len(encoded) > HEADER_SIZE - 12:
                raise SearchError('Search header exceeds reserved space')
            output.seek(0)
            output.write(MAGIC + struct.pack('<I', len(encoded)) + encoded)
            output.flush()
            os.fsync(output.fileno())
        for shard in shards:
            if _signature(shard['path']) != shard['signature']:
                raise SearchError(f"Search shard changed during composition: {shard['path']}")
        report.update(index_bytes=part.stat().st_size, index_sha256=sha256_file(part))
        return report
    finally:
        files.close()


def reindex_metadata(shard: dict, asset: dict, *, key: str, part: Path, job: Path,
                     maximum: int | None, check_budget, notify) -> dict:
    """Reweight cached text after metadata/tokenizer edits; never reopen a source."""
    from .search import (HEADER_SIZE, SearchError, _add_record, _asset_parameters,
                         _clear_job, _database, _progress_event, _save_checkpoint,
                         _serialize_index)
    db_path, records_path = safe_path(job, 'build.sqlite3'), safe_path(job, 'records.bin')
    db = _database(db_path)
    files = _Files()
    checkpoint_key = 'metadata:' + key
    try:
        table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone()
        saved = db.execute('SELECT data FROM checkpoint WHERE id=1').fetchone() if table else None
        state = json.loads(saved[0]) if saved else None
        if not isinstance(state, dict) or state.get('fingerprint') != checkpoint_key:
            db.close()
            _clear_job(job, part)
            db = _database(db_path)
            db.executescript('''
                CREATE TABLE docs (id INTEGER PRIMARY KEY, offset INTEGER, size INTEGER, flags INTEGER);
                CREATE TABLE postings (term TEXT, doc INTEGER, tf INTEGER, dl INTEGER,
                                       PRIMARY KEY (term,doc)) WITHOUT ROWID;
                CREATE TABLE lexicon (id INTEGER PRIMARY KEY, term TEXT, offset INTEGER, count INTEGER, length INTEGER);
                CREATE TABLE lex_offsets (id INTEGER PRIMARY KEY, offset INTEGER, size INTEGER);
                CREATE TABLE checkpoint (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            ''')
            state = {'fingerprint': checkpoint_key, 'documents': 0, 'total_length': 0, 'record_bytes': HEADER_SIZE}
            with records_path.open('w+b') as records:
                records.write(b'\0' * HEADER_SIZE)
                _save_checkpoint(db, records, state, check_budget)
        if (any(type(state.get(name)) is not int or state[name] < 0
                for name in ('documents', 'total_length', 'record_bytes'))
                or state['documents'] > shard['header']['documents'] or state['record_bytes'] < HEADER_SIZE
                or not records_path.is_file() or records_path.stat().st_size < state['record_bytes']):
            raise SearchError('Invalid cached-metadata extraction checkpoint')
        last = db.execute('SELECT id,offset,size FROM docs ORDER BY id DESC LIMIT 1').fetchone()
        if ((last[0] + 1 if last else 0) != state['documents']
                or (last[1] + last[2] if last else HEADER_SIZE) != state['record_bytes']):
            raise SearchError('Cached-metadata checkpoint does not match its records')
        base, flags = _asset_parameters(asset)
        coverage = json.loads(_json(shard['report']['assets'][0]))
        coverage.update(id=asset.get('id', asset['destination']), destination=asset['destination'])
        warnings = [] if coverage['status'] == 'full_text' else [
            f"{coverage['destination']}: {coverage['status']} ({coverage['warning_count']} notices)"]
        report = {'format_version': 3, 'documents': shard['header']['documents'],
                  'assets': [coverage], 'warnings': warnings, 'generated_files': [], 'build_fingerprint': key}
        notify(f"INDEX CACHE METADATA {asset['destination']}: reusing {report['documents']:,} extracted passages", force=True)
        with records_path.open('r+b') as records:
            records.truncate(state['record_bytes'])
            records.seek(state['record_bytes'])
            checkpoint_at = time.monotonic()
            for document in range(state['documents'], report['documents']):
                offset, size = struct.unpack('<QI', files.read(shard, shard['header']['docs_offset'] + document * 12, 12))
                if offset < HEADER_SIZE or not 0 < size <= BLOCK or offset + size > shard['header']['docs_offset']:
                    raise SearchError('Invalid cached source record bounds')
                decoder = zlib.decompressobj()
                data = decoder.decompress(files.read(shard, offset, size), BLOCK + 1)
                if len(data) > BLOCK or not decoder.eof or decoder.unused_data:
                    raise SearchError('Invalid compressed cached source record')
                old = json.loads(data)
                if not isinstance(old, dict) or not isinstance(old.get('text'), str):
                    raise SearchError('Invalid cached source record')
                if old.get('metadata_only') is True:
                    record = {**base, 'text': asset.get('description', ''), 'metadata_only': True}
                else:
                    # ZIM titles originate in the source archive and override the
                    # catalog title; preserve that distinction during reweighting.
                    source_fields = ('text', 'page', 'entry', 'passage', 'title') if base['format'] == 'zim' else ('text', 'page', 'entry', 'passage')
                    record = {**base, **{name: old[name] for name in source_fields if name in old}}
                state['total_length'] += _add_record(db, records, record, document, flags)
                state['documents'] = document + 1
                if state['documents'] % 1000 == 0 or time.monotonic() - checkpoint_at >= 5:
                    _save_checkpoint(db, records, state, check_budget)
                    _progress_event(notify, passages=state['documents'], completed_assets=0, total_assets=1,
                                    active_asset=asset['destination'], checkpoint_at=time.time())
                    checkpoint_at = time.monotonic()
            _save_checkpoint(db, records, state, check_budget)
            _serialize_index(db, records, part, report, state['total_length'], notify,
                             maximum=maximum, check_budget=check_budget)
        if _signature(shard['path']) != shard['signature']:
            raise SearchError('Cached source changed during metadata indexing')
        report.update(total_length=state['total_length'], index_bytes=part.stat().st_size,
                      index_sha256=sha256_file(part))
        return report
    except sqlite3.Error as error:
        raise SearchError(f'Cached-metadata checkpoint database failed: {error}. '
                          f'Check scratch space; extracted sources and checkpoints remain in {job}.') from error
    finally:
        files.close()
        db.close()
