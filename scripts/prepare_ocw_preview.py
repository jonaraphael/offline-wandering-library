#!/usr/bin/env python3
"""Freeze pending complete-package outputs and audit existing captured OCW ZIPs.

Only reads captured bodies. Media identities come from a frozen acquisition
manifest; absent media receipts remain explicit pending pins. The build/preview
commands acquire and render separately after all required originals are pinned.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from owl.acquisition.capture import load_manifest, _digest, _receipt
from owl.acquisition.ocw_package import portable_member_path, inspect_package, VERSION
from owl.safety import atomic_write, SafetyError


def freeze(inventory, source, media_sources, dependencies=()):
    if inventory.get('transformation_version') != 2 or inventory.get('gaps'):
        raise SafetyError('Course has unresolved package media/caption gaps')
    if inventory.get('excluded_translations'):
        raise SafetyError('Explicit translated pages require a reviewed removal/link recipe before this full-package export')
    if inventory['source_id'] != source['id'] or inventory['source_sha256'] != source['sha256']:
        raise SafetyError('Course inventory source differs from captured pin')
    course = inventory['course']; sid = source['id']; rid = sid+'_ordinary_v1'
    title = course['course_title']; base = 'REFERENCE/COURSES/'+sid
    page = 'https://ocw.mit.edu/'+course['site_url_path'].strip('/')+'/'
    assets, members = [], []
    for row in inventory['members']:
        name = row['path']; identity = rid+'_'+hashlib.sha256(name.encode()).hexdigest()[:20]
        extension = Path(name).suffix.lower().lstrip('.') or 'data'
        document = extension in {'html','htm','pdf','txt','md'} and not name.endswith('/data.json')
        assets.append({'id':identity, 'title':title+': '+name, 'category':'education', 'format':extension,
            'source_url':page, 'destination':base+'/'+portable_member_path(name), 'version':source['version'],
            'size_bytes':None, 'sha256':None, 'license':'Preserve original MIT OCW and third-party notices',
            'redistributable':False, 'required':True, 'profiles':[], 'publisher':'MIT OpenCourseWare',
            'source_page':page, 'language':'en', 'supporting_file':not document,
            'status':'unresolved', 'unresolved_reason':'Captured package transformation and content review pending',
            'generation':{'recipe_id':rid}})
        members.append({**row, 'output_asset_id':identity})
    media = []
    for row in inventory['media']:
        original = media_sources.get(row['id'])
        if not original or original['source_url'] != row['source_url']:
            raise SafetyError('Course media identity is missing from frozen capture selection')
        asset = dict(original['fullasset_metadata'])
        # Earlier pending captures used a proposed root name. Production
        # destinations are independently frozen here within the real catalog.
        asset['destination'] = 'REFERENCE/COURSES/MEDIA/'+asset['id']+'.'+asset['format']
        asset['resource_type'] = 'reference'
        asset['sha256'] = original.get('sha256')
        assets.append(asset)
        media.append({'source_url':row['source_url'], 'asset_id':row['id'], 'lessons':row['lessons']})
    dependency_map = {}
    for original in dependencies:
        asset = dict(original['fullasset_metadata'], sha256=original['sha256'])
        if original['source_url'] in dependency_map or asset['id'] in {a['id'] for a in assets}:
            raise SafetyError('Duplicate retained course dependency')
        assets.append(asset);dependency_map[original['source_url']]=asset['id']
    package = {k:source[k] for k in ('id','source_url','version','size_bytes','sha256')}
    package.update(title=title+' original course package', format='zip',
        license='Original course and third-party notices retained in complete generated package',
        notice_asset_ids=[], source_resource_ids=['complete-courses-expansion'], publisher='MIT OpenCourseWare',
        source_page=page, language='en')
    recipe = {'id':rid, 'resource_id':'complete-courses-expansion', 'adapter':'ocw_package', 'version':str(VERSION),
        'source_asset_ids':[sid, *[m['asset_id'] for m in media], *dependency_map.values()], 'output_asset_ids':[m['output_asset_id'] for m in members],
        'build_inputs':[package], 'workspace_bytes':1024*1024,
        'selection':{'transformation_version':VERSION, 'source_asset_id':sid, 'members':members, 'media':media,
            'work_ids':['ocw:'+course['site_uid']], 'inventory_sha256':_digest(inventory), 'dependencies':dependency_map},
        'review':{'status':'pending','evidence':[]},
        'blockers':['Review complete local dependency inventory, notices, caption language, essential external readings and browser playback.']}
    return recipe, {'schema_version':1,'assets':assets}


def immutable(path, value):
    data=(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode()
    if len(data)>16*1024*1024:raise SafetyError('Pending control artifact exceeds16MiB')
    if path.exists() and path.read_bytes()!=data:raise SafetyError('Frozen proposal changed; use a new output directory')
    path.parent.mkdir(parents=True,exist_ok=True);atomic_write(path,data)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--package-staging',type=Path,required=True)
    p.add_argument('--media-manifest',type=Path,required=True);p.add_argument('--media-staging',type=Path)
    p.add_argument('--dependency-staging',type=Path,action='append',default=[])
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();inventory=json.loads(a.inventory.read_text())
    manifest=load_manifest(a.package_staging/'manifest.json')
    source=next(s for s in manifest['sources'] if s['id']==inventory['source_id'])
    receipt=_receipt(a.package_staging,source,_digest(manifest))
    if receipt is None:raise SafetyError('Package original has no verified capture receipt')
    source={**source,'sha256':receipt['sha256']}
    media=load_manifest(a.media_manifest);by_id={s['id']:s for s in media['sources']}
    if a.media_staging:
        captured=load_manifest(a.media_staging/'manifest.json')
        if _digest(captured)!=_digest(media):raise SafetyError('Media staging manifest differs')
        for item in by_id.values():
            if item['id'] in {m['id'] for m in inventory['media']}:
                saved=_receipt(a.media_staging,item,_digest(captured))
                if saved:item['sha256']=saved['sha256']
    dependencies=[]
    for folder in a.dependency_staging:
        capture=load_manifest(folder/'manifest.json')
        for item in capture['sources']:
            saved=_receipt(folder,item,_digest(capture))
            if saved is None:raise SafetyError('Required course dependency has not completed capture')
            dependencies.append({**item,'sha256':saved['sha256']})
    recipe,templates=freeze(inventory,source,by_id,dependencies)
    assets={x['id']:x for x in templates['assets']};assets[source['id']]=source
    result=inspect_package(recipe,{source['id']:a.package_staging/receipt['relative_path']},assets)
    for name,value in [('recipe.json',recipe),('assets.json',templates),('dependency-audit.json',result)]:
        immutable(a.output/name,value)
    print(json.dumps({'operation':'prepare-ocw-preview','content_ready':False,'body_downloads':0,
        'files':result['files'],'output_bytes':result['output_bytes'],'dependency_issues':len(result['issues']),
        'external_references':len(result['external_links']), 'detail':str(a.output)},sort_keys=True))


if __name__=='__main__':main()
