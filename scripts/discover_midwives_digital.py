#!/usr/bin/env python3
"""Freeze official Midwives revision/image metadata; never fetch reading bodies."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.metadata import Fetcher
from owl.acquisition.capture import normalize_manifest

API = 'https://en.hesperian.org/w/api.php?'
PREFIX = 'A Book for Midwives:'


def discover(root, offline=False):
    fetcher = Fetcher(root / 'metadata', offline=offline, timeout=25)
    requests = 0

    def api(params):
        nonlocal requests
        requests += 1
        if requests > 120:
            raise ValueError('Metadata request bound exceeded')
        url = API + urlencode({**params, 'format': 'json'})
        data = json.loads(fetcher.fetch(url, max_bytes=4 * 1024 * 1024))
        if 'error' in data:
            raise ValueError('Publisher API error: ' + str(data['error']))
        return data, fetcher.evidence[-1]

    toc, toc_evidence = api({'action': 'parse', 'page': 'A_Book_for_Midwives', 'prop': 'links|images|sections|revid'})
    pending = {'A Book for Midwives', *(r['*'] for r in toc['parse']['links'] if r['*'].startswith(PREFIX))}
    pages, missing = {}, []
    while pending:
        if len(pages) + len(pending) > 300:
            raise ValueError('Book and template inventory exceeds 300 pages')
        titles = sorted(pending)[:20]
        pending.difference_update(titles)
        continuation = {}
        for part in range(8):
            data, evidence = api({'action': 'query', 'titles': '|'.join(titles), 'prop': 'info|revisions|images|links|templates',
                                  'rvprop': 'ids|timestamp|size|sha1', 'imlimit': 500, 'pllimit': 500, 'tllimit': 500, **continuation})
            for row in data.get('query', {}).get('pages', {}).values():
                if 'missing' in row:
                    missing.append(row['title'])
                    continue
                name = row['title']
                revision = row['revisions'][0]
                saved = pages.setdefault(name, {k: row[k] for k in ('pageid', 'ns', 'title', 'contentmodel')})
                if saved.get('revision', revision) != revision:
                    raise ValueError('Revision changed during metadata inventory')
                saved['revision'] = revision
                saved.setdefault('metadata_evidence', []).append({k: evidence[k] for k in ('url', 'sha256', 'size_bytes', 'checked_at')})
                for field in ('links', 'images', 'templates'):
                    saved[field] = sorted(set(saved.get(field, [])) | {x['title'] for x in row.get(field, [])})
                pending.update(t for t in saved['links'] if t.startswith(PREFIX) and t not in pages and t not in missing)
                pending.update(t for t in saved['templates'] if t not in pages and t not in missing)
            if 'continue' not in data:
                break
            continuation = data['continue']
        else:
            raise ValueError('Page metadata pagination bound exceeded')
    images = sorted({image for row in pages.values() for image in row['images']})
    chapters = {int(match.group(1)) for name in pages
                if (match := re.match(r'^A Book for Midwives:Chapter (\d+):', name))}
    required = {PREFIX + suffix for suffix in ('Copyright Information', 'Due date calculator',
                'Technical and Medical Words', 'Weight and Volume Conversions', 'Thanks - Digital Edition')}
    if missing or chapters != set(range(1, 26)) or not required <= pages.keys():
        raise ValueError('Canonical chapter or backmatter metadata is incomplete')
    if len(images) > 2500:
        raise ValueError('Image inventory exceeds 2500 originals')
    media = {}
    for offset in range(0, len(images), 40):
        data, evidence = api({'action': 'query', 'titles': '|'.join(images[offset:offset+40]), 'prop': 'imageinfo',
                              'iiprop': 'url|size|sha1|timestamp|mime', 'iilimit': 1})
        for row in data.get('query', {}).get('pages', {}).values():
            info = row.get('imageinfo', [])
            media[row['title']] = {'title': row['title'], 'info': info[0] if info else None,
                                  'repository': row.get('imagerepository'), 'metadata_evidence': {k: evidence[k] for k in ('url', 'sha256', 'size_bytes', 'checked_at')}}
    if set(media) != set(images) or any(not row['info'] for row in media.values()):
        raise ValueError('Canonical illustration metadata is incomplete')
    if any(urlsplit(row['info']['url']).hostname not in {'en.hesperian.org', 'pool.hesperian.org'} for row in media.values()):
        raise ValueError('Illustration metadata points outside the official repositories')
    sources = []
    for name, row in sorted(pages.items()):
        revision = row['revision']
        sources.append({'id': 'midwives_digital_page_' + str(row['pageid']), 'resource_ids': ['hesperian-health'],
                        'source_url': 'https://en.hesperian.org/w/index.php?' + urlencode({'title': name, 'oldid': revision['revid'], 'action': 'raw'}),
                        'version': 'Official digital edition revision ' + str(revision['revid']) + ' (' + revision['timestamp'] + ')',
                        'size_bytes': revision['size'], 'sha256': None, 'publisher_checksums': {'sha1': revision['sha1']},
                        'metadata_evidence': row['metadata_evidence'], 'source_role': 'original-wikitext', 'page_title': name})
    for name, row in sorted(media.items()):
        info = row['info']
        if not info:
            continue
        sources.append({'id': 'midwives_digital_image_' + hashlib.sha256(name.encode()).hexdigest()[:16],
                        'resource_ids': ['hesperian-health'], 'source_url': info['url'],
                        'version': 'Official digital image ' + info['timestamp'], 'size_bytes': info['size'], 'sha256': None,
                        'publisher_checksums': {'sha1': info['sha1']}, 'metadata_evidence': [row['metadata_evidence']],
                        'source_role': 'original-image', 'file_title': name})
    result = {'schema_version': 1, 'kind': 'midwives-digital-revision-inventory', 'content_ready': False, 'body_downloads': 0,
              'toc_revision': toc['parse']['revid'], 'toc_metadata_evidence': toc_evidence, 'metadata_requests': requests,
              'pages': list(pages.values()), 'images': list(media.values()), 'missing_pages': sorted(set(missing)),
              'missing_images': [name for name, row in media.items() if not row['info']],
              'template_titles': sorted({t for row in pages.values() for t in row['templates']}),
              'reading_html_status': 'Rendered HTML HEAD has no exact Content-Length. This proposal captures exact publisher-sized and SHA1-bound raw revisions and images only; it does not produce an admitted reading edition.',
              'license_status': 'Personal source review only. Preserve the publisher digital-use permission request; redistribution and any derivative renderer remain unapproved.',
              'source_bytes': sum(s['size_bytes'] for s in sources)}
    manifest = normalize_manifest({'schema_version': 1, 'kind': 'acquisition', 'id': 'midwives-digital-source-review-20260927-v2',
        'profile': 'full-1tb', 'content_ready': False, 'sources': sources,
        'budget': {'download_bytes': result['source_bytes'], 'expanded_bytes': 0, 'preview_bytes': 0, 'scratch_bytes': 0, 'cache_bytes': 0},
        'review_requirements': ['No PDF chapter substitution or edition mixing.', 'Resolve every canonical chapter, backmatter, template, illustration and local link before a readable digital edition can be approved.',
                                'Keep source copyright/permission terms. No redistributable metadata is asserted by this source-review capture.', 'Pin exact observed SHA256 only after publisher SHA1 and size checks pass.']})
    return result, manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--offline', action='store_true')
    args = p.parse_args()
    inventory, manifest = discover(args.root, args.offline)
    for path, value in ((args.inventory, inventory), (args.manifest, manifest)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'pages': len(inventory['pages']), 'images': len(inventory['images']), 'missing_pages': inventory['missing_pages'],
                      'missing_images': inventory['missing_images'], 'source_bytes': inventory['source_bytes'],
                      'capture_peak_bytes': manifest['storage_peak_bytes'], 'metadata_requests': inventory['metadata_requests'], 'content_ready': False}))
