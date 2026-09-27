"""Complete publisher ZIPs with exact, counted local-link attribute repairs.

The original ZIP remains pinned. Only declared href/src value spans may change;
all other HTML bytes and every other package member are preserved verbatim.
"""
from collections import Counter
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from urllib.parse import quote, urlsplit, urlunsplit

from ..archive import ZipSource
from ..safety import SafetyError, atomic_write, safe_path, validate_relative

MAX_ITEM = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
ATTRIBUTE = re.compile(r'''(?P<name>[A-Za-z_:][-\w.:]*)\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)''', re.S)


def validate_recipe(recipe, assets=None):
    selection = recipe.get('selection', {})
    members = selection.get('members')
    source_id = selection.get('source_asset_id')
    if (not isinstance(members, list) or not 0 < len(members) <= 20000
            or recipe.get('source_asset_ids') != [source_id]):
        raise SafetyError('Localized ZIP requires one source and a complete bounded member list')
    paths, ids, destinations, prefixes = set(), set(), set(), set()
    total = 0
    for member in members:
        if not isinstance(member, dict) or set(member) - {'asset_id', 'path', 'size_bytes', 'sha256', 'rewrites'}:
            raise SafetyError('Invalid localized ZIP member record')
        if not {'asset_id', 'path', 'size_bytes', 'sha256'} <= member.keys():
            raise SafetyError('Localized ZIP member needs original bytes and hash')
        validate_relative(member['path'])
        if member['path'].casefold() in paths or member['asset_id'] in ids:
            raise SafetyError('Duplicate localized ZIP member path or output ID')
        paths.add(member['path'].casefold()); ids.add(member['asset_id'])
        if (type(member['size_bytes']) is not int or not 0 <= member['size_bytes'] <= MAX_ITEM
                or not re.fullmatch('[a-f0-9]{64}', str(member['sha256']))):
            raise SafetyError('Localized ZIP member exceeds its pinned item bound')
        total += member['size_bytes']
        if assets is not None:
            if member['asset_id'] not in assets:
                raise SafetyError('Localized ZIP output template is missing')
            destination = assets[member['asset_id']]['destination']
            validate_relative(destination)
            if destination.casefold() in destinations:
                raise SafetyError('Localized ZIP output paths collide')
            destinations.add(destination.casefold())
            suffix = '/' + member['path']
            if not destination.endswith(suffix):
                raise SafetyError('Localized ZIP output paths must preserve package structure')
            prefixes.add(destination[:-len(suffix)])
    if ids != set(recipe.get('output_asset_ids', [])) or total > MAX_TOTAL:
        raise SafetyError('Localized ZIP output set or total byte bound differs')
    if len(prefixes) > 1:
        raise SafetyError('Localized ZIP outputs must share one package root')
    exact_paths = {m['path'] for m in members}
    for member in members:
        seen = set()
        for repair in member.get('rewrites', []):
            if (not isinstance(repair, dict) or set(repair) != {'attribute', 'from', 'target_member', 'expected_count'}
                    or repair['attribute'] not in {'href', 'src'} or not isinstance(repair['from'], str)
                    or not repair['from'].startswith('/') or repair['from'].startswith('//')
                    or repair['target_member'] not in exact_paths or type(repair['expected_count']) is not int
                    or not 0 < repair['expected_count'] <= 10000 or not member['path'].endswith(('.html', '.htm'))):
                raise SafetyError('Invalid counted local-link repair')
            key = repair['attribute'], repair['from']
            if key in seen: raise SafetyError('Duplicate local-link repair')
            seen.add(key)
        if assets is not None:
            # Relative links must resolve to the same package paths in output.
            by_path = {m['path']: assets[m['asset_id']]['destination'] for m in members}
            for repair in member.get('rewrites', []):
                relative = posixpath.relpath(repair['target_member'], posixpath.dirname(member['path']))
                actual = posixpath.normpath(posixpath.join(posixpath.dirname(by_path[member['path']]), relative))
                if actual != by_path[repair['target_member']]:
                    raise SafetyError('Localized ZIP output paths must preserve package structure')


def rewrite_html(data, member):
    repairs = {(r['attribute'], r['from']): r for r in member.get('rewrites', [])}
    if not repairs: return data
    if len(data) > MAX_ITEM: raise SafetyError('HTML exceeds localization bound')
    text = data.decode('utf-8', errors='strict')
    lines = [0] + [match.end() for match in re.finditer('\n', text)]
    replacements, counts = [], Counter()
    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            start = lines[self.getpos()[0] - 1] + self.getpos()[1]
            raw = self.get_starttag_text()
            found = Counter()
            for match in ATTRIBUTE.finditer(raw):
                key = match['name'].lower(), unescape(match['value'])
                if key not in repairs: continue
                repair = repairs[key]; parsed = urlsplit(repair['from'])
                relative = posixpath.relpath(repair['target_member'], posixpath.dirname(member['path']))
                target = urlunsplit(('', '', quote(relative, safe='/'), parsed.query, parsed.fragment))
                replacements.append((start + match.start('value'), start + match.end('value'), escape(target, quote=True)))
                counts[key] += 1; found[key] += 1
            actual = Counter((name, value) for name, value in attrs if (name, value) in repairs)
            if actual != found:
                raise SafetyError('Selected link is unquoted or has ambiguous HTML attribute syntax')
        handle_startendtag = handle_starttag
    parser = Parser(convert_charrefs=True); parser.feed(text); parser.close()
    if any(counts[key] != repair['expected_count'] for key, repair in repairs.items()):
        raise SafetyError('Publisher local-link count changed from the reviewed recipe')
    for start, end, replacement in reversed(replacements):
        text = text[:start] + replacement + text[end:]
    result = text.encode('utf-8')
    if len(result) > MAX_ITEM: raise SafetyError('Localized HTML exceeds its output bound')
    return result


def render(recipe, sources, assets, output_dir, *, output_writer=None):
    validate_recipe(recipe, assets)
    selection = recipe['selection']; source_id = selection['source_asset_id']
    outputs = {}; members = selection['members']
    with ZipSource(sources[source_id], assets[source_id]) as archive:
        if {m['path'] for m in members} != set(archive.entries):
            raise SafetyError('Localized output must preserve the complete publisher ZIP member set')
        for member in members:
            info = archive.entries[member['path']]
            if info.file_size != member['size_bytes']:
                raise SafetyError('Original ZIP member size changed')
            with archive.archive.open(info) as stream:
                data = stream.read(member['size_bytes'] + 1)
                if len(data) != member['size_bytes'] or stream.read(1):
                    raise SafetyError('Original ZIP member exceeded its pin')
            if hashlib.sha256(data).hexdigest() != member['sha256']:
                raise SafetyError('Original ZIP member SHA256 changed')
            data = rewrite_html(data, member)
            target = safe_path(output_dir, assets[member['asset_id']]['destination'])
            if output_writer is None: atomic_write(target, data)
            else: output_writer(target, data)
            outputs[member['asset_id']] = target
            archive.check_source()
    return outputs
