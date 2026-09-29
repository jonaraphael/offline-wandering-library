#!/usr/bin/env python3
"""Inspect the captured format pilot with existing bounded ZIP validation.

No extraction, network access, rendering or content admission takes place.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import load_capture_sources, _digest, _usage
from owl.acquisition.supervisor import read
from owl.archive import ZipSource
from owl.runtime import file_lock
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file


def inspect_json(value):
    stack = [value]
    widgets, references, excerpts = Counter(), set(), []
    visited = 0
    while stack:
        item = stack.pop()
        visited += 1
        if visited > 100000:
            raise SafetyError('Exercise JSON exceeds100,000 inspected nodes')
        if isinstance(item, dict):
            if isinstance(item.get('widgets'), dict):
                widgets.update(str(w.get('type', '<missing>')) for w in item['widgets'].values() if isinstance(w, dict))
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            references.update(re.findall(r'https?://[^\s"<>\)]+', item))
            if len(references) > 5000:
                raise SafetyError('Exercise external-reference count exceeds5,000')
            if len(item) > 40 and len(excerpts) < 5:
                excerpts.append(item[:700])
    return {'top_level_keys': sorted(value)[:50] if isinstance(value, dict) else [],
            'widget_types': dict(widgets), 'external_references': sorted(references),
            'review_excerpts': excerpts, 'json_nodes': visited}


def decode_document(name, body):
    """Read publisher SVG label data as JSON, never evaluate its callback."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate exercise JSON key: '+str(key)[:100])
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError('Non-finite exercise JSON constant: '+value)
    def parse(text):
        return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
    text = body.decode('utf-8')
    try:
        return parse(text), 'json'
    except ValueError as original:
        match = re.fullmatch(r'images/([a-f0-9]{40})-data\.json', name)
        if not match:
            raise ValueError(f'{name}: invalid JSON') from original
        prefix = 'svgData' + match[1] + '('
        text = text.strip()
        if text.endswith(';'):
            text = text[:-1]
        if not text.startswith(prefix) or not text.endswith(')'):
            raise ValueError(f'{name}: unrecognized SVG data wrapper') from original
        value = parse(text[len(prefix):-1])
        if not isinstance(value, dict) or not isinstance(value.get('labels'), list):
            raise ValueError(f'{name}: SVG label data lacks its expected structure')
        return value, 'publisher-svg-label-json-wrapper'


def inspect_package(path, receipt):
    with ZipSource(path, receipt) as source:
        members, documents = [], []
        json_bytes = 0
        for name, info in sorted(source.entries.items()):
            digest = hashlib.sha256()
            body = bytearray() if name.endswith('.json') else None
            if body is not None and (info.file_size > 4*1024**2 or json_bytes + info.file_size > 32*1024**2):
                raise SafetyError('Exercise JSON exceeds4MiB/member or32MiB/package')
            count = 0
            with source.archive.open(info) as stream:
                while chunk := stream.read(65536):
                    count += len(chunk)
                    if count > info.file_size:
                        raise SafetyError('Exercise member exceeded its declared size')
                    digest.update(chunk)
                    if body is not None:
                        body.extend(chunk)
            if count != info.file_size:
                raise SafetyError('Exercise member was truncated')
            members.append({'path': name, 'size_bytes': count, 'sha256': digest.hexdigest()})
            if body is not None:
                json_bytes += count
                value, encoding = decode_document(name, body)
                documents.append({'path': name, 'encoding': encoding, **inspect_json(value)})
        source.check_source()
    return {'members': members, 'json_documents': documents,
            'expanded_bytes': sum(m['size_bytes'] for m in members)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staging', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    manifest, receipts = load_capture_sources(args.staging)
    if len(receipts) > 100 or sum(r['size_bytes'] for r in receipts) > 512*1024**2:
        raise SafetyError('Inspection is limited to the frozen format pilot')
    reject_symlinks(args.output)
    owner = {'schema_version': 1, 'owner': 'owl-kolibri-format-review',
             'manifest_sha256': _digest(manifest), 'reviewer_sha256': sha256_file(Path(__file__)),
             'output_budget_bytes': 1000000000, 'reserve_bytes': 10000000000}
    if args.output.exists() and not (args.output/'owner.json').exists():
        raise SafetyError('Existing review directory is unowned')
    args.output.mkdir(parents=True, exist_ok=True)
    with file_lock(args.output/'review.lock'):
        marker = args.output/'owner.json'
        if marker.exists() and read(marker) != owner:
            raise SafetyError('Review belongs to a different source or inspector version')
        atomic_write(marker, (json.dumps(owner, sort_keys=True)+'\n').encode())
        rows = []
        for receipt in receipts:
            path = safe_path(args.staging, receipt['relative_path'])
            row = {'source_id': receipt['source_id'], 'sha256': receipt['sha256'], 'size_bytes': receipt['size_bytes']}
            if receipt['source_id'].endswith('_perseus'):
                try:
                    row.update(status='format_inspected_awaiting_review', **inspect_package(path, receipt))
                except (OSError, ValueError, RuntimeError, RecursionError) as error:
                    row.update(status='format_blocked', error=str(error)[:500])
            else:
                row['status'] = 'source_verified_playback_or_image_review_pending'
            rows.append(row)
        report = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False,
                  'manifest_sha256': owner['manifest_sha256'], 'rows': rows,
                  'format_errors': sum(r['status'] == 'format_blocked' for r in rows),
                  'required_reviews': ['All video playback, captions and image layouts',
                    'Faithful ordinary exercise prompts, hints, figures and supplied solutions',
                    'Publisher permission scope, complete course inventories and known metadata gaps']}
        payload = (json.dumps(report, sort_keys=True, indent=2)+'\n').encode()
        if (len(payload) > 8*1024**2 or _usage(args.output)+len(payload) > owner['output_budget_bytes']
                or shutil.disk_usage(args.output).free < owner['reserve_bytes']+len(payload)):
            raise SafetyError('Bounded review report would exceed budget/reserve')
        atomic_write(args.output/'report.json', payload)
        print(json.dumps({'content_ready': False, 'sources': len(rows),
                          'counts': dict(Counter(r['status'] for r in rows)),
                          'detail': str(args.output/'report.json')}, sort_keys=True))


if __name__ == '__main__':
    main()
