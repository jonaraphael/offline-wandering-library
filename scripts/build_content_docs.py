#!/usr/bin/env python3
"""Regenerate the human-readable resource scope/status reference from the catalog."""
import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from owl.catalog import load_catalog, load_profiles, resolve_content
from owl.resources import load_resources


def render():
    assets = load_catalog(ROOT/'catalog/library.yaml')
    registry = load_resources(ROOT/'catalog/resources.yaml', assets)
    profiles = load_profiles(ROOT/'profiles')
    counts = Counter(r['status'] for r in registry.values())
    out = ['# Content selection and acquisition status', '',
        'Generated from `catalog/resources.yaml` and `catalog/library.yaml` by `python scripts/build_content_docs.py`.', '',
        'The registry enumerates **46 numbered collections and three support resources**. The catalog contains exact downloadable file records; the registry describes intended scope. The repository contains metadata, not these datasets.', '',
        f"Current status: **{counts['ready']} ready, {counts['partial']} partial, {counts['unresolved']} unresolved**. There are **{sum(a['status']=='resolved' for a in assets)} pinned available file records**. Large archive pins were checked against publisher whole-file SHA-256 metadata and exact HTTP byte counts; the archive bodies have not all been downloaded or device-tested.", '',
        '- **Ready:** the declared acquisition scope has usable pinned files.',
        '- **Partial:** usable files are available, but specific requested content or representations remain missing.',
        '- **Unresolved:** no usable mapping fulfills the collection yet; the reason below states what is missing.',
        '- **Redistributable: false:** OWL has not established a general right to redistribute the file. This does **not** disable a publisher-offered download for personal, noncommercial offline use.', '',
        'Original notices and attribution remain intact. Private acquisition and public redistribution are recorded separately; personal use does not change a publication’s stated license or its download availability.', '',
        'Evidence: [medical and emergency](acquisition-medical.md), [education and agriculture](acquisition-education.md), [large archives](acquisition-archives.md), [programming and Low-tech](acquisition-reference.md), [Gutenberg and Stack Exchange](acquisition-enrichment.md).', '',
        '## Profiles and capacity', '',
        'All values are decimal GB. Planning targets include unresolved collections and are not downloaded byte counts. Every production preset retains the expanded ordinary-format foundation: 427 documents, including 360 PDFs, 23 direct textbooks and 50 illustrated teaching works. Small presets add bounded practical archives and bundled readers; their totals below are exact pinned bytes.', '',
        '| Profile | Content target | Known available files | Search | Scratch | Reserve |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name in ['flash-16gb','critical-64gb','compact-256gb','standard-512gb','full-1tb']:
        p = profiles[name]
        selected, _, report = resolve_content(assets, p, resources_path=ROOT/'catalog/resources.yaml')
        known = sum(a['size_bytes'] for a in selected)/1e9
        target = report['content_target_bytes']/1e9 if report else known
        out.append(f"| `{name}` | {target:.3f} GB | {known:.3f} GB | {p['search_budget_bytes']/1e9:g} GB | {p.get('index_scratch_budget_bytes', 2*p['search_budget_bytes'])/1e9:g} GB | {p['reserve_bytes']/1e9:g} GB |")
    out += ['', 'Known available files include selected reader binaries; content targets exclude their separate allowance. Metadata is additional. Scratch covers raw assembly plus extraction workspace; a verified raw-index checkpoint releases extraction files before browser packaging. Peak indexing space is raw assembly plus the larger of extraction workspace or search output. All five default planning peaks fit their nominal capacities with the explicit search/scratch/reserve allowances. Full-corpus index measurements for the larger profiles are still outstanding. Use the CLI `--plan` for the complete calculation and real free-space/reuse checks; do not assume the final content target proves the build fits.', '',
        'Compact includes #1–18 plus all acquired OpenStax textbooks, PhET circuit simulations, preparedness and programming manuals; it keeps a 10 GB local topographic allocation instead of North America OSM. Standard includes #1–31 and a 75 GB Survivor Tier A target. Full includes #1–36, #42–44 and #46, with full Tier A and a 60 GB direct-reading allowance. Spanish is the default additional Wikipedia; other languages and remaining Khan content are opt-in. A world map replaces the North America archive while retaining local topo.', '',
        'Use [SELECT.html](../SELECT.html) or repeat `--include RESOURCE` / `--exclude RESOURCE` (IDs or list numbers). Exclusion never deletes existing files. A normal build stops for partial/unresolved collections; `--allow-incomplete` explicitly builds the available subset and records the gaps.', '',
        '## Direct editions and exports', '',
        'The [in-place ZIM exporter](direct-export.md) converts explicit article selections and supported local images/styles/fonts into ordinary files on the SSD. Import its completed manifest with `build_drive.py --extra-catalog PATH --allow-local` to refresh global search, navigation, inventory and checksums without copying those files again. Excluding a source collection also excludes its derivatives; an export from a different source checksum is rejected.', '',
        'A conversion mechanism does not establish a curated or visually checked edition. The 60 GB direct-reading expansion remains unresolved until article/book selections are reviewed and their output is verified. Verified compact editions are registered for Gutenberg nonfiction, children, practical Stack Exchange and science Stack Exchange. Profile default_editions selects these without concealing the unfinished direct/curated scopes. Historical Gutenberg publications are not current safety or clinical instructions. It does not invent compression savings or automatically expand Wikipedia.', '',
        'Additional manifests count their actual bytes on top of selected planning targets. When actual exports replace the separate 60 GB estimate, explicitly exclude `direct-reading-expansion` to avoid reserving that estimate as well; other collection gaps remain reported.', '',
        '## Resource scope and remaining work', '',
        '| # | Resource | Status | Planned GB | Pinned files |',
        '| --- | --- | --- | ---: | ---: |']
    by_id = {a['id']:a for a in assets}
    for r in registry.values():
        n = sum(by_id[i]['status']=='resolved' for i in r['asset_ids'])
        out.append(f"| {r.get('number') or '—'} | `{r['id']}` | {r['status']} | {r['target_bytes']/1e9:g} | {n} |")
    for r in registry.values():
        out += ['', f"### {str(r['number'])+'. ' if r.get('number') else ''}{r['title']}", '',
                f"`{r['id']}` · **{r['status']}** · planning target {r['target_bytes']/1e9:g} GB", '',
                r.get('reason', 'The declared scope has pinned files; readiness does not certify every device or every factual statement in the material.'), '',
                '**Include:**', '']
        out += ['- '+str(item).replace('\n',' ') for item in r.get('include',[])]
        for name, edition in r.get('editions', {}).items():
            out += ['', f"**{name.title()} edition:** {edition['status']}; {edition['target_bytes']/1e9:.3f} GB; {len(edition['asset_ids'])} pinned files. {edition['reason']}"]
        if r.get('exclude'):
            out += ['', '**Exclude:**', ''] + ['- '+str(item).replace('\n',' ') for item in r['exclude']]
        if r.get('source_pages'):
            out += ['', 'Sources: '+', '.join(f'[source {i+1}]({url})' for i,url in enumerate(r['source_pages']))+'.']
    return '\n'.join(out)+'\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT/'docs/content-selection.md'
    content = render()
    if args.check:
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            raise SystemExit('Content documentation stale; run python scripts/build_content_docs.py')
    else:
        path.write_text(content, encoding='utf-8')
        print(path)
