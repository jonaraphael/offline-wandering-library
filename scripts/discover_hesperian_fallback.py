#!/usr/bin/env python3
"""Discover whole-book Hesperian alternatives using metadata and HEAD only."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.metadata import Fetcher
from owl.acquisition.pins import PinProbe
from owl.safety import atomic_write, reject_symlinks


def public_editions(rows):
    if not isinstance(rows, list) or len(rows) >= 100:
        raise ValueError('Full public inventory is missing or reaches the pagination bound')
    editions = {}
    for row in rows:
        url = row.get('source_url', '')
        parts = urlsplit(url)
        match = re.fullmatch(r'/wp-content/uploads/pdf/en_midw_(\d{4})/en_midw_\1_(?:full|Full_Book)\.pdf', parts.path, re.I)
        if (parts.scheme != 'https' or parts.hostname != 'hesperian.org' or parts.query or not match
                or row.get('mime_type') != 'application/pdf' or row.get('title', {}).get('rendered') != 'Full Book Download'):
            continue
        current = editions.setdefault(url, {'source_url': url, 'edition': match[1], 'publisher_ids': [],
            'title': 'A Book for Midwives — complete English book', 'body_verified': False})
        current['publisher_ids'].append(row['id'])
    return sorted(editions.values(), key=lambda row: (row['edition'], row['source_url']), reverse=True)


def purchase_edition(product, page, recipe):
    if product.get('id') != recipe['product_id'] or product.get('title') != recipe['title']:
        raise ValueError('Official product identity changed')
    variants = [row for row in product.get('variants', []) if row.get('option1') == 'English' and row.get('option2') == 'PDF']
    if len(variants) != 1 or variants[0].get('requires_shipping') is not False:
        raise ValueError('Expected one ordinary English PDF product variant')
    variant = variants[0]
    if type(variant.get('price')) is not int or variant['price'] <= 0 or type(variant.get('available')) is not bool:
        raise ValueError('Official PDF availability/price metadata is incomplete')
    def value(name):
        matches = re.findall(r'data-custom-variant-id="variant_' + name + r'">([^<]+)</span>', page)
        if len(matches) != 1:
            raise ValueError('Official edition/page metadata changed')
        return html.unescape(matches[0]).strip()
    edition, pages = value('edition'), value('page_count')
    if not re.search(r'\(' + recipe['current_edition'] + r'\)', edition) or not pages.isdigit():
        raise ValueError('Current complete edition no longer matches reviewed recipe')
    return {'product_id': product['id'], 'variant_id': variant['id'], 'sku': variant['sku'],
        'title': product['title'], 'language': 'en', 'format': 'pdf', 'edition': edition,
        'page_count': int(pages), 'available_for_purchase': variant['available'],
        'price_minor_units': variant['price'], 'currency': 'USD',
        'purchase_url': recipe['product_page'] + '?variant=' + str(variant['id']),
        'source_url': None, 'size_bytes': None, 'sha256': None,
        'acquisition_status': 'manual-purchase-or-publisher-provided-file-required',
        'review_status': 'pending', 'content_ready': False}


def discover(recipe, fetcher, probe):
    if recipe.get('schema_version') != 1:
        raise ValueError('Unsupported Hesperian fallback recipe')
    inventory = public_editions(json.loads(fetcher.fetch(recipe['public_inventory'])))
    page = fetcher.fetch(recipe['product_page']).decode('utf-8')
    product = json.loads(fetcher.fetch(recipe['product_json']))
    paid = purchase_edition(product, page, recipe)
    for row in inventory:
        report = probe.probe({'id': 'hesperian_midwives_' + row['edition'] + '_full', 'url': row['source_url']})
        for evidence in report['evidence']:
            evidence.pop('cached', None)
        row['source_probe'] = report
    available = [row for row in inventory if type(row['source_probe']['size_bytes']) is int]
    evidence = [{k: v for k, v in row.items() if k != 'cached'} for row in fetcher.evidence]
    paid['price_checked_at'] = next(row['checked_at'] for row in evidence if row['url'] == recipe['product_json'])
    paid['metadata_evidence'] = [row for row in evidence if row['url'] in (recipe['product_json'], recipe['product_page'])]
    return {'schema_version': 1, 'resource_id': 'hesperian-health', 'recipe_id': recipe['id'],
        'status': 'pending', 'content_ready': False, 'body_downloads': 0,
        'missing_current_backmatter_url': recipe['missing_current_backmatter_url'],
        'public_whole_book_candidates': inventory,
        'newest_reachable_public_edition': available[0] if available else None,
        'current_complete_manual_candidate': paid, 'metadata_evidence': evidence,
        'edition_policy': 'Replace a book only as a whole reviewed edition. Never splice older back matter into the current chapter set.',
        'blockers': ['Current chapter collection still lacks its verified same-edition back matter.',
            'No reachable public complete English edition found in the bounded official media inventory.' if not available else
                'Older complete public candidate requires whole-file capture and edition/content review before replacement.',
            'Current complete English PDF needs an authorized purchase or publisher-provided file, exact size, whole-file SHA256 and notices/completeness review.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--metadata-cache', type=Path, default=Path('.owl/acquisition/metadata'))
    parser.add_argument('--pin-cache', type=Path, default=Path('.owl/acquisition/source-pins'))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    reject_symlinks(args.recipe)
    reject_symlinks(args.output)
    if args.recipe.stat().st_size > 16384:
        parser.error('Recipe exceeds 16 KiB')
    raw = args.recipe.read_bytes()
    result = discover(json.loads(raw), Fetcher(args.metadata_cache, offline=args.offline), PinProbe(args.pin_cache, offline=args.offline))
    result['recipe_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
    print(json.dumps({key: result[key] for key in ('status', 'content_ready', 'body_downloads', 'blockers')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
