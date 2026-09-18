"""Propose source-pinned section maps from local publisher structure.

This importer does not assign topics or extract figures. Output is a reviewable
proposal; unverified locations remain whole-document fallbacks.
"""
from __future__ import annotations

import argparse
import codecs
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import re

import yaml

from .safety import atomic_write, reject_symlinks, safe_path, sha256_file

MAX_SECTIONS = 10_000
MAX_TITLE = 500
MAX_ANCHOR = 1024
MAX_WARNINGS = 20


class SectionImportError(ValueError):
    """The proposed section map cannot be tied to verified source bytes."""


def _warning(report: dict, message: str) -> None:
    report['warning_count'] += 1
    if len(report['warnings']) < MAX_WARNINGS:
        report['warnings'].append(message[:2048])


def _title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    return value if 0 < len(value) <= MAX_TITLE else None


def _anchor(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= MAX_ANCHOR
            and not any(ord(char) <= 32 or ord(char) == 127 for char in value))


def _signature(path: Path) -> tuple:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _pdf_diagnostics(report: dict):
    class Capture(logging.Handler):
        def emit(self, record):
            _warning(report, 'PDF parser: ' + record.getMessage())
    logger = logging.getLogger('pypdf')
    before = logger.handlers[:], logger.level, logger.propagate
    handler = Capture(logging.WARNING)
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.handlers, logger.level, logger.propagate = before
        handler.close()


def _pdf_structure(path: Path, report: dict) -> list[dict]:
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject

    rows = []
    with _pdf_diagnostics(report), path.open('rb') as stream:
        # Strict parsing prevents pypdf's lenient fallback of an invalid
        # destination to page one from becoming a fabricated section locator.
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted and not reader.decrypt(''):
            _warning(report, 'Encrypted PDF cannot be opened without a password; use the whole document.')
            return rows
        pages = len(reader.pages)
        report['physical_pages'] = pages
        stack = [(iter(reader.outline), None)]
        last_position = None
        while stack:
            iterator, parent = stack[-1]
            try:
                item = next(iterator)
            except StopIteration:
                stack.pop()
                last_position = parent
                continue
            if isinstance(item, list):
                if len(stack) >= 128:
                    raise SectionImportError('Publisher outline exceeds the supported depth of 128')
                stack.append((iter(item), last_position))
                continue
            if len(rows) >= MAX_SECTIONS:
                _warning(report, f'Publisher outline exceeds {MAX_SECTIONS:,} entries; remaining entries need review.')
                break
            position = len(rows) + 1
            title = _title(getattr(item, 'title', None))
            row = {'position': position, 'parent_position': parent, 'title': title,
                   'locator': None, 'reason': None}
            last_position = position
            if not title:
                row['reason'] = 'Empty or overlong publisher outline title'
            else:
                node = getattr(item, 'node', None)
                if not isinstance(node, dict):
                    row['reason'] = 'Original PDF destination cannot be inspected'
                elif '/A' in node:
                    action = node['/A']
                    action = action.get_object() if hasattr(action, 'get_object') else action
                    if not isinstance(action, dict) or action.get('/S') != '/GoTo':
                        row['reason'] = 'External or unsupported PDF outline action'
                    elif '/D' not in action:
                        row['reason'] = 'PDF outline action has no destination'
                elif '/Dest' not in node:
                    row['reason'] = 'PDF outline item has no destination'
                if row['reason'] is None and item.get('/Type') not in {
                        '/XYZ', '/Fit', '/FitH', '/FitV', '/FitR', '/FitB', '/FitBH', '/FitBV'}:
                    row['reason'] = 'Unsupported PDF destination fit type'
                if row['reason'] is None:
                    reference = getattr(item, 'page', None)
                    if not isinstance(reference, IndirectObject) or reference.pdf is not reader:
                        row['reason'] = 'PDF destination is not a local physical page reference'
                    else:
                        page_number = reader.get_destination_page_number(item)
                        if type(page_number) is not int or not 0 <= page_number < pages:
                            row['reason'] = 'PDF destination is outside the physical page tree'
                        else:
                            actual = reader.pages[page_number].indirect_reference
                            if (actual.idnum, actual.generation) != (reference.idnum, reference.generation):
                                row['reason'] = 'PDF destination page reference is ambiguous'
                            else:
                                row['locator'] = {'type': 'pdf-page', 'page': page_number + 1}
            rows.append(row)
    return rows


class _Headings(HTMLParser):
    """First streaming pass retains only bounded publisher heading metadata."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.heading = None
        self.parents = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template'}:
            if len(self.hidden) >= 128:
                raise SectionImportError('HTML hidden-element nesting exceeds 128 levels')
            self.hidden.append(tag)
            return
        if self.hidden:
            return
        if re.fullmatch('h[1-6]', tag):
            if self.heading is not None:
                self._finish('Nested or unterminated HTML heading')
            if len(self.rows) >= MAX_SECTIONS:
                raise SectionImportError(f'HTML exceeds {MAX_SECTIONS:,} headings; split or review its structure manually')
            level = int(tag[1])
            while self.parents and self.parents[-1][0] >= level:
                self.parents.pop()
            position = len(self.rows) + 1
            parent = self.parents[-1][1] if self.parents else None
            self.parents.append((level, position))
            self.heading = {'position': position, 'parent_position': parent,
                            'level': level, 'tag': tag, 'own': [value for key, value in attrs if key == 'id'],
                            'nested': [], 'parts': [], 'characters': 0}
        elif self.heading is not None:
            if tag == 'br':
                self.handle_data(' ')
            for key, value in attrs:
                if key == 'id':
                    if len(self.heading['nested']) >= 8:
                        self.heading['nested_overflow'] = True
                    else:
                        self.heading['nested'].append(value)

    def handle_endtag(self, tag):
        if self.hidden:
            if self.hidden[-1] == tag:
                self.hidden.pop()
            return
        if self.heading is not None and re.fullmatch('h[1-6]', tag):
            self._finish(None if self.heading['tag'] == tag else 'Mismatched HTML heading end tag')

    def handle_data(self, data):
        if self.heading is not None and not self.hidden:
            self.heading['characters'] += len(data)
            if self.heading['characters'] <= MAX_TITLE:
                self.heading['parts'].append(data)

    def _finish(self, reason):
        current, self.heading = self.heading, None
        title = _title(''.join(current['parts'])) if current['characters'] <= MAX_TITLE else None
        anchors = current['own'] or current['nested']
        if not title:
            reason = reason or 'Empty or overlong publisher heading title'
        anchor = anchors[0] if len(anchors) == 1 else None
        if current.get('nested_overflow') and not current['own']:
            anchor = None
        if not _anchor(anchor):
            reason = reason or 'Heading has no unambiguous existing element ID'
        self.rows.append({'position': current['position'], 'parent_position': current['parent_position'],
                          'title': title, 'locator': None, 'anchor': anchor, 'reason': reason})

    def finish(self):
        self.close()
        if self.heading is not None:
            self._finish('Unterminated HTML heading')


class _AnchorCounts(HTMLParser):
    def __init__(self, requested):
        super().__init__(convert_charrefs=True)
        self.counts = dict.fromkeys(requested, 0)

    def handle_starttag(self, tag, attrs):
        # Count requested IDs everywhere, including hidden elements: a duplicate
        # can prevent a fragment from selecting the intended visible heading.
        for key, value in attrs:
            if key == 'id' and value in self.counts:
                self.counts[value] += 1


def _parse_html(path: Path, parser: HTMLParser, encoding: str) -> None:
    decoder = codecs.getincrementaldecoder(encoding)(errors='strict')
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(64 * 1024), b''):
            parser.feed(decoder.decode(block))
            if len(parser.rawdata) > 1024 * 1024:
                raise SectionImportError('HTML has an unterminated token larger than 1 MiB')
        parser.feed(decoder.decode(b'', final=True))
    parser.close()


def _html_structure(path: Path, asset: dict, report: dict) -> list[dict]:
    headings = _Headings()
    encoding = asset.get('text_encoding', 'utf-8-sig')
    _parse_html(path, headings, encoding)
    headings.finish()
    counts = _AnchorCounts({row['anchor'] for row in headings.rows if _anchor(row['anchor'])})
    _parse_html(path, counts, encoding)
    for row in headings.rows:
        anchor = row.pop('anchor')
        if row['reason'] is None:
            if counts.counts[anchor] != 1:
                row['reason'] = 'Heading element ID is missing or duplicated elsewhere in the document'
            else:
                row['locator'] = {'type': 'html-anchor', 'id': anchor}
    return headings.rows


def import_sections(path: Path, asset: dict) -> tuple[dict, dict]:
    """Return a draft section map and a bounded review report, without writes.

    A checksum mismatch is a hard failure. A verified source with unreadable,
    absent, or ambiguous publisher structure produces warnings and a whole-file
    fallback. Valid children of an unlocated parent become explicitly warned
    top-level proposals; no parent page, topic, figure, or anchor is invented.
    """
    path = Path(path)
    reject_symlinks(path)
    if not path.is_file():
        raise SectionImportError(f'Section source is not a regular file: {path}')
    identity, expected = asset.get('id'), asset.get('sha256')
    if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', identity):
        raise SectionImportError('Section import requires a valid asset ID')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise SectionImportError('Section import requires a verified source SHA-256')
    before = _signature(path)
    if asset.get('size_bytes') is not None and before[2] != asset['size_bytes']:
        raise SectionImportError('Source size differs from its verified inventory')
    digest = sha256_file(path)
    if digest != expected:
        raise SectionImportError('Source SHA-256 differs from its verified inventory')
    report = {'schema_version': 1, 'asset_id': identity, 'source_sha256': digest,
              'review_required': True, 'warnings': [], 'warning_count': 0,
              'notes': ['No topic assignments or illustration labels were inferred.',
                        'PDF page numbers are one-based physical pages, including covers.']}
    fmt = str(asset.get('format', path.suffix.lstrip('.'))).lower()
    provenance = 'publisher-outline' if fmt == 'pdf' else 'publisher-heading'
    try:
        if fmt == 'pdf':
            structure = _pdf_structure(path, report)
        elif fmt in {'html', 'htm'}:
            structure = _html_structure(path, asset, report)
        else:
            _warning(report, f'{fmt or "Unknown format"}: publisher structure import supports PDF and HTML only.')
            structure = []
    except Exception as error:
        # Source-byte validation above is deliberately outside this fail-soft
        # extraction boundary. KeyboardInterrupt/SystemExit are not swallowed.
        _warning(report, f'Publisher structure could not be safely imported: {type(error).__name__}: {error}')
        structure = []
    if _signature(path) != before:
        raise SectionImportError('Source changed during section import; verify it and retry')
    sections, source_ids = [], {}
    prefix = 'outline' if fmt == 'pdf' else 'heading'
    for row in structure:
        position = row['position']
        if row['reason'] is not None:
            _warning(report, f'{prefix}-{position:04d}: {row["reason"]}; use the whole document.')
            continue
        section = {'id': f'{prefix}-{position:04d}', 'title': row['title'],
                   'locator': row['locator'], 'provenance': provenance}
        parent_position = row['parent_position']
        if parent_position is not None:
            if parent_position in source_ids:
                section['parent'] = source_ids[parent_position]
            else:
                _warning(report, f'{section["id"]}: publisher parent has no verified locator; '
                                'this child is a top-level proposal requiring hierarchy review.')
        sections.append(section)
        source_ids[position] = section['id']
    if not sections:
        _warning(report, 'No usable publisher sections were found; retain the whole-document link.')
    report.update(structure_sha256=hashlib.sha256(json.dumps(structure, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
                  imported_sections=len(sections), source_entries=len(structure),
                  fallback_required=bool(report['warning_count']) or not sections,
                  status=('whole-document-fallback' if not sections else
                          'partial-draft' if report['warning_count'] else 'draft'))
    return {'schema_version': 1, 'asset_id': identity, 'source_sha256': digest,
            'sections': sections}, report


def _local_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise SectionImportError(f'Refusing symlink: {path}')
    path = path.parent.resolve() / path.name
    reject_symlinks(path)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path, help='existing library containing the verified source file')
    parser.add_argument('--asset', required=True, help='asset ID in the inventory')
    parser.add_argument('--inventory', type=Path, help='default: TARGET/INVENTORY.json')
    parser.add_argument('--output', required=True, type=Path, help='new draft section-map YAML path')
    args = parser.parse_args(argv)
    try:
        target = _local_path(args.target)
        inventory_path = _local_path(args.inventory) if args.inventory else safe_path(target, 'INVENTORY.json')
        inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
        assets = inventory.get('assets') if isinstance(inventory, dict) else None
        if not isinstance(assets, list) or any(not isinstance(a, dict) for a in assets):
            raise SectionImportError('Inventory must contain an assets list')
        selected = [a for a in assets if a.get('id') == args.asset]
        if len(selected) != 1:
            raise SectionImportError(f'Inventory must identify asset {args.asset!r} exactly once')
        asset = selected[0]
        source = safe_path(target, asset.get('destination'))
        section_map, report = import_sections(source, asset)
        output = _local_path(args.output)
        review = _local_path(Path(str(output) + '.review.json'))
        if output in {source, inventory_path} or review in {source, inventory_path}:
            raise SectionImportError('Draft output must not replace a source file or inventory')
        artifacts = [(output, yaml.safe_dump(section_map, sort_keys=False, allow_unicode=True).encode('utf-8')),
                     (review, (json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))]
        # Repeating an identical import is safe; existing edits/assignments are
        # never replaced. Check both destinations before writing either artifact.
        for path, data in artifacts:
            if path.exists() and (not path.is_file() or path.read_bytes() != data):
                raise SectionImportError(f'Refusing to replace an existing file: {path}; choose a new output')
        for path, data in artifacts:
            if not path.exists():
                atomic_write(path, data)
        print(f'DRAFT: {output}')
        print(f'REVIEW: {review}')
        print(f"{report['status']}: {report['imported_sections']} sections; {report['warning_count']} warnings")
        return 0
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f'ERROR: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
