"""Reproducible review samples, with explicitly limited statistical claims."""
import math
import random
import re

from ..safety import SafetyError


def sampling_plan(unit_ids, source_sha256, *, targeted=(), screening=8, defect_fraction=.05, detection=.95):
    if not re.fullmatch('[0-9a-f]{64}',source_sha256):raise SafetyError('Sampling requires a frozen source/evidence SHA-256')
    ids=list(unit_ids)
    if not ids or len(ids)>100000 or any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):
        raise SafetyError('Sampling units must be 1–100000 unique identities')
    ids.sort()
    if not 0<defect_fraction<1 or not 0<detection<1 or type(screening)is not int or not 1<=screening<=100:
        raise SafetyError('Invalid bounded sample policy')
    if not set(targeted)<=set(ids):raise SafetyError('Targeted units are absent from the inventory')
    maximum=min(len(ids),math.ceil(math.log1p(-detection)/math.log1p(-defect_fraction)))
    if maximum>1000:raise SafetyError('Requested review sample exceeds1000 units; split the review')
    chosen=random.Random(int(source_sha256,16)).sample(ids,maximum)
    n=min(screening,maximum)
    def chance(count):
        defects=math.ceil(len(ids)*defect_fraction);miss=1.0
        for i in range(count):miss*=max(0,len(ids)-defects-i)/(len(ids)-i)
        return 1-miss
    return {'schema_version':1,'method':'hash-seeded uniform sampling without replacement',
        'source_sha256':source_sha256,'population':len(ids),'targeted_units':sorted(set(targeted)),
        'screening_units':chosen[:n],'escalation_units':chosen[n:],
        'assumed_minimum_defect_fraction':defect_fraction,'screening_encounter_probability':chance(n),
        'full_sample_encounter_probability':chance(maximum),'requested_detection_probability':detection,
        'statistical_scope':'Probability of encountering a defective unit under the random-sampling model, conditional on recognizing every sampled defect. Not confidence in AI judgment or proof of completeness.',
        'ai_review_status':'pending','content_ready':False,'completeness_proven':False,
        'review_contract':{'validity':['File/structure checks and sampled legibility'],
            'utility':['Match contents and substantive excerpts to required topics; compare existing works'],
            'completeness':['Require publisher inventory/TOC and dependency reconciliation; sampling alone is insufficient'],
            'escalate_when':['Any sampled defect','Ambiguous topic/edition/language','Essential content or expected pages missing'],
            'reuse_only_when':['Source, output, transformation and review-policy pins remain unchanged']}}


def excerpt_windows(text, *, width=500):
    """Three labeled text windows for utility screening, never completeness."""
    if not isinstance(text,str) or type(width)is not int or not 100<=width<=2000:
        raise SafetyError('Invalid bounded excerpt request')
    starts=sorted({0,max(0,(len(text)-width)//2),max(0,len(text)-width)})
    return [{'offset':offset,'total_characters':len(text),'text':text[offset:offset+width]}
            for offset in starts if text[offset:offset+width]]
