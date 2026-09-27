#!/usr/bin/env python3
"""Freeze bounded, portable PhET QA evidence; detailed states stay local."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


class EvidenceError(ValueError):
    pass


LOCAL_PATH = re.compile(r'(?:file://\S+|[A-Za-z]:[\\/][^\s]+|/(?:Users|home|private|tmp|var|opt|Volumes)/[^\s]+)')


def portable_text(value, limit=160):
    return LOCAL_PATH.sub('[local path]', str(value))[:limit]


def state_value(value):
    if isinstance(value, str) and (len(value) > 160 or LOCAL_PATH.search(value)):
        return {'sha256': hashlib.sha256(value.encode()).hexdigest(), 'characters': len(value)}
    return value


def primitive(value):
    return type(value) in {str, bool, int, float} and (type(value) not in {int, float} or math.isfinite(value))


def equal(a, b):
    # JavaScript JSON values distinguish boolean true from numeric one.
    return (type(a) is bool) == (type(b) is bool) and a == b


def summarize(raw, manifest_bytes, *, manifest_name, report_name):
    if len(raw) > 64 * 1024 * 1024 or len(manifest_bytes) > 4 * 1024 * 1024:
        raise EvidenceError('Report/manifest exceeds its size bound')
    report, manifest = json.loads(raw), json.loads(manifest_bytes)
    if not isinstance(report, dict) or not isinstance(manifest, dict):
        raise EvidenceError('Report and manifest must be mappings')
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    rows = manifest.get('assets')
    viewports = manifest.get('viewports', [{'width': 1280, 'height': 900}, {'width': 390, 'height': 844}])
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise EvidenceError('Manifest requires 1–1000 assets')
    if not isinstance(viewports, list) or not 1 <= len(viewports) <= 8:
        raise EvidenceError('Manifest requires 1–8 viewports')
    dimensions = []
    for viewport in viewports:
        if not isinstance(viewport, dict) or any(type(viewport.get(k)) is not int or not 200 <= viewport[k] <= 4096 for k in ('width', 'height')):
            raise EvidenceError('Invalid manifest viewport')
        dimensions.append((viewport['width'], viewport['height']))
    if len(set(dimensions)) != len(dimensions):
        raise EvidenceError('Duplicate manifest viewport')
    assets = {}
    for asset in rows:
        if not isinstance(asset, dict):
            raise EvidenceError('Manifest assets must be mappings')
        identity, pin = asset.get('id'), asset.get('sha256')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9_-]{1,128}', identity) or identity in assets:
            raise EvidenceError('Manifest IDs must be unique bounded identifiers')
        if not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{64}', pin):
            raise EvidenceError('Manifest source requires a whole-file SHA-256')
        keys = asset.get('expected_changed_keys', [])
        if not isinstance(keys, list) or not 1 <= len(keys) <= 8 or any(not isinstance(k, str) or not k.strip() or len(k) > 256 for k in keys) or len(set(keys)) != len(keys):
            raise EvidenceError('Manifest requires 1–8 unique reviewed state keys')
        assets[identity] = asset
    expected = {(identity, width, height) for identity in assets for width, height in dimensions}
    observed, checks = set(), []
    report_checks = report.get('checks')
    if not isinstance(report_checks, list) or len(report_checks) > len(expected):
        raise EvidenceError('Report check list is missing or exceeds the manifest')
    for row in report_checks:
        if not isinstance(row, dict) or not isinstance(row.get('viewport'), dict):
            raise EvidenceError('Report checks require a viewport mapping')
        key = (row['id'], row['viewport']['width'], row['viewport']['height'])
        if key not in expected or key in observed or row['sha256'] != assets[row['id']]['sha256'] or row.get('version') != assets[row['id']].get('version'):
            raise EvidenceError('Report contains duplicate, changed or unselected source/viewport checks')
        if type(row.get('success')) is not bool:
            raise EvidenceError('Check success must be an explicit boolean')
        observed.add(key)
        required = assets[row['id']]['expected_changed_keys']
        errors = row.get('errors')
        if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
            raise EvidenceError('Check errors must be a string list')
        states = [row.get(name, {}) for name in ('before', 'after', 'reset')]
        if any(not isinstance(state, dict) for state in states):
            raise EvidenceError('State observations must be mappings')
        values_present = all(k in state and primitive(state[k]) for k in required for state in states)
        meaningful = values_present and all(not equal(states[0][k], states[1][k]) and equal(states[0][k], states[2][k]) for k in required)
        lists = [row.get(name, []) for name in ('changed_keys', 'restored_keys')]
        claimed = all(isinstance(keys, list) and all(k in keys for k in required) for keys in lists)
        layout = row.get('layout', {})
        layout_ok = isinstance(layout, dict) and layout.get('viewport_width') == key[1] and type(layout.get('scroll_width')) in {int, float} and math.isfinite(layout['scroll_width']) and 0 < layout['scroll_width'] <= key[1] + 1 and type(layout.get('visible_rendering_surfaces')) is int and layout['visible_rendering_surfaces'] > 0
        if row['success'] and (not meaningful or not claimed or errors or not layout_ok or row.get('inspection')):
            raise EvidenceError('Report claims success without observed reviewed interaction/reset and valid layout')
        item = {k: row[k] for k in ('id', 'sha256', 'success')}
        item['viewport'] = {'width': key[1], 'height': key[2]}
        item['errors'] = {'count': len(errors), 'samples': [portable_text(s) for s in errors[:2]]}
        requests = row.get('blocked_remote_requests', [])
        if not isinstance(requests, list) or len(requests) > 50 or any(not isinstance(url, str) or len(url) > 4096 for url in requests):
            raise EvidenceError('Remote-request evidence exceeds its bound')
        try:
            hosts = {urlsplit(url).hostname for url in requests if urlsplit(url).hostname}
        except ValueError as error:
            raise EvidenceError('Malformed remote-request URL') from error
        if any(len(host) > 253 for host in hosts):
            raise EvidenceError('Remote-request host exceeds its bound')
        item['blocked_remote_requests'] = {'recorded_count': len(requests), 'hosts': sorted(hosts)[:4]}
        item['layout'] = {k: layout[k] for k in ('viewport_width', 'scroll_width', 'visible_rendering_surfaces') if isinstance(layout, dict) and type(layout.get(k)) in {int, float} and math.isfinite(layout[k])}
        item['reviewed_state_checks'] = [{'key': k, **{name: state_value(state[k]) for name, state in zip(('before', 'after', 'reset'), states) if k in state and primitive(state[k])}} for k in required]
        if row.get('failure'):
            item['failure'] = portable_text(row['failure'], 180)
        checks.append(item)
    blockers = []
    if observed != expected:
        blockers.append(f'{len(expected - observed)} required source/viewport checks are missing')
    if report.get('manifest_sha256') != manifest_hash:
        blockers.append('Raw report is not bound to the current reviewed manifest bytes')
    if report.get('offline') is not True or report.get('downloads') is not False:
        blockers.append('Offline execution without downloads is unproven')
    if report.get('scope') != 'local Chromium browser' or not isinstance(report.get('browser_version'), str) or not report['browser_version'].strip():
        blockers.append('Browser execution identity is missing or unsupported')
    if report.get('success') is not True or not all(row['success'] for row in checks):
        blockers.append('Browser checks are incomplete or unsuccessful')
    return {'schema_version': 1, 'kind': 'bounded-browser-qa-summary', 'validation_tool': 'scripts/check_phet.cjs',
            'manifest': Path(manifest_name).name, 'manifest_sha256': manifest_hash,
            'raw_report': {'filename': Path(report_name).name, 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)},
            'offline': report.get('offline') if type(report.get('offline')) is bool else None,
            'downloads': report.get('downloads') if type(report.get('downloads')) is bool else None,
            'physical_device_certification': 'pending', 'scope': portable_text(report.get('scope'), 80),
            'browser_version': portable_text(report.get('browser_version'), 80), 'success': not blockers,
            'total_checks': len(checks), 'expected_checks': len(expected),
            'passed_checks': sum(row['success'] for row in checks), 'blockers': blockers, 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/acquisition/phet-browser-checks.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.report.stat().st_size > 64 * 1024 * 1024 or args.manifest.stat().st_size > 4 * 1024 * 1024:
        parser.error('Report/manifest exceeds its size bound')
    try:
        result = summarize(args.report.read_bytes(), args.manifest.read_bytes(), manifest_name=args.manifest.name, report_name=args.report.name)
    except (EvidenceError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.error(portable_text(error, 300))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=True, separators=(',', ':')) + '\n')
    print(json.dumps({k: result[k] for k in ('success', 'passed_checks', 'expected_checks', 'physical_device_certification', 'blockers')}))


if __name__ == '__main__':
    main()
