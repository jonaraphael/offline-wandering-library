#!/usr/bin/env python3
"""Read pinned local ZIM inventories and freeze deterministic direct candidates.

No network, export, extraction, or writes to the source library are implemented.
"""
from collections import Counter
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.catalog import load_catalog
from owl.acquisition.capture import normalize_manifest
from owl.export_direct import ExportError, _archive_path, _source_identity
from owl.safety import atomic_write, reject_symlinks, sha256_file

DOCUMENTS = {'text/html', 'application/xhtml+xml', 'application/pdf'}
MAX_METADATA = 64 * 1024 * 1024
MAX_ENTRY = 16 * 1024 * 1024


def write(path, value):
    reject_symlinks(path)
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    if len(raw) > MAX_METADATA:
        raise ValueError('Metadata exceeds 64 MiB; narrow this inventory')
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, raw)


def capture_manifest(assets, recipe):
    sources = []
    for policy in recipe['sources']:
        asset = dict(assets[policy['source_asset_id']])
        record_hash = hashlib.sha256(json.dumps(asset, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        asset['profiles'] = []
        sources.append({'id': asset['id'], 'resource_ids': [policy['resource_id']], 'source_url': asset['source_url'],
            'version': asset['version'], 'size_bytes': asset['size_bytes'], 'sha256': asset['sha256'],
            'publisher_checksums': {}, 'fullasset_metadata': asset,
            'metadata_evidence': [{'url': asset['source_url'], 'sha256': record_hash, 'kind': 'catalog-record',
                'record_id': asset['id'], 'scope': 'Hash of canonical portable catalog asset metadata; not a publisher-page or resource-body hash'}]})
    return normalize_manifest({'schema_version': 1, 'kind': 'acquisition', 'id': 'direct-existing-originals-1tb',
        'profile': 'full-1tb', 'content_ready': False, 'sources': sources,
        'budget': {'download_bytes': sum(row['size_bytes'] for row in sources), 'expanded_bytes': 0,
                   'preview_bytes': 0, 'scratch_bytes': 0, 'cache_bytes': 0},
        'review_requirements': ['This batch captures original pinned ZIMs only; direct outputs still need explicit entry selection and preview review.',
            'Resolve the iFixit HTML-language mismatch and preserve complete guide steps, photographs, captions and notices.',
            'Reserve direct export, scratch and preview bytes separately; source capture is not content readiness.']})


def portable_evidence(document):
    """Keep identities/selection portable and detailed structure evidence local."""
    from copy import deepcopy
    result = deepcopy(document)
    result['detailed_evidence_sha256'] = hashlib.sha256((json.dumps(document, indent=2, sort_keys=True) + '\n').encode()).hexdigest()
    for source in result['sources']:
        source['topic_coverage'] = {key: {'candidate_count': len(entries), 'sample_entries': entries[:3]}
                                    for key, entries in source['topic_coverage'].items()}
        conflicts, replacements = [], []
        for row in source['candidates']:
            structure = row.pop('structure')
            language = structure.get('html_language')
            if language and not re.fullmatch(r'en(?:[-_].*)?', language, re.I):
                conflicts.append(row['entry'])
                row['language_status'] = 'Conflicting HTML language tag ' + language + '; English body-language review required'
            if structure.get('utf8_replacement_characters'):
                replacements.append(row['entry'])
                row['text_review_flag'] = 'Replacement characters observed; compare original text and rendered output before approval'
        source['language_tag_conflicts'] = {'count': len(conflicts), 'sample_entries': conflicts[:3]}
        source['text_character_review'] = {'count': len(replacements), 'sample_entries': replacements[:3]}
        groups = {}
        for row in source['candidates']:
            groups.setdefault(row['entry_sha256'], []).append(row)
        source['unique_candidate_document_bytes'] = sum(group[0]['size_bytes'] for group in groups.values())
        source['duplicate_entry_bodies'] = [{'sha256': digest, 'entries': [row['entry'] for row in group]}
                                           for digest, group in sorted(groups.items()) if len(group) > 1]
    return result


def inventory(source, asset, cache):
    """A cache hit reuses an earlier whole-file verification of unchanged input."""
    from libzim.reader import Archive, set_cluster_cache_max_size
    identity = list(_source_identity(source))
    if identity[2] != asset['size_bytes']:
        raise ValueError('Local ZIM size differs from the active catalog')
    reject_symlinks(cache)
    if cache.is_file() and cache.stat().st_size <= MAX_METADATA:
        previous = json.loads(cache.read_text())
        if (previous.get('source_identity') == identity and previous.get('source_sha256') == asset['sha256']
                and previous.get('inventory_complete') is True and previous.get('source_asset_id') == asset['id']):
            return previous
    if sha256_file(source) != asset['sha256'] or list(_source_identity(source)) != identity:
        raise ValueError('Local ZIM whole-file SHA256 mismatch or source changed')
    set_cluster_cache_max_size(2)
    archive = Archive(source)
    archive.dirent_cache_max_size = 4096
    if archive.all_entry_count > 1_000_000:
        raise ValueError('Inventory exceeds one million entries; review a larger bound')
    rows, exceptions, seen, counts = [], [], set(), Counter()
    for index in range(archive.all_entry_count):
        entry = archive._get_entry_by_id(index)
        if entry.is_redirect or not archive.has_entry_by_path(entry.path):
            continue
        entry = archive.get_entry_by_path(entry.path)
        if entry.is_redirect:
            continue
        item = entry.get_item()
        mime = item.mimetype.split(';')[0].strip().lower()
        counts[mime] += 1
        if mime not in DOCUMENTS:
            continue
        try:
            path = _archive_path(entry.path)
        except ExportError as error:
            if len(exceptions) >= 1000:
                raise ValueError('More than 1,000 unexportable document identities') from error
            exceptions.append({'entry': entry.path, 'title': entry.title, 'reason': str(error)[:500]})
            continue
        if path in seen:
            raise ValueError('Duplicate addressable ZIM document path')
        seen.add(path)
        rows.append({'entry': path, 'title': entry.title, 'mime': mime, 'size_bytes': item.size})
    if list(_source_identity(source)) != identity:
        raise ValueError('Source changed during local inventory')
    result = {'schema_version': 1, 'source_asset_id': asset['id'], 'source_sha256': asset['sha256'],
        'source_identity': identity, 'source_size_bytes': asset['size_bytes'], 'inventory_complete': True,
        'all_entry_count': archive.all_entry_count, 'mime_counts': dict(sorted(counts.items())),
        'documents': sorted(rows, key=lambda row: row['entry']), 'unexportable_documents': exceptions}
    write(cache, result)
    return result


class Structure(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = Counter()
        self.language = None
        self.text_characters = 0

    def handle_starttag(self, tag, attrs):
        self.counts[tag] += 1
        if tag == 'html':
            self.language = dict(attrs).get('lang')

    def handle_data(self, text):
        self.text_characters += len(text.strip())


def choose(rows, policy):
    """Whole entry candidates, exact identity; keyword matches never mean approval."""
    include = re.compile(policy['include_path'], re.I)
    exclude = [re.compile(value, re.I) for value in policy.get('exclude_patterns', [])]
    topics = {key: re.compile(value, re.I) for key, value in policy['topics'].items()}
    selected = []
    for row in rows:
        text = row['title'] if policy.get('match_title_only') else row['entry'] + ' ' + row['title']
        if not include.search(row['entry']) or any(pattern.search(text) for pattern in exclude):
            continue
        matches = sorted(topic for topic, pattern in topics.items() if pattern.search(text))
        if matches:
            selected.append({**row, 'topics': matches})
    # A selected chapter must not become a decontextualized book. Retain every
    # addressable document under its reviewed publisher book directory.
    group_patterns = [re.compile(value, re.I) for value in policy.get('context_group_patterns', [])]
    groups = {}
    for row in selected:
        for pattern in group_patterns:
            match = pattern.search(row['entry'])
            if match:
                groups.setdefault(match[1], set()).update(row['topics'])
                row['context_group'] = match[1]
                break
    by_path = {row['entry']: row for row in selected}
    for row in rows:
        text = row['entry'] + ' ' + row['title']
        if not include.search(row['entry']) or any(pattern.search(text) for pattern in exclude):
            continue
        for prefix, topics in groups.items():
            if row['entry'].startswith(prefix):
                current = by_path.setdefault(row['entry'], {**row, 'topics': sorted(topics), 'selection_reason': 'complete-book-context'})
                current['context_group'] = prefix
                break
    selected = sorted(by_path.values(), key=lambda row: row['entry'])
    if len(selected) > policy.get('max_candidates', 2000):
        raise ValueError('Candidate bound exceeded; narrow reviewed topic rules instead of truncating')
    return selected


def inspect_candidates(source, asset, inventory_record, policy):
    from libzim.reader import Archive
    identity = list(_source_identity(source))
    if identity != inventory_record['source_identity']:
        raise ValueError('Source changed since the verified inventory')
    archive = Archive(source)
    rows = choose(inventory_record['documents'], policy)
    for row in rows:
        item = archive.get_entry_by_path(row['entry']).get_item()
        if item.size != row['size_bytes'] or item.size > MAX_ENTRY:
            raise ValueError('Candidate changed or exceeds bounded local inspection')
        body = bytes(item.content)
        if len(body) != item.size:
            raise ValueError('Incomplete archive entry read')
        row.update(entry_sha256=hashlib.sha256(body).hexdigest(), review_status='pending', content_ready=False)
        if row['mime'] == 'application/pdf':
            row['structure'] = {'pdf_signature': body.startswith(b'%PDF-'), 'document_review': 'pending'}
        else:
            parser = Structure()
            text = body.decode('utf-8', errors='replace')
            parser.feed(text)
            parser.close()
            row['structure'] = {'html_language': parser.language, 'text_characters': parser.text_characters,
                'utf8_replacement_characters': text.count('\ufffd'),
                **{name: parser.counts[name] for name in ('img', 'table', 'figure', 'figcaption', 'math', 'h1', 'h2')}}
        row['language_status'] = 'English selection by source/path; full language and context review pending'
    if list(_source_identity(source)) != identity:
        raise ValueError('Source changed during local document inspection')
    matrix = {topic: [row['entry'] for row in rows if topic in row['topics']] for topic in policy['topics']}
    hashes = {}
    for row in rows:
        hashes.setdefault(row['entry_sha256'], []).append(row)
    return {'source_asset_id': asset['id'], 'resource_id': policy['resource_id'], 'source_url': asset['source_url'],
        'source_version': asset['version'], 'source_sha256': asset['sha256'], 'source_size_bytes': asset['size_bytes'],
        'source_verified': True, 'inventory_complete': True, 'all_entry_count': inventory_record['all_entry_count'],
        'mime_counts': inventory_record['mime_counts'], 'document_count': len(inventory_record['documents']),
        'unexportable_documents': inventory_record.get('unexportable_documents', []),
        'candidate_count': len(rows), 'candidate_document_bytes': sum(row['size_bytes'] for row in rows),
        'unique_candidate_document_bytes': sum(group[0]['size_bytes'] for group in hashes.values()),
        'duplicate_entry_bodies': [{"sha256": digest, "entries": [row['entry'] for row in group]}
                                   for digest, group in sorted(hashes.items()) if len(group) > 1],
        'topic_coverage': matrix, 'missing_topics': [topic for topic, entries in matrix.items() if not entries],
        'candidates': rows, 'content_ready': False,
        'review_requirements': ['Verify English language and complete article or book context.',
            'Preserve every instruction, illustration, caption, table, equation and original notice.',
            'Verify dependency closure and local links in bounded static-export previews.',
            'Review original publication rights and retain historical warnings.'],
        'accounting': 'Document payload is not an export size. Images, styles, dependencies and book-context closure remain unmeasured; no direct-expansion bytes are counted.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-root', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=Path('catalog/library.yaml'))
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, default=Path('.owl/acquisition/zim-inventory'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence-output', type=Path)
    parser.add_argument('--from-evidence', type=Path, help='Reuse an existing local inspection bound to these exact selections and source pins')
    parser.add_argument('--capture-output', type=Path)
    parser.add_argument('--local-manifest-output', type=Path, help='Machine paths; store this only under .owl')
    parser.add_argument('--inventory-only', action='store_true')
    args = parser.parse_args(argv)
    for output in filter(None, (args.output, args.cache_dir, args.evidence_output, args.capture_output, args.local_manifest_output)):
        if output.resolve().is_relative_to(args.library_root.resolve()):
            parser.error('Inventory outputs and caches must remain outside the read-only source library')
    reject_symlinks(args.recipe)
    if args.recipe.stat().st_size > 65536:
        parser.error('Selection recipe exceeds 64 KiB')
    raw = args.recipe.read_bytes()
    recipe = json.loads(raw)
    if recipe.get('schema_version') != 1 or not 1 <= len(recipe.get('sources', [])) <= 10:
        parser.error('Require one to ten explicit source selections')
    assets = {row['id']: row for row in load_catalog(args.catalog)}
    retained = {}
    if args.from_evidence:
        reject_symlinks(args.from_evidence)
        if args.from_evidence.stat().st_size > MAX_METADATA:
            parser.error('Inspection evidence exceeds 64 MiB')
        previous = json.loads(args.from_evidence.read_text())
        if previous.get('recipe_sha256') != hashlib.sha256(raw).hexdigest():
            parser.error('Inspection evidence belongs to a different selection recipe')
        retained = {row['source_asset_id']: row for row in previous['sources']}
    results = []
    for policy in recipe['sources']:
        asset = assets[policy['source_asset_id']]
        if asset['format'] != 'zim':
            raise ValueError('Candidate inventory requires a cataloged ZIM')
        source = args.library_root / asset['destination']
        inv = inventory(source, asset, args.cache_dir / (asset['id'] + '.json'))
        if args.inventory_only:
            results.append({key: value for key, value in inv.items() if key not in ('documents', 'source_identity')})
        else:
            policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            checkpoint = args.cache_dir / (asset['id'] + '-candidates-' + policy_hash[:16] + '.json')
            reject_symlinks(checkpoint)
            previous = json.loads(checkpoint.read_text()) if checkpoint.is_file() and checkpoint.stat().st_size <= MAX_METADATA else {}
            if asset['id'] in retained:
                result = retained[asset['id']]
                selected = choose(inv['documents'], policy)
                fields = ('entry', 'title', 'mime', 'size_bytes', 'topics', 'context_group')
                if (result.get('source_sha256') != asset['sha256'] or result.get('source_size_bytes') != asset['size_bytes'] or
                        [{key: row.get(key) for key in fields} for row in selected] !=
                        [{key: row.get(key) for key in fields} for row in result['candidates']] or
                        any(not re.fullmatch(r'[0-9a-f]{64}', str(row.get('entry_sha256', ''))) or 'structure' not in row for row in result['candidates'])):
                    raise ValueError('Inspection evidence differs from verified source identities or selected entries')
                write(checkpoint, {'source_identity': inv['source_identity'], 'policy_sha256': policy_hash,
                                   'source_sha256': asset['sha256'], 'result': result})
            elif (previous.get('source_identity') == inv['source_identity'] and previous.get('policy_sha256') == policy_hash
                    and previous.get('source_sha256') == asset['sha256']):
                result = previous['result']
            else:
                result = inspect_candidates(source, asset, inv, policy)
                write(checkpoint, {'source_identity': inv['source_identity'], 'policy_sha256': policy_hash,
                                   'source_sha256': asset['sha256'], 'result': result})
            results.append(result)
        print(json.dumps({'source': asset['id'], 'documents': len(inv['documents']),
                          'candidates': results[-1].get('candidate_count'), 'body_downloads': 0}), flush=True)
    result = {'schema_version': 1, 'recipe_id': recipe['id'], 'recipe_sha256': hashlib.sha256(raw).hexdigest(),
        'body_downloads': 0, 'exports': 0, 'production_writes': 0, 'content_ready': False, 'sources': results}
    if args.evidence_output:
        write(args.evidence_output, result)
    write(args.output, result if args.inventory_only else portable_evidence(result))
    if args.capture_output:
        write(args.capture_output, capture_manifest(assets, recipe))
    if args.local_manifest_output:
        if '.owl' not in args.local_manifest_output.parts:
            parser.error('Machine-path reuse mapping must be stored under .owl')
        write(args.local_manifest_output, {policy['source_asset_id']: str((args.library_root / assets[policy['source_asset_id']]['destination']).absolute()) for policy in recipe['sources']})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
