#!/usr/bin/env python3
"""Select small AI review packets from existing complete machine evidence only.

No model calls, downloads, extracted body copies, or automatic admission. Full
evidence stays on disk; the packet references a small initial sample and keeps
the optional expanded sample separate. Every machine anomaly remains explicit.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.sampling import sampling_plan
from owl.acquisition.supervisor import read,save
from owl.safety import safe_path,sha256_file,SafetyError


def prepare(path,output):
    report=read(path,64*1024*1024);seed=sha256_file(path)
    records=report.get('rows',report.get('records',[]))
    if not isinstance(records,list) or not records:raise SafetyError('Review packet needs nonempty machine evidence')
    units={};failed=[]
    for row in records:
        identity=row.get('source_id',row.get('asset_id'))
        if not identity or identity in units:raise SafetyError('Machine evidence has missing/duplicate identities')
        units[identity]=row
        if (any(v is False for v in row.get('checks',{}).values()) or row.get('structural_pass') is False
                or row.get('status') in {'failed','blocked'} or row.get('flags')):
            failed.append(identity)
    target=sorted(units);plan=sampling_plan(list(units),seed,targeted=[target[0],target[-1]],screening=8)
    selected=list(dict.fromkeys([*plan['targeted_units'],*plan['screening_units']]))
    packet=[]
    for identity in selected:
        row=units[identity];item={'id':identity,'machine_evidence':row}
        if row.get('utility_excerpts'):item['utility_excerpts']=row['utility_excerpts']
        if row.get('evidence'):
            detail=safe_path(path.parent,row['evidence']);data=read(detail,16*1024*1024)
            for render in data.get('renders',[]):
                rendered=safe_path(detail.parent,render['path'])
                if sha256_file(rendered)!=render['sha256']:raise SafetyError('Sample render changed')
            item.update(evidence_path=str(detail),evidence_sha256=sha256_file(detail),
                excerpt=str(data.get('text_excerpt',''))[:1800],renders=[{**r,'path':str(safe_path(detail.parent,r['path']))} for r in data.get('renders',[])],
                required_review=data.get('required_review',[]))
            if data.get('utility_excerpts'):
                random_pages=set(data.get('sampling',{}).get('screening_units',[]))
                item['utility_excerpts']=[{'pdf_page':r['pdf_page'],'text':r['text'][:800],
                    'scope':'Random page excerpt for utility screening; full page/statement remains in original PDF.'}
                    for r in data['utility_excerpts'] if str(r['pdf_page']) in random_pages][:3]
        packet.append(item)
    result={'schema_version':1,'content_ready':False,'report':str(path),'report_sha256':seed,
        'sampling':plan,'initial_packet':packet,'machine_flagged_units':failed,
        'machine_flags_require_review':bool(failed),'review_status':'pending',
        'scope':'Only evidence units present in the bound report; missing expected assets remain blockers outside this sample.'}
    if output.exists() and read(output)!=result:raise SafetyError('Review evidence changed; use a new packet version')
    save(output,result)
    return {'content_ready':False,'units':len(units),'initial_samples':len(packet),'flagged_units':len(failed),
        'escalation_sample_count':len(plan['escalation_units']),'packet':str(output)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.report,a.output),sort_keys=True))


if __name__=='__main__':main()
