"""Bounded offline manual rendering from an exact, reviewed source archive.

The build requires mandoc, but never runs source code or a shell. A stable probe
and each pinned output detect renderer differences before publication.
"""
from __future__ import annotations

import hashlib
import gzip
import html
from html.parser import HTMLParser
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading

from ..download import verified
from ..safety import SafetyError, atomic_write, reject_symlinks, safe_path

MAX_INPUT = 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
PROBE = b'.Dd January 1, 2026\n.Dt OWL 1\n.Os\n.Sh NAME\n.Nm owl\n.Nd offline rendering probe\n.Sh DESCRIPTION\n.Pa /tmp/example\n.Xr owl 1\n'
CSS = ('body{max-width:70rem;margin:2rem auto;padding:0 1rem;font-family:system-ui,sans-serif;'
       'line-height:1.5;overflow-wrap:anywhere}table.head,table.foot{width:100%}'
       'td.head-rtitle,td.foot-os{text-align:right}td.head-vol{text-align:center}'
       '.Nd,.Bf,.Op{display:inline}.Pa,.Ad{font-style:italic}.Ms,.Bl-diag>dt{font-weight:bold}'
       'code.Nm,.Fl,.Cm,.Ic,code.In,.Fd,.Fn,.Cd{font-weight:bold;font-family:inherit}'
       'pre{overflow-x:auto;white-space:pre-wrap}table{max-width:100%}'
       'table.Nm td:first-child{white-space:nowrap;vertical-align:top}'
       'dt{margin-top:.7rem}dd{margin-left:2rem}.edition{padding:1rem;background:#eef4ef}'
       'a{overflow-wrap:anywhere}.unbundled{border-bottom:1px dotted #666}')


class _BoundedArchive:
    """Cap decompressed bytes before tarfile parses hidden PAX/GNU headers."""
    def __init__(self, source):
        self.source, self.read_bytes = source, 0

    def read(self, size=-1):
        if size < 0:
            raise SafetyError('Unbounded manual archive read is not permitted')
        remaining = MAX_ARCHIVE_BYTES - self.read_bytes
        data = self.source.read(min(size, remaining + 1))
        if len(data) > remaining:
            raise SafetyError('Manual archive exceeds its decompressed-byte bound, including TAR metadata')
        self.read_bytes += len(data)
        return data


@contextmanager
def _archive_stream(path):
    # Only the reviewed plain/gzip TAR interface is supported. Letting tarfile
    # decompress internally would bypass this limit for PAX/long-name headers.
    with path.open('rb') as raw:
        magic = raw.read(6)
        raw.seek(0)
        if magic.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=raw, mode='rb') as decompressed:
                yield _BoundedArchive(decompressed)
        elif magic.startswith((b'BZh', b'\xfd7zXZ')):
            raise SafetyError('Manual rendering supports only plain or gzip TAR archives')
        else:
            yield _BoundedArchive(raw)


def _mandoc(data: bytes, edition: str) -> bytes:
    if len(data) > MAX_INPUT:
        raise SafetyError('Manual source exceeds the 1 MiB rendering bound')
    executable = shutil.which('mandoc')
    if not executable:
        raise SafetyError('This pinned manual edition requires mandoc on PATH before acquisition')
    command = [executable, '-T', 'html', '-O', 'fragment,man=%N.%S.html',
               '-I', 'os=' + edition, '-K', 'utf-8']
    with tempfile.TemporaryFile() as source:
        source.write(data)
        source.seek(0)
        process = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'}, close_fds=True)
        buffers = [bytearray(), bytearray()]
        overflow = threading.Event()
        def drain(pipe, index, limit):
            while chunk := pipe.read(8192):
                if len(buffers[index]) + len(chunk) > limit:
                    overflow.set()
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    break
                buffers[index].extend(chunk)
            pipe.close()
        threads = [threading.Thread(target=drain, args=(process.stdout, 0, MAX_OUTPUT)),
                   threading.Thread(target=drain, args=(process.stderr, 1, 8192))]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise SafetyError('mandoc exceeded the 10 second per-manual limit') from error
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            for thread in threads:
                thread.join()
        if overflow.is_set():
            raise SafetyError('mandoc exceeded its bounded output allowance')
        if process.returncode or buffers[1]:
            detail = buffers[1].decode('utf-8', errors='replace')[:512]
            raise SafetyError(f'mandoc could not faithfully render the manual: {detail}')
        return bytes(buffers[0])


def preflight(recipe: dict) -> str:
    selection = recipe['selection']
    edition = selection.get('edition')
    if not isinstance(edition, str) or not edition or '\n' in edition:
        raise SafetyError('Manual recipe needs an explicit one-line edition')
    digest = hashlib.sha256(_mandoc(PROBE, edition)).hexdigest()
    if digest != selection.get('renderer_probe_sha256'):
        raise SafetyError('mandoc renderer differs from the reviewed probe; review a new recipe/version before building')
    return digest


class _Links(HTMLParser):
    """Preserve mandoc HTML verbatim except links to absent manuals."""
    def __init__(self, value: str, selected: set[str], section_links: dict | None = None):
        super().__init__(convert_charrefs=False)
        self.output, self.missing, self.selected, self.anchor_stack = [], set(), selected, []
        self.section_links, self.section_counts = section_links or {}, {}
        self.feed(value)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        href = attrs_dict.get('href', '')
        if re.match(r'(?i)\s*(?:javascript|data|vbscript):', href):
            raise SafetyError('Unexpected active URL in rendered manual')
        if tag == 'a':
            absent = bool(re.fullmatch(r'[a-zA-Z0-9_.+-]+\.[1-9][a-z]*\.html', href) and href not in self.selected)
            self.anchor_stack.append(absent)
            if href in self.section_links:
                self.section_counts[href] = self.section_counts.get(href, 0) + 1
                target = self.section_links[href]['target']
                self.output.append('<a' + ''.join(' ' + k + '="' + html.escape(target if k == 'href' else v, quote=True) + '"' for k,v in attrs) + '>')
                return
            if absent:
                self.missing.add(href.removesuffix('.html'))
                self.output.append('<span class="unbundled" title="Referenced manual is not included in this edition">')
                return
        if tag in {'script', 'iframe', 'object', 'img', 'link'} or any(k.startswith('on') for k, _ in attrs):
            raise SafetyError('Unexpected active content or media in rendered manual')
        self.output.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor_stack.pop():
            self.output.append('</span>')
        else:
            self.output.append('</' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        if tag not in {'br', 'hr'}:
            raise SafetyError('Unexpected self-closing element in rendered manual')
        self.output.append(self.get_starttag_text())

    def handle_data(self, data): self.output.append(data)
    def handle_entityref(self, name): self.output.append('&' + name + ';')
    def handle_charref(self, name): self.output.append('&#' + name + ';')
    def handle_comment(self, data): self.output.append('<!--' + data + '-->')


def render(recipe: dict, sources: dict[str, Path], assets: dict[str, dict], output_dir: Path, *, output_writer=None) -> dict[str, Path]:
    preflight(recipe)
    selection = recipe['selection']
    source_id = selection['source_asset_id']
    source = assets[source_id]
    archive = sources[source_id]
    reject_symlinks(archive)
    if source['size_bytes'] > MAX_ARCHIVE_BYTES:
        raise SafetyError('Manual source archive exceeds its compressed-size bound')
    if not verified(archive, source['size_bytes'], source['sha256']):
        raise SafetyError('Manual source archive hash/size mismatch')
    manuals, notice = selection['manuals'], selection['notice']
    members = {m['member'] for m in manuals} | {notice['member']}
    ids = [i for m in manuals for i in (m['html_asset_id'], m['source_asset_id'])] + [notice['asset_id']]
    if len(ids) != len(set(ids)) or set(ids) != set(recipe['output_asset_ids']):
        raise SafetyError('Manual recipe has duplicate or incomplete output IDs')
    if len(members) != len(manuals) + 1 or not 1 <= len(manuals) <= 100:
        raise SafetyError('Manual recipe has duplicate members or exceeds its selection bound')
    parents = {PurePosixPath(assets[i]['destination']).parent for i in ids}
    if len(parents) != 1:
        raise SafetyError('Manual edition and source/notice companions must share one output directory')
    payloads, seen, expanded = {}, set(), 0
    with _archive_stream(archive) as stream, tarfile.open(fileobj=stream, mode='r|') as tar:
        for index, member in enumerate(tar):
            path = PurePosixPath(member.name)
            if (index >= 10000 or path.is_absolute() or '..' in path.parts or '\\' in member.name
                    or member.name in seen or not (member.isfile() or member.isdir())):
                raise SafetyError('Unsafe, duplicate, or unsupported manual archive member')
            seen.add(member.name)
            expanded += member.size
            if expanded > MAX_ARCHIVE_BYTES:
                raise SafetyError('Manual source archive exceeds its expanded-size bound')
            if member.name in members:
                if not member.isfile() or member.size > MAX_INPUT:
                    raise SafetyError('Selected manual archive member is not a bounded regular file')
                payloads[member.name] = tar.extractfile(member).read(MAX_INPUT + 1)
    if set(payloads) != members:
        raise SafetyError('Pinned manual archive lacks a selected source or notice')
    reject_symlinks(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    def put(identity, value):
        path = safe_path(output_dir, identity + '.' + assets[identity]['format'])
        (output_writer or atomic_write)(path, value)
        result[identity] = path
    notice_bytes = payloads[notice['member']]
    if hashlib.sha256(notice_bytes).hexdigest() != notice['sha256']:
        raise SafetyError('Manual license member hash mismatch')
    put(notice['asset_id'], notice_bytes)
    selected = {PurePosixPath(assets[m['html_asset_id']]['destination']).name for m in manuals}
    fragments = {}
    for manual in manuals:
        raw = payloads[manual['member']]
        if hashlib.sha256(raw).hexdigest() != manual['sha256']:
            raise SafetyError('Manual source member hash mismatch')
        if re.search(rb"^[.'](?:so|mso|sy|pso|open|opena|pi)(?:\s|$)", raw, re.M):
            raise SafetyError('Manual source includes an unsupported external-file or command directive')
        put(manual['source_asset_id'], raw)
        fragments[manual['html_asset_id']] = _mandoc(raw, selection['edition']).decode('utf-8')
    names = {PurePosixPath(assets[identity]['destination']).name: body for identity,body in fragments.items()}
    for manual in manuals:
        section_links = manual.get('section_links',{})
        for spec in section_links.values():
            target, _, anchor = spec['target'].partition('#')
            if target not in names or not anchor or ('id="' + anchor + '"') not in names[target]:
                raise SafetyError('Manual section link points to a missing pinned target')
        fragment = _Links(fragments[manual['html_asset_id']], selected, section_links)
        if fragment.section_counts != {key:spec['expected_count'] for key,spec in section_links.items()}:
            raise SafetyError('Manual section-link occurrence count changed')
        title = assets[manual['html_asset_id']]['title']
        source_name = PurePosixPath(assets[manual['source_asset_id']]['destination']).name
        notice_name = PurePosixPath(assets[notice['asset_id']]['destination']).name
        archive_link = os.path.relpath(source['destination'], str(next(iter(parents)))).replace(os.sep, '/')
        missing = ', '.join(sorted(fragment.missing)) or 'None'
        page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>' + html.escape(title) + '</title><style>' + CSS + '</style></head><body>'
                '<header class="edition"><strong>' + html.escape(selection['edition']) + '</strong>'
                '<p>Complete manual from the original portable release. This is not an OpenBSD 7.9 manual. '
                'Platform-specific paths and build options may differ.</p><nav>'
                '<a href="' + html.escape(source_name) + '">Original roff and per-file notices</a> · '
                '<a href="' + html.escape(notice_name) + '">Release license</a> · '
                '<a href="' + html.escape(archive_link) + '">Complete source archive</a></nav></header>'
                + ''.join(fragment.output) + '<footer><p>Referenced manuals outside this portable release: '
                + html.escape(missing) + '. Their names are preserved, with no broken local links.</p>'
                '<p>Rendered by OWL mdoc adapter v1 from the pinned publisher archive; original authorship '
                'and per-file notices remain in the linked unmodified source.</p></footer></body></html>\n')
        put(manual['html_asset_id'], page.encode('utf-8'))
    return result
