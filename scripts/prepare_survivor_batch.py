#!/usr/bin/env python3
"""Bounded Survivor review shortlist and frozen candidate acquisition batches.

Shortlists are suggestions, never accepted titles or topic coverage. Freeze
requires an explicit list of stable candidate IDs; HEAD probes supply exact
sizes. The normal acquisition build alone downloads originals for scan review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import normalize_manifest, _digest
from owl.acquisition.pins import PinProbe
from owl.safety import SafetyError, atomic_write

SYNONYMS={'animal husbandry':r'husbandry|stock|cattle|sheep|poultry|pig|horse',
    'crop cultivation':r'crop|cultivat|gardening|horticultur', 'food drying':r'drying|dehydrat',
    'grain milling':r'flour|grain.*mill|milling', 'structural fundamentals':r'construction|structur|foundation',
    'process chemistry':r'industrial.*chemi|chemical.*process', 'materials chemistry':r'material|metallurg|industrial.*chemi',
    'sheet metal':r'sheet.?metal|sheet.?iron|tin.?plate', 'toolmaking':r'tool.?mak',
    'metrology':r'metrolog|measur', 'machining':r'machin|lathe', 'horticulture':r'horticultur|garden',
    'papermaking':r'paper.?mak|manufacture.*paper', 'butchering':r'butcher|meat',
    'brickmaking':r'brick', 'basketry':r'basket', 'advanced mining':r'mining|ore.?dress',
    'advanced steam engineering':r'steam|boiler', 'radio history':r'radio|wireless',
    'electronics history':r'electronic|radio|wireless', 'industrial chemical processes':r'industrial.*chemi|chemical.*process',
    'textile machinery':r'textile|spinn|weav', 'historical transportation engineering':r'locomotive|railroad|railway',
    'railroad engineering':r'railroad|railway|locomotive', 'foundry':r'foundr|mould|mold',
    'specialized foundry':r'foundr|mould|mold', 'glassmaking':r'glass', 'leatherworking':r'leather|tanning',
    'papermaking':r'paper.?mak|manufacture.*paper|paper manufacture', 'pumps':r'pump', 'bearings':r'bearing',
    'roofing':r'roof', 'shipbuilding':r'ship.?build|boat.?build', 'steam systems':r'steam|boiler',
    'wind power':r'wind.?mill|wind.?power'}
# Publisher titles can append a year directly to the last word (Surgery1900).
EXCLUDE=re.compile(r'\b(anesthesia|anaesthesia|obstetric\w*|surgery|medical|medicine|nursing|encyclop\w*|christmas|thanksgiving|periodical|magazine|transactions|banking|accounting)(?=\b|[0-9])',re.I)


def candidates(report):
    result={}
    excluded={r['source_url'] for lane in report['results']
        for key in ('rejected','selected') for r in lane.get('selection_report',{}).get(key,[])}
    for lane in report['results']:
        if lane['resource_id'] not in {'survivor-tier-a','survivor-tier-b'}:continue
        for row in lane['selection_report']['pending']:
            if row['source_url'] in excluded or EXCLUDE.search(row['title']):continue
            url=row['source_url'];identity='survivor_'+hashlib.sha256(url.encode()).hexdigest()[:20]
            item=result.setdefault(identity,{**row,'id':identity,'resource_ids':[],
                'metadata_evidence':lane['metadata_evidence'], 'reviewed':False})
            if item['title']!=row['title']:raise SafetyError('One publisher source has conflicting title metadata')
            item['resource_ids']=sorted(set(item['resource_ids'])|{lane['resource_id']})
            item['topics']=sorted(set(item['topics'])|set(row.get('topics',[])))
    return result


def shortlist(report):
    rows=candidates(report);topics=sorted({t for lane in report['results'] for t in lane.get('selection_report',{}).get('missing_topics',[])})
    suggestions={};unmatched=[]
    for topic in topics:
        pattern=re.compile(r'\b(?:'+SYNONYMS.get(topic,re.escape(topic).replace(r'\ ',r'[ -]'))+r')\w*\b',re.I)
        matching=[r for r in rows.values() if pattern.search(r['title'])]
        def rank(row):
            title=row['title'];years=re.findall(r'\b(?:18|19)\d{2}\b',title)
            return (-bool(re.search(r'practical|manual|handbook|complete|elements|text.?book',title,re.I)),
                bool(re.search(r'history|society|biograph|adventure|annual',title,re.I)),
                -int(years[-1]) if years else 0,title,row['id'])
        matching.sort(key=rank)
        suggestions[topic]=[{k:r[k] for k in ('id','title','source_url','resource_ids','title_source')} for r in matching[:3]]
        if not matching:unmatched.append(topic)
    return {'schema_version':1,'kind':'pending-survivor-shortlist','content_ready':False,
        'report_sha256':_digest(report),'candidate_count':len(rows),'topic_suggestions':suggestions,
        'unmatched_topics':unmatched,'warning':'Title matches do not establish completeness, English language, scan quality, safety or topic coverage.'}


def freeze(report, selection, probe):
    if selection.get('report_sha256')!=_digest(report):raise SafetyError('Candidate selection is bound to different publisher metadata')
    ids=selection.get('candidate_ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or len(set(ids))!=len(ids):raise SafetyError('Choose1–100 distinct candidate IDs')
    rows=candidates(report)
    if set(ids)-rows.keys():raise SafetyError('Unknown/excluded/previously accepted candidate ID')
    sources=[]
    for identity in ids:
        row=rows[identity];observed=probe.probe({'id':identity,'url':row['source_url']})
        size=observed.get('size_bytes')
        if type(size)is not int or not 0<size<=128*1024*1024:raise SafetyError('Missing exact size or source exceeds128MiB scan-review bound: '+identity)
        evidence=[{k:v for k,v in e.items() if k!='cached'} for e in observed['evidence']]
        headers=evidence[0].get('headers',{})
        version='publisher-last-modified:'+headers.get('last-modified','unknown')
        asset={'id':identity,'title':'Historical: '+row['title'],'category':'historical-trades','format':'pdf',
            'source_url':row['source_url'],'source_page':row['discovered_on'],'version':version,
            'destination':'REFERENCE/HISTORICAL/SURVIVOR/'+identity+'.pdf','size_bytes':size,'sha256':observed.get('sha256'),
            'license':'Original publisher and scan notices require review; no blanket redistribution grant asserted',
            'redistributable':False,'required':True,'profiles':[],'publisher':'Scan hosted by Survivor Library',
            'resource_type':'reference','language':'en','tags':['historical','survivor-library','pending-scan-review'],
            'description':'Candidate practical historical work; does not establish current safety practice. Completeness, language, edition deduplication and scan review pending.'}
        sources.append({'id':identity,'resource_ids':row['resource_ids'],'source_url':row['source_url'],
            'version':version,'size_bytes':size,'sha256':observed.get('sha256'),'publisher_checksums':{},
            'metadata_evidence':[{'kind':'publisher-category','url':row['discovered_on'],
                'sha256':_digest(row),'scope':'Canonical parsed publisher row; exact metadata page hashes retained in source report'},
                {'kind':'source-head','url':row['source_url'],'sha256':_digest(evidence),'responses':evidence}],
            'fullasset_metadata':asset,'candidate_topics':row['topics'],'topic_review':'pending'})
    return normalize_manifest({'schema_version':1,'kind':'acquisition','id':selection['id'],'profile':'full-1tb',
        'content_ready':False,'sources':sources,'budget':{'download_bytes':sum(r['size_bytes'] for r in sources),
            'expanded_bytes':0,'preview_bytes':0,'scratch_bytes':0,'cache_bytes':0},
        'review_requirements':['Original complete work, whole-file pins, English language and legible illustrations/tables',
            'Review actual contents against topic matrix; publisher categories and title matches are not coverage evidence',
            'Deduplicate works/editions across both tiers and existing books; preserve source exclusions and historical warnings']})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['shortlist','freeze'])
    p.add_argument('--report',type=Path,required=True);p.add_argument('--selection',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--offline',action='store_true')
    p.add_argument('--cache',type=Path,default=ROOT/'.owl/acquisition/survivor-candidate-heads')
    a=p.parse_args()
    if a.report.stat().st_size>32*1024*1024:raise SafetyError('Discovery report exceeds32MiB')
    report=json.loads(a.report.read_text())
    if a.command=='freeze' and not a.selection:p.error('freeze requires explicit --selection')
    result=shortlist(report) if a.command=='shortlist' else freeze(report,json.loads(a.selection.read_text()),PinProbe(a.cache,offline=a.offline))
    data=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    if len(data)>16*1024*1024:raise SafetyError('Frozen report exceeds16MiB')
    if a.output.exists() and a.output.read_bytes()!=data:raise SafetyError('Frozen output differs; use a new version')
    a.output.parent.mkdir(parents=True,exist_ok=True);atomic_write(a.output,data)
    print(json.dumps({'operation':'survivor-'+a.command,'content_ready':False,'body_downloads':0,'output':str(a.output),
        'candidates':result.get('candidate_count',len(result.get('sources',[]))),
        'source_bytes':result.get('budget',{}).get('download_bytes'),'unmatched_topics':result.get('unmatched_topics',[])},sort_keys=True))


if __name__=='__main__':main()
