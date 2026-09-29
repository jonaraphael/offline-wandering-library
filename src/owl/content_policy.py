"""Fail-closed catalog admission against the bundled, machine-readable policy.

This checks declarations, not downloaded bytes or factual content. Structural
catalog loading remains available for inspection of rejected records. Admission
commands and the builder must call require_content_policy before writing.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import yaml


class ContentPolicyError(ValueError):
    pass

POLICY_PATH = Path(__file__).with_suffix('.json')


def _strings(value):
    return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value) and len(set(value)) == len(value)


def load_policy() -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContentPolicyError(f'Duplicate content-policy key: {key}')
            result[key] = value
        return result

    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'), object_pairs_hook=unique)
    keys = {'schema_version', 'id', 'allowed_materialization', 'forbidden_asset_fields',
            'roles', 'requirements', 'forbidden_true_fields', 'preferred_book_format', 'direct_reading_formats'}
    if not isinstance(policy, dict) or set(policy) != keys or type(policy['schema_version']) is not int or policy['schema_version'] != 1:
        raise ContentPolicyError('Invalid content policy schema')
    if not isinstance(policy['id'], str) or not policy['id']:
        raise ContentPolicyError('Content policy requires an id')
    for key in ('allowed_materialization', 'forbidden_asset_fields', 'forbidden_true_fields'):
        if not _strings(policy[key]):
            raise ContentPolicyError(f'Invalid content policy {key}')
    if set(policy['allowed_materialization']) - {'download', 'unpack'}:
        raise ContentPolicyError('Unsupported content materialization operation')
    roles = policy['roles']
    if not isinstance(roles, dict) or set(roles) != {'document', 'companion', 'package', 'software', 'search_index'} or any(not _strings(v) for v in roles.values()):
        raise ContentPolicyError('Invalid content policy roles')
    if not _strings(policy['direct_reading_formats']) or not set(policy['direct_reading_formats']) <= set(roles['document']):
        raise ContentPolicyError('Direct reading formats must be allowed document formats')
    if policy['preferred_book_format'] not in roles['document']:
        raise ContentPolicyError('Preferred book format must be an allowed document format')
    if not isinstance(policy['requirements'], list):
        raise ContentPolicyError('Invalid content policy requirements')
    for rule in policy['requirements']:
        if (not isinstance(rule, dict) or set(rule) != {'formats', 'roles', 'values'} or
                not _strings(rule['formats']) or not _strings(rule['roles']) or
                set(rule['roles']) - roles.keys() or
                not set(rule['formats']) <= set().union(*(set(roles[r]) for r in rule['roles'])) or
                not isinstance(rule['values'], dict) or not rule['values']):
            raise ContentPolicyError('Invalid content policy requirement')
        for field, values in rule['values'].items():
            if (not field or not isinstance(values, list) or not values or
                    any(type(v) not in (str, bool) for v in values)):
                raise ContentPolicyError('Invalid content policy required values')
    return policy


def asset_role(asset: dict, policy: dict) -> str:
    # These roles reflect existing catalog semantics; an explicit label cannot
    # turn a book into software or hide a generated PDF among companion files.
    if str(asset.get('destination', '')).startswith('SOFTWARE/') or asset.get('resource_type') == 'software':
        return 'software'
    if asset.get('artifact_role') == 'search_index':
        return 'search_index'
    if asset.get('supporting_file') is True or (isinstance(asset.get('archive_member'), dict) and asset['archive_member'].get('document') is False):
        return 'package' if asset.get('format', '').lower() in policy['roles']['package'] else 'companion'
    return 'document'


def audit_assets(assets: list[dict]) -> dict:
    policy = load_policy()
    violations, counts, identities = [], Counter(), set()
    def issue(identity, rule, message):
        violations.append({'asset_id': identity, 'rule': rule, 'message': message})

    for number, asset in enumerate(assets):
        if not isinstance(asset, dict):
            issue(f'entry-{number}', 'invalid_asset', 'Asset must be an object')
            continue
        identity = asset.get('id')
        if not isinstance(identity, str) or not identity:
            issue(f'entry-{number}', 'invalid_asset', 'Asset id must be a nonempty string')
            continue
        if identity in identities:
            issue(identity, 'invalid_asset', 'Duplicate asset id')
        identities.add(identity)
        if asset.get('status', 'resolved') != 'resolved':
            issue(identity, 'not_download_ready', 'Unresolved entries are not finished downloadable content')
        if (not isinstance(asset.get('source_url'), str) or not asset['source_url'] or
                type(asset.get('size_bytes')) is not int or asset['size_bytes'] < 0 or
                not isinstance(asset.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', asset['sha256'])):
            issue(identity, 'missing_pin', 'Finished files require a source URL, exact byte size, and SHA-256')
        if not isinstance(asset.get('format'), str):
            issue(identity, 'invalid_format', 'Asset requires a format string')
            continue
        fmt = asset['format'].lower()
        role = asset_role(asset, policy)
        counts[role] += 1
        if 'artifact_role' in asset and asset['artifact_role'] != role:
            issue(identity, 'invalid_role', f'Catalog semantics require role {role}')
        if fmt not in policy['roles'][role]:
            issue(identity, 'format_not_allowed', f'{fmt!r} is not allowed for {role}')
        for field in policy['forbidden_asset_fields']:
            if field in asset:
                issue(identity, 'processing_forbidden', f'{field} requires build-time processing; select a finished download')
        operation = 'unpack' if 'archive_member' in asset else 'download'
        if operation not in policy['allowed_materialization']:
            issue(identity, 'operation_not_allowed', f'{operation} is not allowed')
        if 'materialization' in asset and asset['materialization'] != operation:
            issue(identity, 'operation_not_allowed', f'Expected {operation}; declared materialization cannot override the catalog')
        for field in policy['forbidden_true_fields']:
            if field in asset and asset[field] is not False:
                issue(identity, 'access_requirement', f'{field} must be false')
        for rule in policy['requirements']:
            if fmt in rule['formats'] and role in rule['roles']:
                for field, values in rule['values'].items():
                    if not any(type(asset.get(field)) is type(v) and asset.get(field) == v for v in values):
                        issue(identity, 'missing_requirement', f'{field} must be one of {json.dumps(values)} for {role}/{fmt}')
    failed = {v['asset_id'] for v in violations}
    return {'schema_version': 1, 'policy_id': policy['id'],
            'policy_sha256': hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
            'validation_scope': 'catalog declarations; not a download, offline playback, or license verification',
            'checked_assets': len(assets), 'noncompliant_assets': len(failed),
            'compliant': not violations, 'roles': dict(sorted(counts.items())),
            'violations': violations}


def require_content_policy(assets: list[dict]) -> None:
    from .catalog import CatalogError
    report = audit_assets(assets)
    if report['compliant']:
        return
    examples = '; '.join(f"{v['asset_id']}: {v['message']}" for v in report['violations'][:5])
    raise CatalogError(f"Content policy {report['policy_id']}: {report['noncompliant_assets']} noncompliant assets. "
                       f"{examples}. Run scripts/check_content_policy.py for the full JSON report.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalogs', type=Path, nargs='*', default=[Path('catalog/library.yaml')])
    args = parser.parse_args(argv)
    reports = []
    try:
        from .catalog import CatalogError, read_yaml
        for path in args.catalogs:
            document = read_yaml(path)
            if not isinstance(document, dict) or not isinstance(document.get('assets'), list):
                raise CatalogError(f'{path}: requires an assets list')
            reports.append({'catalog': str(path), **audit_assets(document['assets'])})
        print(json.dumps({'compliant': all(r['compliant'] for r in reports), 'catalogs': reports}, indent=2))
        return 0 if all(r['compliant'] for r in reports) else 1
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(json.dumps({'compliant': False, 'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
