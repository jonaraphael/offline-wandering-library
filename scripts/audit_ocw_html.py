#!/usr/bin/env python3
"""Inspect complete captured OCW course HTML with explicitly unpinned media stand-ins.

No media bodies are opened or acquired. This produces dependency-review evidence,
not a renderable recipe, accepted pins or content readiness.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition import ocw_package
from owl.safety import SafetyError, atomic_write, reject_symlinks


def inspect(inventory, source_root):
    source_id=inventory['source_id']; recipe_id=source_id+'_html_audit'
    package={'id':source_id,'sha256':inventory['source_sha256'],'size_bytes':inventory['source_bytes']}
    assets={source_id:package}; members=[]
    for row in inventory['members']:
        identity='member_'+hashlib.sha256(row['path'].encode()).hexdigest()[:32]
        suffix=Path(row['path']).suffix.lower()
        assets[identity]={'id':identity,'destination':'REFERENCE/COURSES/'+source_id+'/members/'+identity+suffix,
            'generation':{'recipe_id':recipe_id}}
        members.append({**row,'output_asset_id':identity})
    media=[]
    for record in inventory['media']:
        identity=record['id']
        assets[identity]={'id':identity,'destination':'REFERENCE/COURSES/MEDIA/'+identity+'.mp4',
            'source_pin':'pending-no-media-read'}
        media.append({'asset_id':identity,'source_url':record['source_url'],'lessons':record['lessons']})
    recipe={'id':recipe_id,'source_asset_ids':[source_id]+[row['asset_id'] for row in media],
        'output_asset_ids':[row['output_asset_id'] for row in members],
        'selection':{'transformation_version':ocw_package.VERSION,'source_asset_id':source_id,'members':members,'media':media}}
    report=ocw_package.inspect_package(recipe,{source_id:source_root/source_id},assets)
    report.update(source_id=source_id,course=inventory['course']['course_title'],source_sha256=package['sha256'],
        media_pins='pending; body-free stand-ins only',media_bodies_read=0)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory-dir',required=True,type=Path)
    parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args(); summaries=[]
    reject_symlinks(args.output_dir); args.output_dir.mkdir(parents=True,exist_ok=True)
    inventories=sorted(args.inventory_dir.glob('*.json'))
    if len(inventories)>64:raise SafetyError('OCW course audit inventory count exceeds 64')
    for path in inventories:
        if path.stat().st_size>16*1024*1024:raise SafetyError('OCW inventory exceeds 16 MiB')
        inventory=json.loads(path.read_text())
        if inventory['gaps']:continue
        print('AUDIT '+inventory['source_id'],file=sys.stderr,flush=True)
        report=inspect(inventory,args.source_root)
        payload=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
        if len(payload)>64*1024*1024:raise SafetyError('OCW audit report exceeds 64 MiB')
        atomic_write(args.output_dir/(inventory['source_id']+'.json'),payload)
        counts=Counter(row['kind'] for row in report['issues'])
        values=Counter((row['kind'],row['value']) for row in report['issues'])
        summary={key:report[key] for key in ('source_id','course','files','output_bytes','content_ready','media_bodies_read')}
        summary.update(issue_counts=dict(counts),common_issues=[{'kind':k,'value':v,'count':c} for (k,v),c in values.most_common(12)],
            report_sha256=hashlib.sha256(payload).hexdigest())
        summaries.append(summary)
        print(json.dumps({key:value for key,value in summary.items() if key!='common_issues'},sort_keys=True),flush=True)
    atomic_write(args.output_dir/'summary.json',(json.dumps(summaries,sort_keys=True,indent=2)+'\n').encode())

if __name__=='__main__':
    main()
