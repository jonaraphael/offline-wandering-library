#!/usr/bin/env python3
"""Freeze complete captured course selections with explicitly reviewed decoration policies.

Reads existing package bodies and frozen media metadata only. Acquisition and
ordinary output rendering remain separate registered build/preview operations.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import _read, _digest, load_manifest, normalize_manifest
from owl.acquisition.ocw_expansion import immutable_json
from owl.acquisition.ocw_html import _Tokens
from owl.acquisition.ocw_package import inspect_package
from owl.archive import ZipSource, MAX_EXPLICIT_PACKAGE_BYTES
from owl.safety import SafetyError


def reviewed_tags(text, choices):
    policies={};counts=Counter()
    for token in _Tokens(text).tokens:
        if token['kind']!='start':continue
        attrs=token['attrs'];reason=None;kind=None
        if token['tag']=='img' and attrs.get('alt')=='':
            if ('gallery-posters' in choices and 'thumbnail' in attrs.get('class','').split()
                    and attrs.get('src','').startswith('https://img.youtube.com/vi/')):
                kind='decorative-image';reason='Optional gallery poster; the adjacent original lecture title and linked lesson context are retained.'
            elif 'hlevel-help-icon' in choices and attrs.get('src')=='../../images/educator/icon-question-hlevel.png':
                kind='decorative-image';reason='Missing alt-empty H-Level help decoration; the original H-Level Graduate Credit text and all course material are retained.'
        if (token['tag']=='a' and 'memorial-warning' in choices and attrs.get('onclick')=='event.preventDefault()'
                and attrs.get('href')=='https://www.ocw-openmatters.org/2020/06/10/in-memory-of-herb-gross/'
                and 'external-link-warning' in attrs.get('class','').split()):
            kind='obsolete-external-warning-handler';reason='Optional instructor memorial reference; retain original URL and label while removing retired modal interception.'
        if reason:
            pin=hashlib.sha256(token['raw'].encode()).hexdigest();counts[pin]+=1
            policies[pin]={'tag_sha256':pin,'kind':kind,'reason':reason}
    return [{**policies[pin],'count':counts[pin]} for pin in sorted(policies)]


def run(args):
    chosen=_read(args.selection);rows=chosen['courses']
    if not 1<=len(rows)<=25:raise SafetyError('Reviewed course batch requires1–25 courses')
    packages={s['id']:s for s in load_manifest(args.package_staging/'manifest.json')['sources']}
    prior={s['source_url'] for p in args.existing_capture for s in load_manifest(p)['sources'] if s.get('fullasset_metadata',{}).get('format')=='mp4'}
    spec=importlib.util.spec_from_file_location('ocw_preview',ROOT/'scripts/prepare_ocw_preview.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sources={};local={};results=[]
    for row in rows:
        sid=row['source_id'];inventory=_read(args.review_root/'inventories'/(sid+'.json'));src={**packages[sid],'sha256':inventory['source_sha256']}
        if row['source_sha256']!=inventory['source_sha256'] or not row.get('essential_material_review'):
            raise SafetyError('Course selection needs exact source pin and substantive essential-material review')
        selection=load_manifest(args.review_root/'media-proposals'/(sid+'.json'));media={s['id']:s for s in selection['sources']}
        if any(s['source_url'] in prior for s in media.values()):raise SafetyError('Course selection overlaps a prior captured media rendition')
        recipe,templates=module.freeze(inventory,src,media)
        policies={}
        with ZipSource(args.package_staging/'sources'/sid,src,max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,allow_long_member_names=True) as archive:
            for member in inventory['members']:
                if not member['path'].endswith('.html'):continue
                data=archive.archive.read(member['path'])
                if len(data)!=member['size_bytes'] or hashlib.sha256(data).hexdigest()!=member['sha256']:
                    raise SafetyError('Reviewed decoration page differs from exact frozen member')
                tags=reviewed_tags(data.decode(),row.get('optional_policies',[]))
                if tags:policies[member['path']]=tags
        recipe['selection']['reviewed_html_omissions']=policies
        assets={a['id']:a for a in templates['assets']};assets[sid]=src
        audit=inspect_package(recipe,{sid:args.package_staging/'sources'/sid},assets)
        destination=args.output/sid
        for name,value in [('inventory.json',inventory),('dependency-audit.json',audit),('policy.json',{'source_sha256':src['sha256'],'local_link_repairs':{},'reviewed_html_omissions':policies,'essential_material_review':row['essential_material_review']})]:
            immutable_json(destination/name,value)
        if audit['issues']:raise SafetyError('Reviewed course still has unresolved dependencies: '+sid)
        for source in [src,*media.values()]:
            if source['id'] in sources and sources[source['id']]!=source:raise SafetyError('New course media identities conflict')
            sources[source['id']]=source
        local[sid]=str(args.package_staging/'sources'/sid)
        results.append({'source_id':sid,'title':inventory['course']['course_title'],'ordinary_package_bytes':audit['output_bytes'],
            'media_bytes':sum(s['size_bytes'] for s in media.values()),'media_sources':len(media),'files':audit['files'],'dependency_issues':0,
            'source_sha256':src['sha256'],'reviewed_optional_tags':sum(t['count'] for tags in policies.values() for t in tags)})
    expected=sum(r['ordinary_package_bytes']+r['media_bytes'] for r in results)
    if args.preview_bytes<expected:raise SafetyError('Preview allowance is smaller than measured complete ordinary outputs')
    manifest=normalize_manifest({'schema_version':1,'kind':'acquisition','id':chosen['id'],'profile':'full-1tb','content_ready':False,
        'sources':list(sources.values()),'budget':{'download_bytes':sum(s['size_bytes'] for s in sources.values()),'expanded_bytes':0,
            'preview_bytes':args.preview_bytes,'scratch_bytes':1048576,'cache_bytes':0},
        'review_requirements':['Source inputs remain unapproved. Frozen optional tag policies preserve original teaching text, notes, assignments, solutions and navigation.',
            'Complete ordinary output review, observed playback, teaching legibility, captions and notices remain required. No ZIP input or decorative support receives useful-content credit.']})
    immutable_json(args.capture_output,manifest);immutable_json(args.output/'local-originals.json',local)
    report={'schema_version':1,'content_ready':False,'accepted_useful_bytes':0,'courses':results,'expected_ordinary_bytes':expected,
        'unique_media_source_bytes':sum(r['media_bytes'] for r in results),'capture_peak_bytes':manifest['storage_peak_bytes'],'body_downloads':0}
    immutable_json(args.output/'report.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['package-staging','review-root','selection','output','capture-output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--existing-capture',type=Path,action='append',default=[]);p.add_argument('--preview-bytes',type=int,required=True)
    run(p.parse_args())
