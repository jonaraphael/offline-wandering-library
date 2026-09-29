#!/usr/bin/env python3
"""Freeze exact SQLite package repairs after all missing companions are captured.

Reads only receipted local bodies and a reviewed source-bound policy. Retains the
whole official ZIP and every original member; never admits the proposed edition.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import load_capture_sources,_json,_digest
from owl.acquisition.zip_localized import rewrite_member,validate_recipe
from owl.archive import ZipSource
from owl.catalog import read_yaml
from owl.safety import SafetyError,atomic_write,sha256_file


def immutable(path,value):
    data=_json(value)
    if len(data)>16*1024*1024:raise SafetyError('Package proposal exceeds16MiB')
    if path.exists() and path.read_bytes()!=data:raise SafetyError('Frozen proposal changed; use a new version')
    atomic_write(path,data)


def prepare(args):
    policy=json.loads(args.policy.read_text())
    if policy.get('schema_version')!=1 or policy.get('original_audit_sha256')!=sha256_file(args.source_audit):
        raise SafetyError('SQLite policy must bind its reviewed original audit')
    manifest,receipts=load_capture_sources(args.staging);by_id={r['source_id']:r for r in receipts}
    sources={s['id']:{**s['fullasset_metadata'],'sha256':by_id[s['id']]['sha256']} for s in manifest['sources']}
    identity=policy['id'];source_id=policy['source_id'];source=sources[source_id]
    if source['sha256']!=policy['source_sha256'] or set(sources)!={source_id,*policy['dependencies'].values(),*policy.get('additional_source_ids',[])}:
        raise SafetyError('SQLite source and companion identities differ from reviewed policy')
    originals=[deepcopy(a) for a in read_yaml(args.members)['assets'] if a.get('archive_member',{}).get('source_asset_id')==source_id]
    if not originals:raise SafetyError('SQLite complete member manifest is absent')
    rules={}
    for repair in policy['repairs']:rules.setdefault(repair['member'],[]).append(repair)
    records=[];outputs=[];used=set()
    with ZipSource(args.staging/by_id[source_id]['relative_path'],source) as archive:
        if {a['archive_member']['path'] for a in originals}!=set(archive.entries):raise SafetyError('SQLite package member set changed')
        for asset in originals:
            name=asset.pop('archive_member')['path'];repairs=[]
            for rule in rules.get(name,[]):
                if rule['original_sha256']!=asset['sha256']:raise SafetyError('Repair source-member hash changed')
                repairs.append({k:v for k,v in rule.items() if k not in {'member','original_sha256'}});used.add(name)
            record={'asset_id':asset['id']+'_local','path':name,'size_bytes':asset['size_bytes'],'sha256':asset['sha256'],'rewrites':repairs}
            for change in policy.get('member_annotations',[]):
                if name==change['member']:
                    if asset['sha256']!=change['original_sha256']:raise SafetyError('Annotated source member changed')
                    record.update({k:v for k,v in change.items() if k in {'stylesheet_patch','reference_annotation'}})
            with archive.archive.open(name) as stream:data=stream.read(asset['size_bytes']+1)
            if len(data)!=asset['size_bytes'] or hashlib.sha256(data).hexdigest()!=asset['sha256']:raise SafetyError('SQLite source member differs from complete pins')
            data=rewrite_member(data,record)
            asset.update(id=record['asset_id'],size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),generation={'recipe_id':identity},version=source['version']+'; counted local references v1')
            records.append(record);outputs.append(asset)
        if used!=set(rules):raise SafetyError('A reviewed repair names an absent member')
        archive.check_source()
    additional=policy.get('additional_source_ids',[])
    for supplemental in policy.get('supplemental_members',[]):
        record=deepcopy(supplemental);origin=record['source_asset_id'];asset=deepcopy(sources[origin])
        if any(asset[key]!=record[key] for key in ('size_bytes','sha256')):raise SafetyError('Supplemental notice differs from policy source pin')
        path=args.staging/by_id[origin]['relative_path'];data=path.read_bytes()
        data=rewrite_member(data,record)
        asset.update(id=record['asset_id'],destination='REFERENCE/COMPUTING/'+record['path'],
            size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),generation={'recipe_id':identity})
        outputs.append(asset);records.append(record)
    recipe={'id':identity,'resource_id':'linux-programming-docs','adapter':'zip_localized','version':'1',
        'source_asset_ids':[source_id,*policy['dependencies'].values(),*additional],'output_asset_ids':[a['id'] for a in outputs],
        'workspace_bytes':50000000,'selection':{'source_asset_id':source_id,'members':records,'dependencies':policy['dependencies'],'additional_source_ids':additional},
        'review':{'status':'pending','evidence':[]},'blockers':['Whole-package output, dependency/notice, browser and optional historical-reference review remain required.'],'metadata_sources':[]}
    # The original notice is a pinned build input; its complete localized
    # derivative supplies the retained rights statement with its captured badge.
    recipe['build_inputs']=[{**{key:sources[identity][key] for key in
        ('id','title','format','source_url','version','size_bytes','sha256','license','publisher','source_page','attribution','language')},
        'notice_asset_ids':[],'source_resource_ids':['linux-programming-docs']} for identity in additional]
    assets=[*[a for identity,a in sources.items() if identity not in additional],*outputs]
    validate_recipe(recipe,{a['id']:a for a in [*sources.values(),*outputs]})
    result={'schema_version':1,'content_ready':False,'kind':'pending-localized-sqlite-package','source_id':source_id,'assets':assets,'recipes':[recipe],
        'policy_sha256':sha256_file(args.policy),'capture_binding':{'manifest_sha256':_digest(manifest),'source_receipts_sha256':_digest(receipts)},
        'optional_historical_reference':policy['optional_historical_reference'],'physical_device_certification':'pending'}
    immutable(args.output,result);immutable(args.output.with_suffix('.recipe.json'),recipe)
    return {'content_ready':False,'members':len(outputs),'companions':len(policy['dependencies']),'repaired_spans':sum(r['expected_count'] for r in policy['repairs']),'output_bytes':sum(a['size_bytes'] for a in outputs),'fragment':str(args.output)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['staging','policy','source-audit','members','output']:p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(prepare(p.parse_args())))


if __name__=='__main__':main()
