"""Compile small search/atlas metadata without reading source document bodies."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote

import yaml

from .archive import document_assets
from .atlas import _locator, _location_key
from .atlas_model import AtlasError, load_navigation, read_asset_assignments
from .catalog import learning_shelves, read_yaml
from .safety import SafetyError, atomic_write, reject_symlinks, validate_relative

DEFAULT_BUDGET = 16 * 1024 * 1024
FORMAT = 'owl-discovery-v1'


def encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode()


def discovery_assets(assets: list[dict]) -> list[dict]:
    """Reader installers remain in the inventory, not knowledge search."""
    return [a for a in document_assets(assets) if a.get('resource_type') != 'software'
            and not a['destination'].startswith('SOFTWARE/')]


def selected_navigation(assets: list[dict], navigation: dict | None) -> dict | None:
    """Trust approved maps only for the exact inventory edition; no source I/O."""
    if navigation is None:
        return None
    selected = {a['id']: a for a in discovery_assets(assets)}
    maps = {}
    for aid, mapping in navigation.get('sections', {}).items():
        if aid not in selected:
            continue
        if not selected[aid].get('sha256') or mapping['source_sha256'] != selected[aid]['sha256']:
            raise AtlasError(f'Stale reviewed source map: {aid}')
        maps[aid] = mapping
    return {**navigation, 'sections': maps,
            'assignments': [a for a in navigation['assignments'] if a['asset_id'] in selected]}


def compile_records(assets: list[dict], navigation: dict | None = None) -> tuple[list[dict], list[dict]]:
    assets = sorted(discovery_assets(assets), key=lambda a: a['destination'])
    if len({a['id'] for a in assets}) != len(assets):
        raise SafetyError('Duplicate discovery asset ID')
    navigation = selected_navigation(assets, navigation)
    topics = navigation['topics'] if navigation else {}
    assignments = navigation['assignments'] if navigation else []
    maps = navigation['sections'] if navigation else {}
    rows, coverage, source_records = [], [], {}
    by_asset = defaultdict(list)
    for assignment in assignments:
        by_asset[assignment['asset_id']].append(assignment)
    topic_sources = defaultdict(set)
    for asset in assets:
        aid = asset['id']
        validate_relative(asset['destination'])
        base = {'asset_id': aid, 'source_title': asset['title'], 'destination': asset['destination'],
                'category': asset['category'], 'publisher': asset.get('publisher', ''),
                'shelves': sorted(learning_shelves(asset)), 'legacy': bool(asset.get('legacy')),
                'reader_required': bool(asset.get('reader_required')) or asset['format'] in {'zim', 'epub'},
                'license': asset.get('license', ''), 'attribution': asset.get('attribution', ''),
                'illustrated': bool(asset.get('illustrated')), 'kind': 'document'}
        section_rows = {s['id']: s for s in maps.get(aid, {}).get('sections', [])}
        records = {}
        for section in [None, *section_rows.values()]:
            key = _location_key(aid, section)
            if key in records:
                records[key]['aliases'].append(section['title'])
                continue
            fragment, location = _locator(section)
            href = '/'.join(quote(part, safe='') for part in asset['destination'].split('/'))
            if fragment:
                href += '#' + (fragment if section['locator']['type'] == 'pdf-page' else quote(fragment, safe=''))
            record = {**base, 'id': aid + (':' + section['id'] if section else ''),
                      'kind': 'section' if section else 'document',
                      'title': section['title'] if section else asset['title'],
                      'description': '' if section else asset.get('description', ''),
                      'aliases': [], 'labels': list(asset.get('tags', [])),
                      'href': href, 'location': location}
            records[key] = record
        for assignment in by_asset[aid]:
            sid = assignment.get('section_id')
            if sid and sid not in section_rows:
                raise AtlasError(f'Missing approved section: {aid}/{sid}')
            topic = topics[assignment['topic_id']]
            record = records[_location_key(aid, section_rows.get(sid))]
            record['labels'].append(topic['title'])
            record['aliases'].extend(assignment.get('aliases', []))
            topic_sources[topic['id']].add(aid)
        for record in records.values():
            record['aliases'] = sorted(set(record['aliases']))
            record['labels'] = sorted(set(record['labels']))
            rows.append(record)
        source_records[aid] = base
        coverage.append({'id': aid, 'destination': asset['destination'],
                         'status': 'sections' if section_rows else 'catalog', 'records': len(records)})
    # A topic is visible only when its descendants contain a selected source.
    pending = list(topic_sources)
    while pending:
        tid = pending.pop()
        for parent in topics[tid]['parents']:
            before = len(topic_sources[parent])
            topic_sources[parent].update(topic_sources[tid])
            if len(topic_sources[parent]) != before:
                pending.append(parent)
    for tid in sorted(topic_sources):
        topic = topics[tid]
        source_ids = sorted(topic_sources[tid])
        shelves = sorted({s for aid in source_ids for s in source_records[aid]['shelves']})
        rows.append({'id': 'topic:' + tid, 'kind': 'topic', 'asset_id': None,
                     'title': topic['title'], 'aliases': topic['aliases'], 'labels': [],
                     'description': topic['description'], 'href': f'INDEX/topics/{tid}.html',
                     'destination': f'INDEX/topics/{tid}.html', 'location': 'Topic atlas',
                     'shelves': shelves, 'legacy': all(source_records[a]['legacy'] for a in source_ids),
                     'source_ids': source_ids, 'source_title': 'Topic atlas', 'reader_required': False,
                     'category': 'topic', 'publisher': '', 'license': '', 'attribution': ''})
    return rows, coverage


def plan_discovery(assets, navigation=None, *, budget=DEFAULT_BUDGET):
    """Return complete small outputs for the caller's locked, owned publication."""
    from .search_ui import render_search_page
    if type(budget) is not int or budget <= 0:
        raise SafetyError('Discovery budget must be a positive integer')
    records, coverage = compile_records(assets, navigation)
    generation = hashlib.sha256(encode(records)).hexdigest()
    data = encode({'format': FORMAT, 'generation': generation, 'records': records})
    digest = hashlib.sha256(data).hexdigest()
    path = f'SEARCH/data/{digest}.js'
    manifest = {'format': FORMAT, 'path': path, 'sha256': digest, 'generation': generation, 'records': len(records)}
    outputs = {path: b'globalThis.OWLDiscoveryData(' + data.rstrip() + b');\n',
               'SEARCH/manifest.js': b'globalThis.OWLDiscoveryManifest(' + encode(manifest).rstrip() + b');\n',
               'SEARCH/search.js': Path(__file__).with_name('templates').joinpath('search.js').read_bytes(),
               'SEARCH.html': render_search_page().encode()}
    report = {'format': FORMAT, 'status': 'ready', 'records': len(records), 'assets': coverage,
              'manifest': manifest, 'source_body_bytes_read': 0,
              'generated_files': sorted([*outputs, 'SEARCH/coverage.json']),
              'file_integrity': {name: {'size_bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                                 for name, value in outputs.items()}}
    outputs['SEARCH/coverage.json'] = encode(report)
    if sum(map(len, outputs.values())) > budget:
        raise SafetyError(f'Discovery output exceeds its {budget:,}-byte allowance; shorten metadata or increase discovery_budget_bytes')
    return {name: value.decode('utf-8') for name, value in outputs.items()}, report


@dataclass(frozen=True)
class Annotation:
    asset_id: str
    aliases: list[str]
    topic_ids: list[str]
    basis: str

    @classmethod
    def parse(cls, value, assets, topics):
        if not isinstance(value, dict) or set(value) != {'asset_id', 'aliases', 'topic_ids', 'basis'}:
            raise ValueError('Annotation requires exactly asset_id, aliases, topic_ids, basis')
        aid = value['asset_id']
        if not isinstance(aid, str) or aid not in assets:
            raise ValueError('Unknown annotation asset_id')
        for name in ('aliases', 'topic_ids'):
            items = value[name]
            if (not isinstance(items, list) or not 1 <= len(items) <= 20 or
                    any(not isinstance(s, str) or not s.strip() or len(s) > 200 or
                        any(ord(c) < 32 for c in s) for s in items)):
                raise ValueError(f'{name} requires 1–20 bounded plain-text strings')
        if any(t not in topics for t in value['topic_ids']):
            raise ValueError('Unknown annotation topic_id')
        if (not isinstance(value['basis'], str) or not value['basis'].strip() or len(value['basis']) > 2000 or
                any(ord(c) < 32 and c not in '\n\t' for c in value['basis'])):
            raise ValueError('Annotation basis must describe inspected evidence (1–2000 characters)')
        return cls(**value)


def annotate(navigation_dir, assets, annotation_path, output, *, catalog_assets=None):
    """Write a reviewable assignments draft, never silently approve or publish it."""
    navigation = load_navigation(navigation_dir, catalog_assets if catalog_assets is not None else assets)
    raw = read_yaml(annotation_path)
    annotations = raw if isinstance(raw, list) else [raw]
    items = [Annotation.parse(value, {a['id'] for a in assets}, navigation['topics']) for value in annotations]
    if not items or len({item.asset_id for item in items}) != 1:
        raise ValueError('Annotate one asset at a time; each asset has its own draft')
    document = deepcopy(read_asset_assignments(navigation_dir, items[0].asset_id))
    for item in items:
        for tid in item.topic_ids:
            row = next((r for r in document['assignments'] if r['topic_id'] == tid and not r.get('section_id')), None)
            if row is None:
                row = {'topic_id': tid, 'purpose': 'reference'}
                document['assignments'].append(row)
            row['aliases'] = sorted(set(row.get('aliases', []) + item.aliases))
            row['basis'] = item.basis
    _draft(output, yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode())


def _draft(path, data):
    reject_symlinks(path)
    if path.exists() and path.read_bytes() != data:
        raise SafetyError(f'Refusing to overwrite a different draft: {path}')
    atomic_write(path, data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'annotate', 'assemble', 'build'))
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--profile', help='assemble: profile whose downloaded files should be included')
    parser.add_argument('--profiles-dir', type=Path)
    parser.add_argument('--navigation-dir', type=Path)
    parser.add_argument('--asset')
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--allow-local', action='store_true', help='allow local fixture sources')
    parser.add_argument('--outline', action='store_true', help='explicitly inspect publisher PDF bookmarks using the existing importer')
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'assemble':
            if not args.profile:
                raise ValueError('assemble requires --profile')
            if args.inventory is not None:
                raise ValueError('assemble discovers completed downloads; omit --inventory')
            from .atlas_build import build_atlas
            from .build import REPO_ROOT
            build_atlas(args.output, navigation_dir=args.navigation_dir or REPO_ROOT / 'catalog/navigation',
                        catalog=args.catalog or REPO_ROOT / 'catalog/library.yaml', profile=args.profile,
                        profiles_dir=args.profiles_dir or REPO_ROOT / 'profiles',
                        from_downloads=True, allow_local=args.allow_local)
        else:
            if args.inventory is None:
                raise ValueError(args.operation + ' requires --inventory')
            inventory = json.loads(args.inventory.read_text())
            assets = inventory['assets']
        if args.operation == 'prepare':
            asset = next((a for a in assets if a['id'] == args.asset), None)
            if asset is None:
                raise ValueError('--asset must name an inventory asset')
            packet = {'asset': asset, 'source_inspected': False}
            if args.outline:
                if asset['format'] != 'pdf':
                    raise ValueError('--outline currently supports publisher PDF bookmarks only')
                from .atlas_import import import_sections
                from .safety import safe_path
                sections, report = import_sections(safe_path(args.inventory.parent, asset['destination']), asset)
                packet.update(sections=sections, inspection=report, source_inspected=True)
            _draft(args.output, encode(packet))
        elif args.operation == 'annotate':
            if args.navigation_dir is None or args.annotations is None:
                raise ValueError('annotate requires --navigation-dir and --annotations')
            from .catalog import load_catalog
            from .build import REPO_ROOT
            annotate(args.navigation_dir, assets, args.annotations, args.output,
                     catalog_assets=load_catalog(args.catalog or REPO_ROOT / 'catalog/library.yaml',
                                                 allow_local=args.allow_local))
        elif args.operation == 'build':
            # Refresh the actual drive with the existing publisher/ownership rules.
            from .atlas_build import build_atlas
            from .build import REPO_ROOT
            if args.inventory.resolve() != (args.output / 'LIBRARY/INVENTORY.json').resolve():
                raise ValueError('build --output must be the drive containing this inventory')
            build_atlas(args.output, navigation_dir=args.navigation_dir or REPO_ROOT / 'catalog/navigation',
                        catalog=args.catalog or REPO_ROOT / 'catalog/library.yaml', metadata_only=True, allow_local=args.allow_local)
        print(json.dumps({'status': 'complete', 'output': str(args.output)}))
        return 0
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
