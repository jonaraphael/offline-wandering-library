#!/usr/bin/env python3
"""Freeze already-pinned selected originals for source-review acquisition.

Reads catalog metadata only. Generated outputs and archive members must use
their generation recipes instead. Existing differing manifests are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import normalize_manifest
from owl.catalog import load_catalog, load_profiles, resolve_content
from owl.resources import load_resources, resource_asset_ids
from owl.safety import atomic_write, reject_symlinks


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def freeze(identity, profile, assets, resources, selected_ids, requested_ids, requested_resources):
    by_id = {a['id']: a for a in assets}
    if not requested_ids or len(requested_ids) != len(set(requested_ids)):
        raise ValueError('Select explicit unique asset IDs')
    if not requested_resources or set(requested_resources) - resources.keys():
        raise ValueError('Select known explicit resource IDs')
    if set(requested_ids) - set(selected_ids):
        raise ValueError('Every requested asset must belong to the current profile selection')
    sources = []
    for aid in sorted(requested_ids):
        asset = by_id[aid]
        owners = sorted(r for r in requested_resources if aid in resource_asset_ids(resources[r]))
        if not owners:
            raise ValueError(f'{aid}: source is outside the requested resources')
        if (asset.get('status') != 'resolved' or not asset.get('sha256') or
                asset.get('generation') or asset.get('archive_member')):
            raise ValueError(f'{aid}: capture requires a pinned original, not a generated/member output')
        evidence = {'kind': 'catalog-record', 'record_id': aid,
            'url': asset['source_url'], 'sha256': hashlib.sha256(canonical(asset)).hexdigest(),
            'scope': 'Canonical accepted catalog metadata; not a publisher-page or body hash'}
        sources.append({'id': aid, 'resource_ids': owners, 'source_url': asset['source_url'],
            'version': asset.get('version') or asset.get('snapshot_date'),
            'size_bytes': asset['size_bytes'], 'sha256': asset['sha256'],
            'publisher_checksums': {}, 'metadata_evidence': [evidence],
            'fullasset_metadata': asset})
    return normalize_manifest({'schema_version': 1, 'kind': 'acquisition', 'id': identity,
        'profile': profile, 'content_ready': False, 'sources': sources,
        'budget': {'download_bytes': sum(a['size_bytes'] for a in sources),
            'expanded_bytes': 0, 'preview_bytes': 0, 'scratch_bytes': 0, 'cache_bytes': 0},
        'review_requirements': ['Capture verifies existing originals; it does not admit new content.',
            'Freeze and review complete work inventories before admitting overlapping expansion works.']})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT/'catalog/library.yaml')
    parser.add_argument('--resources', type=Path, default=ROOT/'catalog/resources.yaml')
    parser.add_argument('--profiles-dir', type=Path, default=ROOT/'profiles')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--asset', action='append', required=True)
    parser.add_argument('--resource', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profiles = load_profiles(args.profiles_dir)
        assets = load_catalog(args.catalog, profiles)
        resources = load_resources(args.resources, assets)
        selected, _, _ = resolve_content(assets, profiles[args.profile], resources_path=args.resources)
        ids = [part for raw in args.asset for part in raw.split(',')]
        requested_resources = {part for raw in args.resource for part in raw.split(',')}
        result = freeze(args.id, args.profile, assets, resources,
                        {a['id'] for a in selected}, ids, requested_resources)
        payload = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)+'\n').encode()
        reject_symlinks(args.output)
        if args.output.exists() and args.output.read_bytes() != payload:
            raise ValueError('Existing frozen manifest differs; use a new output/version')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output, payload)
        print(json.dumps({'manifest': str(args.output), 'sources': len(result['sources']),
            'source_bytes': result['budget']['download_bytes'], 'peak_bytes': result['storage_peak_bytes'],
            'body_downloads': 0, 'content_ready': False}))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(str(error)[:1500], file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
