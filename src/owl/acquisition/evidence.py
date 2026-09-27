"""Turn existing reviewed local evidence into portable pinned recipes.

No networking: original URLs are provenance and future build-time inputs only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urldefrag, urljoin

from ..catalog import load_catalog, read_yaml
from ..safety import atomic_write, reject_symlinks, safe_path, sha256_file
from .documents import render, _Tree, _selected, _text, _walk


def prepare_health(evidence_dir: Path, output: Path, catalog: Path, resources: Path):
    evidence_dir = evidence_dir.resolve()
    reject_symlinks(evidence_dir)
    report_path = safe_path(evidence_dir, 'snapshot-evidence.json')
    evidence = json.loads(report_path.read_text(encoding='utf-8'))
    original = safe_path(evidence_dir, Path(evidence['output']).name)
    if sha256_file(original) != evidence['sha256'] or not evidence.get('all_entry_text_preserved'):
        raise ValueError('Previously reviewed snapshot differs from its evidence')
    if len(evidence['entries']) != 36:
        raise ValueError('Expected the reviewed 27 updates, eight context pages and oils article')
    records = {}
    for path in sorted(evidence_dir.glob('download*results.json')):
        for row in json.loads(path.read_text(encoding='utf-8')):
            if 'local_path' in row:
                records[row['source_url']] = row
    source_rows = evidence['source_files'] + [r for r in records.values()
                                              if r.get('content_type', '').startswith('image/')]
    assets, paths, by_url = [], {}, {}
    for row in source_rows:
        if row['source_url'] in by_url:
            continue
        path = safe_path(evidence_dir, row['filename'])
        if path.stat().st_size != row['size_bytes'] or sha256_file(path) != row['sha256']:
            raise ValueError('Original source bytes changed: ' + row['filename'])
        identity = 'food_snapshot_' + re.sub('[^a-z0-9]+', '_', path.stem.lower())
        fmt = path.suffix.lstrip('.').lower()
        asset = dict(id=identity, title='Snapshot source: ' + path.name,
                     category='food-preservation', format=fmt, source_url=row['source_url'],
                     destination='REFERENCE/SOURCES/FOOD_UPDATES/' + path.name,
                     version='Publisher snapshot 2026-09-18', size_bytes=row['size_bytes'],
                     sha256=row['sha256'], license='Publisher copyright and original notices; personal offline copy',
                     redistributable=False, required=True, profiles=[], critical=False,
                     supporting_file=True, reader_required=False, publisher='NCHFP / University of Georgia',
                     language='en', snapshot_date='2026-09-18',
                     attribution='National Center for Home Food Preservation and University of Georgia; original article and illustration credits retained.')
        assets.append(asset)
        paths[identity] = path
        by_url[row['source_url']] = identity
    existing = load_catalog(catalog)
    by_id = {a['id']: a for a in existing + assets}
    output_id = 'food_updates_2026_09_18_direct'
    output_asset = dict(id=output_id, title='NCHFP preservation updates and complete linked guidance',
        category='food-preservation', format='html', source_url='https://nchfp.uga.edu/newsflash',
        destination='CRITICAL/FOOD/nchfp_updates_2026_09_18.html', version='2026-09-18 reviewed snapshot, OWL document renderer v1',
        size_bytes=1, sha256='0' * 64, license='Publisher copyright; original notices and source links retained',
        redistributable=False, required=True, profiles=[], critical=True, reader_required=False,
        illustrated=True, resource_type='guide', publisher='NCHFP / University of Georgia', language='en',
        snapshot_date='2026-09-18', attribution='National Center for Home Food Preservation and University of Georgia; original authors and illustration credits retained.',
        generation={'recipe_id': 'food-updates-2026-09-18'})
    by_id[output_id] = output_asset
    sections, referenced_urls = [], set()
    for row in evidence['source_files']:
        identity = by_url[row['source_url']]
        name = row['filename']
        if 'newsflash' in name:
            spec = dict(source_asset_id=identity, tag='article', attribute='class', value='article--resource',
                        expected_count=7 if 'P20' in name else 10)
        elif name == 'uga_infused_oils_page.html':
            spec = dict(source_asset_id=identity, tag='div', attribute='class', value='entry-content', expected_count=1,
                        heading='How to Safely Make Infused Oils: Best Practices for Food Safety',
                        credit='Carla Luisa Schwan, University of Georgia Extension. Circular 1334, published December 17, 2024.')
        else:
            spec = dict(source_asset_id=identity, tag='div', attribute='class', value='section__content', class_exact=True, expected_count=2, match_index=0)
        tree = _Tree(paths[identity].read_text(encoding='utf-8'))
        selected = _selected(tree.root, spec)
        referenced_urls.update(urldefrag(urljoin(row['source_url'], node.attrs['href']))[0]
                               for selected_node in selected for node in _walk(selected_node)
                               if node.tag == 'a' and node.attrs.get('href'))
        text = re.sub(r'\s+', ' ', ''.join(_text(node) for node in selected)).strip()
        spec['expected_text_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        sections.append(spec)
    links = {a['source_url']: a['id'] for a in existing if a['format'] == 'pdf'}
    links.update({row['source_url']: output_id for row in evidence['source_files']})
    # Publisher landing URLs are explicitly bound to the complete selected PDF.
    aliases = {
        'https://fieldreport.caes.uga.edu/publications/C1312/whats-the-word-on-homemade-kombucha/': 'uga_kombucha_c1312',
        'https://nchfp.uga.edu/publications/uga-publications/using-pressure-canners': 'uga_using_pressure_canners',
        'https://nchfp.uga.edu/publications/uga-publications/using-boiling-water-canners': 'uga_using_boiling_water_canners_2025',
    }
    links.update({url: identity for url, identity in aliases.items() if identity in by_id})
    links = {url: identity for url, identity in links.items() if url in referenced_urls}
    recipe = dict(id='food-updates-2026-09-18', resource_id='food-preservation', adapter='html_snapshot', version='1',
        source_asset_ids=sorted(paths), output_asset_ids=[output_id], workspace_bytes=0,
        dependency_asset_ids=sorted(set(links.values()) - {output_id}),
        selection=dict(outputs=[dict(asset_id=output_id, title=output_asset['title'], sections=sections,
                        intro='Snapshot of 27 publisher updates, eight complete linked recipes or prerequisite pages, and the UGA infused-oils article, collected September 18, 2026. Original dates, qualifications, tables and illustrations are retained. This dated selection does not claim to mirror the entire NCHFP website or later updates.')],
                       dependencies={r['source_url']: by_url[r['source_url']] for r in source_rows
                                     if r.get('content_type', '').startswith('image/')}, links=links),
        review=dict(status='approved', evidence=['docs/acquisition-hour-health.md', 'catalog/acquisition/food-updates-evidence.json']),
        blockers=[], metadata_sources=[])
    output = Path(output).absolute()
    reject_symlinks(output)
    if output.exists():
        raise ValueError('Choose a new evidence output directory')
    output.mkdir(parents=True)
    rendered = render(recipe, paths, by_id, output / 'rendered')[output_id]
    output_asset.update(size_bytes=rendered.stat().st_size, sha256=sha256_file(rendered))
    assets.append(output_asset)
    resource = next(r for r in read_yaml(resources)['resources'] if r['id'] == 'food-preservation')
    update = dict(id=resource['id'], asset_ids=list(dict.fromkeys(resource['asset_ids'] + [a['id'] for a in assets])),
                  status='ready', reason='17 pinned PDFs plus a source-pinned build-time HTML snapshot cover the five declared topic groups, 27 dated updates, eight complete linked context pages and the UGA oils article. Coverage is frozen to September 18, 2026; it is not a claim about later publisher updates.',
                  review=dict(status='approved', full_scope=True, evidence=recipe['review']['evidence']))
    fragment = dict(schema_version=1, assets=assets, acquisition_recipes=[recipe], resource_updates=[update],
                    navigation_assignments=[{'asset_id':output_id, 'topic_id':'food-preservation', 'purpose':'practical'}])
    portable_evidence = dict(schema_version=1, recipe_id=recipe['id'], source_snapshot_sha256=evidence['sha256'],
                            output_sha256=output_asset['sha256'], output_size_bytes=output_asset['size_bytes'],
                            declared_sections=36, source_files=[{k:v for k,v in r.items() if k != 'local_path'} for r in source_rows],
                            review='Whole source pins, counted complete sections and normalized-text hashes preserve the previously reviewed selection; no factual rewriting or new download.')
    atomic_write(output / 'fragment.json', (json.dumps(fragment, indent=2) + '\n').encode())
    atomic_write(output / 'evidence.json', (json.dumps(portable_evidence, indent=2) + '\n').encode())
    return {'fragment': str(output / 'fragment.json'), 'evidence':str(output / 'evidence.json'), 'assets':len(assets),
            'output_bytes': output_asset['size_bytes'], 'downloads': 0}


def main(argv=None):
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_dir', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--catalog', type=Path, default=root / 'catalog/library.yaml')
    parser.add_argument('--resources', type=Path, default=root / 'catalog/resources.yaml')
    args = parser.parse_args(argv)
    print(json.dumps(prepare_health(args.evidence_dir,args.output,args.catalog,args.resources), sort_keys=True))
    return 0
