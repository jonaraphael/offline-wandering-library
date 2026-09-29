#!/usr/bin/env python3
"""Resume a complete, bounded exercise-format census without rendering or admission."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import _digest, _json, _read, _usage, load_capture_sources
from owl.runtime import file_lock
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file
from inspect_kolibri_capture import inspect_package

BUDGET = 100000000
RESERVE = 10000000000
MAX_RECORD = 4*1024**2


def summarize_package(result):
    widgets, encodings = Counter(), Counter()
    references = set()
    questions = []
    for document in result['json_documents']:
        widgets.update(document['widget_types'])
        encodings[document['encoding']] += 1
        references.update(document['external_references'])
        questions.append({'path': document['path'], 'keys': document['top_level_keys'],
                          'widgets': document['widget_types'], 'encoding': document['encoding']})
    return {'member_count': len(result['members']), 'members': result['members'],
            'expanded_bytes': result['expanded_bytes'], 'documents': questions,
            'widget_counts': dict(sorted(widgets.items())), 'encodings': dict(sorted(encodings.items())),
            'external_references': sorted(references),
            'checks': {'all_members_hashed': True, 'bounded_archive_structure': True},
            'required_review': ['Complete assessment mapping and prompt/hint/answer preservation',
                'Every widget, equation and illustration rendered faithfully in ordinary files',
                'Local dependencies, publisher rights notices and full course coverage']}


def run(staging, output):
    staging, output = staging.absolute(), output.absolute()
    reject_symlinks(staging); reject_symlinks(output)
    if output == staging or output in staging.parents or staging in output.parents:
        raise SafetyError('Census evidence needs a separate owned review directory')
    manifest, receipts = load_capture_sources(staging)
    if (not 1 <= len(receipts) <= 1500 or sum(r['size_bytes'] for r in receipts) > 1024**3
            or any(not r['source_id'].endswith('_perseus') for r in receipts)):
        raise SafetyError('Census requires1–1500 frozen exercise packages totaling at most1GiB')
    owner = {'schema_version': 1, 'owner': 'owl-kolibri-exercise-census',
             'manifest_sha256': _digest(manifest), 'output_budget_bytes': BUDGET, 'reserve_bytes': RESERVE,
             'inspector_sha256': sha256_file(Path(__file__)),
             'format_inspector_sha256': sha256_file(Path(__file__).with_name('inspect_kolibri_capture.py'))}
    if output.exists() and not (output/'owner.json').exists():
        raise SafetyError('Existing census output is unowned')
    output.mkdir(parents=True, exist_ok=True)
    with file_lock(output/'review.lock'):
        marker = output/'owner.json'
        if marker.exists() and _read(marker) != owner:
            raise SafetyError('Census inspector/source changed; use a new versioned review root')
        used = _usage(output)
        def write(path, value):
            nonlocal used
            reject_symlinks(path)
            payload = _json(value)
            # Account for the temporary atomic replacement as well as retained
            # evidence; reconcile once on entry and exit under the review lock.
            if len(payload) > MAX_RECORD or used+len(payload) > BUDGET:
                raise SafetyError('Census evidence exceeds its bounded record or total allowance')
            if shutil.disk_usage(output).free < RESERVE+len(payload):
                raise SafetyError('Census evidence would consume shared reserve')
            old = path.stat().st_size if path.exists() else 0
            atomic_write(path, payload)
            used += len(payload)-old
        write(marker, owner)
        checkpoint = output/'checkpoint.json'
        previous = _read(checkpoint, MAX_RECORD) if checkpoint.exists() else {}
        if previous and (previous.get('manifest_sha256') != owner['manifest_sha256']
                         or previous.get('content_ready') is not False):
            raise SafetyError('Census checkpoint belongs to different inputs')
        previous_rows = previous.get('rows', [])
        known = {r['source_id'] for r in receipts}
        if (len({r['source_id'] for r in previous_rows}) != len(previous_rows)
                or any(r['source_id'] not in known for r in previous_rows)):
            raise SafetyError('Census checkpoint contains duplicate or unrelated sources')
        previous_pins = {r['source_id']: r['evidence_sha256'] for r in previous_rows}
        rows = []
        for receipt in sorted(receipts, key=lambda r: r['source_id']):
            binding = {'source_id': receipt['source_id'], 'source_sha256': receipt['sha256'],
                       'receipt_sha256': _digest(receipt), 'owner_sha256': _digest(owner)}
            detail = safe_path(output, receipt['source_id']+'.json')
            if receipt['source_id'] in previous_pins:
                if not detail.exists() or sha256_file(detail) != previous_pins[receipt['source_id']]:
                    raise SafetyError('Cached census evidence changed or disappeared')
                result = _read(detail, MAX_RECORD)
                if result.get('binding') != binding or result.get('content_ready') is not False:
                    raise SafetyError('Cached exercise census has a different source or inspector')
            else:
                result = {'schema_version': 1, 'binding': binding, 'content_ready': False}
                try:
                    result.update(status='inspected_awaiting_review', **summarize_package(
                        inspect_package(safe_path(staging, receipt['relative_path']), receipt)))
                except (OSError, ValueError, RuntimeError, RecursionError) as error:
                    result.update(status='format_blocked', error=str(error)[:500])
                write(detail, result)
            row = {'source_id': receipt['source_id'], 'status': result['status'],
                   'evidence': detail.name, 'evidence_sha256': sha256_file(detail),
                   'widget_counts': result.get('widget_counts', {}),
                   'external_reference_count': len(result.get('external_references', []))}
            if result.get('error'): row['error'] = result['error']
            rows.append(row)
            write(checkpoint, {'schema_version': 1, 'content_ready': False,
                'manifest_sha256': owner['manifest_sha256'], 'rows': rows})
        widgets = Counter()
        for row in rows: widgets.update(row['widget_counts'])
        report = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False,
                  'manifest_sha256': owner['manifest_sha256'], 'rows': rows,
                  'requested_sources': len(receipts),
                  'inspected_sources': sum(r['status']=='inspected_awaiting_review' for r in rows),
                  'format_errors': sum(r['status']=='format_blocked' for r in rows),
                  'widget_counts': dict(sorted(widgets.items())), 'accepted_useful_bytes': 0}
        write(output/'report.json', report)
        if _usage(output) != used:
            raise SafetyError('Census evidence usage changed outside the owned writer')
    return {k: v for k, v in report.items() if k != 'rows'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staging', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(run(args.staging, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
