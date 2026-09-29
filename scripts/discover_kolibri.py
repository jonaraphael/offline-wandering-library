#!/usr/bin/env python3
"""Freeze bounded public Kolibri lesson metadata; never download lesson bodies."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.metadata import Fetcher
from owl.acquisition.capture import normalize_manifest
from owl.acquisition.supervisor import read
from owl.safety import atomic_write, reject_symlinks, sha256_file

BASE = 'https://studio.learningequality.org'
HEX = re.compile(r'[a-f0-9]{32}')


def identity(channel):
    return {k: channel[k] for k in ('id', 'version', 'last_published')}


def choose_files(node):
    """One media rendition, all available English caption/exercise companions."""
    files = node.get('files', [])
    main = [f for f in files if not f.get('supplementary') and not f.get('thumbnail')]
    selected = [f for f in files if f.get('thumbnail') or
                f.get('supplementary') and (f.get('lang') or {}).get('lang_code') == 'en']
    if node['kind'] == 'video':
        ranks = {'high_res_video': 0, 'low_res_video': 1}
        video = sorted((f for f in main if f['extension'] in {'mp4', 'webm'}),
                       key=lambda f: (ranks.get(f.get('preset'), 2), f['priority'], f['checksum']))
        if video:
            selected.append(video[0])
        selected += [f for f in main if f['extension'] not in {'mp4', 'webm'}]
    else:
        selected += main
    return sorted(selected, key=lambda f: (f['checksum'], f['extension']))


def discover(selection, fetcher):
    limits = selection['limits']
    if not (1 <= limits['requests'] <= 200 and 0 < limits['metadata_bytes'] <= 128 * 1024**2
            and 1 <= limits['nodes'] <= 30000 and 1 <= limits['files'] <= 30000):
        raise ValueError('Unbounded discovery selection')
    requests, total = 0, 0
    def fetch(url):
        nonlocal requests, total
        requests += 1
        if requests > limits['requests']:
            raise ValueError('Metadata request count exceeded')
        body = fetcher.fetch(url, max_bytes=min(8*1024**2, limits['metadata_bytes']-total))
        total += len(body)
        return json.loads(body)

    nodes, courses, observed_channels, issues = [], [], [], []
    seen_nodes = set()
    for channel in selection['channels']:
        cid = channel['id']
        if not HEX.fullmatch(cid):
            raise ValueError('Invalid channel identity')
        current = fetch(BASE + '/api/public/v2/channel/' + cid + '/')
        if identity(current) != identity(channel) or current['lang_code'] != 'en':
            raise ValueError('Published channel revision or language changed')
        observed_channels.append(identity(current))
        for course in channel['courses']:
            course_id = course['id']
            if not HEX.fullmatch(course_id):
                raise ValueError('Invalid course identity')
            params = {'channel_id': cid, 'descendant_of': course_id, 'max_results': '250'}
            cursors, count = set(), 0
            while params is not None:
                url = BASE + '/api/public/v2/contentnode/?' + urlencode(sorted(params.items()))
                if url in cursors:
                    raise ValueError('Publisher repeated a pagination cursor')
                cursors.add(url)
                page = fetch(url)
                for node in page['results']:
                    if (not HEX.fullmatch(node['id']) or node['id'] in seen_nodes
                            or node['channel_id'] != cid
                            or not course['lft'] < node['lft'] < node['rght'] < course['rght']):
                        raise ValueError('Duplicate or out-of-scope course node')
                    if len(nodes) >= limits['nodes']:
                        raise ValueError('Node count exceeds bound')
                    seen_nodes.add(node['id'])
                    evidence = {k: v for k, v in fetcher.evidence[-1].items() if k != 'cached'} if fetcher.evidence else {}
                    nodes.append(dict(node, owl_course_id=course_id, owl_resource_id=channel['resource_id'],
                                      owl_metadata_evidence=evidence))
                    count += 1
                params = page['more']
                if params is not None:
                    if (set(params) - {'channel_id', 'descendant_of', 'max_results', 'cursor'}
                            or params.get('channel_id') != cid or params.get('descendant_of') != course_id
                            or str(params.get('max_results')) != '250'):
                        raise ValueError('Pagination changed frozen subject scope')
            expected = (course['rght'] - course['lft'] - 1) // 2
            if count != expected:
                issues.append({'id': course_id, 'kind': 'incomplete_course_inventory', 'expected': expected, 'actual': count})
            courses.append(dict(course, channel_id=cid, descendants=count, expected_descendants=expected))

    files, works = {}, {}
    for node in nodes:
        if node['kind'] == 'topic':
            continue
        cid = node['content_id']
        if not HEX.fullmatch(cid):
            raise ValueError('Invalid stable content identity')
        lang = (node.get('lang') or {}).get('lang_code')
        if lang != 'en':
            issues.append({'id': node['id'], 'kind': 'non_english_lesson', 'language': lang})
        selected = choose_files(node)
        if cid in works:
            works[cid]['aliases'].append(node['id'])
            if works[cid]['file_ids'] != [f['checksum'] + '.' + f['extension'] for f in selected]:
                issues.append({'id': node['id'], 'kind': 'duplicate_content_different_files'})
            continue
        works[cid] = {'id': cid, 'node_id': node['id'], 'kind': node['kind'], 'title': node['title'],
                      'course_id': node['owl_course_id'], 'resource_id': node['owl_resource_id'],
                      'aliases': [], 'file_ids': []}
        if node['kind'] == 'video' and not any(f['extension'] in {'vtt', 'srt'} for f in selected):
            issues.append({'id': node['id'], 'kind': 'english_captions_not_in_inventory'})
        if not node.get('license_name') or node['license_name'] == 'Special Permissions':
            issues.append({'id': node['id'], 'kind': 'publisher_permission_scope_review',
                           'terms': node.get('license_description', '')[:500]})
        if node['kind'] not in {'video', 'exercise', 'document', 'audio'}:
            issues.append({'id': node['id'], 'kind': 'unsupported_essential_format', 'format': node['kind']})
        if not selected:
            issues.append({'id': node['id'], 'kind': 'missing_files'})
        for f in selected:
            md5, ext = f['checksum'], f['extension']
            if (not HEX.fullmatch(md5) or not re.fullmatch('[a-z0-9]{1,12}', ext)
                    or type(f['file_size']) is not int or f['file_size'] <= 0
                    or f['storage_url'] != '/content/storage/' + md5[0] + '/' + md5[1] + '/' + md5 + '.' + ext):
                raise ValueError('Malformed publisher file identity or size')
            key = md5 + '.' + ext
            works[cid]['file_ids'].append(key)
            if not f['available']:
                issues.append({'id': node['id'], 'kind': 'unavailable_dependency', 'file': key})
            record = {'id': key, 'source_url': urljoin(BASE, f['storage_url']), 'size_bytes': f['file_size'],
                      'publisher_checksums': {'md5': md5}, 'format': ext}
            if key in files and any(files[key][k] != v for k, v in record.items()):
                raise ValueError('Conflicting metadata for identical publisher file')
            entry = files.setdefault(key, dict(record, resource_ids=[], work_ids=[], presets=[]))
            for name, value in (('resource_ids', node['owl_resource_id']), ('work_ids', cid), ('presets', f['preset'])):
                if value not in entry[name]:
                    entry[name].append(value)
            if len(files) > limits['files']:
                raise ValueError('File count exceeds bound')
    return {'schema_version': 1, 'kind': 'kolibri-pending-inventory', 'content_ready': False,
            'channels': observed_channels, 'courses': courses, 'nodes': nodes,
            'works': list(works.values()), 'files': list(files.values()), 'issues': issues,
            'coverage_gaps': selection.get('coverage_gaps', []), 'metadata_bytes': total,
            'request_count': requests, 'metadata_evidence': [
                {k: v for k, v in row.items() if k != 'cached'} for row in fetcher.evidence],
            'download_bytes': sum(f['size_bytes'] for f in files.values())}


def freeze_pilot(inventory, selection, inventory_sha256):
    """Small format-review selection; source receipts cannot approve lessons."""
    nodes = {n['id']: n for n in inventory['nodes']}
    courses = set(selection['pilot_course_ids'])
    if not courses <= {c['id'] for c in inventory['courses']}:
        raise ValueError('Pilot course is outside frozen inventory')
    works = []
    for cid in sorted(courses):
        for kind in ('exercise', 'video'):
            candidates = sorted((w for w in inventory['works'] if w['course_id'] == cid and w['kind'] == kind),
                                key=lambda w: w['node_id'])
            if candidates:
                works.append(candidates[0])
    file_works = {}
    for work in works:
        for key in work['file_ids']:
            file_works.setdefault(key, []).append(work)
    if not 1 <= len(file_works) <= 100:
        raise ValueError('Format pilot must contain1–100 unique files')
    sources = []
    for f in sorted(inventory['files'], key=lambda f: f['id']):
        if f['id'] not in file_works:
            continue
        owners = file_works[f['id']]
        evidence = {json.dumps(nodes[w['node_id']]['owl_metadata_evidence'], sort_keys=True):
                    nodes[w['node_id']]['owl_metadata_evidence'] for w in owners}
        sources.append({'id': 'kolibri_' + f['id'].replace('.', '_'), 'source_url': f['source_url'],
                        'version': 'Published Kolibri metadata frozen by inventory SHA256 ' + inventory_sha256,
                        'resource_ids': sorted({w['resource_id'] for w in owners}), 'size_bytes': f['size_bytes'],
                        'sha256': None, 'publisher_checksums': f['publisher_checksums'],
                        'metadata_evidence': list(evidence.values()), 'purpose': 'quarantine format-review input',
                        'work_ids': sorted(w['id'] for w in owners)})
    size = sum(s['size_bytes'] for s in sources)
    if size > 512*1024**2:
        raise ValueError('Pilot exceeds512MiB source cap')
    return normalize_manifest({'schema_version': 1, 'kind': 'acquisition', 'id': selection['id']+'-format-pilot',
        'profile': 'full-1tb', 'content_ready': False, 'sources': sources,
        'selection_inventory_sha256': inventory_sha256, 'selected_work_ids': [w['id'] for w in works],
        'budget': {'download_bytes': size, 'expanded_bytes': 0, 'preview_bytes': 0,
                   'scratch_bytes': 1048576, 'cache_bytes': 0},
        'review_requirements': ['Verify publisher MD5 and exact lengths, then observe whole-file SHA256 in quarantine.',
            'Inspect complete exercises, prompts, widgets, hints, figures and supplied answers before ordinary rendering.',
            'Resolve channel permission scope, missing captions and changed-rendition aliases before content admission.',
            'Pilot is format evidence only; no lesson, course or collection completeness claim.']})


def freeze_exercises(inventory, inventory_sha256):
    """Freeze every unique exercise package for bounded format census only."""
    nodes = {n['id']: n for n in inventory['nodes']}
    files = {f['id']: f for f in inventory['files']}
    owners = {}
    for work in inventory['works']:
        if work['kind'] != 'exercise':
            continue
        packages = [key for key in work['file_ids'] if files[key]['format'] == 'perseus']
        if len(packages) != 1:
            raise ValueError('Each exercise must identify exactly one complete package')
        owners.setdefault(packages[0], []).append(work)
    if not 1 <= len(owners) <= 1500:
        raise ValueError('Exercise census requires1–1500 unique packages')
    sources = []
    for key, works in sorted(owners.items()):
        f = files[key]
        evidence = {json.dumps(nodes[w['node_id']]['owl_metadata_evidence'], sort_keys=True):
                    nodes[w['node_id']]['owl_metadata_evidence'] for w in works}
        sources.append({'id': 'kolibri_' + key.replace('.', '_'), 'source_url': f['source_url'],
                        'version': 'Published Kolibri metadata frozen by inventory SHA256 ' + inventory_sha256,
                        'resource_ids': sorted({w['resource_id'] for w in works}),
                        'size_bytes': f['size_bytes'], 'sha256': None,
                        'publisher_checksums': f['publisher_checksums'],
                        'metadata_evidence': list(evidence.values()),
                        'work_ids': sorted(w['id'] for w in works),
                        'purpose': 'quarantine complete exercise-package format census'})
    size = sum(s['size_bytes'] for s in sources)
    if size > 1024**3:
        raise ValueError('Exercise census exceeds1GiB source cap')
    return normalize_manifest({'schema_version': 1, 'kind': 'acquisition',
        'id': 'kolibri-english-core-exercise-census-v1', 'profile': 'full-1tb',
        'content_ready': False, 'sources': sources, 'selection_inventory_sha256': inventory_sha256,
        'budget': {'download_bytes': size, 'expanded_bytes': 0, 'preview_bytes': 0,
                   'scratch_bytes': 1048576, 'cache_bytes': 0},
        'review_requirements': ['Inventory every assessment, figure and widget before ordinary rendering.',
            'Resolve complete lesson dependencies, publisher permission scope and captions separately.',
            'Format census is not course completeness, content approval or redistribution permission.']})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection', type=Path, required=True)
    p.add_argument('--cache', type=Path, default=ROOT / '.owl/acquisition/kolibri-discovery-cache')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--offline', action='store_true')
    p.add_argument('--pilot-manifest', type=Path)
    p.add_argument('--exercise-manifest', type=Path)
    args = p.parse_args()
    result = discover(read(args.selection), Fetcher(args.cache, offline=args.offline))
    result['selection_sha256'] = sha256_file(args.selection)
    data = (json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':'))+'\n').encode()
    if len(data) > 64 * 1024**2:
        raise ValueError('Detailed inventory exceeds64MiB')
    reject_symlinks(args.output)
    atomic_write(args.output, data)
    if args.pilot_manifest:
        pilot = freeze_pilot(result, read(args.selection), hashlib.sha256(data).hexdigest())
        reject_symlinks(args.pilot_manifest)
        payload = (json.dumps(pilot, sort_keys=True, indent=2)+'\n').encode()
        if args.pilot_manifest.exists() and args.pilot_manifest.read_bytes() != payload:
            raise ValueError('Frozen pilot differs; select a new manifest identity/path')
        atomic_write(args.pilot_manifest, payload)
    if args.exercise_manifest:
        exercise_manifest = freeze_exercises(result, hashlib.sha256(data).hexdigest())
        reject_symlinks(args.exercise_manifest)
        payload = (json.dumps(exercise_manifest, sort_keys=True, indent=2)+'\n').encode()
        if args.exercise_manifest.exists() and args.exercise_manifest.read_bytes() != payload:
            raise ValueError('Frozen exercise census differs; select a new version/path')
        atomic_write(args.exercise_manifest, payload)
    print(json.dumps({'content_ready': False, 'courses': len(result['courses']), 'nodes': len(result['nodes']),
                      'works': len(result['works']), 'unique_files': len(result['files']),
                      'download_bytes': result['download_bytes'], 'issues': dict(Counter(r['kind'] for r in result['issues'])),
                      'detail': str(args.output)}, sort_keys=True))


if __name__ == '__main__':
    main()
