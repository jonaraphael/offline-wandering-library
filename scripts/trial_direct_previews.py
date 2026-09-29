#!/usr/bin/env python3
"""Prepare/run bounded direct-edition trials from frozen candidate manifests.

Reads only receipted quarantine originals. Never fetches a publisher body,
changes production, admits a catalog, or treats structural checks as approval.
"""
from collections import Counter
import argparse
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.capture import preview, _read, _json, _digest
from owl.export_direct import _source_identity, DROP_CONTENT, VERSION as EXPORT_VERSION
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file

LIMITS = {'appropedia_en': (2_000_000_000, 25000), 'cd3wd_en': (2_000_000_000, 60000),
          'ifixit_en': (3_000_000_000, 60000), 'lowtech_magazine': (1_000_000_000, 15000)}
TOTAL_PREVIEW = 8_000_000_000
TOTAL_SCRATCH = 1_000_000_000
WORKSPACE = 250_000_000
MAX_METADATA = 64 * 1024 * 1024
MAX_ENTRY = 16 * 1024 * 1024


def read(path):
    reject_symlinks(path)
    if path.stat().st_size > MAX_METADATA:
        raise SafetyError('Trial metadata exceeds 64 MiB')
    return json.loads(path.read_text())


def write(path, value):
    data = _json(value)
    if len(data) > MAX_METADATA:
        raise SafetyError('Trial evidence exceeds 64 MiB')
    atomic_write(path, data)


def prepare(candidates_path, output):
    evidence = read(candidates_path)
    if evidence.get('content_ready') is not False:
        raise SafetyError('Expected explicitly pending frozen candidates')
    result = []
    for source in evidence['sources']:
        sid = source['source_asset_id']
        if sid not in LIMITS:
            raise SafetyError('Unreviewed trial source')
        selected = source['candidates']
        entries = [row['entry'] for row in selected]
        if len(entries) != len(set(entries)) or not entries or len(entries) > 10000:
            raise SafetyError('Duplicate/empty/excessive trial entry selection')
        if source['candidate_count'] != len(entries) or any(row['size_bytes'] > MAX_ENTRY for row in selected):
            raise SafetyError('Candidate count or item bound changed')
        max_bytes, max_files = LIMITS[sid]
        identity = source['resource_id'] + '-trial-v' + str(EXPORT_VERSION)
        blockers = ['Frozen candidate selection still requires substantive language, completeness, safety/context and illustration review.']
        if source.get('language_tag_conflicts', {}).get('count'):
            blockers.append('HTML language tags conflict with English source/body evidence; per-work body-language review remains required.')
        if source.get('unexportable_documents'):
            blockers.append('Source inventory contains explicitly recorded unsafe/unexportable paths outside this selection; coverage remains pending.')
        work_ids = sorted({('document-sha256:' + row['entry_sha256']) if row['mime'] == 'application/pdf'
                           else source['source_asset_id'] + ':' + row.get('context_group', row['entry']) for row in selected})
        recipe = {'id': identity, 'resource_id': source['resource_id'], 'adapter': 'zim_direct', 'version': str(EXPORT_VERSION),
            'source_asset_ids': [sid], 'output_asset_ids': [], 'workspace_bytes': WORKSPACE,
            'selection': {'source_asset_id': sid, 'entries': entries, 'max_bytes': max_bytes,
                'max_files': max_files, 'max_item_bytes': MAX_ENTRY, 'work_ids': work_ids,
                'additional_only': False, 'trial_candidate_manifest_sha256': sha256_file(candidates_path),
                'selection_review': 'exact frozen candidate set with captured book-directory closure; substantive approval pending'},
            'review': {'status': 'pending', 'evidence': []}, 'blockers': blockers}
        folder = output / identity
        recipe_path = folder / 'recipe.json'
        if recipe_path.exists() and read(recipe_path) != recipe:
            raise SafetyError('Frozen trial recipe changed; choose a new trial directory/version')
        write(recipe_path, recipe)
        write(folder / 'assets.json', {'assets': []})
        result.append({'id': identity, 'source_asset_id': sid, 'source_sha256': source['source_sha256'],
                       'entries': len(entries), 'pdf_entries': sum(row['mime'] == 'application/pdf' for row in selected),
                       'work_ids': len(work_ids), 'max_bytes': max_bytes, 'max_files': max_files,
                       'workspace_bytes': WORKSPACE, 'recipe': str(recipe_path), 'assets': str(folder / 'assets.json')})
    manifest = {'schema_version': 1, 'kind': 'direct-trial-recipes', 'content_ready': False,
                'candidate_manifest_sha256': sha256_file(candidates_path), 'recipes': result,
                'preview_bytes': TOTAL_PREVIEW, 'scratch_bytes': TOTAL_SCRATCH}
    write(output / 'trial.json', manifest)
    return manifest


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts, self.text, self.skip, self.links = Counter(), [], [], []
    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_CONTENT | {'style'}: self.skip.append(tag)
            return
        if tag in DROP_CONTENT | {'style'}:
            if tag != 'embed': self.skip.append(tag)
            return
        self.counts[tag] += 1
        attr = dict(attrs)
        if tag == 'html': self.language = attr.get('lang')
        for name in ('src','href'):
            if attr.get(name): self.links.append(attr[name])
    def handle_endtag(self, tag):
        if self.skip and self.skip[-1] == tag: self.skip.pop()
    def handle_data(self, text):
        if not self.skip and text.strip(): self.text.append(text)
    def normalized(self): return re.sub(r'\s+', ' ', ' '.join(self.text)).strip()


def inspect(source_record, staging, preview_result, output):
    from libzim.reader import Archive, set_cluster_cache_max_size
    source = safe_path(staging, 'sources/' + source_record['source_asset_id'])
    before = _source_identity(source)
    if before[2] != source_record['source_size_bytes']:
        raise SafetyError('Captured source size changed')
    fragment = read(Path(preview_result['candidate_fragment']))
    outputs = {a['source_archive_entry']: a for a in fragment['assets'] if a.get('export_document')}
    selected = source_record['candidates']
    if set(outputs) != {a['entry'] for a in selected}:
        raise SafetyError('Trial document output set differs from the frozen selection')
    locations = {a['id']: safe_path(staging, a['relative_path']) for a in preview_result['outputs']}
    set_cluster_cache_max_size(2)
    archive = Archive(source); archive.dirent_cache_max_size = 4096
    records = []
    for row in selected:
        item = archive.get_entry_by_path(row['entry']).get_item()
        if item.size != row['size_bytes'] or item.size > MAX_ENTRY:
            raise SafetyError('Entry changed or exceeds its frozen item bound')
        body = bytes(item.content)
        if hashlib.sha256(body).hexdigest() != row['entry_sha256']:
            raise SafetyError('Entry hash changed from frozen candidate evidence')
        asset = outputs[row['entry']]; target = locations[asset['id']]
        if target.stat().st_size > 4 * MAX_ENTRY or sha256_file(target) != asset['sha256']:
            raise SafetyError('Generated document changed or exceeds structural read bound')
        derived = target.read_bytes()
        result = {'entry': row['entry'], 'asset_id': asset['id'], 'source_sha256': row['entry_sha256'],
                  'output_sha256': asset['sha256'], 'output_path': str(target), 'mime': row['mime'], 'topics': row['topics']}
        if row['mime'] == 'application/pdf':
            result.update(original_pdf_retained=derived == body, structural_pass=derived == body)
        else:
            left, right = Document(), Document()
            left.feed(body.decode('utf-8', errors='strict')); left.close()
            right.feed(derived.decode('utf-8', errors='strict')); right.close()
            original_text, generated_text = left.normalized(), right.normalized()
            from owl.acquisition.sampling import excerpt_windows
            result['utility_excerpts']=excerpt_windows(original_text)
            counts = {tag: {'source': left.counts[tag], 'output': right.counts[tag]}
                      for tag in ('img','table','figure','figcaption','math','svg','canvas','video','audio')}
            losses = [tag for tag, count in counts.items() if count['source'] > count['output']]
            text_present = original_text in generated_text
            result.update(source_language=getattr(left,'language',None), source_text_characters=len(original_text),
                output_text_characters=len(generated_text), normalized_source_text_present=text_present,
                structure=counts, structural_losses=losses, structural_pass=text_present and not losses)
        records.append(result)
    if _source_identity(source) != before:
        raise SafetyError('Source changed during structural inspection')
    report = {'schema_version': 1, 'content_ready': False, 'source_asset_id': source_record['source_asset_id'],
        'source_sha256': source_record['source_sha256'], 'documents': len(records),
        'structural_passed': sum(r['structural_pass'] for r in records),
        'original_pdf_count': sum(r.get('original_pdf_retained') is True for r in records),
        'content_review': 'pending; structural checks are not substantive approval', 'records': records}
    write(output, report)
    return {k:v for k,v in report.items() if k != 'records'}


def wait_for_prior_queue(directory, plan_path, task_ids, *, timeout=6*60*60, sleep=time.sleep):
    """Avoid competing with the frozen prior direct-export queue on its batch."""
    from owl.acquisition.supervisor import digest
    plan = read(plan_path)
    expected = digest(plan)
    if not task_ids or set(task_ids) - {t['id'] for t in plan['tasks']}:
        raise SafetyError('Unknown prior trial tasks')
    started = time.monotonic()
    while True:
        owner = read(directory / 'owner.json')
        if owner.get('plan_sha256') != expected:
            raise SafetyError('Prior supervisor belongs to a different frozen plan')
        state = read(directory / 'state.json')
        if all(state['tasks'][identity]['state'] in {'done','needs_review','blocked'} for identity in task_ids):
            return
        if state['state'] in {'paused','failed'}:
            raise SafetyError('Prior supervisor is paused or failed; do not bypass it')
        if time.monotonic() - started > timeout:
            raise SafetyError('Prior direct-export queue did not finish within six hours')
        sleep(30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare','run','report'])
    parser.add_argument('--candidates',type=Path,default=Path('catalog/acquisition/direct-local-candidates.json'))
    parser.add_argument('--output',type=Path,default=Path('.owl/acquisition/direct-trial'))
    parser.add_argument('--staging',type=Path)
    parser.add_argument('--resource')
    parser.add_argument('--wait-supervisor',type=Path)
    parser.add_argument('--wait-plan',type=Path)
    parser.add_argument('--wait-task',action='append',default=[])
    args=parser.parse_args()
    if args.command=='prepare':
        result=prepare(args.candidates,args.output)
        print(json.dumps({k:v for k,v in result.items() if k!='recipes'} | {'recipes':[{k:v for k,v in r.items() if k not in {'recipe','assets'}} for r in result['recipes']]}))
        return
    trial=read(args.output/'trial.json')
    if trial['candidate_manifest_sha256']!=sha256_file(args.candidates):raise SafetyError('Candidate manifest changed')
    candidates={r['source_asset_id']:r for r in read(args.candidates)['sources']}
    if args.command=='report':
        results=[read(args.output/r['id']/'result.json') for r in trial['recipes'] if (args.output/r['id']/'result.json').exists()]
        summaries=[]
        for result in results:
            summary={k:v for k,v in result.items() if k not in {'candidate_fragment','structural','error'}}
            if result.get('error'):summary['error']=result['error'][:220]
            if result.get('structural'):
                summary['structural']={k:v for k,v in result['structural'].items() if k in {'documents','structural_passed','original_pdf_count'}}
            summaries.append(summary)
        print(json.dumps({'content_ready':False,'finished':len(results),'expected':len(trial['recipes']),'results':summaries}));return
    if args.staging is None:parser.error('--staging required for run')
    if args.wait_supervisor:
        if args.wait_plan is None:parser.error('--wait-plan is required with --wait-supervisor')
        wait_for_prior_queue(args.wait_supervisor,args.wait_plan,args.wait_task)
    selected=[r for r in trial['recipes'] if not args.resource or r['id']==args.resource or candidates[r['source_asset_id']]['resource_id']==args.resource]
    if not selected:raise SafetyError('Requested resource absent from trial')
    for row in selected:
        last=[0.0]
        def progress(message):
            if time.monotonic()-last[0]>10:
                print(message[:350],flush=True);last[0]=time.monotonic()
        folder=args.output/row['id']
        try:
            result=preview(args.staging,Path(row['recipe']),Path(row['assets']),preview_bytes=TOTAL_PREVIEW,
                scratch_bytes=TOTAL_SCRATCH,reserve_bytes=10_000_000_000,resource_ids=[candidates[row['source_asset_id']]['resource_id']],
                profile='full-1tb',progress=progress)
            if result.get('reused'):
                receipt=read(Path(result['receipt']));result['outputs']=receipt['outputs']
            write(folder/'preview-result.json',result)
            structural=inspect(candidates[row['source_asset_id']],args.staging,result,folder/'structure.json')
            final={'id':row['id'],'status':'awaiting_review','content_ready':False,'exported_files':len(result['outputs']),
                   'output_bytes':sum(r['size_bytes'] for r in result['outputs']), 'warning_count':len(result.get('blockers',[])),
                   'structural':structural,'candidate_fragment':result['candidate_fragment']}
        except Exception as error:
            final={'id':row['id'],'status':'blocked','content_ready':False,'error_type':type(error).__name__,'error':str(error)[:700]}
        write(folder/'result.json',final)
        print(json.dumps(final),flush=True)


if __name__=='__main__': main()
