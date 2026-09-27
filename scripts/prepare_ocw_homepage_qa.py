#!/usr/bin/env python3
"""Prepare a source-bound, <=100 MB homepage-only OCW behavior trial."""
from __future__ import annotations
import argparse,hashlib,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition import capture,ocw_html
from owl.archive import ZipSource,MAX_EXPLICIT_PACKAGE_BYTES
from owl.safety import SafetyError,atomic_write,guard_directory,safe_path
from owl.runtime import file_lock


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('inventory','source-staging','output','production-root','report'):p.add_argument('--'+flag,type=Path,required=True)
    a=p.parse_args();inventory=capture._read(a.inventory,16*1024*1024)
    manifest=capture.load_manifest(a.source_staging/'manifest.json');digest=capture._digest(manifest)
    source=next(s for s in manifest['sources'] if s['id']==inventory['source_id'])
    receipt=capture._receipt(a.source_staging,source,digest)
    if not receipt or receipt['sha256']!=inventory['source_sha256']:raise SafetyError('Homepage QA requires the captured package whole-file pin')
    output,anchor=capture._staging(a.output,a.production_root)
    peak,reserve=100000000,10000000000
    code_hash=hashlib.sha256(Path(ocw_html.__file__).read_bytes()).hexdigest()
    owner={'schema_version':1,'owner':'owl-ocw-homepage-qa','manifest_sha256':digest,'source_id':source['id'],
        'source_sha256':receipt['sha256'],'output_budget_bytes':peak,'reserve_bytes':reserve,'html_transform_sha256':code_hash}
    by_path={r['path']:r for r in inventory['members']}
    chosen=[r for r in inventory['members'] if r['path']=='index.html' or r['path'].startswith('static_shared/') or r['path'].startswith('static_resources/') and Path(r['path']).suffix.lower() in {'.png','.jpg','.jpeg','.svg','.gif','.webp'}]
    if sum(r['size_bytes'] for r in chosen)+1000000>peak:raise SafetyError('Homepage QA source selection exceeds its100MBpeak')
    mapping={r['path']:r['path'] for r in inventory['members']};rows=[];issues=[];rewrites=[]
    with guard_directory(anchor):
        if output.exists() and (not (output/'owner.json').is_file() or capture._read(output/'owner.json')!=owner):raise SafetyError('Homepage QA output is unowned or its source/transform changed')
        output.mkdir(parents=True,exist_ok=True)
        with guard_directory(output),file_lock(output/'qa.lock'):
            capture._space(output,peak,reserve);atomic_write(output/'owner.json',capture._json(owner))
            with ZipSource(a.source_staging/receipt['relative_path'],{**source,'sha256':receipt['sha256']},max_archive_bytes=MAX_EXPLICIT_PACKAGE_BYTES,allow_long_member_names=True) as archive:
                for row in chosen:
                    data=archive.archive.read(row['path'])
                    if len(data)!=row['size_bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise SafetyError('Homepage QA member pin changed')
                    if row['path']=='index.html':
                        result=ocw_html.localize_html(data.decode(),member_path=row['path'],output_destination=row['path'],member_destinations=mapping,media_bindings={},caption_texts={})
                        data=result['html'].encode();issues.extend(result['issues']);rewrites.extend(result['rewrites'])
                    elif row['path'].endswith('.css'):
                        result=ocw_html.localize_css(data.decode(),member_path=row['path'],output_destination=row['path'],member_destinations=mapping)
                        data=result['css'].encode();issues.extend(result['issues']);rewrites.extend(result['rewrites'])
                    if shutil.disk_usage(output).free<len(data)+reserve or capture._usage(output)+len(data)>peak:raise SafetyError('Homepage QA write would cross finite peak or live reserve')
                    atomic_write(safe_path(output,row['path']),data)
                    rows.append({'path':row['path'],'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
                archive.check_source()
            report={'schema_version':1,'kind':'ocw-homepage-qa-preparation','content_ready':False,'scope':'homepage and static assets only; no media or whole-course certification',
                'owner_sha256':capture._digest(owner),'source_sha256':receipt['sha256'],'html_transform_sha256':code_hash,
                'files':rows,'bytes':sum(r['size_bytes'] for r in rows),'output_budget_bytes':peak,'reserve_bytes':reserve,'issues':issues,'rewrites':rewrites,'body_downloads':0}
            atomic_write(output/'qa-preparation.json',capture._json(report));capture._space(output,peak,reserve)
            atomic_write(a.report,capture._json(report))
    print(json.dumps({'content_ready':False,'files':len(rows),'bytes':report['bytes'],'issues':len(issues),'body_downloads':0,'report':str(a.report)}))

if __name__=='__main__':main()
