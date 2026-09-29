"""Pinned complete OCW package rendering; original videos stay streaming inputs.

Every ZIP member has its own reviewed pin and portable destination. Inspection
and rendering share the same transformations. Inspection never admits content;
rendering refuses unresolved active/local dependencies before writing outputs.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from ..archive import ZipSource, MAX_EXPLICIT_PACKAGE_BYTES, MAX_ITEM_BYTES
from ..safety import SafetyError, atomic_write, safe_path, validate_relative
from .corpus import verify_sources, check_source_identities
from .ocw_html import localize_html, localize_css, _media_key
from .ocw_runtime import localize_runtime, MEMBER, POLICY, SOURCE_SHA256

VERSION = 1
MAX_ISSUES = 20000


class _VideoURLs(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.urls = set(); self.feed(text); self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'video':
            self.urls.add(_media_key(dict(attrs).get('data-downloadlink', '')))


def portable_member_path(name):
    """Preserve normal publisher paths; shorten only nonportable components."""
    parts = []
    for part in name.split('/'):
        try:
            validate_relative(part)
            portable = len(part) <= 100
        except (ValueError, SafetyError):
            portable = False
        if not portable:
            suffix = PurePosixPath(part).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
                suffix = ''
            part = 'member-' + hashlib.sha256(part.encode()).hexdigest()[:32] + suffix
        parts.append(part)
    result = '/'.join(parts)
    # The final catalog prefix also consumes the portable 240-character path
    # limit. Long course navigation paths get a stable flat member name; every
    # relative link is rewritten through the complete member destination map.
    if len(result) > 150:
        suffix = PurePosixPath(result).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
            suffix = ''
        result = 'members/' + hashlib.sha256(name.encode()).hexdigest() + suffix
    validate_relative(result)
    return result


def _layout(recipe, assets):
    selection = recipe['selection']
    if selection.get('transformation_version') != VERSION:
        raise SafetyError('OCW transformation version differs from the frozen selection')
    members = selection.get('members')
    if not isinstance(members, list) or not members or len(members) > 20000:
        raise SafetyError('OCW requires a bounded complete pinned member manifest')
    by_path, destinations, outputs = {}, set(), {}
    for row in members:
        if set(row) != {'path', 'size_bytes', 'sha256', 'output_asset_id'}:
            raise SafetyError('OCW member requires path, size, SHA-256 and output identity')
        identity = row['output_asset_id']
        if (row['path'] in by_path or identity in outputs or identity not in assets or
                type(row['size_bytes']) is not int or not 0 <= row['size_bytes'] <= MAX_ITEM_BYTES or
                not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise SafetyError('OCW member has duplicate identity or invalid independent pin')
        asset = assets[identity]
        destination = validate_relative(asset['destination'])
        if destination.casefold() in destinations or asset.get('generation', {}).get('recipe_id') != recipe['id']:
            raise SafetyError('OCW outputs collide or belong to another recipe')
        destinations.add(destination.casefold())
        by_path[row['path']] = row
        outputs[identity] = asset
    if set(outputs) != set(recipe['output_asset_ids']):
        raise SafetyError('OCW output inventory differs from the complete member selection')
    repairs = selection.get('local_link_repairs', {})
    if not isinstance(repairs, dict) or any(path not in by_path or not isinstance(links, dict)
            or any(not isinstance(url, str) or target not in by_path for url, target in links.items())
            for path, links in repairs.items()):
        raise SafetyError('OCW explicit link repairs must bind source pages to pinned package members')
    omissions=selection.get('reviewed_html_omissions',{})
    if not isinstance(omissions,dict) or any(path not in by_path or not isinstance(rows,list) for path,rows in omissions.items()):
        raise SafetyError('OCW reviewed omissions must bind exact pinned package pages')
    runtimes = selection.get('reviewed_runtime_policies', {})
    if (not isinstance(runtimes, dict) or len(runtimes) > 1 or any(
            path != MEMBER or path not in by_path or by_path[path]['sha256'] != SOURCE_SHA256
            or policy != {'policy': POLICY, 'source_sha256': SOURCE_SHA256}
            for path, policy in runtimes.items())):
        raise SafetyError('OCW runtime policy must bind the exactly reviewed bundle')
    # Catch file/directory collisions too, before any output is written.
    for destination in destinations:
        if any('/'.join(destination.split('/')[:i]) in destinations for i in range(1, len(destination.split('/')))):
            raise SafetyError('OCW output file/directory collision')
    bindings = selection.get('media', [])
    if not isinstance(bindings, list) or len(bindings) > 2000:
        raise SafetyError('OCW media inventory exceeds its finite bound')
    contexts, global_bindings = {}, {}
    for item in bindings:
        identity = item['asset_id']
        if identity not in recipe['source_asset_ids'] or identity not in assets:
            raise SafetyError('OCW media must be an independently pinned streaming source')
        for lesson in item['lessons']:
            path = lesson['context_path']
            if path not in by_path or path in contexts:
                raise SafetyError('OCW media context is absent or ambiguous')
            captions = []
            for caption in lesson['captions']:
                member = caption['path']
                if member not in by_path or caption.get('language') not in {'en', 'unlabelled'}:
                    raise SafetyError('OCW English caption member is absent')
                captions.append({'member_path': member, 'language': 'en', 'label': 'English',
                    'destination': assets[by_path[member]['output_asset_id']]['destination'],
                    'sha256': by_path[member]['sha256']})
            contexts[path] = {item['source_url']: {'asset_id': identity,
                'destination': assets[identity]['destination'], 'captions': captions,
                'start_time': lesson.get('start_time'), 'end_time': lesson.get('end_time')}}
            # The publisher embeds the same media in reading/exercise pages as
            # well as its resource page. Those occurrences may use the complete
            # media with its exact same caption members. Page-specific excerpt
            # timings remain attached only to their own frozen context.
            whole = {'asset_id': identity, 'destination': assets[identity]['destination'],
                'captions': captions}
            previous = global_bindings.setdefault(item['source_url'], whole)
            variants = previous.get('caption_variants', [{'captions': previous.get('captions', [])}])
            hashes = sorted(c['sha256'] for c in captions)
            if not any(sorted(c['sha256'] for c in v['captions']) == hashes for v in variants):
                previous.pop('captions', None)
                previous['caption_variants'] = variants + [{'captions': captions}]
    caption_pins = {caption['path']: by_path[caption['path']]['sha256']
        for item in bindings for lesson in item['lessons'] for caption in lesson['captions']}
    for page_bindings in [global_bindings, *contexts.values()]:
        for binding in page_bindings.values():
            binding['caption_member_sha256'] = caption_pins
    for url, identity in selection.get('dependencies', {}).items():
        if identity not in recipe['source_asset_ids'] or identity not in assets or url != assets[identity]['source_url']:
            raise SafetyError('OCW dependency needs its exact pinned source identity')
        if url in global_bindings:
            raise SafetyError('OCW dependency and media identities overlap')
        global_bindings[url] = {'asset_id': identity, 'destination': assets[identity]['destination'], 'captions': []}
    contexts['*'] = global_bindings
    return by_path, outputs, contexts


def _member(source, row):
    info = source.entries[row['path']]
    if info.file_size != row['size_bytes']:
        raise SafetyError('OCW member size differs from frozen pin')
    data = source.archive.read(info)
    if len(data) != row['size_bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
        raise SafetyError('OCW member whole-file hash differs from frozen pin')
    return data


def _transform(source, by_path, outputs, contexts, row, *, local_link_repairs=None, reviewed_html_omissions=None, reviewed_runtime_policies=None):
    data = _member(source, row)
    path = row['path']
    if path in (reviewed_runtime_policies or {}):
        return localize_runtime(data, path, reviewed_runtime_policies[path]), [], []
    if not path.lower().endswith(('.html', '.css')):
        return data, [], []
    text = data.decode('utf-8')
    kwargs = {'member_path': path, 'output_destination': outputs[row['output_asset_id']]['destination'],
        'member_destinations': {p: outputs[r['output_asset_id']]['destination'] for p, r in by_path.items()}}
    if path.lower().endswith('.css'):
        result = localize_css(text, **kwargs)
        return result['css'].encode(), result['issues'], []
    media = {**contexts['*'], **contexts.get(path, {})}
    needed = _VideoURLs(text).urls
    captions = {caption['member_path']: _member(source, by_path[caption['member_path']]).decode('utf-8-sig')
        for url, binding in media.items() if _media_key(url) in needed
        for variant in binding.get('caption_variants', [{'captions': binding.get('captions', [])}])
        for caption in variant['captions']}
    result = localize_html(text, media_bindings=media, caption_texts=captions,
        reviewed_omissions=(reviewed_html_omissions or {}).get(path, []),
        local_link_repairs=(local_link_repairs or {}).get(path, {}), **kwargs)
    return result['html'].encode(), result['issues'], result.get('external_links', [])


def inspect_package(recipe, sources, assets):
    """Audit every member and dependency without writing extracted bodies."""
    by_path, outputs, contexts = _layout(recipe, assets)
    source_id = recipe['selection']['source_asset_id']
    if source_id not in recipe['source_asset_ids']:
        raise SafetyError('OCW package is not a frozen recipe source')
    issues, links, total = [], [], 0
    with ZipSource(sources[source_id], assets[source_id], max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,
                   allow_long_member_names=True) as source:
        if set(source.entries) != set(by_path):
            raise SafetyError('OCW complete member inventory differs from source ZIP')
        for path, row in sorted(by_path.items()):
            data, found, external = _transform(source, by_path, outputs, contexts, row,
                local_link_repairs=recipe['selection'].get('local_link_repairs'),
                reviewed_html_omissions=recipe['selection'].get('reviewed_html_omissions'),
                reviewed_runtime_policies=recipe['selection'].get('reviewed_runtime_policies'))
            total += len(data)
            issues.extend({'document_member': path, **issue} for issue in found)
            if len(issues) > MAX_ISSUES:
                raise SafetyError('OCW review issues exceed bounded report allowance')
            links.extend({'member': path, 'url': url} for url in external)
        source.check_source()
    return {'schema_version': 1, 'transformation_version': VERSION, 'content_ready': False,
        'files': len(outputs), 'output_bytes': total, 'issues': issues, 'external_links': links,
        'reviewed_runtime_policies': recipe['selection'].get('reviewed_runtime_policies', {}),
        'required_reviews': ['English captions, complete exercises and supplied solutions',
            'External readings: essential versus optional', 'Offline browser/media/layout and notices']}


def render(recipe, sources, assets, output_dir, *, output_writer=None):
    identities = verify_sources(recipe, sources, assets)
    report = inspect_package(recipe, sources, assets)
    if report['issues']:
        raise SafetyError('OCW unresolved dependencies: ' + str(report['issues'][:3]))
    by_path, outputs, contexts = _layout(recipe, assets)
    source_id = recipe['selection']['source_asset_id']
    result = {}
    with ZipSource(sources[source_id], assets[source_id], max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,
                   allow_long_member_names=True) as source:
        for path, row in sorted(by_path.items()):
            data, issues, _ = _transform(source, by_path, outputs, contexts, row,
                local_link_repairs=recipe['selection'].get('local_link_repairs'),
                reviewed_html_omissions=recipe['selection'].get('reviewed_html_omissions'),
                reviewed_runtime_policies=recipe['selection'].get('reviewed_runtime_policies'))
            if issues:
                raise SafetyError('OCW dependencies changed during rendering')
            target = safe_path(output_dir, outputs[row['output_asset_id']]['destination'])
            if output_writer:
                output_writer(target, data)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(target, data)
            result[row['output_asset_id']] = target
        source.check_source()
    check_source_identities(sources, identities)
    return result
