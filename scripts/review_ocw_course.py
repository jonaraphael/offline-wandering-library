#!/usr/bin/env python3
"""Bounded full inventory and offline browser/media evidence for one OCW preview.

Waits for the exact existing preview receipt, preserves all failure evidence,
and stops at a concrete admission proposal. No bodies are fetched or admitted.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import _digest, _read, _usage, load_manifest
from owl.acquisition.ocw_expansion import immutable_json
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file
from owl.runtime import file_lock


def caption_evidence(text):
    pattern=r'(?m)^(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})'
    rows=list(re.finditer(pattern,text));ends=[];starts=[]
    for row in rows:
        v=row.groups();starts.append(int(v[0] or 0)*3600+int(v[1])*60+int(v[2])+int(v[3])/1000)
        ends.append(int(v[4] or 0)*3600+int(v[5])*60+int(v[6])+int(v[7])/1000)
    return {'cues':len(rows),'first_seconds':min(starts) if starts else None,'last_seconds':max(ends) if ends else None,
        'ordered':all(a<=b for a,b in zip(starts,ends)) and all(a<=b for a,b in zip(starts,starts[1:])),
        'text_sample':' '.join(line for line in text.splitlines() if '-->' not in line and not line.isdigit())[:700]}


def run(args):
    for path in [args.capture_staging,args.inventory,args.output]:reject_symlinks(path)
    if args.output_budget_bytes!=500000000 or args.reserve_bytes<10000000000:
        raise SafetyError('Course review requires its registered500MB peak and10GB reserve')
    inventory=_read(args.inventory);sid=inventory['source_id']
    preview_id=getattr(args,'preview_id',None) or sid+'_ordinary_v1'
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}',preview_id):raise SafetyError('Invalid OCW preview identity')
    preview=args.capture_staging/'previews'/preview_id
    deadline=time.monotonic()+6*3600
    while not (preview/'preview-receipt.json').exists():
        if time.monotonic()>=deadline:raise SafetyError('Preview did not finish within six-hour review dependency wait')
        time.sleep(15)
    manifest=load_manifest(args.capture_staging/'manifest.json');receipt=_read(preview/'preview-receipt.json')
    fragment=_read(preview/'candidate-fragment.json');recipe=fragment['recipes'][0]
    if (receipt['manifest_sha256']!=_digest(manifest) or receipt['candidate_sha256']!=_digest(fragment)
            or recipe['selection']['inventory_sha256']!=_digest(inventory)
            or inventory['gaps'] or inventory['excluded_translations']):
        raise SafetyError('Course preview differs from complete frozen source inventory')
    owner={'schema_version':1,'owner':'owl-ocw-course-review','output_budget_bytes':args.output_budget_bytes,'reserve_bytes':args.reserve_bytes}
    if args.output.exists() and not (args.output/'owner.json').exists():raise SafetyError('Course review output is unowned')
    args.output.mkdir(parents=True,exist_ok=True);immutable_json(args.output/'owner.json',owner)
    review_id=getattr(args,'review_id',None) or sid
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}',review_id):raise SafetyError('Invalid OCW review identity')
    course=args.output/review_id;course.mkdir(exist_ok=True)
    def check_space(amount=0):
        if _usage(args.output)+amount>args.output_budget_bytes or shutil.disk_usage(args.output).free<amount+args.reserve_bytes:
            raise SafetyError('Course review exceeds reserved peak/free space')
    with file_lock(args.output/'review.lock'):
        check_space(20*1024*1024)
        expected={r['id']:r for r in receipt['outputs']+receipt.get('companions',[])}
        sources={s['id']:s for s in manifest['sources']};assets={a['id']:a for a in fragment['assets']}
        for companion in receipt.get('companions',[]):
            source=sources[companion['id']];saved=_read(args.capture_staging/'receipts'/(source['id']+'.json'))
            if saved['sha256']!=companion['sha256'] or saved['size_bytes']!=companion['size_bytes']:
                raise SafetyError('Course companion is not the captured source bytes')
            assets[source['id']]={**source['fullasset_metadata'],'sha256':companion['sha256']}
        if set(expected)!=set(assets):raise SafetyError('Preview outputs/companions do not exactly match reviewed course assets')
        media_ids={row['id'] for row in inventory['media']};media=[]
        for aid,asset in assets.items():
            record=expected[aid];path=safe_path(args.capture_staging,record['relative_path'])
            if path.stat().st_size!=record['size_bytes']:raise SafetyError('Preview output size changed')
            if aid in media_ids:
                media.append({'id':aid,'path':str(path),'sha256':record['sha256'],'size_bytes':record['size_bytes'],
                    'title':asset['title'],'source_url':asset['source_url']})
            elif sha256_file(path)!=record['sha256']:raise SafetyError('Preview output hash changed')
        by_member={row['path']:row for row in recipe['selection']['members']};captions=[]
        for media_record in inventory['media']:
            for lesson in media_record['lessons']:
                for caption in lesson['captions']:
                    record=expected[by_member[caption['path']]['output_asset_id']];path=safe_path(args.capture_staging,record['relative_path'])
                    if record['sha256']!=caption['sha256']:raise SafetyError('Original caption bytes were changed')
                    evidence=caption_evidence(path.read_text(encoding='utf-8-sig'))
                    captions.append({'media_id':media_record['id'],'lesson':lesson['title'],'member':caption['path'],'sha256':caption['sha256'],
                        'language':caption['language'],**evidence})
        immutable_json(course/'media-input.json',{'media':media})
        command=[args.node,str(ROOT/'scripts/check_ocw_media.cjs'),'--input',str(course/'media-input.json'),'--output',str(course/'media'),
            '--budget-root',str(args.output),'--browser',args.browser,'--playwright',args.playwright]
        with (course/'media.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=6*3600)
        media_report=_read(course/'media'/'report.json')
        if (media_report['requested']!=len(media) or media_report['checked']!=len(media)
                or {row['id'] for row in media_report['results']}!=media_ids):
            raise SafetyError('Media review omitted an expected course source')
        check_space(20*1024*1024)
        spec=importlib.util.spec_from_file_location('ocw_browser_package',ROOT/'scripts/check_manual_package.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        browser_args=argparse.Namespace(fragment=preview/'candidate-fragment.json',root=preview/'files',output=course/'browser',
            batch_size=50,node=args.node,browser=args.browser,playwright=args.playwright)
        browser=module.run(browser_args);check_space()
        report={'schema_version':1,'status':'course_evidence_awaiting_review','content_ready':False,'source_id':sid,'course':inventory['course']['course_title'],
            'manifest_sha256':receipt['manifest_sha256'],'preview_receipt_sha256':sha256_file(preview/'preview-receipt.json'),
            'candidate_fragment':str(preview/'candidate-fragment.json'),'candidate_fragment_sha256':sha256_file(preview/'candidate-fragment.json'),
            'files_root':str(preview/'files'),'whole_output_files':len(expected),'whole_output_bytes':sum(r['size_bytes'] for r in expected.values()),
            'build_input_bytes_counted':0,'media_sources':len(media),'media_bytes':sum(r['size_bytes'] for r in media),
            'candidate_nonsupporting_bytes':sum(expected[aid]['size_bytes'] for aid,a in assets.items() if not a.get('supporting_file',False)),
            'media_checked':media_report['checked'],'media_passed':media_report['passed'],'browser':browser,'captions':captions,
            'caption_failures':[c['member'] for c in captions if not c['cues'] or not c['ordered']],
            'remaining_reviews':['Evaluate decoded-frame teaching legibility and English caption samples; retain full failure reports.',
                'Confirm essential readings/exercises/solutions and notices for this exact course.',
                'No sampling result, ZIP input, duplicate rendition or supporting image constitutes useful-byte admission.']}
        immutable_json(course/'report.json',report);print(json.dumps({k:report[k] for k in ['course','whole_output_bytes','media_sources','media_bytes','media_checked','media_passed','caption_failures']}),flush=True)
        return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['capture-staging','inventory','output']:p.add_argument('--'+name,type=Path,required=True)
    for name in ['node','browser','playwright']:p.add_argument('--'+name,required=True)
    p.add_argument('--output-budget-bytes',type=int,default=500000000);p.add_argument('--reserve-bytes',type=int,default=10000000000)
    p.add_argument('--preview-id');p.add_argument('--review-id')
    run(p.parse_args())


if __name__=='__main__':main()
