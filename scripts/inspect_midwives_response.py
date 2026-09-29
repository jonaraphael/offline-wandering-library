#!/usr/bin/env python3
"""Read bounded quarantined revision responses; preserve all acceptance blockers."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.capture import _digest, _owner, _read, _receipt, normalize_manifest
from owl.acquisition.supervisor import save


def inspect(capture, output):
    manifest = normalize_manifest(_read(capture / 'manifest.json'))
    signature = _digest(manifest)
    _owner(capture, signature)
    rows = []
    for source in manifest['sources']:
        if source.get('capture_mode') != 'bounded-response-review':
            raise ValueError('Only diagnostic sources are permitted')
        receipt = _receipt(capture, source, signature)
        if not receipt:
            raise ValueError('Diagnostic response is incomplete')
        body = (capture / receipt['relative_path']).read_bytes()
        expected = source['prior_revision']
        variants = {'unchanged': body, 'utf8_bom_removed': body.removeprefix(b'\xef\xbb\xbf'),
                    'crlf_to_lf': body.replace(b'\r\n', b'\n'), 'trailing_newline_removed': body.rstrip(b'\r\n')}
        comparisons = {name: {'size_bytes': len(value), 'sha1': hashlib.sha1(value).hexdigest(),
                             'matches_publisher_revision': len(value) == expected['size_bytes'] and hashlib.sha1(value).hexdigest() == expected['sha1']}
                       for name, value in variants.items()}
        rows.append({'id': source['id'], 'source_url': source['source_url'], 'sha256': receipt['sha256'],
                     'comparison': receipt['comparison'], 'transport': receipt['response_evidence'],
                     'diagnostic_variants': comparisons, 'first_1024_bytes': body[:1024].decode('utf-8', errors='replace'),
                     'last_1024_bytes': body[-1024:].decode('utf-8', errors='replace')})
    result = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False, 'admissible': False,
              'manifest_sha256': signature, 'sources': rows,
              'limits': 'Diagnostic only. No response or transformation is admitted or substitutes for an exact publisher revision.'}
    save(output, result)
    return {'status': result['status'], 'content_ready': False, 'sources': len(rows), 'report': str(output)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(inspect(args.capture, args.output)))
