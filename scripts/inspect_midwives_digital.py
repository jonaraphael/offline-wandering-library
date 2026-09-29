#!/usr/bin/env python3
"""Verify every frozen Midwives revision/image and inventory rendering requirements."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.capture import load_capture_sources, _publisher_payload
from owl.acquisition.supervisor import save


def inspect(capture, inventory_path, output):
    inventory = json.loads(inventory_path.read_text())
    manifest, receipts = load_capture_sources(capture)
    receipts = {r['source_id']: r for r in receipts}
    pages = {row['pageid']: row for row in inventory['pages']}
    media = {row['title']: row for row in inventory['images']}
    page_rows, image_rows, template_names, parser_functions = [], [], Counter(), Counter()
    for source in manifest['sources']:
        receipt = receipts[source['id']]
        path = capture / receipt['relative_path']
        body = path.read_bytes()
        if source['source_role'] == 'original-wikitext':
            pin = source['publisher_payload']
            _publisher_payload(path, pin)
            page = pages[int(source['id'].rsplit('_', 1)[1])]
            if (pin['size_bytes'], pin['sha1']) != (page['revision']['size'], page['revision']['sha1']):
                raise ValueError('Revision differs from the frozen inventory')
            text = body[4:].decode('utf-8', errors='strict')
            template_names.update(re.findall(r'\{\{\s*([^{}|\n]+)', text))
            parser_functions.update(re.findall(r'\{\{\s*(#[a-zA-Z]+)', text))
            page_rows.append({'title': page['title'], 'pageid': page['pageid'], 'revision': page['revision'],
                              'source_id': source['id'], 'whole_response_sha256': receipt['sha256'],
                              'canonical_payload_sha1_verified': True, 'raw_path': str(path),
                              'has_wiki_table': bool(re.search(r'^\s*\{\|', text, re.M)),
                              'has_html_table': '<table' in text.lower(), 'expected_images': len(page['images'])})
        elif source['source_role'] == 'original-image':
            row = media[source['file_title']]
            if len(body) != row['info']['size'] or hashlib.sha1(body).hexdigest() != row['info']['sha1']:
                raise ValueError('Illustration differs from the frozen inventory')
            image_rows.append({'title': row['title'], 'source_id': source['id'], 'size_bytes': len(body),
                               'sha256': receipt['sha256'], 'publisher_sha1_verified': True,
                               'mime': row['info']['mime'], 'width': row['info']['width'], 'height': row['info']['height']})
        else:
            raise ValueError('Unknown source role')
    if len(page_rows) != len(pages) or len(image_rows) != len(media):
        raise ValueError('Incomplete frozen source coverage')
    result = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False,
              'inventory_sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
              'page_count': len(page_rows), 'image_count': len(image_rows), 'all_publisher_pins_verified': True,
              'pages': page_rows, 'images': image_rows, 'template_tokens': dict(template_names.most_common()),
              'parser_functions': dict(parser_functions),
              'remaining_gates': ['Faithful ordinary offline rendering including template semantics, tables and all illustrations.',
                                  'Complete canonical navigation, notices and local dependencies; identify print-only differences.',
                                  'Actual visual and clinical-structure review; source acquisition is not content admission.']}
    save(output, result)
    return {k: result[k] for k in ('status', 'content_ready', 'page_count', 'image_count', 'all_publisher_pins_verified')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.capture, args.inventory, args.output)))
