#!/usr/bin/env python3
"""Freeze header-only capture candidates for publisher-linked course thumbnails."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition.capture import normalize_manifest, _digest
from owl.acquisition.pins import PinProbe
from owl.archive import ZipSource, MAX_EXPLICIT_PACKAGE_BYTES
from owl.catalog import validate_catalog
from owl.safety import SafetyError, atomic_write, reject_symlinks


def prepare(inventory_path, source_path, dependency_report, cache_dir, output, *, offline=False):
    for path in (inventory_path,dependency_report):
        reject_symlinks(path)
        if path.stat().st_size>16*1024*1024:raise SafetyError('OCW thumbnail metadata exceeds 16 MiB')
    inventory=json.loads(inventory_path.read_text()); dependencies=json.loads(dependency_report.read_text())
    urls=sorted({r['value'] for r in dependencies['issues'] if r['kind']=='active-remote-dependency' and r.get('context')=='img.src'})
    if not 1<=len(urls)<=100:raise SafetyError('OCW thumbnail candidates must contain 1–100 exact dependencies')
    package={'id':inventory['source_id'],'sha256':inventory['source_sha256'],'size_bytes':inventory['source_bytes']}
    publisher={}
    with ZipSource(source_path,package,max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,allow_long_member_names=True) as archive:
        for media in inventory['media']:
            for lesson in media['lessons']:
                member=lesson['metadata_member']; data=archive.archive.read(member['path'])
                if len(data)!=member['size_bytes'] or hashlib.sha256(data).hexdigest()!=member['sha256']:
                    raise SafetyError('Course metadata differs from its frozen member pin')
                record=json.loads(data); url=record.get('video_files',{}).get('video_thumbnail_file')
                if url in urls:
                    publisher.setdefault(url,[]).append({'course_url':'https://ocw.mit.edu/'+inventory['course']['site_url_path']+'/',
                        'lesson_url':'https://ocw.mit.edu/'+inventory['course']['site_url_path']+'/'+lesson['context_path'].removesuffix('index.html'),
                        'metadata_member':member,'source_id':package['id'],'source_sha256':package['sha256'],
                        'license':record.get('license'),'title':record.get('title')})
        archive.check_source()
    if set(publisher)!=set(urls):raise SafetyError('Thumbnail URL lacks exact frozen publisher-course linkage')
    probe=PinProbe(cache_dir,offline=offline); sources=[]; reports=[]
    for url in urls:
        identifier='ocw_thumbnail_'+hashlib.sha256(url.encode()).hexdigest()[:20]
        result=probe.probe({'id':identifier,'url':url});reports.append(result)
        if not result['size_bytes'] or result['size_bytes']>2*1024*1024:
            raise SafetyError('Thumbnail HEAD lacks a bounded exact size: '+url)
        head={k:v for k,v in result['evidence'][0].items() if k!='cached'}
        if head['status']!=200 or head['headers'].get('content-type','').split(';')[0]!='image/jpeg':
            raise SafetyError('Thumbnail HEAD is not an available complete JPEG')
        version='observed-head:'+head['checked_at']
        binding=publisher[url][0]
        sources.append({'id':identifier,'resource_ids':['complete-courses-expansion'],'source_url':url,'version':version,
            'size_bytes':result['size_bytes'],'sha256':result['sha256'],'publisher_checksums':{},
            'metadata_evidence':[{'url':url,'sha256':_digest(head),'kind':'HEAD','body_read':False,'record':head},
                {'url':binding['lesson_url'],'sha256':binding['metadata_member']['sha256'],'kind':'captured-course-metadata'}],
            'publisher_course_bindings':publisher[url],
            'fullasset_metadata':{'id':identifier,'title':binding['title']+' — publisher thumbnail','category':'education','format':'jpg',
                'language':'en','license':binding['license'],'publisher':'MIT OpenCourseWare','attribution':'MIT OpenCourseWare; retain individual publisher notices.',
                'source_url':url,'source_page':binding['lesson_url'],'version':version,'size_bytes':result['size_bytes'],'sha256':result['sha256'],
                'profiles':[],'destination':'REFERENCE/COURSES/MEDIA/'+identifier+'.jpg','required':True,'critical':False,
                'illustrated':False,'reader_required':False,'redistributable':False,'supporting_file':True,
                'resource_type':'reference','status':'unresolved','unresolved_reason':'Whole-file SHA-256 capture and image/notice review pending.',
                'description':'Original publisher-linked thumbnail; whole-file capture and image/notice review pending.'}})
    validate_catalog({'schema_version':1,'assets':[source['fullasset_metadata'] for source in sources]})
    result=normalize_manifest({'schema_version':1,'kind':'acquisition','id':'ocw-python-thumbnails-v1','profile':'full-1tb','content_ready':False,
        'sources':sources,'budget':{'download_bytes':sum(s['size_bytes'] for s in sources),'expanded_bytes':0,'preview_bytes':0,'scratch_bytes':0,'cache_bytes':0},
        'review_requirements':['Observed full-file SHA-256, JPEG integrity, publisher linkage and notices before admission.','Supporting thumbnails add no knowledge content.']})
    reject_symlinks(output);payload=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    if output.exists() and output.read_bytes()!=payload:raise SafetyError('Existing frozen thumbnail manifest changed; choose a fresh output')
    atomic_write(output,payload)
    atomic_write(output.with_suffix('.probe.json'),(json.dumps({'body_downloads':0,'records':reports},sort_keys=True,indent=2)+'\n').encode())
    return {'sources':len(sources),'source_bytes':result['budget']['download_bytes'],'whole_sha_pins':sum(bool(s['sha256']) for s in sources),
        'body_downloads':0,'content_ready':False,'output':str(output)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('inventory','source','dependency-report','cache-dir','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--offline',action='store_true');a=p.parse_args()
    print(json.dumps(prepare(a.inventory,a.source,a.dependency_report,a.cache_dir,a.output,offline=a.offline),sort_keys=True))

if __name__=='__main__':main()
