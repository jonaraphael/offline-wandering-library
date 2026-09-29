#!/usr/bin/env python3
"""One bounded, body-free checkpoint for timed acquisition follow-ups.

Reads current supervisor controls, never starts/stops jobs or admits content.
Writes a detailed local snapshot and a small change-only model-facing summary.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.supervisor import read, save
from owl.safety import reject_symlinks


def snapshot(root, now):
    reject_symlinks(root)
    owners = sorted(root.glob('*/owner.json'))
    if len(owners) > 128:
        raise ValueError('More than 128 supervisor candidates; narrow the root')
    rows = []
    for owner_path in owners:
        owner = read(owner_path)
        if owner.get('owner') != 'owl-trial-supervisor':
            continue
        directory = owner_path.parent
        row = {'directory': str(directory), 'id': directory.name}
        try:
            if not (directory / 'state.json').exists() and not (directory / 'manager-job').exists():
                # A read-only capacity preflight writes ownership but no worker.
                continue
            state = read(directory / 'state.json')
            tasks = state['tasks']
            if not isinstance(tasks, dict) or len(tasks) > 100:
                raise ValueError('Invalid task inventory')
            row.update(state=state['state'], revision=state['revision'],
                       counts=dict(Counter(t['state'] for t in tasks.values())),
                       running=[k for k, v in tasks.items() if v['state'] == 'running'],
                       exceptions=[{'task': k, 'reason': v.get('reason', '')[:350]}
                                   for k, v in tasks.items()
                                   if v['state'] in {'needs_review', 'blocked'}])
            # Heartbeats can be delayed by the shared external disk. Flag ten
            # minutes as uncertain, never claim that a process is dead from age.
            row['heartbeat_stale'] = (state['state'] == 'running' and
                                     now - float(state['heartbeat_at']) > 600)
            if state.get('exception'):
                row['exception'] = str(state['exception'])[:350]
            status = directory / 'manager-job/status.json'
            if status.exists():
                manager = read(status)
                row['manager_state'] = manager['state']
                if state['state'] == 'running' and manager['state'] in {'failed', 'cancelled'}:
                    row['exception'] = 'Supervisor state says running but manager is ' + manager['state']
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(state='inspection_error', exception=str(error)[:350])
        row['fingerprint'] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / '.owl/acquisition')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.root / 'timed-progress.json'
    previous = read(output) if output.exists() else {}
    before = {r['id']: r['fingerprint'] for r in previous.get('workers', [])}
    rows = snapshot(args.root, time.time())
    changed = [r for r in rows if before.get(r['id']) != r['fingerprint']]
    report = {'schema_version': 1, 'content_complete': False,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'workers': rows}
    save(output, report)
    summary = {'content_complete': False, 'unchanged': not changed,
               'workers': len(rows), 'running': sum(r['state'] == 'running' for r in rows),
               'stale_or_error': sum(bool(r.get('heartbeat_stale') or r.get('exception')) for r in rows),
               'review_queues': sum(bool(r.get('exceptions')) for r in rows),
               'changed_count': len(changed), 'detail': str(output),
               'changed': [{'id': r['id'], 'state': r['state'], 'revision': r.get('revision')}
                           for r in changed]}
    while len(json.dumps(summary).encode()) > 2048 and summary['changed']:
        summary['changed'].pop()
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
