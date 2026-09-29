#!/usr/bin/env python3
"""Freeze and audit one complete course from a combined, finished capture.

Package, media and retained thumbnails share one captured manifest so the
existing acquisition preview adapter can produce a complete ordinary edition.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.acquisition.capture import load_manifest, _digest, _owner, _receipt
from owl.acquisition.ocw_expansion import immutable_json
from owl.acquisition.ocw_package import inspect_package
from owl.acquisition.ocw_runtime import policy_for_inventory
from owl.safety import SafetyError, reject_symlinks


def captured_course_sources(staging, inventory):
    """Reverify exactly the sources used by this course, not unrelated courses."""
    manifest=load_manifest(staging/'manifest.json');digest=_digest(manifest)
    _owner(staging,digest)
    required={inventory['source_id'],*[m['id'] for m in inventory['media']]}
    selected=[source for source in manifest['sources'] if source['id'] in required
        or any(isinstance(binding,dict) and binding.get('source_id')==inventory['source_id']
            for binding in source.get('publisher_course_bindings', []))]
    if not required<={source['id'] for source in selected}:
        raise SafetyError('Course capture lacks an independently pinned required source')
    observed={}
    for source in selected:
        receipt=_receipt(staging,source,digest)
        if receipt is None:raise SafetyError('A required course source is not captured')
        observed[source['id']]=receipt
    return {s['id']:{**s,'sha256':observed[s['id']]['sha256']} for s in selected},observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-staging', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--link-repairs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preview-id')
    parser.add_argument('--offline-runtime-policy', action='store_true')
    args = parser.parse_args()
    for p in (args.inventory, args.link_repairs):
        reject_symlinks(p)
        if p.stat().st_size > 16 * 1024**2:
            raise SafetyError('Course preview control exceeds16MiB')
    inventory = json.loads(args.inventory.read_text())
    repairs = json.loads(args.link_repairs.read_text())
    if repairs.get('source_sha256') != inventory['source_sha256']:
        raise SafetyError('Course link repair review belongs to a different package')
    sources, observed = captured_course_sources(args.capture_staging, inventory)
    package = sources[inventory['source_id']]
    media_ids = {m['id'] for m in inventory['media']}
    dependencies = [source for sid, source in sources.items()
        if sid != package['id'] and sid not in media_ids
        and any(binding.get('source_id') == package['id']
            for binding in source.get('publisher_course_bindings', [])
            if isinstance(binding, dict))]
    if any(s.get('fullasset_metadata', {}).get('format') != 'jpg' for s in dependencies):
        raise SafetyError('Unexpected dependency in the frozen complete-course capture')
    spec = importlib.util.spec_from_file_location('owl_prepare_ocw_preview', ROOT / 'scripts/prepare_ocw_preview.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    recipe, templates = module.freeze(inventory, package, sources, dependencies, preview_id=args.preview_id)
    recipe['selection']['local_link_repairs'] = repairs['local_link_repairs']
    recipe['selection']['reviewed_html_omissions'] = repairs.get('reviewed_html_omissions', {})
    if args.offline_runtime_policy:
        recipe['selection']['reviewed_runtime_policies'] = policy_for_inventory(inventory)
    assets = {a['id']: a for a in templates['assets']}; assets[package['id']] = package
    audit = inspect_package(recipe, {package['id']: args.capture_staging / observed[package['id']]['relative_path']}, assets)
    for name, value in [('recipe.json', recipe), ('assets.json', templates), ('dependency-audit.json', audit)]:
        immutable_json(args.output / name, value)
    print(json.dumps({'content_ready': False, 'body_downloads': 0, 'files': audit['files'],
        'output_bytes': audit['output_bytes'], 'dependency_issues': len(audit['issues']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
