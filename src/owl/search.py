"""Build OWL's disk-backed, versioned full-text index.

The database is scratch space, never a runtime dependency. The portable index
contains JSON records, fixed-width offset tables, and sorted binary postings;
SEARCH.html reads only requested ranges with the browser File API.
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import time
import unicodedata
import zipfile
from collections import Counter
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import BinaryIO, Callable, Iterable, Iterator


MAGIC = b"OWLIDX1\n"
HEADER_SIZE = 4096
PASSAGE_CHARS = 8192
MAX_ZIM_ITEM = 64 * 1024 * 1024
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
    for chunk in chunks:
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


def _units(path: Path, asset: dict, coverage: dict) -> Iterator[tuple[dict, Iterable[str]]]:
    fmt = str(asset.get("format", path.suffix.lstrip("."))).lower()
    encoding = asset.get("text_encoding", "utf-8-sig")
    if fmt in {"html", "htm", "txt", "text", "md", "markdown"}:
        with path.open("rb") as stream:
            chunks = _decode_chunks(stream, encoding)
            yield {}, _html_chunks(chunks) if fmt in {"html", "htm"} else chunks
    elif fmt == "pdf":
        from pypdf import PdfReader
        with _capture_pdf_warnings(coverage), path.open("rb") as stream:
            pdf = PdfReader(stream)
            if pdf.is_encrypted and not pdf.decrypt(""):
                raise SearchError(f"Cannot extract encrypted PDF: {asset['destination']}")
            for page_number, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                yield {"page": page_number}, [text]
    elif fmt == "epub":
        with zipfile.ZipFile(path) as archive:
            # Never extract archive filenames onto the filesystem.
            for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
                suffix = Path(info.filename).suffix.lower()
                if not info.is_dir() and suffix in {".html", ".htm", ".xhtml", ".txt"}:
                    with archive.open(info) as stream:
                        chunks = _decode_chunks(stream, encoding)
                        yield {"entry": info.filename}, (chunks if suffix == ".txt" else _html_chunks(chunks))
    elif fmt == "zim":
        from libzim.reader import Archive, set_cluster_cache_max_size
        set_cluster_cache_max_size(2)
        archive = Archive(path)
        archive.dirent_cache_max_size = 4096
        if not hasattr(archive, "_get_entry_by_id"):
            raise SearchError("Unsupported libzim API: _get_entry_by_id is unavailable")
        # python-libzim's published reader.pyi provides this low-level iterator
        # primitive. Pin the compatible major version in the project's extras.
        for entry_id in range(archive.all_entry_count):
            entry = archive._get_entry_by_id(entry_id)
            if entry.is_redirect:
                continue  # Target text is indexed once.
            item = entry.get_item()
            mime = item.mimetype.split(";", 1)[0].lower()
            if mime not in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}:
                if mime == "application/pdf":
                    _warn(coverage, f"Embedded PDF needs its archive reader: {entry.path}")
                continue
            if item.size > MAX_ZIM_ITEM:
                _warn(coverage, f"Text entry exceeds 64 MiB extraction limit: {entry.path}")
                continue
            content = item.content
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            def chunks() -> Iterator[str]:
                for start in range(0, len(content), 65536):
                    yield decoder.decode(content[start:start + 65536])
                yield decoder.decode(b"", final=True)
            yield {"entry": entry.path, "title": entry.title}, (
                _html_chunks(chunks()) if "html" in mime else chunks())


def _add_record(db: sqlite3.Connection, output: BinaryIO, record: dict, doc_id: int) -> int:
    if doc_id >= 2**32:
        raise SearchError("Index exceeds version 1's 2^32 passage limit")
    data = _json(record)
    if len(data) > 1024 * 1024:
        raise SearchError("Search record exceeds 1 MiB: shorten catalog metadata")
    db.execute("INSERT INTO docs VALUES (?, ?, ?)", (doc_id, output.tell(), len(data)))
    output.write(data)
    counts = Counter(tokens(record["text"]))
    for key, weight in [("title", 5), ("category", 2), ("tags", 2),
                        ("destination", 1), ("source", 1), ("entry", 1)]:
        for token in tokens(str(record.get(key, ""))):
            counts[token] += weight
    length = max(1, sum(counts.values()))
    db.executemany("INSERT INTO postings VALUES (?, ?, ?, ?)",
                   ((term, doc_id, frequency, length) for term, frequency in counts.items()))
    return length


def build_search(target: Path, assets: list[dict], *, work_dir: Path | None = None,
                 progress: Callable[[str], None] | None = None) -> dict:
    """Index every extractable passage; failures are explicit in coverage.json.

    Missing extractor dependencies and corrupt documents fail the build. Empty
    PDF pages, oversized ZIM entries, and unsupported binary formats are reported
    in coverage rather than silently claiming full-text coverage.
    """
    check_extractors(assets)
    target = Path(target)
    directory = _safe_path(target, "SEARCH")
    directory.mkdir(parents=True, exist_ok=True)
    index_path = _safe_path(target, "SEARCH/library.owl")
    report_path = _safe_path(target, "SEARCH/coverage.json")
    page_path = _safe_path(target, "SEARCH.html")
    if work_dir is not None:
        work_dir = Path(work_dir)
        from .safety import reject_symlinks
        reject_symlinks(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    report = {"format_version": 1, "documents": 0, "assets": [], "warnings": [],
              "generated_files": ["SEARCH.html", "SEARCH/library.owl", "SEARCH/coverage.json"]}
    total_length = 0
    last_progress = time.monotonic()

    def notify(message: str, *, force: bool = False) -> None:
        nonlocal last_progress
        now = time.monotonic()
        if progress is not None and (force or now - last_progress >= 5):
            progress(message)
            last_progress = now

    with tempfile.TemporaryDirectory(prefix="owl-index-", dir=work_dir or directory) as scratch:
        db = sqlite3.connect(Path(scratch) / "build.sqlite3")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=FILE")
        db.execute("PRAGMA cache_size=-16384")
        db.execute("PRAGMA mmap_size=0")
        db.executescript("""
            CREATE TABLE docs (id INTEGER PRIMARY KEY, offset INTEGER, size INTEGER);
            CREATE TABLE postings (term TEXT, doc INTEGER, tf INTEGER, dl INTEGER,
                                   PRIMARY KEY (term,doc)) WITHOUT ROWID;
            CREATE TABLE lexicon (id INTEGER PRIMARY KEY, term TEXT, offset INTEGER, count INTEGER);
            CREATE TABLE lex_offsets (id INTEGER PRIMARY KEY, offset INTEGER, size INTEGER);
        """)
        # Keep output temporary on the destination filesystem for atomic replace.
        descriptor, temporary = tempfile.mkstemp(prefix=".library-", suffix=".part", dir=directory)
        try:
            with os.fdopen(descriptor, "w+b") as output:
                output.write(b"\0" * HEADER_SIZE)
                for asset_number, asset in enumerate(sorted(assets, key=lambda a: a["destination"]), 1):
                    notify(f"INDEX {asset_number}/{len(assets)} {asset['destination']}", force=True)
                    path = _safe_path(target, asset["destination"])
                    if not path.is_file():
                        raise SearchError(f"Search input is not a regular file: {asset['destination']}")
                    fmt = str(asset.get("format", path.suffix.lstrip("."))).lower()
                    coverage = {"id": asset.get("id", asset["destination"]),
                                "destination": asset["destination"], "status": "full_text",
                                "passages": 0, "text_units": 0, "empty_units": 0,
                                "warning_count": 0, "warnings": []}
                    base = {"title": asset.get("title", path.name),
                            "destination": asset["destination"], "category": asset.get("category", ""),
                            "source": asset.get("publisher") or asset.get("source_url", ""),
                            "tags": " ".join(asset.get("tags", [])),
                            "reader_required": bool(asset.get("reader_required", fmt in {"zim", "epub"})),
                            "format": fmt, "critical": bool(asset.get("critical", False))}
                    for metadata, chunks in _units(path, asset, coverage):
                        coverage["text_units"] += 1
                        nonempty = False
                        for passage_number, passage in enumerate(_passages(chunks), 1):
                            nonempty = True
                            record = {**base, **metadata, "text": passage, "passage": passage_number}
                            total_length += _add_record(db, output, record, report["documents"])
                            report["documents"] += 1
                            coverage["passages"] += 1
                            if report["documents"] % 1000 == 0:
                                db.commit()
                                notify(f"INDEX {asset['destination']}: {coverage['passages']:,} passages; "
                                       f"{report['documents']:,} total; {output.tell():,} text bytes")
                        if not nonempty:
                            coverage["empty_units"] += 1
                    if coverage["empty_units"]:
                        _warn(coverage, f"{coverage['empty_units']} text units have no extractable text; images/scans need visual reading (no OCR)")
                    if not coverage["passages"]:
                        coverage["status"] = "metadata_only"
                        reason = ("No extractable text" if fmt in TEXT_FORMATS else "Binary format: searchable catalog metadata only")
                        _warn(coverage, reason)
                        record = {**base, "text": asset.get("description", ""), "metadata_only": True}
                        total_length += _add_record(db, output, record, report["documents"])
                        report["documents"] += 1
                        coverage["passages"] = 1
                    elif coverage["warning_count"]:
                        coverage["status"] = "partial"
                    if coverage["status"] != "full_text":
                        report["warnings"].append(f"{coverage['destination']}: {coverage['status']} ({coverage['warning_count']} notices)")
                    report["assets"].append(coverage)
                    db.commit()
                    notify(f"INDEXED {asset['destination']}: {coverage['passages']:,} passages, "
                           f"{coverage['status']}, {coverage['warning_count']:,} notices", force=True)
                notify("INDEX writing document offsets", force=True)
                docs_offset = output.tell()
                for offset, size in db.execute("SELECT offset,size FROM docs ORDER BY id"):
                    output.write(struct.pack("<QI", offset, size))
                terms = 0
                previous = None
                posting_offset = count = 0
                postings_written = 0
                notify("INDEX writing sorted postings", force=True)
                for term, doc_id, tf, dl in db.execute("SELECT term,doc,tf,dl FROM postings ORDER BY term,doc"):
                    if term != previous:
                        if previous is not None:
                            db.execute("INSERT INTO lexicon VALUES (?,?,?,?)", (terms, previous, posting_offset, count))
                            terms += 1
                        previous, posting_offset, count = term, output.tell(), 0
                    output.write(struct.pack("<III", doc_id, tf, dl))
                    count += 1
                    postings_written += 1
                    if postings_written % 100000 == 0:
                        notify(f"INDEX {postings_written:,} postings, {terms:,} terms written")
                if previous is not None:
                    db.execute("INSERT INTO lexicon VALUES (?,?,?,?)", (terms, previous, posting_offset, count))
                    terms += 1
                db.commit()
                notify(f"INDEX writing lexicon ({terms:,} terms)", force=True)
                for term_id, term, offset, count in db.execute("SELECT * FROM lexicon ORDER BY id"):
                    record = _json([term, offset, count])
                    db.execute("INSERT INTO lex_offsets VALUES (?,?,?)", (term_id, output.tell(), len(record)))
                    output.write(record)
                    if term_id % 100000 == 0:
                        notify(f"INDEX {term_id:,}/{terms:,} lexicon terms written")
                lexicon_offset = output.tell()
                for offset, size in db.execute("SELECT offset,size FROM lex_offsets ORDER BY id"):
                    output.write(struct.pack("<QI", offset, size))
                header = {"version": 1, "documents": report["documents"], "terms": terms,
                          "average_length": total_length / max(1, report["documents"]),
                          "docs_offset": docs_offset, "lexicon_offset": lexicon_offset,
                          "size": output.tell(), "tokenizer": "NFKC-lower-unicode-letter-number-v1",
                          "passage_characters": PASSAGE_CHARS}
                data = _json(header)
                if len(data) + 12 > HEADER_SIZE:
                    raise SearchError("Index header exceeds reserved space")
                output.seek(0)
                output.write(MAGIC + struct.pack("<I", len(data)) + data)
                output.flush()
                os.fsync(output.fileno())
            _safe_path(target, "SEARCH/library.owl")
            os.replace(temporary, index_path)
            report["index_bytes"] = index_path.stat().st_size
        except sqlite3.Error as error:
            raise SearchError(f"Search scratch database failed: {error}. "
                              "Check available scratch space and rebuild; verified source files are reusable.") from error
        finally:
            db.close()
            if os.path.exists(temporary):
                os.unlink(temporary)
    from .safety import atomic_write
    atomic_write(page_path, (Path(__file__).parent / "templates" / "search.html").read_bytes())
    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    notify(f"INDEX COMPLETE: {report['documents']:,} passages; {report['index_bytes']:,} bytes", force=True)
    return report
