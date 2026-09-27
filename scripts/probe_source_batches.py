#!/usr/bin/env python3
"""Bounded, checkpointed HEAD-only source probes for a large reviewed selection."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.pins import PinProbe, probe_manifest
from owl.acquisition.model import AcquisitionError
from owl.safety import atomic_write, reject_symlinks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, default=Path('.owl/acquisition/source-pins'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--request-interval', type=float, default=.15)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 4 or not .1 <= args.request_interval <= 10:
        parser.error('Choose 1–4 workers and a request interval of 0.1–10 seconds')
    reject_symlinks(args.manifest)
    reject_symlinks(args.output)
    if args.manifest.stat().st_size > 8 * 1024 * 1024:
        parser.error('Request manifest exceeds 8 MiB')
    document = json.loads(args.manifest.read_text())
    requests = document.get('requests', [])
    if document.get('schema_version') != 1 or not isinstance(requests, list) or not 1 <= len(requests) <= 10000 or any(not isinstance(r, dict) for r in requests):
        parser.error('Require 1–10000 reviewed requests')
    if len({r.get('id') for r in requests}) != len(requests) or len({r.get('url') for r in requests}) != len(requests):
        parser.error('Duplicate source identity or URL')
    class ValidationOnly:
        def probe(self, request):
            return {'status': 'pending'}
    batches = [requests[start:start + 100] for start in range(0, len(requests), 100)]
    for batch in batches:
        probe_manifest({'schema_version': 1, 'requests': batch}, ValidationOnly())
    lock, last_request = threading.Lock(), [0.0]
    def probe(request):
        if not args.offline:
            with lock:
                remaining = args.request_interval - (time.monotonic() - last_request[0])
                if remaining > 0:
                    time.sleep(remaining)
                last_request[0] = time.monotonic()
        record = PinProbe(args.cache_dir, offline=args.offline).probe(request)
        for evidence in record['evidence']:
            evidence.pop('cached', None)
        return record
    records = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for batch in batches:
            records.extend(executor.map(probe, batch))
            result = {'schema_version': 1, 'operation': 'source-pin-probe', 'body_downloads': 0,
                      'expected_count': len(requests), 'complete': len(records) == len(requests),
                      'records': records, 'proposed_count': sum(r['status'] == 'proposed' for r in records),
                      'pending_count': sum(r['status'] != 'proposed' for r in records)}
            atomic_write(args.output, (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
    print(json.dumps({'body_downloads': 0, 'complete': result['complete'], 'sources': len(records),
                      'exact_sizes': sum(type(r['size_bytes']) is int for r in records),
                      'proposed_count': result['proposed_count'], 'pending_count': result['pending_count'],
                      'detail': str(args.output)}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AcquisitionError, ValueError, OSError) as error:
        raise SystemExit(str(error)[:500])
