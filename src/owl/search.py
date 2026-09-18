"""Build OWL's disk-backed, versioned full-text index.

The database is scratch space, never a runtime dependency. The portable index
contains JSON records, fixed-width offset tables, and sorted binary postings;
The browser reads requested ranges from bounded local script chunks automatically.
"""
from __future__ import annotations

import codecs
import errno
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import sys
import time
import unicodedata
import zipfile
import zlib
from collections import Counter
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import BinaryIO, Callable, Iterable, Iterator


MAGIC = b"OWLIDX3\n"
HEADER_SIZE = 4096
PASSAGE_CHARS = 8192
MAX_ZIM_ITEM = 64 * 1024 * 1024
CHECKPOINT_UNITS = 50
CHECKPOINT_SECONDS = 5
TEXTBOOK_FLAG = 1
ILLUSTRATED_GUIDE_FLAG = 2
TEXT_FORMATS = {"txt", "text", "md", "markdown", "html", "htm", "epub", "pdf", "zim"}
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class SearchError(ValueError):
    """An index cannot safely or completely be built as requested."""


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(unicodedata.normalize("NFKC", text).lower())


def check_extractors(assets: list[dict]) -> None:
    formats = {str(a.get("format", "")).lower() for a in assets}
    for fmt, module in [("pdf", "pypdf"), ("zim", "libzim")]:
        if fmt in formats and importlib.util.find_spec(module) is None:
            raise SearchError(f"{fmt.upper()} full-text indexing requires {module}; "
                              f"install {module} before building")


def _safe_path(root: Path, relative: str) -> Path:
    # Also validate when callers use this module independently of the builder.
    from .safety import safe_path
    return safe_path(root, relative)


def _json(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "template"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if self.hidden[-1] == tag:
                self.hidden.pop()
        elif tag in {"p", "div", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _decode_chunks(stream: BinaryIO, encoding: str = "utf-8-sig") -> Iterator[str]:
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    while block := stream.read(64 * 1024):
        yield decoder.decode(block)
    yield decoder.decode(b"", final=True)


def _html_chunks(chunks: Iterable[str]) -> Iterator[str]:
    parser = _HTMLText()
    for chunk in chunks:
        parser.feed(chunk)
        yield "".join(parser.parts)
        parser.parts.clear()
        if len(parser.rawdata) > 1024 * 1024:
            raise SearchError("HTML contains an unterminated token over 1 MiB")
    parser.close()
    yield "".join(parser.parts)


def _passages(chunks: Iterable[str]) -> Iterator[str]:
    buffer = ""
    previous_space = False
    for chunk in chunks:
        # Whitespace belongs to the search representation, not the source file.
        # Collapse across chunk boundaries without ever joining distinct words
        # or inserting a boundary into a word split between incoming chunks.
        chunk = re.sub(r"\s+", " ", chunk)
        if previous_space and chunk.startswith(" "):
            chunk = chunk[1:]
        if chunk:
            previous_space = chunk.endswith(" ")
        buffer += chunk
        while len(buffer) > PASSAGE_CHARS:
            # Preserve normal words at passage boundaries. Pathological unbroken
            # strings are split; no source text is discarded.
            matches = list(re.finditer(r"\s", buffer[:PASSAGE_CHARS + 1]))
            end = matches[-1].end() if matches else PASSAGE_CHARS
            value, buffer = buffer[:end], buffer[end:]
            if value.strip():
                yield value.strip()
    if buffer.strip():
        yield buffer.strip()


def _warn(coverage: dict, message: str) -> None:
    coverage["warning_count"] += 1
    if len(coverage["warnings"]) < 20:
        coverage["warnings"].append(message[:2048] + ("…" if len(message) > 2048 else ""))


@contextmanager
def _capture_pdf_warnings(coverage: dict):
    """Count extractor diagnostics without flooding stderr or retaining a log.

    A handler receives one record at a time; only twenty bounded examples are
    retained. Restore application logging even if PDF extraction fails. Indexing
    is intentionally single-threaded, so this scope belongs to exactly one PDF.
    """
    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            _warn(coverage, f"PDF extractor [{record.name}]: {record.getMessage()}")

    handler = Capture(level=logging.WARNING)
    previous = []
    for name in ("pypdf", "fontTools"):
        logger = logging.getLogger(name)
        previous.append((logger, logger.handlers[:], logger.level, logger.propagate))
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    try:
        yield
    finally:
        for logger, handlers, level, propagate in previous:
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
        handler.close()


def _units(path: Path, asset: dict, coverage: dict, start: int = 0
           ) -> Iterator[tuple[int, dict | None, Iterable[str]]]:
    """Yield a stable raw-unit cursor, including skipped archive entries.

    A cursor resumes before a PDF page, EPUB member, or ZIM directory entry.
    Plain streams form one unit because an HTML parser cannot safely seek into
    arbitrary source bytes. A skipped entry has no searchable metadata.
    """
    fmt = str(asset.get("format", path.suffix.lstrip("."))).lower()
    encoding = asset.get("text_encoding", "utf-8-sig")
    if fmt in {"html", "htm", "txt", "text", "md", "markdown"}:
        if start:
            return
        with path.open("rb") as stream:
            chunks = _decode_chunks(stream, encoding)
            yield 0, {}, _html_chunks(chunks) if fmt in {"html", "htm"} else chunks
    elif fmt == "pdf":
        from pypdf import PdfReader
        with path.open("rb") as stream:
            # Opening a resumed reader may repeat structural diagnostics. Those
            # were counted by the first opening; page diagnostics remain local.
            opening = coverage if start == 0 else {"warning_count": 0, "warnings": []}
            with _capture_pdf_warnings(opening):
                pdf = PdfReader(stream)
                if pdf.is_encrypted and not pdf.decrypt(""):
                    raise SearchError(f"Cannot extract encrypted PDF: {asset['destination']}")
                page_count = len(pdf.pages)
            with _capture_pdf_warnings(coverage):
                for page_index in range(start, page_count):
                    text = pdf.pages[page_index].extract_text() or ""
                    yield page_index, {"page": page_index + 1}, [text]
    elif fmt == "epub":
        with zipfile.ZipFile(path) as archive:
            # Never extract archive filenames onto the filesystem.
            for member_index, info in enumerate(sorted(archive.infolist(), key=lambda entry: entry.filename)):
                if member_index < start:
                    continue
                suffix = Path(info.filename).suffix.lower()
                if not info.is_dir() and suffix in {".html", ".htm", ".xhtml", ".txt"}:
                    with archive.open(info) as stream:
                        chunks = _decode_chunks(stream, encoding)
                        yield member_index, {"entry": info.filename}, (chunks if suffix == ".txt" else _html_chunks(chunks))
                else:
                    yield member_index, None, ()
    elif fmt == "zim":
        from libzim.reader import Archive, set_cluster_cache_max_size
        set_cluster_cache_max_size(2)
        archive = Archive(path)
        archive.dirent_cache_max_size = 4096
        if not hasattr(archive, "_get_entry_by_id"):
            raise SearchError("Unsupported libzim API: _get_entry_by_id is unavailable")
        # python-libzim's published reader.pyi provides this low-level iterator
        # primitive. Pin the compatible major version in the project's extras.
        for entry_id in range(start, archive.all_entry_count):
            entry = archive._get_entry_by_id(entry_id)
            if entry.is_redirect:
                yield entry_id, None, ()
                continue  # Target text is indexed once.
            item = entry.get_item()
            mime = item.mimetype.split(";", 1)[0].lower()
            if mime not in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}:
                if mime == "application/pdf":
                    _warn(coverage, f"Embedded PDF needs its archive reader: {entry.path}")
                yield entry_id, None, ()
                continue
            if item.size > MAX_ZIM_ITEM:
                _warn(coverage, f"Text entry exceeds 64 MiB extraction limit: {entry.path}")
                yield entry_id, None, ()
                continue
            content = item.content
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            def chunks() -> Iterator[str]:
                for start in range(0, len(content), 65536):
                    yield decoder.decode(content[start:start + 65536])
                yield decoder.decode(b"", final=True)
            yield entry_id, {"entry": entry.path, "title": entry.title}, (
                _html_chunks(chunks()) if "html" in mime else chunks())


def _add_record(db: sqlite3.Connection, output: BinaryIO, record: dict, doc_id: int,
                flags: int) -> int:
    if doc_id >= 2**32:
        raise SearchError("Index exceeds version 3's 2^32 passage limit")
    data = _json(record)
    if len(data) > 1024 * 1024:
        raise SearchError("Search record exceeds 1 MiB: shorten catalog metadata")
    data = zlib.compress(data, 6)
    if len(data) > 1024 * 1024:
        raise SearchError("Compressed search record exceeds 1 MiB: shorten catalog metadata")
    db.execute("INSERT INTO docs VALUES (?, ?, ?, ?)", (doc_id, output.tell(), len(data), flags))
    output.write(data)
    counts = Counter(tokens(record["text"]))
    for key, weight in [("title", 5), ("category", 2), ("tags", 2),
                        ("resource_labels", 2),
                        ("destination", 1), ("source", 1), ("entry", 1)]:
        for token in tokens(str(record.get(key, ""))):
            counts[token] += weight
    length = max(1, sum(counts.values()))
    db.executemany("INSERT INTO postings VALUES (?, ?, ?, ?)",
                   ((term, doc_id, frequency, length) for term, frequency in counts.items()))
    return length


def _job_paths(target: Path, work_dir: Path | None) -> tuple[Path, Path, dict]:
    from .safety import reject_symlinks
    target = target.absolute()
    reject_symlinks(target)
    work = Path(work_dir) if work_dir is not None else target / '.owl/work'
    reject_symlinks(work)
    identity = hashlib.sha256(str(target).encode('utf-8')).hexdigest()[:16]
    job = _safe_path(work, 'owl-search-' + identity)
    relative = 'SEARCH/.owl-index-' + identity + '.part'
    owner = {'owner': 'offline-wandering-library-search', 'schema_version': 1,
             'target': str(target), 'output_part': relative}
    return job, _safe_path(target, relative), owner


_EXTRACTION_FILES = ('build.sqlite3', 'build.sqlite3-journal', 'build.sqlite3-wal',
                     'build.sqlite3-shm', 'records.bin')
_JOB_FILES = (*_EXTRACTION_FILES, 'serialized.json')


def _owned_job(job: Path, owner: dict) -> bool:
    marker = _safe_path(job, 'owner.json')
    if not marker.exists():
        return False
    try:
        actual = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise SearchError(f'Unreadable search workspace marker: {marker}') from error
    if actual != owner:
        raise SearchError(f'Unrecognized search workspace owner: {marker}')
    for name in (*_JOB_FILES, 'lock'):
        path = _safe_path(job, name)
        if path.exists() and not path.is_file():
            raise SearchError(f'Search workspace file is not a regular file: {path}')
    return True


def checkpoint_usage(target: Path, *, work_dir: Path | None = None) -> dict:
    """Read-only allocated-file estimate for the builder's free-space planning.

    Only files under a matching ownership marker count. The caller must cap each
    credit at its corresponding new-output or scratch allowance. Old completed
    indexes do not count because they remain until atomic replacement succeeds.
    """
    job, part, owner = _job_paths(Path(target), work_dir)
    if not _owned_job(job, owner):
        return {'scratch_bytes': 0, 'output_bytes': 0, 'raw_checkpoint_present': False}
    if part.exists() and not part.is_file():
        raise SearchError(f'Search output part is not a regular file: {part}')
    return {'scratch_bytes': sum(_safe_path(job, name).stat().st_size
                                 for name in _EXTRACTION_FILES if _safe_path(job, name).exists()),
            'output_bytes': part.stat().st_size if part.exists() else 0,
            'raw_checkpoint_present': _safe_path(job, 'serialized.json').is_file()}


def _clear_extraction(job: Path) -> None:
    # Caller has verified the durable raw checkpoint and closed its connection.
    for name in _EXTRACTION_FILES:
        _safe_path(job, name).unlink(missing_ok=True)


def _clear_job(job: Path, part: Path) -> None:
    # The caller holds the job lock and has validated its exact ownership marker.
    # Never recursively delete the workspace: unrelated files remain untouched.
    from .safety import reject_symlinks
    reject_symlinks(part)
    for name in _JOB_FILES:
        _safe_path(job, name).unlink(missing_ok=True)
    part.unlink(missing_ok=True)


def _signature(path: Path) -> tuple:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _input_fingerprint(target: Path, assets: list[dict], notify: Callable) -> tuple[str, list]:
    from .safety import sha256_file
    inputs, signatures = [], []
    for number, asset in enumerate(assets, 1):
        path = _safe_path(target, asset['destination'])
        if not path.is_file():
            raise SearchError(f"Search input is not a regular file: {asset['destination']}")
        notify(f"INDEX VERIFY {number}/{len(assets)} {asset['destination']}", force=True)
        before = _signature(path)
        if asset.get('size_bytes') is not None and before[2] != asset['size_bytes']:
            raise SearchError(f'Search source size differs from verified inventory: {path}')
        digest = sha256_file(path)
        if before != _signature(path):
            raise SearchError(f'Search source changed while hashing: {path}')
        if asset.get('sha256') is not None and digest != asset['sha256']:
            raise SearchError(f'Search source checksum differs from verified inventory: {path}')
        signatures.append((path, before))
        inputs.append({'asset': asset, 'sha256': digest})
    dependencies = {}
    for name in ('pypdf', 'fonttools', 'libzim'):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    recipe = {'inputs': inputs, 'dependencies': dependencies,
              'python': list(sys.version_info[:3]), 'unicode': unicodedata.unidata_version,
              'extractor': sha256_file(Path(__file__)),
              'catalog_rules': sha256_file(Path(__file__).with_name('catalog.py')),
              'passage_chars': PASSAGE_CHARS, 'max_zim_item': MAX_ZIM_ITEM}
    return hashlib.sha256(_json(recipe)).hexdigest(), signatures


def _completed_report(target: Path, report_path: Path, fingerprint: str) -> dict | None:
    from .search_pack import verify_pack
    if not report_path.is_file():
        return None
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if not isinstance(report, dict) or report.get('build_fingerprint') != fingerprint:
            return None
        data = verify_pack(target, report)
        if len(data) < 12 or data[:8] != MAGIC:
            return None
        size = struct.unpack_from('<I', data, 8)[0]
        if size > HEADER_SIZE - 12:
            return None
        header = json.loads(data[12:12 + size])
        if (header.get('version') != 3 or report.get('format_version') != 3 or
                header.get('document_encoding') != 'zlib-json-v1' or
                header.get('postings_encoding') != 'delta-uvarint-v1' or
                header.get('size') != report['index_bytes'] or header.get('documents') != report['documents']):
            return None
        return report
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _ready_report(job: Path, part: Path, fingerprint: str) -> dict | None:
    """Verify a durable serialized checkpoint before trusting extraction cleanup."""
    from .safety import sha256_file
    marker = _safe_path(job, 'serialized.json')
    if not marker.is_file() or not part.is_file():
        return None
    try:
        saved = json.loads(marker.read_text(encoding='utf-8'))
        report = saved['report']
        if (saved.get('schema_version') != 1 or saved.get('fingerprint') != fingerprint or
                not isinstance(report, dict) or report.get('build_fingerprint') != fingerprint or
                report.get('format_version') != 3 or type(report.get('index_bytes')) is not int or
                part.stat().st_size != report['index_bytes'] or
                not isinstance(report.get('index_sha256'), str) or
                not re.fullmatch(r'[0-9a-f]{64}', report['index_sha256'])):
            return None
        with part.open('rb') as stream:
            data = stream.read(HEADER_SIZE)
        if len(data) != HEADER_SIZE or data[:8] != MAGIC:
            return None
        size = struct.unpack_from('<I', data, 8)[0]
        if size > HEADER_SIZE - 12:
            return None
        header = json.loads(data[12:12 + size])
        if (header.get('version') != 3 or header.get('document_encoding') != 'zlib-json-v1' or
                header.get('postings_encoding') != 'delta-uvarint-v1' or
                header.get('size') != report['index_bytes'] or header.get('documents') != report.get('documents') or
                sha256_file(part) != report['index_sha256']):
            return None
        return report
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _sync_directory(path: Path) -> bool:
    """Order directory updates where supported; never suppress real I/O faults."""
    from .safety import reject_symlinks
    reject_symlinks(path)
    if os.name == 'nt':
        # Python's portable os.open/fsync interface cannot sync a Windows
        # directory handle. Process-interruption recovery still works there.
        return False
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            unsupported = {errno.EINVAL, getattr(errno, 'ENOTSUP', errno.EINVAL),
                           getattr(errno, 'EOPNOTSUPP', errno.EINVAL)}
            if error.errno in unsupported:
                return False
            raise
        return True
    finally:
        os.close(descriptor)


def _save_ready(job: Path, part: Path, fingerprint: str, report: dict) -> bool:
    from .safety import atomic_write
    # The raw file itself was fsynced by serialization. Order its directory
    # entry before publishing the recovery marker in a possibly different FS.
    raw_synced = _sync_directory(part.parent)
    atomic_write(_safe_path(job, 'serialized.json'), _json({
        'schema_version': 1, 'fingerprint': fingerprint, 'report': report}) + b'\n')
    marker_synced = _sync_directory(job)
    return raw_synced and marker_synced


def _prepare_ui(report: dict) -> dict[str, bytes]:
    from .search_ui import render_search_page
    outputs = {'SEARCH.html': render_search_page().encode('utf-8'),
               'SEARCH/search.js': (Path(__file__).parent / 'templates/search.js').read_bytes()}
    for relative, data in outputs.items():
        report['file_integrity'][relative] = {'sha256': hashlib.sha256(data).hexdigest(),
                                            'size_bytes': len(data)}
    report['generated_files'] = sorted([*report['file_integrity'], 'SEARCH/coverage.json'])
    return outputs


def _publish_ui(target: Path, report: dict, outputs: dict[str, bytes] | None = None) -> None:
    from .safety import atomic_write
    for relative, data in (_prepare_ui(report) if outputs is None else outputs).items():
        atomic_write(_safe_path(target, relative), data)


def probe_completed_search(target: Path, assets: list[dict], *, progress: Callable | None = None) -> dict | None:
    """Read-only reuse proof for space planning, including every input and chunk.

    The builder must use the same inventory metadata as build_search. This probe
    grants no trust to an old completion flag: current extraction dependencies,
    source bytes/metadata and the entire logical index must match. Search checks
    them again after preflight before reusing the result.
    """
    target = Path(target)
    report_path = _safe_path(target, 'SEARCH/coverage.json')
    if not report_path.is_file():
        return None
    notify = lambda message, **_kwargs: progress(message) if progress is not None else None
    fingerprint, signatures = _input_fingerprint(target, sorted(assets, key=lambda a: a['destination']), notify)
    report = _completed_report(target, report_path, fingerprint)
    if report is None or any(signature != _signature(path) for path, signature in signatures):
        return None
    ui = _prepare_ui(report)
    coverage = _json(report) + b'\n'
    return {'generated_bytes': sum(item['size_bytes'] for item in report['file_integrity'].values()) + len(coverage),
            'rewrite_bytes': sum(map(len, ui.values())) + len(coverage),
            'index_bytes': report['index_bytes'], 'index_sha256': report['index_sha256']}


def probe_raw_checkpoint(target: Path, assets: list[dict], *, work_dir: Path | None = None,
                         progress: Callable | None = None) -> dict | None:
    """Verify raw staging and exact partial-package credit, without writing."""
    from .search_pack import probe_pack
    target = Path(target)
    job, part, owner = _job_paths(target, work_dir)
    if not _owned_job(job, owner) or not _safe_path(job, 'serialized.json').is_file():
        return None
    notify = lambda message, **_kwargs: progress(message) if progress is not None else None
    fingerprint, signatures = _input_fingerprint(target, sorted(assets, key=lambda a: a['destination']), notify)
    report = _ready_report(job, part, fingerprint)
    if report is None:
        return None
    package = probe_pack(target, part, report['index_sha256'])
    if any(signature != _signature(path) for path, signature in signatures):
        return None
    report.update(package['report'])
    ui = _prepare_ui(report)
    coverage = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
    rewrites = sum(map(len, ui.values())) + len(coverage)
    return {'index_bytes': report['index_bytes'], 'index_sha256': report['index_sha256'],
            'generated_bytes': report['transport_bytes'] + rewrites,
            'retained_transport_bytes': package['retained_transport_bytes'],
            'remaining_pack_allocation_bytes': package['remaining_bytes'] + rewrites}


def _database(path: Path) -> sqlite3.Connection:
    from .safety import reject_symlinks
    reject_symlinks(path)
    db = None
    try:
        db = sqlite3.connect(path)
        # DELETE/FULL is intentionally slower than disposable scratch mode: a
        # checkpoint must survive process termination and filesystem crashes.
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        # Every ordered query follows an existing primary key. No sort/temp table
        # is required; MEMORY forbids hidden large spills into the OS /tmp.
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA cache_size=-16384')
        db.execute('PRAGMA mmap_size=0')
        return db
    except BaseException as error:
        if db is not None:
            db.close()
        if isinstance(error, sqlite3.Error):
            raise SearchError(f'Cannot open search checkpoint database {path}: {error}') from error
        raise


def _save_checkpoint(db: sqlite3.Connection, records: BinaryIO, state: dict,
                     check_budget: Callable = lambda: None) -> None:
    from .safety import reject_symlinks
    reject_symlinks(Path(records.name))
    records.flush()
    os.fsync(records.fileno())
    check_budget()
    state['record_bytes'] = records.tell()
    db.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?)', (_json(state).decode('utf-8'),))
    db.commit()


class _BoundedIndexWriter:
    """Reject an individual raw-index write before it exceeds its allocation."""
    def __init__(self, handle: BinaryIO, maximum: int | None):
        self.handle, self.maximum = handle, maximum
        self.position = handle.tell()

    def write(self, data):
        if self.maximum is not None and self.position + len(data) > self.maximum:
            raise SearchError('Raw search index exceeds its serialization allowance; increase search_budget_bytes '
                              'and index_scratch_budget_bytes or reduce content, then rerun. Checkpoint retained.')
        count = self.handle.write(data)
        self.position += count
        return count

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = self.handle.seek(offset, whence)
        return self.position

    def __getattr__(self, name):
        return getattr(self.handle, name)


def _uvarint(value: int) -> bytes:
    if type(value) is not int or not 0 <= value < 2**32:
        raise SearchError('Posting value exceeds the unsigned 32-bit format limit')
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def _serialize_index(db: sqlite3.Connection, records: BinaryIO, part: Path,
                     report: dict, total_length: int, notify: Callable,
                     maximum: int | None = None, check_budget: Callable = lambda: None) -> None:
    # Serialization can be repeated from durable records/postings. Intermediate
    # lexicon rows are not extraction checkpoints and are always recreated.
    from .safety import reject_symlinks
    reject_symlinks(part)
    db.execute('DELETE FROM lexicon')
    db.execute('DELETE FROM lex_offsets')
    db.commit()
    with part.open('w+b') as handle:
        output = _BoundedIndexWriter(handle, maximum)
        records.seek(0)
        while block := records.read(1024 * 1024):
            check_budget()
            output.write(block)
        notify('INDEX writing document offsets', force=True)
        docs_offset = output.tell()
        for offset, size in db.execute('SELECT offset,size FROM docs ORDER BY id'):
            output.write(struct.pack('<QI', offset, size))
        flags_offset = output.tell()
        for (flags,) in db.execute('SELECT flags FROM docs ORDER BY id'):
            output.write(bytes([flags]))
        terms = 0
        previous = None
        posting_offset = count = 0
        previous_doc = 0
        postings_written = 0
        notify('INDEX writing sorted postings', force=True)
        for term, doc_id, tf, dl in db.execute('SELECT term,doc,tf,dl FROM postings ORDER BY term,doc'):
            if term != previous:
                if previous is not None:
                    db.execute('INSERT INTO lexicon VALUES (?,?,?,?,?)',
                               (terms, previous, posting_offset, count, output.tell() - posting_offset))
                    terms += 1
                previous, posting_offset, count = term, output.tell(), 0
                previous_doc = 0
            delta = doc_id - previous_doc
            if (count and delta <= 0) or tf <= 0 or dl <= 0:
                raise SearchError('Invalid sorted posting in extraction checkpoint')
            output.write(_uvarint(delta) + _uvarint(tf) + _uvarint(dl))
            previous_doc = doc_id
            count += 1
            postings_written += 1
            if postings_written % 100000 == 0:
                db.commit()
                notify(f'INDEX {postings_written:,} postings, {terms:,} terms written')
        if previous is not None:
            db.execute('INSERT INTO lexicon VALUES (?,?,?,?,?)',
                       (terms, previous, posting_offset, count, output.tell() - posting_offset))
            terms += 1
        db.commit()
        notify(f'INDEX writing lexicon ({terms:,} terms)', force=True)
        for term_id, term, offset, count, length in db.execute('SELECT * FROM lexicon ORDER BY id'):
            record = _json([term, offset, count, length])
            db.execute('INSERT INTO lex_offsets VALUES (?,?,?)', (term_id, output.tell(), len(record)))
            output.write(record)
            if term_id % 100000 == 0:
                db.commit()
                notify(f'INDEX {term_id:,}/{terms:,} lexicon terms written')
        db.commit()
        lexicon_offset = output.tell()
        for offset, size in db.execute('SELECT offset,size FROM lex_offsets ORDER BY id'):
            output.write(struct.pack('<QI', offset, size))
        header = {'version': 3, 'document_encoding': 'zlib-json-v1', 'postings_encoding': 'delta-uvarint-v1',
                  'documents': report['documents'], 'terms': terms,
                  'average_length': total_length / max(1, report['documents']),
                  'docs_offset': docs_offset, 'flags_offset': flags_offset,
                  'lexicon_offset': lexicon_offset,
                  'size': output.tell(), 'tokenizer': 'NFKC-lower-unicode-letter-number-v1',
                  'passage_characters': PASSAGE_CHARS}
        data = _json(header)
        if len(data) + 12 > HEADER_SIZE:
            raise SearchError('Index header exceeds reserved space')
        output.seek(0)
        output.write(MAGIC + struct.pack('<I', len(data)) + data)
        output.flush()
        os.fsync(output.fileno())


def build_search(target: Path, assets: list[dict], *, work_dir: Path | None = None,
                 progress: Callable[[str], None] | None = None,
                 search_budget_bytes: int | None = None,
                 index_scratch_budget_bytes: int | None = None,
                 reserve_bytes: int = 0, reuse_only: bool = False,
                 raw_reuse_only: bool = False) -> dict:
    """Build or resume full-text extraction and atomically replace the index.

    Durable extraction checkpoints cover at most 50 text-bearing units, or five
    seconds at any raw-unit boundary, including skipped archive entries. An
    interrupted plain text/HTML file restarts that file. After a verified durable
    serialized checkpoint, extraction files are reclaimed and packaging resumes
    from that raw index. Input bytes, metadata, and extractor versions determine
    reuse; budgets do not invalidate retained work.
    """
    from .catalog import learning_shelves
    from .runtime import file_lock
    from .safety import atomic_write, sha256_file
    check_extractors(assets)
    for name, value in (('search_budget_bytes', search_budget_bytes),
                        ('index_scratch_budget_bytes', index_scratch_budget_bytes), ('reserve_bytes', reserve_bytes)):
        if value is not None and (type(value) is not int or value < 0):
            raise SearchError(f'{name} must be a nonnegative integer')
    target = Path(target)
    assets = sorted(assets, key=lambda a: a['destination'])
    last_progress = time.monotonic()
    raw_limit = None if search_budget_bytes is None else (search_budget_bytes * 3 + 3) // 4
    monitor_workspace = False

    def check_budget() -> None:
        if monitor_workspace and index_scratch_budget_bytes is not None:
            usage = checkpoint_usage(target, work_dir=work_dir)
            extraction_limit = index_scratch_budget_bytes - (raw_limit or 0)
            if usage['scratch_bytes'] > extraction_limit:
                raise SearchError('Search extraction workspace exceeds index_scratch_budget_bytes; '
                                  'increase the allowance or reduce content and rerun. Checkpoint retained.')
        if reserve_bytes and target.exists() and shutil.disk_usage(target).free < reserve_bytes:
            raise SearchError('Search reached the drive free-space reserve; reconnect a drive with more space '
                              'or reduce content and rerun. Checkpoint retained.')

    def check_outputs(report: dict, coverage: bytes | None = None, ui: dict[str, bytes] | None = None) -> None:
        if search_budget_bytes is not None:
            total = sum(len(coverage) if name == 'SEARCH/coverage.json' and coverage is not None
                        else len(ui[name]) if ui is not None and name in ui
                        else _safe_path(target, name).stat().st_size for name in report['generated_files'])
            if total > search_budget_bytes:
                raise SearchError(f'Search outputs require {total:,} bytes, exceeding search_budget_bytes '
                                  f'({search_budget_bytes:,}); increase the allowance or reduce content and rerun.')
        check_budget()

    def notify(message: str, *, force: bool = False) -> None:
        nonlocal last_progress
        check_budget()
        now = time.monotonic()
        if progress is not None and (force or now - last_progress >= 5):
            progress(message)
            last_progress = now

    fingerprint, signatures = _input_fingerprint(target, assets, notify)
    directory = _safe_path(target, 'SEARCH')
    report_path = _safe_path(target, 'SEARCH/coverage.json')
    job, part, owner = _job_paths(target, work_dir)
    if not _owned_job(job, owner):
        if (job.exists() and any(job.iterdir())) or part.exists():
            raise SearchError(f'Refusing unowned search workspace/output: {job}')
        job.mkdir(parents=True, exist_ok=True)
        atomic_write(_safe_path(job, 'owner.json'), _json(owner))
    directory.mkdir(parents=True, exist_ok=True)

    def publish_report(report: dict) -> None:
        from .search_pack import publish_pack
        for path, signature in signatures:
            if signature != _signature(path):
                raise SearchError(f'Search source changed during extraction: {path}; rerun to invalidate its checkpoint')
        report.update(publish_pack(target, part, report['index_sha256'], notify=notify,
                                   max_bytes=search_budget_bytes))
        ui = _prepare_ui(report)
        coverage_data = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
        check_outputs(report, coverage_data, ui)
        _publish_ui(target, report, ui)
        atomic_write(report_path, coverage_data)

    def directory_sync_notice(supported: bool) -> None:
        if not supported:
            notify('INDEX DURABILITY NOTICE: directory sync is unavailable on this platform or filesystem. '
                   'Process-interruption resume remains supported; power-loss ordering of directory updates '
                   'is unconfirmed. Use safe eject; exFAT and USB hardware can still lose data after sudden removal.',
                   force=True)

    with file_lock(_safe_path(job, 'lock')):
        _owned_job(job, owner)
        if part.exists() and not part.is_file():
            raise SearchError(f'Search output part is not a regular file: {part}')
        reusable = _completed_report(target, report_path, fingerprint)
        if reusable is not None:
            ui = _prepare_ui(reusable)
            coverage_data = _json(reusable) + b'\n'
            check_outputs(reusable, coverage_data, ui)
            _publish_ui(target, reusable, ui)
            atomic_write(report_path, coverage_data)
            _clear_job(job, part)
            notify(f"INDEX REUSE: {reusable['documents']:,} verified passages", force=True)
            return reusable
        if reuse_only:
            raise SearchError('Verified search changed after space preflight; rerun to reserve replacement-index space. '
                              'No extraction was started.')
        ready = _ready_report(job, part, fingerprint)
        if ready is not None:
            if raw_limit is not None and ready['index_bytes'] > raw_limit:
                raise SearchError('Verified raw index exceeds its serialization allowance; increase search_budget_bytes and rerun.')
            notify(f"INDEX RAW REUSE: {ready['documents']:,} verified passages; completing local script packaging", force=True)
            raw_synced = _sync_directory(part.parent)
            marker_synced = _sync_directory(job)
            directory_sync_notice(raw_synced and marker_synced)
            _clear_extraction(job)
            publish_report(ready)
            _clear_job(job, part)
            notify(f"INDEX COMPLETE: {ready['documents']:,} passages; {ready['transport_bytes']:,} local script bytes", force=True)
            return ready
        if raw_reuse_only:
            raise SearchError('Verified raw checkpoint changed after space preflight; rerun to reserve extraction space. '
                              'No extraction was started.')
        db_path = _safe_path(job, 'build.sqlite3')
        records_path = _safe_path(job, 'records.bin')
        db = _database(db_path)
        success = False
        try:
            table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone()
            saved = db.execute('SELECT data FROM checkpoint WHERE id=1').fetchone() if table else None
            state = json.loads(saved[0]) if saved else None
            if state is not None and not isinstance(state, dict):
                raise SearchError(f'Invalid extraction checkpoint: {db_path}')
            if state is not None and state.get('fingerprint') != fingerprint:
                notify('INDEX inputs/extractor changed; replacing owned extraction checkpoint', force=True)
                state = None
            if state is None:
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
                report = {'format_version': 3, 'documents': 0, 'assets': [], 'warnings': [],
                          'generated_files': []}
                state = {'fingerprint': fingerprint, 'asset_index': 0, 'unit_cursor': 0,
                         'coverage': None, 'report': report, 'total_length': 0,
                         'record_bytes': HEADER_SIZE, 'extracted': False}
                with records_path.open('w+b') as records:
                    records.write(b'\0' * HEADER_SIZE)
                    _save_checkpoint(db, records, state, check_budget)
            else:
                if (any(type(state.get(key)) is not int or state[key] < 0
                        for key in ('asset_index', 'unit_cursor', 'total_length', 'record_bytes'))
                        or state['asset_index'] > len(assets)
                        or state['record_bytes'] < HEADER_SIZE
                        or not isinstance(state.get('report'), dict)
                        or type(state['report'].get('documents')) is not int
                        or not isinstance(state['report'].get('assets'), list)
                        or len(state['report']['assets']) != state['asset_index']
                        or (state.get('coverage') is not None and
                            not isinstance(state['coverage'], dict))
                        or (state['unit_cursor'] > 0 and state.get('coverage') is None)):
                    raise SearchError(f'Invalid extraction checkpoint: {db_path}')
                last = db.execute('SELECT id,offset,size FROM docs ORDER BY id DESC LIMIT 1').fetchone()
                if ((last[0] + 1 if last else 0) != state['report']['documents']
                        or (last[1] + last[2] if last else HEADER_SIZE) != state['record_bytes']):
                    raise SearchError(f'Extraction checkpoint does not match its records: {db_path}')
                notify(f"INDEX RESUME: {state['report']['documents']:,} checkpointed passages; "
                       f"asset {state['asset_index'] + 1}, unit {state['unit_cursor']}", force=True)
            if not records_path.is_file() or records_path.stat().st_size < state['record_bytes']:
                raise SearchError(f'Search checkpoint text is missing or truncated: {records_path}')
            report = state['report']
            with records_path.open('r+b') as records:
                records.truncate(state['record_bytes'])
                records.seek(state['record_bytes'])
                monitor_workspace = True
                check_budget()
                last_checkpoint = time.monotonic()
                units_since_checkpoint = 0
                for asset_index in range(state['asset_index'], len(assets)):
                    asset = assets[asset_index]
                    notify(f"INDEX {asset_index + 1}/{len(assets)} {asset['destination']}", force=True)
                    path = _safe_path(target, asset['destination'])
                    fmt = str(asset.get('format', path.suffix.lstrip('.'))).lower()
                    coverage = state['coverage'] or {
                        'id': asset.get('id', asset['destination']), 'destination': asset['destination'],
                        'status': 'full_text', 'passages': 0, 'text_units': 0, 'empty_units': 0,
                        'warning_count': 0, 'warnings': []}
                    state['coverage'] = coverage
                    shelves = learning_shelves(asset)
                    flags = ((TEXTBOOK_FLAG if 'textbooks' in shelves else 0) |
                             (ILLUSTRATED_GUIDE_FLAG if 'illustrated-guides' in shelves else 0))
                    resource_type = asset.get('resource_type', 'reference')
                    illustrated = bool(asset.get('illustrated', False))
                    base = {'title': asset.get('title', path.name), 'destination': asset['destination'],
                            'category': asset.get('category', ''),
                            'source': asset.get('publisher') or asset.get('source_url', ''),
                            'tags': ' '.join(asset.get('tags', [])),
                            'reader_required': fmt == 'zim' or bool(asset.get('reader_required', fmt == 'epub')),
                            'format': fmt, 'critical': bool(asset.get('critical', False)),
                            'resource_type': resource_type, 'illustrated': illustrated,
                            'resource_labels': ' '.join([resource_type, 'illustrated' if illustrated else '']).strip(),
                            'attribution': asset.get('attribution', ''), 'license': asset.get('license', '')}
                    units = _units(path, asset, coverage, state['unit_cursor'])
                    try:
                        for unit_id, metadata, chunks in units:
                            if metadata is not None:
                                coverage['text_units'] += 1
                                nonempty = False
                                for passage_number, passage in enumerate(_passages(chunks), 1):
                                    nonempty = True
                                    record = {**base, **metadata, 'text': passage, 'passage': passage_number}
                                    state['total_length'] += _add_record(db, records, record, report['documents'], flags)
                                    report['documents'] += 1
                                    coverage['passages'] += 1
                                    if report['documents'] % 1000 == 0:
                                        notify(f"INDEX {asset['destination']}: {coverage['passages']:,} passages; "
                                               f"{report['documents']:,} total; {records.tell():,} text bytes")
                                if not nonempty:
                                    coverage['empty_units'] += 1
                            state['unit_cursor'] = unit_id + 1
                            if metadata is not None:
                                units_since_checkpoint += 1
                            now = time.monotonic()
                            if units_since_checkpoint >= CHECKPOINT_UNITS or now - last_checkpoint >= CHECKPOINT_SECONDS:
                                _save_checkpoint(db, records, state, check_budget)
                                units_since_checkpoint = 0
                                last_checkpoint = now
                    finally:
                        units.close()
                    if coverage['empty_units']:
                        _warn(coverage, f"{coverage['empty_units']} text units have no extractable text; images/scans need visual reading (no OCR)")
                    if not coverage['passages']:
                        coverage['status'] = 'metadata_only'
                        reason = ('No extractable text' if fmt in TEXT_FORMATS else 'Binary format: searchable catalog metadata only')
                        _warn(coverage, reason)
                        record = {**base, 'text': asset.get('description', ''), 'metadata_only': True}
                        state['total_length'] += _add_record(db, records, record, report['documents'], flags)
                        report['documents'] += 1
                        coverage['passages'] = 1
                    elif coverage['warning_count']:
                        coverage['status'] = 'partial'
                    if coverage['status'] != 'full_text':
                        report['warnings'].append(f"{coverage['destination']}: {coverage['status']} ({coverage['warning_count']} notices)")
                    report['assets'].append(coverage)
                    state.update(asset_index=asset_index + 1, unit_cursor=0, coverage=None)
                    _save_checkpoint(db, records, state, check_budget)
                    units_since_checkpoint = 0
                    last_checkpoint = time.monotonic()
                    notify(f"INDEXED {asset['destination']}: {coverage['passages']:,} passages, "
                           f"{coverage['status']}, {coverage['warning_count']:,} notices", force=True)
                state['extracted'] = True
                _save_checkpoint(db, records, state, check_budget)
                _serialize_index(db, records, part, report, state['total_length'], notify,
                                 maximum=raw_limit, check_budget=check_budget)
            for path, signature in signatures:
                if signature != _signature(path):
                    raise SearchError(f'Search source changed during extraction: {path}; rerun to invalidate its checkpoint')
            report['build_fingerprint'] = fingerprint
            report['index_bytes'] = part.stat().st_size
            report['index_sha256'] = sha256_file(part)
            for path, signature in signatures:
                if signature != _signature(path):
                    raise SearchError(f'Search source changed while verifying raw index: {path}; rerun')
            # Raw output has been fsynced, hashed and checked against unchanged
            # source signatures. Publish its durable marker before any cleanup.
            directory_sync_notice(_save_ready(job, part, fingerprint, report))
            db.close()
            db = None
            monitor_workspace = False
            _clear_extraction(job)
            publish_report(report)
            success = True
        except sqlite3.Error as error:
            raise SearchError(f'Search checkpoint database failed: {error}. Check scratch space; '
                              f'verified sources and durable extraction checkpoints remain in {job}.') from error
        finally:
            if db is not None:
                db.close()
            if success:
                _clear_job(job, part)
        notify(f"INDEX COMPLETE: {report['documents']:,} passages; {report['transport_bytes']:,} local script bytes", force=True)
        return report
