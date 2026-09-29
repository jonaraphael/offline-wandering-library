"""Inspect captured OCW packages without extracting or acquiring new bodies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote

from ..archive import ZipSource, BLOCK, MAX_EXPLICIT_PACKAGE_BYTES
from ..safety import SafetyError, atomic_write, reject_symlinks
from .capture import _digest, _read, _receipt, load_manifest

VERSION = 2
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024


def package_inventory(path, asset):
    """Hash all bounded members and record original complete video dependencies."""
    members, resources, courses = [], [], []
    with ZipSource(path, asset, max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,
                   allow_long_member_names=True) as source:
        for name, info in sorted(source.entries.items()):
            digest, count, data = hashlib.sha256(), 0, bytearray()
            is_metadata = name == 'data.json' or name.endswith('/data.json')
            if is_metadata and info.file_size > MAX_JSON_BYTES:
                raise SafetyError('OCW resource metadata exceeds 2 MiB')
            with source.archive.open(info) as stream:
                while block := stream.read(min(BLOCK, info.file_size-count+1)):
                    count += len(block)
                    if count > info.file_size:
                        raise SafetyError('OCW member exceeds its audited ZIP size')
                    digest.update(block)
                    if is_metadata:
                        data.extend(block)
            if count != info.file_size:
                raise SafetyError('Truncated OCW package member')
            member = {'path': name, 'size_bytes': count, 'sha256': digest.hexdigest()}
            members.append(member)
            if is_metadata:
                row = json.loads(data)
                if not isinstance(row, dict):
                    raise SafetyError('OCW resource metadata must be an object')
                if name == 'data.json':
                    courses.append(row)
                elif row.get('resourcetype') == 'Video':
                    resources.append({**row, 'metadata_member': member,
                        'html_member': name.removesuffix('data.json')+'index.html'})
        source.check_source()
    if len(courses) != 1:
        raise SafetyError('Course package must contain exactly one root course record')
    paths = {m['path']: m for m in members}
    media, gaps, exclusions = {}, [], []
    for row in resources:
        if not row.get('uid') or not row.get('title') or row['html_member'] not in paths:
            raise SafetyError('Video lacks stable lesson identity/context page')
        files = row.get('video_files', {})
        url = files.get('archive_url', '')
        # Publisher course packages include optional translated resource pages.
        # Record exact explicit language markers; do not infer every other
        # resource is English merely because its course is English.
        if isinstance(url, str) and ('/MIT18.06SCF11-zh/' in url or '_zh-hans-cmn_' in url):
            exclusions.append({'lesson_id':row['uid'], 'title':row['title'],
                'metadata_member':row['metadata_member'], 'source_url':url,
                'reason':'Publisher media identity explicitly marks optional Chinese translation'})
            continue
        parsed = urlsplit(url)
        if parsed.scheme not in {'https', 'http'} or parsed.netloc not in {'archive.org', 'www.archive.org'}:
            gaps.append({'lesson_id': row['uid'], 'title':row['title'],
                'metadata_member':row['metadata_member'], 'reason': 'Missing supported publisher-linked media URL'})
            continue
        url = parsed._replace(scheme='https', netloc='archive.org').geturl()
        identity = 'ocw_media_'+hashlib.sha256(url.encode()).hexdigest()[:20]
        candidate = media.setdefault(url, {'id': identity, 'source_url': url,
            'publisher_links': [], 'lessons': [], 'source_pin': 'pending', 'rendition_review': 'pending'})
        candidate['publisher_links'] = sorted(set(candidate['publisher_links']) | {files['archive_url']})
        captions = []
        caption_records = list(files.get('video_captions_resources', []))
        if files.get('video_captions_file'):
            caption_records.append({'file':files['video_captions_file'],'language':'unlabelled'})
        for caption in caption_records:
            expected = 'static_resources/'+unquote(urlsplit(caption.get('file', '')).path.rsplit('/',1)[-1])
            if caption.get('language') in {'en','unlabelled'} and expected in paths:
                captions.append({**paths[expected], 'language':caption['language'],
                    'language_review':'pending' if caption['language']=='unlabelled' else 'publisher-labelled'})
        if not captions:
            gaps.append({'lesson_id': row['uid'], 'title':row['title'],
                'metadata_member':row['metadata_member'], 'reason': 'No English caption member found'})
        candidate['lessons'].append({'id':row['uid'], 'title':row['title'],
            'context_path':row['html_member'], 'metadata_member':row['metadata_member'],
            'start_time':row.get('start_time'), 'end_time':row.get('end_time'),
            'license':row.get('license'), 'captions':captions})
    return {'schema_version':1, 'transformation_version':VERSION, 'source_id':asset['id'],
        'source_sha256':asset['sha256'], 'source_bytes':asset['size_bytes'],
        'course':courses[0], 'members':members, 'expanded_bytes':sum(m['size_bytes'] for m in members),
        'video_lesson_count':len(resources), 'media':sorted(media.values(),key=lambda m:m['id']),
        'gaps':gaps, 'excluded_translations':exclusions, 'content_ready':False,
        'remaining_reviews':['Complete local links, essential readings, exercises and supplied solutions',
            'One appropriate original media rendition, playback, captions and notices',
            'Retain useful complete files; no duplicate renditions or metadata credited as knowledge']}


def inspect_capture(staging, output, *, isolate_package_failures=False):
    staging, output = Path(staging), Path(output)
    manifest = load_manifest(staging/'manifest.json')
    digest = _digest(manifest)
    reject_symlinks(output)
    output.mkdir(parents=True, exist_ok=True)
    summaries, failures = [], []
    for source in manifest['sources']:
        receipt = _receipt(staging, source, digest)
        if receipt is None:
            raise SafetyError('Course source capture is incomplete')
        asset = {**source, 'sha256':receipt['sha256']}
        destination = output/(asset['id']+'.json')
        if destination.exists():
            result = _read(destination, MAX_REPORT_BYTES)
            if (result.get('source_sha256') != asset['sha256'] or result.get('source_bytes') != asset['size_bytes']
                    or result.get('source_id') != asset['id'] or result.get('transformation_version') != VERSION):
                raise SafetyError('Cached course inventory differs; use a fresh evidence directory')
        else:
            try:
                result = package_inventory(staging/receipt['relative_path'], asset)
            except (ValueError, OSError) as error:
                if not isolate_package_failures:
                    raise
                # Source receipt checks and output writes remain fatal. Only
                # this independently captured package is held at its unchanged
                # archive/inventory bounds; other complete courses can proceed.
                failures.append({'source_id':asset['id'], 'source_sha256':asset['sha256'],
                    'source_bytes':asset['size_bytes'], 'status':'package_inventory_failed',
                    'reason':str(error)[:500], 'content_ready':False})
                continue
            payload = (json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
            if len(payload)>MAX_REPORT_BYTES:
                raise SafetyError('Course inventory exceeds 16 MiB report bound')
            atomic_write(destination,payload)
        summaries.append({'source_id':asset['id'],'source_sha256':asset['sha256'],
            'files':len(result['members']),'expanded_bytes':result['expanded_bytes'],
            'video_lessons':result['video_lesson_count'],'unique_media':len(result['media']),
            'gaps':len(result['gaps']),'inventory_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    return {'operation':'inspect-ocw','content_ready':False,'body_downloads':0,
        'courses':summaries,'failures':failures,'detail_directory':str(output)}
