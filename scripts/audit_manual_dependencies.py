#!/usr/bin/env python3
"""Recheck captured manual pins, publisher ZIP members, and offline dependencies.

No network, extraction, catalog admission, or assertion of substantive approval.
Detailed evidence stays local; stdout contains a bounded summary.
"""
import argparse
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import sys
from urllib.parse import urljoin, urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import load_capture_sources, _json, _read, _digest, _preview_receipt
from owl.archive import ZipSource
from owl.safety import SafetyError, atomic_write, sha256_file, safe_path

MAX_HTML = 8 * 1024 * 1024


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self.counts = [], [], Counter()
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.counts[tag] += 1
        for name in ('src', 'href', 'poster'):
            if values.get(name):
                kind = 'cross-reference' if tag == 'a' else 'active-dependency'
                if tag == 'link' and 'stylesheet' not in values.get('rel', '').split():
                    kind = 'publisher-metadata-link'
                self.links.append({'tag': tag, 'attribute': name, 'url': values[name], 'kind': kind})
    def handle_data(self, text):
        if text.strip(): self.text.append(text)


def audit_html(data, location, known_urls, members=None):
    if len(data) > MAX_HTML:
        return {'status': 'pending_oversized_html', 'size_bytes': len(data)}
    parsed = Document(); parsed.feed(data.decode('utf-8-sig', errors='strict')); parsed.close()
    dependencies = []
    for row in parsed.links:
        raw = row['url']; parts = urlsplit(raw)
        if raw.startswith('#') or parts.scheme in ('data', 'mailto', 'tel'):
            continue
        if members is not None and not parts.scheme and not parts.netloc:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(location), unquote(parts.path)))
            if resolved in members or not parts.path:
                continue
            status = 'missing_package_member'
        else:
            resolved = urljoin(location, raw).split('#')[0]
            status = 'captured_source_link_requires_localization' if resolved in known_urls else 'external_not_captured'
        dependencies.append({**row, 'resolved': resolved, 'status': status})
    return {'status': 'inspected_awaiting_review', 'text_characters': sum(map(len, parsed.text)),
        'structure': {key: parsed.counts[key] for key in ('img', 'table', 'math', 'svg', 'pre')},
        'dependency_counts': dict(Counter(r['kind'] for r in dependencies)), 'dependencies': dependencies}


def inspect(staging, catalog, output):
    import yaml
    manifest, receipts = load_capture_sources(staging)
    records = {r['source_id']: r for r in receipts}
    assets = yaml.safe_load(catalog.read_text())['assets']
    known_urls = {s['source_url'] for s in manifest['sources']}
    rows = []
    for source in manifest['sources']:
        sid = source['id']; receipt = records[sid]; path = staging / receipt['relative_path']
        metadata = {**source['fullasset_metadata'], 'sha256': receipt['sha256'], 'size_bytes': receipt['size_bytes']}; fmt = metadata['format']
        row = {'source_id': sid, 'source_url': source['source_url'], 'sha256': receipt['sha256'],
               'size_bytes': receipt['size_bytes'], 'format': fmt, 'source_pin_verified': True}
        if fmt == 'html':
            if receipt['size_bytes'] > MAX_HTML:
                row['inspection'] = {'status': 'pending_oversized_html'}
            else:
                row['inspection'] = audit_html(path.read_bytes(), source['source_url'], known_urls)
        members = [a for a in assets if a.get('archive_member', {}).get('source_asset_id') == sid]
        if fmt == 'zip' and members:
            expected = {a['archive_member']['path']: a for a in members}
            verified, html_rows = [], []
            with ZipSource(path, metadata) as archive:
                if set(expected) != set(archive.entries):
                    raise SafetyError(sid + ': accepted manifest does not cover the complete publisher ZIP')
                for name, member in sorted(expected.items()):
                    info = archive.entries[name]
                    if info.file_size != member['size_bytes']:
                        raise SafetyError(sid + ': ZIP member size changed')
                    digest, count, chunks = hashlib.sha256(), 0, []
                    is_html = name.endswith(('.html', '.htm')) and info.file_size <= MAX_HTML
                    with archive.archive.open(info) as handle:
                        while block := handle.read(min(1024 * 1024, info.file_size - count + 1)):
                            count += len(block)
                            if count > info.file_size: raise SafetyError('ZIP member exceeds its declared bound')
                            digest.update(block)
                            if is_html: chunks.append(block)
                    if count != member['size_bytes'] or digest.hexdigest() != member['sha256']:
                        raise SafetyError(sid + ': ZIP member hash changed')
                    verified.append({'asset_id': member['id'], 'path': name, 'sha256': digest.hexdigest(), 'size_bytes': count})
                    if is_html:
                        html_rows.append({'path': name, **audit_html(b''.join(chunks), name, known_urls, archive.entries)})
                    elif name.endswith(('.html','.htm')):
                        html_rows.append({'path': name, 'status': 'pending_oversized_html'})
                archive.check_source()
            row['package'] = {'complete_member_manifest': True, 'members_verified': len(verified),
                'expanded_bytes': sum(m['size_bytes'] for m in verified), 'members': verified, 'html': html_rows}
        rows.append(row)
    result = {'schema_version': 1, 'content_ready': False, 'status': 'inspected_awaiting_review',
        'manifest_sha256': sha256_file(staging/'manifest.json'), 'source_count': len(rows), 'body_downloads': 0,
        'physical_device_certification': 'pending', 'records': rows,
        'required_review': ['Classify essential dependencies separately from publisher UI, cosmetic resources and external references.',
            'Preserve original source and file-specific notices; generic project license text does not close per-file notice gaps.',
            'This structural audit does not approve unavailable editions or certify physical devices.']}
    atomic_write(output, _json(result))
    return {'source_count': len(rows), 'html_originals': sum('inspection' in r for r in rows),
        'packages': [{'source_id': r['source_id'], 'members': r['package']['members_verified'], 'expanded_bytes': r['package']['expanded_bytes']} for r in rows if 'package' in r],
        'content_ready': False, 'detail': str(output)}


def inspect_localized(staging, recipe_path, catalog, output):
    """Check the entire captured ZIP against its source-bound localized preview."""
    from owl.acquisition.zip_localized import rewrite_member, validate_recipe
    manifest, receipts = load_capture_sources(staging)
    recipe = _read(recipe_path); proposal = _read(catalog)
    from owl.acquisition.model import build_input_assets
    assets = {**{a['id']: a for a in proposal['assets']}, **build_input_assets([recipe])}
    validate_recipe(recipe, assets)
    preview = safe_path(staging, 'previews/' + recipe['id'])
    preview_receipt = _preview_receipt(staging, preview/'preview-receipt.json')
    if preview_receipt['manifest_sha256'] != _digest(manifest):
        raise SafetyError('Localized review belongs to another capture')
    source_id = recipe['selection']['source_asset_id']
    receipt = next(r for r in receipts if r['source_id'] == source_id)
    source = assets[source_id]
    if source['sha256'] != receipt['sha256'] or source['size_bytes'] != receipt['size_bytes']:
        raise SafetyError('Localized ZIP source pin differs from captured bytes')
    declared = recipe['selection']['members']
    expected_outputs = {r['id']: r for r in preview_receipt['outputs']}
    if set(expected_outputs) != {m['asset_id'] for m in declared}:
        raise SafetyError('Localized preview output membership differs')
    member_paths = {m['path'] for m in declared}
    dependency_paths = set(recipe.get('selection', {}).get('dependencies', {}))
    source_urls = {s['source_url'] for s in manifest['sources']}
    rows, html_rows, repaired = [], [], 0
    with ZipSource(safe_path(staging, receipt['relative_path']), source) as archive:
        if {m['path'] for m in declared if not m.get('source_asset_id')} != set(archive.entries):
            raise SafetyError('Localized review must cover the complete publisher package')
        from owl.acquisition.python_manual import auxiliary
        runtime_inputs=auxiliary(archive,declared)
        for member in declared:
            identity = member['asset_id']; asset = assets[identity]
            origin=member.get('source_asset_id')
            if origin:
                original_receipt=next(r for r in receipts if r['source_id']==origin)
                stream=safe_path(staging,original_receipt['relative_path']).open('rb')
            else:
                info = archive.entries[member['path']]
                if info.file_size != member['size_bytes']:
                    raise SafetyError('Source member size differs from its bounded declaration')
                stream=archive.archive.open(info)
            with stream:
                raw = stream.read(member['size_bytes'] + 1)
                if stream.read(1): raise SafetyError('Source member exceeds its declared bound')
            if len(raw) != member['size_bytes'] or hashlib.sha256(raw).hexdigest() != member['sha256']:
                raise SafetyError('Source member differs from frozen original pin')
            path = safe_path(preview/'files', asset['destination'])
            if path.stat().st_size != asset['size_bytes'] or sha256_file(path) != asset['sha256']:
                raise SafetyError('Localized output pin differs from reviewed proposal')
            if any(expected_outputs[identity][key] != asset[key] for key in ('size_bytes', 'sha256')):
                raise SafetyError('Localized proposal pin differs from preview receipt')
            expected = rewrite_member(raw, member, runtime_inputs)
            if path.read_bytes() != expected:
                raise SafetyError('Localized output differs from its declared member transformation')
            repaired += sum(r['expected_count'] for r in member.get('rewrites', []))
            rows.append({'asset_id': identity, 'path': member['path'], 'size_bytes': len(expected),
                'sha256': asset['sha256'], 'original_sha256': member['sha256'], 'preservation': 'exact_except_declared_transformations',
                'stylesheet_patch': member.get('stylesheet_patch'), 'runtime_patch': member.get('runtime_patch'), 'reference_annotation': member.get('reference_annotation'), 'source_asset_id': member.get('source_asset_id')})
            if member['path'].endswith(('.html', '.htm')):
                html_rows.append({'path': member['path'], **audit_html(expected, member['path'], source_urls, member_paths | dependency_paths)})
        archive.check_source()
    companion_rows = []
    preview_companions = {row['id']: row for row in preview_receipt.get('companions', [])}
    for member_path, identity in recipe.get('selection', {}).get('dependencies', {}).items():
        asset = assets[identity]
        companion = preview_companions.get(identity, {})
        if any(companion.get(key) != asset[key] for key in ('size_bytes', 'sha256')):
            raise SafetyError('Supporting dependency differs from its captured preview pins')
        path = safe_path(preview/'files', asset['destination'])
        companion_rows.append({'asset_id': identity, 'path': member_path, 'size_bytes': asset['size_bytes'], 'sha256': asset['sha256']})
        if member_path.endswith(('.html', '.htm')):
            html_rows.append({'path': member_path, **audit_html(path.read_bytes(), member_path, source_urls, member_paths | dependency_paths)})
    missing = [dict(document=doc['path'], **link) for doc in html_rows for link in doc.get('dependencies', []) if link['status']=='missing_package_member']
    result = {'schema_version': 1, 'content_ready': False, 'status': 'inspected_awaiting_review',
        'manifest_sha256': _digest(manifest), 'recipe_sha256': _digest(recipe), 'proposal_sha256': _digest(proposal),
        'preview_receipt_sha256': _digest(preview_receipt), 'source_sha256': source['sha256'],
        'members_verified': len(rows), 'html_documents': len(html_rows), 'attribute_spans_repaired': repaired,
        'whole_package_preserved': True, 'missing_local_links': missing, 'members': rows, 'html': html_rows,
        'supporting_dependencies': companion_rows,
        'physical_device_certification': 'pending'}
    atomic_write(output, _json(result))
    return {key: result[key] for key in ('content_ready','members_verified','html_documents','attribute_spans_repaired','whole_package_preserved')} | {
        'missing_local_links': len(missing), 'missing_examples': missing[:3], 'detail': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=ROOT/'catalog/library.yaml')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--localized-recipe', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_localized(args.staging, args.localized_recipe, args.catalog, args.output) if args.localized_recipe
        else inspect(args.staging, args.catalog, args.output)))


if __name__ == '__main__': main()
