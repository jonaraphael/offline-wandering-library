#!/usr/bin/env python3
"""Replay one fully pinned ZIP proposal through the normal builder, offline.

The isolated package-trial profile is never a completed default preset and
never admits its proposed assets into the active catalog.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import load_capture_sources, _read, _json, _digest, validate_review_binding
from owl.build import build, _owned_directory
from owl.catalog import validate_catalog
from owl.safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file
from owl.transfer import resume_copy
from owl.verify import verify_drive
from owl.runtime import file_lock

RESERVE=10_000_000_000
PEAK=500_000_000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging',type=Path,required=True)
    parser.add_argument('--fragment',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--production-root',type=Path,default=Path('/Volumes/OWL'))
    parser.add_argument('--review-receipt',type=Path,help='Exact capture review receipt required for generated package replay')
    parser.add_argument('--plan',action='store_true')
    args=parser.parse_args()
    proposal=_read(args.fragment);assets=validate_catalog({'schema_version':1,'assets':proposal['assets']})
    originals=[a for a in assets if not a.get('archive_member') and not a.get('generation')]
    if len(originals)!=1:raise SafetyError('Need one pinned original plus its complete ZIP output set')
    source_id=originals[0]['id']
    if proposal.get('source_id',source_id)!=source_id:raise SafetyError('Proposal source identity differs')
    recipes=[]
    if any(a.get('generation') for a in assets):
        if args.review_receipt is None:raise SafetyError('Generated package replay requires its exact capture review receipt')
        validate_review_binding(proposal,args.review_receipt)
        recipes=deepcopy(proposal.get('recipes',[]))
        if len(recipes)!=1 or recipes[0].get('adapter')!='zip_localized' or recipes[0]['source_asset_ids']!=[source_id]:
            raise SafetyError('Only a complete captured localized ZIP can use generated package replay')
        if set(recipes[0]['output_asset_ids'])!={a['id'] for a in assets if a.get('generation')}:
            raise SafetyError('Reviewed package output set differs from its exact recipe')
        # This approval is scoped to this isolated package trial. The caller's
        # pending fragment and every default catalog remain unchanged.
        recipes[0]['review']={'status':'approved','evidence':['Isolated package trial; capture review SHA256 '+sha256_file(args.review_receipt)]}
        recipes[0]['blockers']=[]
    if any(a['archive_member']['source_asset_id']!=source_id for a in assets if a.get('archive_member')):raise SafetyError('Foreign member source')
    manifest,receipts=load_capture_sources(args.staging);source=next(s for s in manifest['sources'] if s['id']==source_id);receipt=next(r for r in receipts if r['source_id']==source_id)
    if any(originals[0][key]!=source[key] for key in ('source_url','version','size_bytes')) or originals[0]['sha256']!=receipt['sha256']:raise SafetyError('Proposal source differs from captured original')
    output=args.output.resolve();reject_symlinks(output)
    if output==args.staging.resolve() or output.is_relative_to(args.staging.resolve()):raise SafetyError('Keep trial build separate from immutable capture')
    anchor=output
    while not anchor.exists():anchor=anchor.parent
    if not args.production_root.is_dir() or anchor.stat().st_dev==args.production_root.stat().st_dev:raise SafetyError('Trial requires a separate filesystem from production')
    if not output.is_relative_to(args.staging.resolve().parent):raise SafetyError('Trial output must stay under the approved acquisition parent')
    owner={'owner':'owl-captured-package-trial','schema_version':1,'manifest_sha256':_digest(manifest),'proposal_sha256':_digest(proposal)}
    if recipes:owner['review_receipt_sha256']=sha256_file(args.review_receipt)
    if output.exists() and (not (output/'owner.json').is_file() or _read(output/'owner.json')!=owner):raise SafetyError('Trial output ownership or proposal changed')
    if shutil.disk_usage(anchor).free<PEAK+RESERVE:raise SafetyError('Insufficient separate-volume trial space and reserve')
    if args.plan:
        print(json.dumps({'scope':'one-package-trial','source_id':source_id,'assets':len(assets),'source_bytes':source['size_bytes'],'output_bytes':sum(a['size_bytes'] for a in assets),'reserved_peak_bytes':PEAK,'reserve_bytes':RESERVE,'content_ready':False}));return
    output.mkdir(parents=True,exist_ok=True)
    with guard_directory(output), file_lock(output/'trial.lock'):
        atomic_write(output/'owner.json',_json(owner))
        profiles=output/'profiles';profiles.mkdir(exist_ok=True)
        profile={'id':'package-trial','capacity_bytes':PEAK+RESERVE,'reserve_bytes':RESERVE,'search_budget_bytes':64*1024*1024}
        atomic_write(profiles/'package-trial.yaml',_json(profile))
        trial_assets=deepcopy(assets)
        for asset in trial_assets:asset['profiles']=['package-trial']
        catalog=output/'catalog.json';atomic_write(catalog,_json({'schema_version':1,'assets':trial_assets,'acquisition_recipes':recipes}))
        cache=output/'cache';target=output/'drive'
        last=[0.0]
        def progress(message):
            if time.monotonic()-last[0]>15:print(message[:250],flush=True);last[0]=time.monotonic()
        plan=build(target,catalog=catalog,profiles_dir=profiles,profile_name='package-trial',cache_dir=cache,plan_only=True,progress=progress)
        _owned_directory(cache/'owl-v1')
        resume_copy(args.staging/receipt['relative_path'],cache/'owl-v1'/receipt['sha256'],size=receipt['size_bytes'],checksum=receipt['sha256'],progress=progress)
        # Any missing source/cache path fails the trial instead of fetching an
        # unrequested substitute. The ordinary build/extraction/index paths run.
        with patch('owl.build.download',side_effect=SafetyError('Offline package replay must use the verified captured original')):
            result=build(target,catalog=catalog,profiles_dir=profiles,profile_name='package-trial',cache_dir=cache,progress=progress)
        counts=verify_drive(target,emit=lambda _:None)
        report={'schema_version':1,'scope':'one-package-trial','content_ready':False,'source_id':source_id,'source_sha256':receipt['sha256'],
            'proposal_sha256':_digest(proposal),'build_profile':'package-trial','default_preset_complete':False,
            'asset_count':len(assets),'verification':counts,'build_result':result,'planned':plan,'output':str(target),
            'blockers':['Content, notice/dependency and intended-device review remain separate from byte/build verification.']}
        atomic_write(args.evidence,_json(report))
        print(json.dumps({key:report[key] for key in ('scope','source_id','asset_count','verification','content_ready','default_preset_complete')}))


if __name__=='__main__':main()
