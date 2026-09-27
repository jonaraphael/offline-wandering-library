"""Freeze publisher-linked OCW media from captured course inventories and IA metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from ..safety import SafetyError, atomic_write, reject_symlinks
from .capture import normalize_manifest
from .metadata import Fetcher


def freeze(inventories, fetcher, *, identity='ocw-foundational-media-v1'):
    candidates, archive_ids = {}, set()
    for document in inventories:
        if document.get('transformation_version') != 2 or document.get('content_ready') is not False:
            raise SafetyError('Media freeze requires the current pending package inventory')
        for item in document['media']:
            url = item['source_url']; parts = urlsplit(url)
            components = parts.path.split('/')
            if parts.scheme != 'https' or parts.netloc != 'archive.org' or len(components)<4 or components[1]!='download':
                raise SafetyError('Expected publisher-linked Archive.org media identity')
            archive_id, filename = unquote(components[2]), unquote('/'.join(components[3:]))
            if not filename.lower().endswith(('.mp4','.mp3','.webm')):
                raise SafetyError('Unsupported OCW media rendition')
            archive_ids.add(archive_id)
            row = candidates.setdefault(url, {**item, 'archive_id':archive_id, 'filename':filename,
                'courses':[], 'package_pins':[], 'metadata_members':[]})
            row['courses'].append(document['course']['course_title'])
            row['package_pins'].append({'source_id':document['source_id'],'sha256':document['source_sha256']})
            row['metadata_members'].extend(lesson['metadata_member'] for lesson in item['lessons'])
    if len(archive_ids)>100 or not 1<=len(candidates)<=2000:
        raise SafetyError('OCW media discovery exceeds the bounded initial batch')
    metadata = {}
    for archive_id in sorted(archive_ids):
        url='https://archive.org/metadata/'+quote(archive_id,safe='')
        body=fetcher.fetch(url,kind='json')
        record=json.loads(body)
        if record.get('metadata',{}).get('identifier')!=archive_id or not isinstance(record.get('files'),list):
            raise SafetyError('Publisher archive metadata has a different identity')
        if len(record['files'])>50000:
            raise SafetyError('Publisher media file inventory exceeds bound')
        rows={}
        for item in record['files']:
            name=item.get('name')
            if not isinstance(name,str) or name in rows:
                raise SafetyError('Duplicate or missing publisher media filename')
            rows[name]=item
        metadata[archive_id]=(record['metadata'],rows,{'url':url,'sha256':hashlib.sha256(body).hexdigest(),'kind':'json'})
    sources, exceptions = [], []
    for url, candidate in sorted(candidates.items()):
        info, files, evidence=metadata[candidate['archive_id']]
        raw=files.get(candidate['filename'])
        if not raw:
            exceptions.append({'source_url':url,'reason':'Exact publisher-linked file absent from archive metadata'})
            continue
        size=raw.get('size')
        if not isinstance(size,(str,int)) or isinstance(size,bool) or not str(size).isdigit() or int(size)<=0:
            raise SafetyError('Publisher media lacks an exact positive file size')
        checksums={k:raw[k] for k in ('md5','sha1','crc32') if raw.get(k)}
        if not checksums:
            raise SafetyError('Publisher media lacks available integrity metadata')
        version='archive-mtime:'+str(raw.get('mtime','unknown'))
        extension=candidate['filename'].rsplit('.',1)[-1].lower()
        identifier=candidate['id']
        label=raw.get('title') or candidate['filename']
        creator=info.get('creator','MIT OpenCourseWare')
        license_url=info.get('licenseurl','See original publisher course and media notices')
        source={'id':identifier,'resource_ids':['complete-courses-expansion'],'source_url':url,
            'version':version,'size_bytes':int(size),'sha256':None,'publisher_checksums':checksums,
            'metadata_evidence':[evidence],
            'publisher_course_bindings':{'courses':sorted(set(candidate['courses'])),
                'package_pins':candidate['package_pins'],'metadata_members':candidate['metadata_members']},
            'rendition':{'policy':'One exact publisher-linked rendition; do not upscale or retain alternate encodings',
                'height':raw.get('height'),'width':raw.get('width'),'duration_seconds':raw.get('length'),
                'review':'Check available publisher720p alternative and actual legibility before admission'},
            'fullasset_metadata':{'id':identifier,'title':label,'category':'education','format':extension,
                'language':'en','license':str(license_url),'publisher':str(creator),
                'attribution':str(creator)+'; retain original course, media and individual notices.',
                'source_url':url,'source_page':'https://archive.org/details/'+quote(candidate['archive_id'],safe=''),
                'version':version,'size_bytes':int(size),'sha256':None,'profiles':[],
                'destination':'REFERENCE/COURSES/MEDIA/'+identifier+'.'+extension,
                'required':True,'critical':False,'illustrated':False,'reader_required':False,
                'redistributable':False,'resource_type':'reference',
                'description':'Publisher-linked course media pending integrity, language, rendition and complete-course review.'}}
        from ..catalog import validate_catalog
        validate_catalog({'schema_version':1,'assets':[dict(source['fullasset_metadata'],status='unresolved',
            unresolved_reason='Capture and complete-course review pending')]})
        sources.append(source)
    if exceptions:
        # No silent truncation into a seemingly complete media selection.
        return {'schema_version':1,'content_ready':False,'sources':sources,'exceptions':exceptions}
    manifest=normalize_manifest({'schema_version':1,'kind':'acquisition','id':identity,'profile':'full-1tb',
        'content_ready':False,'sources':sources,'budget':{'download_bytes':sum(s['size_bytes'] for s in sources),
        'expanded_bytes':0,'preview_bytes':0,'scratch_bytes':0,'cache_bytes':0},
        'review_requirements':['Course-package inventory gaps remain pending; media capture does not establish course completeness.',
            'Verify English language, original rendition legibility, captions, local playback and individual notices.']})
    return manifest


def prepare(inventory_directory, cache_directory, output, *, offline=False, course_sources=(), identity='ocw-foundational-media-v1'):
    paths=sorted(Path(inventory_directory).glob('*.json'))
    if not 1<=len(paths)<=100:
        raise SafetyError('Select one to100 frozen course inventories')
    inventories=[]
    for path in paths:
        reject_symlinks(path)
        if path.stat().st_size>16*1024**2:raise SafetyError('Course inventory exceeds16MiB')
        inventories.append(json.loads(path.read_text()))
    if course_sources:
        requested=set(course_sources)
        if requested-{row['source_id'] for row in inventories}:
            raise SafetyError('Requested course source is absent from inventories')
        inventories=[row for row in inventories if row['source_id'] in requested]
    result=freeze(inventories,Fetcher(Path(cache_directory),offline=offline),identity=identity)
    payload=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    if len(payload)>16*1024**2:raise SafetyError('Media capture manifest exceeds16MiB')
    destination=Path(output);reject_symlinks(destination)
    if destination.exists() and destination.read_bytes()!=payload:
        raise SafetyError('Frozen media selection differs; use a new output/version')
    destination.parent.mkdir(parents=True,exist_ok=True);atomic_write(destination,payload)
    return {'output':str(output),'content_ready':False,'sources':len(result['sources']),
        'source_bytes':sum(s['size_bytes'] for s in result['sources']),
        'storage_peak_bytes':result.get('storage_peak_bytes'),'exceptions':len(result.get('exceptions',[])),
        'body_downloads':0}
