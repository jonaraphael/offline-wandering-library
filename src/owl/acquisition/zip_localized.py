"""Complete publisher ZIPs with exact, counted local-link attribute repairs.

The original ZIP remains pinned. Only declared href/src value spans may change;
a declared fixed stylesheet append may also repair index layout. All remaining
bytes and every other package member are preserved verbatim.
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
from ..download import verified
from ..safety import SafetyError, atomic_write, safe_path, validate_relative

MAX_ITEM = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
STYLESHEET_PATCHES = {'sqlite-responsive-v1': b'\n/* OWL: responsive presentation; preserve all code, tables and diagram data. */\nbody { overflow-wrap: anywhere; }\npre, .codeblock { max-width: 100%; box-sizing: border-box; overflow: auto; }\ntable { display: block; max-width: 100%; overflow: auto; }\nimg, svg { max-width: 100%; height: auto; }\n', 'python-responsive-v2': b'\n/* OWL responsive index and diagrams; all source text and SVG data retained. */\ntable.indextable { table-layout: fixed; width: 100%; }\ntable.indextable td, table.indextable a { overflow-wrap: anywhere; }\ndiv.graphviz { max-width: 100%; overflow: auto; }\nsvg { max-width: 100%; height: auto; }\n', 'python-index-wrap-v1': b'\n/* OWL Python index layout v1: preserve long symbol names at narrow widths. */\ntable.indextable { table-layout: fixed; width: 100%; }\ntable.indextable td, table.indextable a { overflow-wrap: anywhere; }\n'}
STYLESHEET_PATCHES['sqlite-responsive-v2'] = STYLESHEET_PATCHES['sqlite-responsive-v1'] + (
    b'.fancy .codeblock, .fancy .codeblock pre { display: block; }\n'
    b'div.columns > ul li, div.columns > ul li a { white-space: normal; }\n'
    b'dt { max-width: 100%; overflow: auto; }\n'
    b'@media (max-width: 600px) { .fancy img { margin-left: 0 !important; margin-right: 0 !important; } }\n')
STYLESHEET_TARGETS = {key: '/sqlite.css' if key.startswith('sqlite-') else '/_static/pydoctheme.css' for key in STYLESHEET_PATCHES}
REFERENCE_ANNOTATIONS = {'sqlite-obsolete-asyncvfs-v1': ("/docs.html", "<a class='sh_link' href='asyncvfs.html'>Asynchronous IO Mode</a>", "<span class='sh_link'>Asynchronous IO Mode (obsolete; not included in this edition)</span>")}
REFERENCE_ANNOTATIONS['sqlite-press-release-title-v1'] = (
    '/pressrelease-20071212.html', '<html>\n<body bgcolor="white">',
    '<html>\n<head><title>SQLite Consortium Launches With Mozilla And Symbian As Charter Members</title></head>\n<body bgcolor="white">')
ATTRIBUTE = re.compile(r'''(?P<name>[A-Za-z_:][-\w.:]*)\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)''', re.S)


def validate_recipe(recipe, assets=None):
    selection = recipe.get('selection', {})
    members = selection.get('members')
    source_id = selection.get('source_asset_id')
    dependencies = selection.get('dependencies', {})
    additional = selection.get('additional_source_ids', [])
    if (not isinstance(additional, list) or len(additional)>20 or any(not isinstance(i,str) for i in additional)
            or len(set(additional))!=len(additional) or source_id in additional):
        raise SafetyError('Invalid additional document source list')
    if (not isinstance(dependencies, dict) or len(dependencies) > 20
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in dependencies.items())
            or len(set(dependencies.values())) != len(dependencies)):
        raise SafetyError('Localized ZIP requires bounded unique supporting dependencies')
    if (not isinstance(members, list) or not 0 < len(members) <= 20000
            or not isinstance(recipe.get('source_asset_ids'), list)
            or recipe['source_asset_ids'][:1] != [source_id]
            or len(recipe['source_asset_ids']) != len(dependencies) + len(additional) + 1
            or set(recipe['source_asset_ids']) != {source_id, *dependencies.values(), *additional}):
        raise SafetyError('Localized ZIP requires one source and a complete bounded member list')
    paths, ids, destinations, prefixes = set(), set(), set(), set()
    total = 0
    for member in members:
        if not isinstance(member, dict) or set(member) - {'asset_id', 'path', 'size_bytes', 'sha256', 'rewrites', 'stylesheet_patch', 'runtime_patch', 'source_asset_id', 'reference_annotation'}:
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
        origin = member.get('source_asset_id')
        if origin is not None and origin not in additional:
            raise SafetyError('Supplemental member source is not explicitly declared')
        if origin and assets is not None and any(assets.get(origin,{}).get(k)!=member[k] for k in ('size_bytes','sha256')):
            raise SafetyError('Supplemental document differs from original captured pins')
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
    if {m.get('source_asset_id') for m in members if m.get('source_asset_id')} != set(additional):
        raise SafetyError('Additional sources must each preserve a declared supplemental document')
    exact_paths = {m['path'] for m in members}
    for path, identity in dependencies.items():
        validate_relative(path)
        if path.casefold() in paths or identity in ids or identity == source_id or identity in additional:
            raise SafetyError('Localized ZIP supporting dependency collides with package')
        paths.add(path.casefold())
        if assets is not None:
            asset = assets.get(identity, {})
            if (asset.get('supporting_file') is not True or asset.get('destination') != next(iter(prefixes)) + '/' + path
                    or type(asset.get('size_bytes')) is not int or not 0 < asset['size_bytes'] <= MAX_ITEM
                    or not re.fullmatch('[a-f0-9]{64}', str(asset.get('sha256')))):
                raise SafetyError('Localized ZIP supporting dependency needs exact pins and package destination')
    exact_paths.update(dependencies)
    for member in members:
        from .python_manual import validate_runtime
        validate_runtime(member)
        annotation=member.get('reference_annotation')
        if annotation is not None and (not isinstance(annotation,str) or annotation not in REFERENCE_ANNOTATIONS
                or not member['path'].endswith(REFERENCE_ANNOTATIONS[annotation][0])):
            raise SafetyError('Invalid source-bound optional-reference annotation')
        patch = member.get('stylesheet_patch')
        if patch is not None and (not isinstance(patch, str) or patch not in STYLESHEET_PATCHES
                or not member['path'].endswith(STYLESHEET_TARGETS[patch]) or member.get('rewrites')):
            raise SafetyError('Invalid fixed publisher stylesheet patch')
        seen = set()
        for repair in member.get('rewrites', []):
            if (not isinstance(repair, dict) or set(repair) - {'attribute', 'from', 'target_member', 'expected_count', 'target_fragment'}
                    or not {'attribute', 'from', 'target_member', 'expected_count'} <= repair.keys()
                    or repair['attribute'] not in {'href', 'src'} or not isinstance(repair['from'], str)
                    or not repair['from'] or repair['from'].startswith('//')
                    or urlsplit(repair['from']).scheme not in {'', 'https'}
                    or repair['target_member'] not in exact_paths or type(repair['expected_count']) is not int
                    or not 0 < repair['expected_count'] <= 10000 or not member['path'].endswith(('.html', '.htm'))):
                raise SafetyError('Invalid counted local-link repair')
            if 'target_fragment' in repair and (not isinstance(repair['target_fragment'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', repair['target_fragment'])):
                raise SafetyError('Invalid explicit local-link fragment')
            key = repair['attribute'], repair['from']
            if key in seen: raise SafetyError('Duplicate local-link repair')
            seen.add(key)
        if assets is not None:
            # Relative links must resolve to the same package paths in output.
            by_path = {m['path']: assets[m['asset_id']]['destination'] for m in members}
            by_path.update({path: assets[identity]['destination'] for path, identity in dependencies.items()})
            for repair in member.get('rewrites', []):
                relative = posixpath.relpath(repair['target_member'], posixpath.dirname(member['path']))
                actual = posixpath.normpath(posixpath.join(posixpath.dirname(by_path[member['path']]), relative))
                if actual != by_path[repair['target_member']]:
                    raise SafetyError('Localized ZIP output paths must preserve package structure')


def rewrite_member(data, member, auxiliary=None):
    from .python_manual import repair as runtime_repair
    data = runtime_repair(data, member, auxiliary or {})
    annotation=member.get('reference_annotation')
    if annotation is not None:
        if not isinstance(annotation,str) or annotation not in REFERENCE_ANNOTATIONS or not member['path'].endswith(REFERENCE_ANNOTATIONS[annotation][0]):
            raise SafetyError('Invalid source-bound optional-reference annotation')
        _,before,after=REFERENCE_ANNOTATIONS[annotation];text=data.decode('utf-8')
        if text.count(before)!=1:raise SafetyError('Optional-reference annotation source span changed')
        data=text.replace(before,after).encode('utf-8')
    if len(data) > MAX_ITEM: raise SafetyError('Repaired runtime exceeds its output bound')
    repairs = {(r['attribute'], r['from']): r for r in member.get('rewrites', [])}
    patch = member.get('stylesheet_patch')
    if patch is not None:
        if not isinstance(patch, str) or patch not in STYLESHEET_PATCHES or not member['path'].endswith(STYLESHEET_TARGETS[patch]) or repairs:
            raise SafetyError('Invalid fixed publisher stylesheet patch')
        addition = STYLESHEET_PATCHES[patch]
        if addition in data: raise SafetyError('Publisher stylesheet already contains this layout patch')
        result = data + addition
        if len(result) > MAX_ITEM: raise SafetyError('Patched stylesheet exceeds its output bound')
        return result
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
                target = urlunsplit(('', '', quote(relative, safe='/'), parsed.query, repair.get('target_fragment', parsed.fragment)))
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
    for identity in selection.get('dependencies', {}).values():
        if identity not in sources or not verified(sources[identity], assets[identity]['size_bytes'], assets[identity]['sha256']):
            raise SafetyError('Localized ZIP supporting dependency changed or is missing')
    with ZipSource(sources[source_id], assets[source_id]) as archive:
        if {m['path'] for m in members if not m.get('source_asset_id')} != set(archive.entries):
            raise SafetyError('Localized output must preserve the complete publisher ZIP member set')
        from .python_manual import auxiliary as runtime_inputs
        inputs = runtime_inputs(archive, members)
        for member in members:
            origin = member.get('source_asset_id')
            if origin:
                if origin not in sources or not verified(sources[origin], member['size_bytes'], member['sha256']):
                    raise SafetyError('Supplemental document source changed')
                stream = Path(sources[origin]).open('rb')
            else:
                info = archive.entries[member['path']]
                if info.file_size != member['size_bytes']:
                    raise SafetyError('Original ZIP member size changed')
                stream = archive.archive.open(info)
            with stream:
                data = stream.read(member['size_bytes'] + 1)
                if len(data) != member['size_bytes'] or stream.read(1):
                    raise SafetyError('Original ZIP member exceeded its pin')
            if hashlib.sha256(data).hexdigest() != member['sha256']:
                raise SafetyError('Original ZIP member SHA256 changed')
            data = rewrite_member(data, member, inputs)
            target = safe_path(output_dir, assets[member['asset_id']]['destination'])
            if output_writer is None: atomic_write(target, data)
            else: output_writer(target, data)
            outputs[member['asset_id']] = target
            archive.check_source()
    return outputs
