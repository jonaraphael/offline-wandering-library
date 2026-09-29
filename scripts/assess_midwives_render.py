#!/usr/bin/env python3
"""Assess frozen raw source expansion without writing a readable-content preview."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.capture import _digest, _owner, _read, _receipt, normalize_manifest
from owl.acquisition.midwives_wikitext import Expander, RenderError
from owl.acquisition.supervisor import save


def load_raw(capture, inventory_path):
    inventory = json.loads(inventory_path.read_text())
    manifest = normalize_manifest(_read(capture / 'manifest.json'))
    signature = _digest(manifest)
    _owner(capture, signature)
    raw, pins = {}, {}
    for source in manifest['sources']:
        if source.get('source_role') != 'original-wikitext':
            continue
        receipt = _receipt(capture, source, signature)
        if not receipt:
            raise ValueError('Frozen raw source has no verified receipt: ' + source['id'])
        body = (capture / receipt['relative_path']).read_bytes()
        payload = source['publisher_payload']
        if body[:4] != b'\n\n\n\n' or len(body[4:]) != payload['size_bytes'] or hashlib.sha1(body[4:]).hexdigest() != payload['sha1']:
            raise ValueError('Frozen publisher revision verification failed')
        raw[source['page_title']] = body[4:].decode('utf-8', errors='strict')
        pins[source['page_title']] = {'source_id': source['id'], 'whole_response_sha256': receipt['sha256'],
                                    'publisher_payload': payload}
    if set(raw) != {p['title'] for p in inventory['pages']}:
        raise ValueError('Raw revision inventory is incomplete')
    return inventory, raw, pins


def assess(capture, inventory_path, output):
    inventory, raw, pins = load_raw(capture, inventory_path)
    engine = Expander({k: v for k, v in raw.items() if k.startswith('Template:')})
    results, errors = [], []
    for page in inventory['pages']:
        title = page['title']
        if title.startswith('Template:'):
            continue
        try:
            expanded = engine.page(title, page['revision'], raw[title])
            if '{{' in expanded or '}}' in expanded:
                raise RenderError('Unresolved braces remain after expansion')
            results.append({'title': title, **pins[title], 'expanded_bytes': len(expanded.encode()),
                            'expanded_sha256': hashlib.sha256(expanded.encode()).hexdigest(), 'expansion_calls': engine.calls,
                            'wiki_table_count': len(re.findall(r'^\s*\{\|', expanded, re.M)),
                            'image_references': len(re.findall(r'\[\[(?:File|Image):', expanded, re.I)),
                            'html_tags': dict(Counter(re.findall(r'<\s*([A-Za-z][\w-]*)\b', expanded)))})
        except RenderError as exc:
            errors.append({'title': title, **pins[title], 'error': str(exc)})
    result = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False, 'preview_written': False,
              'inventory_sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
              'renderer_sha256': hashlib.sha256((Path(__file__).resolve().parents[1] / 'src/owl/acquisition/midwives_wikitext.py').read_bytes()).hexdigest(),
              'book_pages': 132, 'expanded_pages': len(results), 'unhandled_count': len(errors), 'errors': errors, 'pages': results,
              'next_gate': 'Convert expanded wiki links/images/lists/headings/table to ordinary HTML, validate all structure and dependencies, then render and inspect clinical content.'}
    save(output, result)
    return {k: result[k] for k in ('content_ready', 'preview_written', 'expanded_pages', 'unhandled_count')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(assess(args.capture, args.inventory, args.output)))
