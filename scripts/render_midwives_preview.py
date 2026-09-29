#!/usr/bin/env python3
"""Assess a bounded ordinary-HTML review candidate from frozen sources."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from assess_midwives_render import load_raw
from owl.acquisition.midwives_wikitext import Expander, RenderError
from owl.acquisition.midwives_html import OrdinaryHTML, CSS, normal_title
from owl.acquisition.supervisor import save
from owl.safety import sha256_file

PEAK = 703655187


def render(capture, inventory_path, literal_path, comparison_path, report_path, preview_root=None):
    if preview_root is not None:
        raise ValueError("Preview writer remains disabled pending full-source structure and visual review")
    comparison_sha = sha256_file(comparison_path)
    cases = json.loads(literal_path.read_text())['cases']
    if any(row['comparison_report_sha256'] != comparison_sha for row in cases):
        raise ValueError('Literal exception evidence changed')
    inventory, raw, pins = load_raw(capture, inventory_path)
    templates = {k: v for k, v in raw.items() if k.startswith('Template:')}
    engine = Expander(templates, literal_cases=cases)
    manifest = json.loads((capture / 'manifest.json').read_text())
    image_sources = {s['file_title']: s for s in manifest['sources'] if s.get('source_role') == 'original-image'}
    images = [{**r, 'source_id': image_sources[r['title']]['id']} for r in inventory['images']]
    compiler = OrdinaryHTML(inventory['pages'], images)
    output, pages, errors = {}, [], []
    for page in inventory['pages']:
        title = page['title']
        if title.startswith('Template:'):
            continue
        try:
            expanded = engine.page(title, page['revision'], raw[title])
            html, structure = compiler.render(title, expanded, engine.display_title)
            name = compiler.pages[normal_title(title)]
            output[name] = html.encode()
            pages.append({'title': title, 'path': name, **pins[title], 'output_sha256': hashlib.sha256(output[name]).hexdigest(),
                          'size_bytes': len(output[name]), 'literal_preservations': engine.literal_preservations, **structure})
        except RenderError as error:
            errors.append({'title': title, **pins[title], 'error': str(error)})
    by_title = {normal_title(p['title']): p for p in pages}
    missing_links = []
    for page in pages:
        for link in page['local_links']:
            target = by_title.get(link['page'])
            if target is None or link['fragment'] and link['fragment'] not in target['ids']:
                missing_links.append({'source': page['title'], **link, 'reason': 'page_not_rendered' if target is None else 'missing_anchor'})
    code = [Path(__file__), Path(__file__).parent / 'assess_midwives_render.py',
            Path(__file__).resolve().parents[1] / 'src/owl/acquisition/midwives_wikitext.py',
            Path(__file__).resolve().parents[1] / 'src/owl/acquisition/midwives_html.py']
    controls = {str(p): sha256_file(p) for p in [inventory_path, literal_path, comparison_path, *code]}
    result = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False, 'preview_written': False,
              'source_manifest_sha256': sha256_file(capture / 'manifest.json'), 'controls': controls,
              'rendered_pages': len(pages), 'expected_pages': 132, 'unhandled_count': len(errors), 'errors': errors,
              'missing_local_links': missing_links, 'pages': pages, 'image_inventory_count': len(images),
              'storage_cap_bytes': PEAK, 'planned_html_bytes': sum(map(len, output.values())),
              'limitations': ['No clinical content admission. Every external reference still requires scope review.',
                              'Visual figure/annotation/table fidelity and phone reading checks remain pending.']}
    save(report_path, result)
    return {k: result[k] for k in ('content_ready', 'preview_written', 'rendered_pages', 'unhandled_count', 'planned_html_bytes')} | {'missing_local_links': len(missing_links)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--literal-cases', type=Path, required=True)
    p.add_argument('--comparison-report', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--preview-root', type=Path, help='Reserved; writer disabled until renderer review is complete')
    args = p.parse_args()
    print(json.dumps(render(args.capture, args.inventory, args.literal_cases, args.comparison_report, args.report, args.preview_root)))
