#!/usr/bin/env python3
"""Validate the saved 1 TB source inventory offline; does not certify large bodies."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.atlas_model import load_navigation
from owl.catalog import capacity_plan, load_catalog, load_profiles, resolve_content
from owl.acquisition.pins import probe_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Save validation.json after all checks pass')
    args = parser.parse_args()
    directory = ROOT / 'catalog/acquisition/full-1tb-capacity-20260928'
    def read(name):
        return json.loads((directory / name).read_text())
    plan = read('plan.json')
    assets = load_catalog(ROOT / 'catalog/library.yaml')
    profile = load_profiles(ROOT / 'profiles')['full-1tb']
    selected, _, selection = resolve_content(assets, profile, resources_path=ROOT / 'catalog/resources.yaml')
    capacity = capacity_plan(selected, profile, selection)
    baseline = plan['baseline']
    assert baseline['content_bytes'] == capacity['content_bytes']
    assert baseline['modeled_other_bytes_before_reserve'] == capacity['planned_final_bytes'] - capacity['content_bytes']
    assert baseline['reader_file_bytes'] == capacity['pinned_reader_bytes']
    assert baseline['reader_budget_bytes'] == selection['readers_budget_bytes']
    assert baseline['in_place_peak_budget_bytes'] == capacity['in_place_peak_budget_bytes']
    assert sum(a['budget_bytes'] for a in plan['allocations']) == plan['additional_headroom_bytes']
    assert capacity['capacity_bytes'] - capacity['in_place_peak_budget_bytes'] == plan['additional_headroom_bytes']
    target = plan['packing_target']
    assert target['library_and_support_ceiling_bytes'] + profile['reserve_bytes'] == profile['capacity_bytes']
    assert profile['capacity_bytes'] + target['filesystem_and_partition_margin_bytes'] == target['nominal_drive_bytes']
    downloads, readable, manifests = [], [], ['plan.json']
    total = 0
    for allocation in plan['allocations']:
        if 'manifest' not in allocation:
            assert allocation['enumerated_bytes'] == 0
            continue
        rows = read(allocation['manifest'])
        manifests.append(allocation['manifest'])
        assert len(rows) == allocation['file_count']
        amount = sum(r['retained_bytes'] if r['format'] == 'zip' else r['size_bytes'] for r in rows)
        assert amount == allocation['enumerated_bytes'] <= allocation['budget_bytes']
        total += amount
        for row in rows:
            assert row['status'] == 'candidate_not_admitted'
            assert row['source_url'].startswith('https://')
            assert type(row['size_bytes']) is int and row['size_bytes'] > 0
            assert type(row['body_verified']) is bool
            assert row['verification_evidence'].startswith('evidence/')
            assert (directory / row['verification_evidence']).is_file()
            if row['sha256'] is not None:
                assert re.fullmatch('[0-9a-f]{64}', row['sha256'])
            if row['body_verified']:
                assert row['sha256'] is not None and row['pages'] > 0
            downloads.append(row)
            if row['format'] == 'zip':
                assert row['expanded_bytes'] == sum(m['size_bytes'] for m in row['members'])
                assert row['retained_bytes'] == row['size_bytes'] + row['expanded_bytes']
                assert len({m['path'] for m in row['members']}) == len(row['members'])
                for member in row['members']:
                    parts = member['path'].replace('\\', '/').split('/')
                    assert '..' not in parts and not member['path'].startswith(('/', '\\'))
                    assert not re.match(r'^[A-Za-z]:', member['path'])
                    assert re.fullmatch('[0-9a-f]{8}', member['zip_crc32'])
                    if member.get('format') == 'pdf':
                        assert member['verification'] == 'pdf_signature_verified'
                        assert member['pdf_signature'].startswith('%PDF-')
                        readable.append(member)
            else:
                readable.append(row)
    assert len({r['id'] for r in downloads}) == len(downloads)
    assert len({r['source_url'] for r in downloads}) == len(downloads)
    assert not {r['source_url'] for r in downloads}.intersection(a.get('source_url') for a in assets)
    assert len({r['id'] for r in readable}) == len(readable)
    assert not {r['id'] for r in downloads + readable}.intersection(a['id'] for a in assets)
    assert total == plan['totals']['exact_enumerated_candidate_bytes']
    assert capacity['planned_final_bytes'] + total == plan['totals']['modeled_library_and_support_bytes']
    assert target['library_and_support_ceiling_bytes'] - (capacity['planned_final_bytes'] + total) == plan['totals']['unfilled_growth_allowance_bytes']
    assert len(downloads) == plan['totals']['candidate_download_count']
    assert len(readable) == plan['totals']['draft_pseudoindexes']
    assert {p.stem for p in (directory / 'pseudoindexes').glob('*.yaml')} == {r['id'] for r in readable}
    assert all(r['pseudoindex'] == 'pseudoindexes/' + r['id'] + '.yaml' for r in readable)
    # Resolve the temp root to avoid platform /var -> /private/var symlink aliases.
    with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        navigation = Path(temporary)
        shutil.copyfile(ROOT / 'catalog/navigation/topics.yaml', navigation / 'topics.yaml')
        shutil.copytree(directory / 'pseudoindexes', navigation / 'assignments')
        nav = load_navigation(navigation, readable)
    assert not nav['sections']
    usgs = [r for r in downloads if r['id'].startswith('usgs_')]
    checks = {r['asset_id']: r for r in read('evidence/usgs-verification.json')}
    for row in usgs:
        probe = checks[row['id']]
        assert row['source_url'] == probe['source_url'] and '/Current/' not in row['source_url']
        assert row['size_bytes'] == probe['observed_size_bytes'] == int(probe['head']['headers']['content-length'])
        assert row['publisher_metadata_size_bytes'] == probe['publisher_metadata_size_bytes']
        assert probe['prefix']['headers']['content-range'] == f"bytes 0-63/{row['size_bytes']}"
        assert probe['head']['headers']['etag'] == probe['prefix']['headers']['etag']
        assert probe['status'] == row['verification'] == 'headers_and_pdf_signature_verified'
        assert abs(probe['metadata_size_delta_bytes']) <= 1
        assert row['scale'] == 24000
    assert len({r['gnis_cell_id'] for r in usgs}) == len(usgs)
    canada = read('canada-nearby.json')
    checks = {r['sheet_id']: r for r in read('evidence/canada-verification.json')}
    assert len({r['sheet_id'] for r in canada}) == len(canada)
    for row in canada:
        probe = checks[row['sheet_id']]
        assert row['source_url'] == probe['source_url']
        assert row['retained_bytes'] == probe['retained_bytes']
        assert row['size_bytes'] == probe['size_bytes'] == int(probe['head']['headers']['content-length'])
        assert row['verification'] == probe['status'] == 'zip_directory_and_pdf_member_signatures_verified'
        pdfs = {m['path'] for m in row['members'] if m.get('format') == 'pdf'}
        assert pdfs == {m['path'] for m in probe['pdf_member_probes']}
        assert all(m['status'] == 'pdf_signature_verified' for m in probe['pdf_member_probes'])
    archives = read('archives.json')
    checks = {r['asset_id']: r for r in read('evidence/archive-verification.json')}
    for row in archives:
        probe = checks[row['id']]
        assert row['source_url'] == probe['source_url']
        assert row['sha256'] == probe['publisher_sha256']
        assert row['size_bytes'] == probe['size_bytes'] == int(probe['head']['headers']['content-length'])
        assert probe['status'] == row['verification'] == 'headers_publisher_hash_and_zim_header_verified'
        assert not probe['body_verified'] and not row['body_verified']
    school = read('school.json')
    schools_by_id = {r['id']: r for r in school}
    checks = {r['id']: r for r in read('evidence/school-verification.json')}
    for row in school:
        probe = checks[row['id']]
        assert row['source_url'] == probe['source_url']
        assert row['size_bytes'] == probe['size_bytes'] == int(probe['head']['headers']['content-length'])
        assert probe['status'] == 'headers_and_pdf_signature_verified'
        assert probe['head']['headers']['etag'] == probe['prefix']['headers']['etag']
        assert all(c['language'] == 'English' for c in row['components'])
    kindergarten = read('ckla-kindergarten.json')
    assert all(row == schools_by_id[row['id']] for row in kindergarten)
    assert {row['unit'] for row in kindergarten} == set(range(1, 11))
    units = read('school-units.json')
    assert len(units['units']) == units['included_pages']
    assert units['included_pages'] + units['excluded_pages'] == units['publisher_records']
    assert all(u['components'] and not u['instructional_completeness_reviewed'] for u in units['units'])
    assert {c['asset_id'] for u in units['units'] for c in u['components'] if c['selected']} == set(schools_by_id)
    full = {r['id']: r for name in ['evidence/kindergarten-verification.json', 'evidence/practical-verification.json'] for r in read(name) if r['body_verified']}
    for row in readable:
        if row['body_verified']:
            assert row['sha256'] == full[row['id']]['sha256'] and row['size_bytes'] == full[row['id']]['size_bytes']
    requests = read('source-probe-requests.json')['requests']
    assert len(requests) == len(downloads)
    by_id = {r['id']: r for r in downloads}
    class ValidationOnly:
        def probe(self, request):
            row = by_id[request['id']]
            assert request['url'] == row['source_url']
            assert request['expected_size_bytes'] == row['size_bytes']
            assert request.get('expected_sha256') == row['sha256']
            return {'status': 'pending'}
    for start in range(0, len(requests), 100):
        probe_manifest({'schema_version': 1, 'requests': requests[start:start + 100]}, ValidationOnly())
    body_count = sum(r['body_verified'] for r in readable)
    assert body_count == plan['totals']['candidate_bodies_verified_this_pass']
    # Evidence for HEADs must never imply full or partial response-body downloads.
    def check_head_bytes(value):
        if isinstance(value, dict):
            if 'body_bytes_received' in value and 'requested_range' not in value:
                assert value['body_bytes_received'] == 0
            for item in value.values():
                check_head_bytes(item)
        elif isinstance(value, list):
            for item in value:
                check_head_bytes(item)
    for path in (directory / 'evidence').glob('*verification.json'):
        check_head_bytes(json.loads(path.read_text()))
    # Every smaller expansion reuses this inventory; no second source catalog.
    preset_path = ROOT / 'catalog/acquisition/preset-capacity-20260929.json'
    preset_document = json.loads(preset_path.read_text())
    assert preset_document['schema_version'] == 1
    by_candidate_id = {row['id']: row for row in downloads}
    profiles = load_profiles(ROOT / 'profiles')
    preset_reports = []
    assert {row['profile'] for row in preset_document['presets']} == {
        'flash-16gb', 'critical-64gb', 'compact-256gb', 'standard-512gb', 'full-1tb'}
    assert len(preset_document['presets']) == 5
    for name, digest in preset_document['inventory_manifest_sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    for preset in preset_document['presets']:
        profile = profiles[preset['profile']]
        current, unresolved, selection = resolve_content(assets, profile, resources_path=ROOT / 'catalog/resources.yaml')
        assert not unresolved and not selection['incomplete_resources']
        cap = capacity_plan(current, profile, selection)
        assert set(preset['current_build_asset_ids']) == {row['id'] for row in current}
        assert preset['current_build_resource_ids'] == profile['default_resources']
        assert preset['current_build_file_bytes'] == cap['content_bytes']
        assert preset['current_build_modeled_support_bytes'] == cap['planned_final_bytes'] - cap['content_bytes']
        assert preset['pinned_reader_bytes'] == cap['pinned_reader_bytes']
        assert preset['reader_total_budget_bytes'] == profile['readers_budget_bytes']
        ids = preset['candidate_download_ids']
        assert len(set(ids)) == len(ids) == preset['candidate_download_count']
        sources = [by_candidate_id[identity] for identity in ids]
        retained = sum(row.get('retained_bytes', row['size_bytes']) for row in sources)
        assert retained == preset['candidate_retained_bytes']
        assert cap['content_bytes'] + retained == preset['expanded_library_file_bytes']
        final_bytes = cap['planned_final_bytes'] + retained
        assert final_bytes == preset['expanded_library_and_support_bytes']
        ceiling = preset['library_and_support_ceiling_bytes']
        assert final_bytes <= ceiling
        assert ceiling - final_bytes == preset['unfilled_growth_bytes']
        assert ceiling + preset['free_space_reserve_bytes'] == profile['capacity_bytes']
        assert preset['free_space_reserve_bytes'] == profile['reserve_bytes']
        assert profile['capacity_bytes'] + preset['filesystem_and_partition_margin_bytes'] == preset['nominal_drive_bytes']
        assert sum(row['sha256'] is None for row in sources) == preset['candidate_downloads_missing_sha256']
        groups = {group['series']: set(group['grades']) for group in preset['school_groups']}
        expected_school = {row['id'] for row in school if any(
            groups.get(component['series'], set()).intersection(component['grades'])
            for component in row['components'])}
        assert set(ids).intersection(schools_by_id) == expected_school
        scope = preset['map_selection']
        expected_maps = {row['id'] for row in usgs if scope['all_full_inventory_maps'] or
                         set(row['states']).intersection(scope['usgs_states']) or
                         ('MA' in row['states'] and set(row['counties']).intersection(scope['usgs_massachusetts_counties']))}
        assert set(ids).intersection(row['id'] for row in usgs) == expected_maps
        assert set(ids).intersection(row['id'] for row in canada) == ({row['id'] for row in canada} if scope['all_full_inventory_maps'] else set())
        preset_reports.append({'profile': preset['profile'], 'modeled_bytes': final_bytes,
                               'ceiling_bytes': ceiling, 'unfilled_growth_bytes': ceiling - final_bytes})
    report = {
        'status': 'passed', 'checked_on': plan['reviewed_on'],
        'checks': ['Baseline and decimal drive capacity reconcile', 'No duplicate selected source URLs, asset IDs or USGS cell IDs', 'Source probes match selected manifests', 'Canadian retained bytes include every extracted member', 'English curriculum component inventory and kindergarten subset reconcile', 'All readable candidates have valid per-asset navigation assignments', 'No invented internal sections or PDF page links', 'Full body hash evidence is distinguished from header/range checks'],
        'candidate_download_count': len(downloads), 'draft_pseudoindex_count': len(readable),
        'validated_assignments': len(nav['assignments']), 'pseudoindex_file_bytes': sum(p.stat().st_size for p in (directory / 'pseudoindexes').glob('*.yaml')),
        'exact_enumerated_candidate_bytes': total, 'modeled_library_and_support_bytes': capacity['planned_final_bytes'] + total,
        'fully_downloaded_and_hashed_files': body_count, 'all_candidate_body_integrity_verified': False, 'editorial_adequacy_established': False,
        'preset_capacity_selections': preset_reports,
        'preset_capacity_manifest_sha256': hashlib.sha256(preset_path.read_bytes()).hexdigest(),
        'verification_evidence_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((directory / 'evidence').glob('*verification.json'))},
        'manifest_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in manifests + ['school-units.json', 'ckla-kindergarten.json', 'source-probe-requests.json', 'school-excluded.json', 'rejected-sources.json']},
    }
    if args.write:
        (directory / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
