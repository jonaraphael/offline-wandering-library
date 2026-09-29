#!/usr/bin/env python3
"""Generate the current selection reference from admitted files and real defaults."""
import argparse
from collections import Counter
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from owl.catalog import capacity_plan, load_catalog, load_profiles, resolve_content
from owl.content_policy import require_content_policy
from owl.resources import load_resources
from owl.utility_policy import require_utility_policy
from owl.catalog import read_yaml
from owl.atlas_model import load_navigation


def render_coverage_plan():
    """Validate editorial references; never infer depth from source presence."""
    path = ROOT/'catalog/coverage-plan.yaml'
    plan = read_yaml(path)
    assets = load_catalog(ROOT/'catalog/library.yaml')
    profiles = load_profiles(ROOT/'profiles')
    resources_path = ROOT/'catalog/resources.yaml'
    resources = load_resources(resources_path, assets)
    navigation = load_navigation(ROOT/'catalog/navigation', assets)
    if plan.get('schema_version') != 1 or plan.get('profile') not in profiles:
        raise ValueError('Coverage plan requires schema_version 1 and a known profile')
    for key in ('reviewed_on', 'purpose', 'completion_rule', 'maintenance_rule'):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError('Coverage plan requires text: ' + key)
    if not isinstance(plan.get('topics'), list) or not plan['topics']:
        raise ValueError('Coverage plan requires topic rows')
    if not isinstance(plan.get('next_batch'), list) or any(not isinstance(x, str) for x in plan['next_batch']):
        raise ValueError('Coverage next_batch must contain text')
    seen, covered_topics, covered_resources = set(), set(), set()
    for row in plan['topics']:
        for key in ('id', 'title', 'intended', 'existing', 'done_when'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError('Coverage topic requires text: ' + key)
        if row['id'] in seen or row.get('status') not in {'gap', 'partial', 'optional', 'adequate'}:
            raise ValueError('Duplicate coverage topic or invalid editorial status')
        seen.add(row['id'])
        for key in ('atlas_topics', 'resources', 'gaps', 'next'):
            if not isinstance(row.get(key), list) or any(not isinstance(x, str) or not x.strip() for x in row[key]):
                raise ValueError(row['id'] + ': invalid ' + key)
        if set(row['atlas_topics']) - navigation['topics'].keys() or set(row['resources']) - resources.keys():
            raise ValueError(row['id'] + ': unknown topic or resource reference')
        if row['status'] == 'adequate' and (not isinstance(row.get('review_evidence'), str) or not row['review_evidence'].strip()):
            raise ValueError(row['id'] + ': adequate requires explicit editorial review_evidence')
        covered_topics.update(row['atlas_topics'])
        covered_resources.update(row['resources'])
    missing = navigation['topics'].keys() - covered_topics
    if missing:
        raise ValueError('Atlas topics missing an editorial plan: ' + ', '.join(sorted(missing)))
    missing = set(profiles[plan['profile']]['default_resources']) - covered_resources
    if missing:
        raise ValueError('Default collections missing an editorial plan: ' + ', '.join(sorted(missing)))
    selected, _, _ = resolve_content(assets, profiles[plan['profile']], resources_path=resources_path)
    selected_ids = {a['id'] for a in selected}
    statuses = Counter(row['status'] for row in plan['topics'])
    lines = ['# Full 1 TB topic-by-topic completion plan', '',
        f"Editorial review: {plan['reviewed_on']}. Generated from [the editable plan](../catalog/coverage-plan.yaml) and current catalog.", '',
        plan['purpose'], '', plan['completion_rule'], '',
        f"Current selection: {len(selected):,} pinned files, {sum(a['size_bytes'] for a in selected)/1e9:.3f} GB, including reader packages. "
        f"The {len(plan['topics'])} editorial workstreams account for all {len(navigation['topics'])} atlas topics, including optional study topics, and additional gaps without atlas tags.", '',
        'A selected collection establishes availability only. Broad archives are supplementary until specific task coverage is reviewed. Optional collections below do not count toward default depth. '
        + 'Editorial assessments: ' + ', '.join(f'{statuses.get(state, 0)} {state}' for state in ('adequate', 'partial', 'gap', 'optional')) + '.', '',
        '## Next selection batch', '']
    lines += [f'{i}. {entry}' for i, entry in enumerate(plan['next_batch'], 1)]
    lines += ['', '## Topic plans', '']
    for row in plan['topics']:
        labels = [resources[r]['title'] + (' (selected)' if selected_ids.intersection(resources[r]['asset_ids']) else ' (optional; not selected)')
                  for r in row['resources']]
        lines += [f"### {row['title']} — {row['status']}", '',
            '**Intended coverage:** ' + row['intended'], '',
            '**Existing resources:** ' + row['existing'], '',
            '**Catalog collections:** ' + '; '.join(labels) + '.', '',
            '**Remaining gaps:** ' + '; '.join(row['gaps']) + '.', '',
            '**Next selections/review:** ' + ' '.join(row['next']), '',
            '**Adequate when:** ' + row['done_when'], '']
        if row.get('review_evidence'):
            lines += ['**Editorial review evidence:** ' + row['review_evidence'], '']
    lines += ['## Keep the plan current', '', plan['maintenance_rule'], '',
        'Python checks referenced collections and complete atlas-topic coverage when generating this document. It never upgrades an editorial status from tags, file counts or downloads. '
        'The latest small acquisition batch is recorded in [the seed and water review](../catalog/acquisition/seed-water-discovery-20260928.json). '
        'The [remaining-capacity specification](full-1tb-capacity-spec.md) records enumerated candidate files, source-verification evidence, draft pseudoindexes and remaining admission gates; these are not ready collections.', '']
    return '\n'.join(lines)


def render():
    profiles = load_profiles(ROOT/'profiles')
    assets = load_catalog(ROOT/'catalog/library.yaml', profiles)
    path = ROOT/'catalog/resources.yaml'
    resources = load_resources(path, assets)
    require_content_policy(assets)
    require_utility_policy(assets, resources, profiles, path)
    counts = Counter(a['utility_tier'] for a in assets)
    out = ['# Content selection', '', 'Generated by `python scripts/build_content_docs.py` from the active catalogs and policies.', '',
           f'{len(assets)} selectable asset records in {len(resources)} collections pass the finished-download policy. Priority counts: '+', '.join(f'{k}: {counts[k]}' for k in ('CRITICAL','USEFUL','NONESSENTIAL'))+'.', '',
           'CRITICAL protects life and supports household survival. USEFUL covers practical trades, appropriate technology, general reference and school education. NONESSENTIAL includes stories, college study, computing and cultural enrichment; these collections are opt-in.', '',
           'Files are selected for substantial, diversified knowledge useful in a post-internet, low-electronic life. There are no minimum book counts or artificial content-size targets. Chapter files and archive members are not independent whole books.', '',
           '## Default selections', '', '| Drive | Pinned files, GB | In-place planning peak, GB | Records |', '| --- | ---: | ---: | ---: |']
    for p in sorted(profiles.values(), key=lambda p:p['capacity_bytes']):
        if not p.get('default_resources'):continue
        selected, _, report = resolve_content(assets,p,resources_path=path)
        plan=capacity_plan(selected,p,report)
        out.append(f"| {p['id']} | {sum(a['size_bytes'] for a in selected)/1e9:.3f} | {plan['in_place_peak_budget_bytes']/1e9:.3f} | {len(selected)} |")
    out += ['', 'Decimal GB. File totals include reader packages. Planning peaks include a small discovery allowance, metadata and reserve. Original downloads stay on the target drive. Search and atlas pages compile from approved metadata without reading source bodies; no indexing workspace or cache is needed.', '',
            'Exact [near-full selections for all five presets](preset-capacity-plans.md) are saved separately from these admitted build defaults. They reuse the verified candidate inventory and retain its pending hash/content review gates. The 64 GB and 256 GB defaults use North America maps; larger presets substitute the world map. Additional encyclopedia languages are opt-in.', '',
            'The [topic-by-topic completion plan](full-1tb-coverage-plan.md) governs intended depth and remaining gaps. Capacity utilization alone does not establish adequate coverage.', '',
            '## Evidence and limits', '',
            '[The machine-readable review](../catalog/content-review.json) records every former asset, its original policy failures, priority, disposition, replacement group and coverage limitations. Download evidence records full-file hashes, byte sizes and PDF page counts for new sources. Existing large ZIM bodies were not downloaded again in this review.', '',
            'Local topography, a complete initial-literacy/humanities curriculum, missing Hesperian back matter and finished SQLite/OpenSSH replacements remain coverage gaps. Removing unavailable wishlist entries from the active menu does not mean those gaps are solved. Historical books supplement current references; they do not replace current clinical or safety guidance.', '',
            'Original published PDFs/ZIMs are downloaded unchanged. Optional Python PDFs are unpacked unchanged from the publisher ZIP. PhET uses original HTML with hash-bound offline screen evidence; full editorial review and physical-device certification remain pending.', '',
            '## Selectable collections', '', '| Collection | Priority | GB | Files | Coverage |', '| --- | --- | ---: | ---: | --- |']
    for r in sorted(resources.values(),key=lambda r:({'CRITICAL':0,'USEFUL':1,'NONESSENTIAL':2}[r['utility_tier']],r['id'])):
        out.append(f"| {r['title']} (`{r['id']}`) | {r['utility_tier']} | {r['target_bytes']/1e9:.3f} | {len(r['asset_ids'])} | {r['reason'].replace('|','/')} |")
    return '\n'.join(out)+'\n'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    outputs = {ROOT/'docs/content-selection.md': render(), ROOT/'docs/full-1tb-coverage-plan.md': render_coverage_plan()}
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=content:raise SystemExit('Content documentation stale; run python scripts/build_content_docs.py')
        else:path.write_text(content, encoding='utf-8', newline='\n');print(path)
