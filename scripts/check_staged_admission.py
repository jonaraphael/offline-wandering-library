#!/usr/bin/env python3
"""Compare a reviewed staging bundle with active selections; never publish it.

Records exact profile deltas and capacity accounting, verifies the capture review
binding, and rejects any change to the fixed small-preset selections. Detailed
evidence stays local; stdout is bounded for unattended acquisition follow-ups.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import validate_review_binding
from owl.acquisition.cli import _capacity
from owl.acquisition.model import build_inputs, validate_generation, validate_recipes
from owl.acquisition.supervisor import save
from owl.catalog import load_catalog, load_profiles, read_yaml, resolve_content, validate_catalog
from owl.safety import SafetyError, reject_symlinks, sha256_file

PROFILES = ('flash-16gb', 'critical-64gb', 'compact-256gb', 'standard-512gb', 'full-1tb')
FIXED_PROFILES = {'flash-16gb', 'critical-64gb'}
# Navigation has one assignment/section file per asset. Bound the whole bundle
# without tying admission to a particular catalog's current document count.
MAX_CONTROL_FILES = 10000
MAX_CONTROL_BYTES = 64 * 1024 * 1024


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def compare_selection(name, before, after):
    old = {a['id']: a for a in before}
    new = {a['id']: a for a in after}
    row = {'profile': name, 'before_count': len(old), 'after_count': len(new),
           'before_sha256': signature(sorted(old.values(), key=lambda a: a['id'])),
           'after_sha256': signature(sorted(new.values(), key=lambda a: a['id'])),
           'added_ids': sorted(new.keys() - old.keys()), 'removed_ids': sorted(old.keys() - new.keys()),
           'changed_ids': sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}
    if name in FIXED_PROFILES and old != new:
        raise SafetyError('Fixed small-preset selection changed: ' + name)
    return row


def control_members(candidate):
    members, total = [], 0
    for path in candidate.rglob('*'):
        reject_symlinks(path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise SafetyError('Staged bundle contains a non-regular control member')
        members.append(path)
        total += path.stat().st_size
        if len(members) > MAX_CONTROL_FILES or total > MAX_CONTROL_BYTES:
            raise SafetyError('Staged bundle exceeds its control-file count or byte budget')
    return sorted(members)


def inspect(candidate, fragment_path, receipt_path):
    for path in (candidate, fragment_path, receipt_path):
        reject_symlinks(path)
    members = control_members(candidate)
    fragment = read_yaml(fragment_path)
    validate_review_binding(fragment, receipt_path)
    stage = read_yaml(candidate / 'stage-report.json')
    if stage.get('source_fragment_sha256') != sha256_file(fragment_path):
        raise SafetyError('Staged bundle differs from its reviewed fragment')
    profiles = load_profiles(ROOT / 'profiles')
    if load_profiles(candidate / 'profiles') != profiles:
        raise SafetyError('Admission must preserve every profile definition')
    before = load_catalog(ROOT / 'catalog/library.yaml', profiles)
    after = load_catalog(candidate / 'library.yaml', profiles)
    old_assets = {a['id']: a for a in before}
    new_assets = {a['id']: a for a in after}
    admitted = validate_catalog({'schema_version': 1, 'assets': fragment.get('assets', [])}, profiles)
    admitted = {a['id']: a for a in admitted}
    if old_assets.keys() - new_assets.keys():
        raise SafetyError('Admission cannot remove existing catalog pins')
    for identity, asset in new_assets.items():
        if asset != old_assets.get(identity) and asset != admitted.get(identity):
            raise SafetyError('Candidate has an asset change outside the reviewed fragment: ' + identity)
    recipes = validate_recipes(read_yaml(candidate / 'library.yaml').get('acquisition_recipes', []))
    validate_generation(after, recipes)
    temporary = build_inputs(recipes)
    if temporary.keys() & {a['id'] for a in after}:
        raise SafetyError('Build-only source also appears in retained catalog')
    rows = []
    for name in PROFILES:
        old, _, _ = resolve_content(before, profiles[name], resources_path=ROOT / 'catalog/resources.yaml')
        new, unresolved, selection = resolve_content(after, profiles[name], resources_path=candidate / 'resources.yaml')
        row = compare_selection(name, old, new)
        plan = _capacity(new, profiles[name], selection, list(recipes.values()))
        if not plan['in_place_target_budget_fits']:
            raise SafetyError('Candidate does not fit profile capacity: ' + name)
        row.update({k: plan[k] for k in ('content_bytes', 'pinned_knowledge_bytes',
                                        'target_shortfall_bytes', 'acquisition_workspace_bytes', 'content_complete')})
        row['unresolved_assets'] = [a['id'] for a in unresolved]
        row['incomplete_resources'] = [r['id'] for r in selection['incomplete_resources']] if selection else []
        rows.append(row)
    return {'schema_version': 1, 'kind': 'staged-admission-invariants', 'checks_passed': True,
            'published': False, 'physical_device_certification': 'pending',
            'fragment_sha256': sha256_file(fragment_path), 'review_receipt_sha256': sha256_file(receipt_path),
            'candidate': str(candidate), 'candidate_files': {p.relative_to(candidate).as_posix(): sha256_file(p) for p in members},
            'build_only_source_count': len(temporary), 'build_only_source_bytes': sum(a['size_bytes'] for a in temporary.values()),
            'profiles': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'fragment', 'receipt', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.candidate, args.fragment, args.receipt)
    if args.output.exists() and read_yaml(args.output) != result:
        raise SafetyError('Admission evidence changed; choose a new output')
    save(args.output, result)
    print(json.dumps({'checks_passed': True, 'published': False, 'detail': str(args.output),
                      'profiles': [{k: r[k] for k in ('profile', 'after_count', 'pinned_knowledge_bytes',
                                                      'target_shortfall_bytes', 'content_complete')} for r in result['profiles']]}))


if __name__ == '__main__':
    main()
