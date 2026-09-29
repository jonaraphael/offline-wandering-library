#!/usr/bin/env python3
"""Run bounded, cached offline browser shards over a complete generated manual.

This is layout/link evidence, not source/subject admission. Every HTML member is
checked at both supported widths; unchanged verified shards resume without an
LLM or browser replay. Detailed failures remain local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.supervisor import read,save,digest
from owl.safety import SafetyError,safe_path,sha256_file


def companion_ids(fragment):
    return {identity for recipe in fragment.get('recipes', [])
        for identity in recipe.get('selection', {}).get('dependencies', {}).values()}


def plan(fragment,*,batch_size=75):
    if type(batch_size) is not int or not 1<=batch_size<=100:
        raise SafetyError('Browser shard size must be1–100')
    companions=companion_ids(fragment)
    assets=sorted((a for a in fragment['assets'] if a.get('format')=='html' and (a.get('generation') or a['id'] in companions)),key=lambda a:a['id'])
    if not 1<=len(assets)<=2000:raise SafetyError('Complete browser package requires1–2000 HTML pages')
    if len({a['id'] for a in assets})!=len(assets) or len({a['destination'].casefold() for a in assets})!=len(assets):
        raise SafetyError('Browser package has duplicate identities or destinations')
    return [assets[i:i+batch_size] for i in range(0,len(assets),batch_size)]


def run(args):
    fragment=read(args.fragment,16*1024*1024);batches=plan(fragment,batch_size=args.batch_size)
    # Shared CSS, images, scripts and notices affect every browser result too.
    companions=companion_ids(fragment)
    for asset in fragment['assets']:
        if not asset.get('generation') and asset['id'] not in companions:continue
        path=safe_path(args.root,asset['destination'])
        if path.stat().st_size!=asset['size_bytes'] or sha256_file(path)!=asset['sha256']:
            raise SafetyError('Manual browser source changed: '+asset['id'])
    package_digest=digest(fragment)
    checker=ROOT/'scripts/check_manuals.cjs';helper=ROOT/'scripts/manual_link_checks.cjs'
    toolchain={'checker_sha256':sha256_file(checker),'helper_sha256':sha256_file(helper),
        'browser_version':subprocess.run([args.browser,'--version'],capture_output=True,text=True,check=True,timeout=15).stdout.strip(),
        'viewports':[1280,390]}
    args.output.mkdir(parents=True,exist_ok=True)
    shards=[];all_results=[];reused=0
    for index,assets in enumerate(batches):
        identity=f'shard-{index+1:03d}';proposal={'schema_version':1,'assets':assets}
        shard=args.output/(identity+'.fragment.json');report=args.output/(identity+'.report.json');receipt=args.output/(identity+'.receipt.json')
        binding={'fragment_sha256':digest(proposal),'package_sha256':package_digest,'toolchain':toolchain}
        cached=read(receipt) if receipt.exists() else {}
        if cached.get('binding')==binding and report.exists() and cached.get('report_sha256')==sha256_file(report):
            result=read(report,8*1024*1024);reused+=1
        else:
            save(shard,proposal)
            pending=args.output/(identity+'.pending.json');pending.unlink(missing_ok=True)
            command=[args.node,str(checker),'--fragment',str(shard),'--root',str(args.root),'--output',str(pending),
                '--browser',args.browser,'--playwright',args.playwright,'--package-fragment',str(args.fragment)]
            log=args.output/(identity+'.log')
            with log.open('w') as stream:
                process=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=3600)
            if process.returncode not in (0,1) or not pending.exists():raise SafetyError('Browser shard failed; inspect '+str(log))
            result=read(pending,8*1024*1024)
            pending.replace(report)
            save(receipt,{'binding':binding,'report_sha256':sha256_file(report)})
        expected={(a['id'],w) for a in assets for w in [1280,390]}
        if (len(result['results'])!=len(expected) or {(r['asset_id'],r['width']) for r in result['results']}!=expected
                or result['checks']!=len(expected) or result['passed']!=sum(bool(r['passed']) for r in result['results'])):
            raise SafetyError('Browser shard omitted or duplicated a required page/width')
        all_results.extend(result['results']);shards.append({'id':identity,'report':str(report),'report_sha256':sha256_file(report),
            'checks':result['checks'],'passed':result['passed']})
        save(args.output/'checkpoint.json',{'content_ready':False,'completed_shards':len(shards),'total_shards':len(batches),'shards':shards})
    failures=[r for r in all_results if not r['passed']]
    summary={'schema_version':1,'status':'browser_evidence_awaiting_review','content_ready':False,
        'fragment_sha256':sha256_file(args.fragment),'toolchain':toolchain,'html_pages':sum(map(len,batches)),
        'checks':len(all_results),'passed':len(all_results)-len(failures),'shards_reused':reused,'shards':shards,
        'failures':failures,'physical_device_certification':'pending'}
    save(args.output/'report.json',summary)
    return {k:summary[k] for k in ('content_ready','html_pages','checks','passed','shards_reused')}|{'failure_count':len(failures),
        'failure_examples':[{'asset_id':r['asset_id'],'width':r['width'],'overflow':r['scrollWidth']-r['viewportWidth'],
            'broken_files':r['brokenFiles'][:3],'broken_anchors':r['brokenAnchors'][:3]} for r in failures[:3]],'report':str(args.output/'report.json')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['fragment','root','output']:p.add_argument('--'+name,type=Path,required=True)
    for name in ['node','browser','playwright']:p.add_argument('--'+name,required=True)
    p.add_argument('--batch-size',type=int,default=75)
    a=p.parse_args();print(json.dumps(run(a)))


if __name__=='__main__':main()
