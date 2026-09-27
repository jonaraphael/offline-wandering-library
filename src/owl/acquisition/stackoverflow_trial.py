"""Measured shared XML inputs for an explicitly authorized Stack Overflow trial.

These operations never download, approve content, or publish a library. They
reuse captured archives and keep one owned expansion for discovery and previews.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import shutil

from ..runtime import file_lock
from ..safety import SafetyError, guard_directory, reject_symlinks, safe_path
from . import capture, sevenzip

ROLES={'posts':'Posts.xml','comments':'Comments.xml','users':'Users.xml','links':'PostLinks.xml'}
SHARED_ID='stackoverflow-shared-xml-v1'


def inspect(staging, *, max_expanded_bytes=650_000_000_000, progress=print):
    """Measure complete archive inventories without expanding any bodies."""
    path,_=capture._staging(staging)
    manifest,receipts=capture.load_capture_sources(path)
    sources={s.get('input_role'):s for s in manifest['sources']}
    if set(sources)!=set(ROLES) or len(manifest['sources'])!=4:
        raise SafetyError('Stack Overflow inspection needs the four distinct frozen input roles')
    if type(max_expanded_bytes) is not int or max_expanded_bytes<=0:
        raise SafetyError('Inspection needs a positive total expansion bound')
    by_id={r['source_id']:r for r in receipts}
    specs=[];total=0
    for role,expected in ROLES.items():
        source=sources[role];receipt=by_id[source['id']]
        progress('INSPECT '+source['id'])
        inventory=sevenzip.inspect_archive(safe_path(path,receipt['relative_path']),receipt,
            max_bytes=max_expanded_bytes,max_files=8)
        if len(inventory)!=1 or inventory[0]['path']!=expected:
            raise SafetyError('Publisher archive inventory differs from its single declared XML member: '+source['id'])
        member=inventory[0];total+=member['size_bytes']
        if total>max_expanded_bytes:raise SafetyError('Combined XML expansion exceeds the inspection bound')
        # An explicit wall-clock bound scaled from measured bytes, with a
        # conservative 16 MB/s baseline and a hard one-hour subprocess ceiling.
        timeout=min(3600,max(300,math.ceil(member['size_bytes']/16_000_000)))
        specs.append({'source_id':source['id'],'format':'7z','max_bytes':member['size_bytes'],
            'max_files':1,'timeout_seconds':timeout,
            'members':[{'id':source['id']+'_xml',**member}]})
    return {'schema_version':1,'kind':'stackoverflow-archive-inspection','content_ready':False,
        'manifest_sha256':capture._digest(manifest),'source_receipts':{r['source_id']:capture._digest(r) for r in receipts},
        'download_bytes':manifest['budget']['download_bytes'],'xml_bytes':total,
        'expanded_bytes':total+131072*len(specs),'metadata_allowance_bytes':manifest['metadata_allowance_bytes'],
        'build_input_extractions':specs,'input_roles':{role:sources[role]['id']+'_xml' for role in ROLES},
        'pending':['Measured scratch and preview budget approval','Whole XML SHA-256','Deterministic selection and document review']}


def expand(staging, inspection_path, *, expanded_bytes, scratch_bytes, preview_bytes,
           budget_bytes, reserve_bytes, progress=print):
    """Freeze one shared expansion, respecting an explicitly supplied phase peak."""
    path,_=capture._staging(staging)
    inspection=capture._document(inspection_path)
    manifest,receipts=capture.load_capture_sources(path)
    bindings={r['source_id']:capture._digest(r) for r in receipts}
    if (inspection.get('kind')!='stackoverflow-archive-inspection' or
            inspection.get('manifest_sha256')!=capture._digest(manifest) or inspection.get('source_receipts')!=bindings):
        raise SafetyError('Archive inspection belongs to different captured sources')
    source_roles={s['id']:s.get('input_role') for s in manifest['sources']}
    specs=inspection.get('build_input_extractions',[])
    if len(specs)!=4 or {s.get('source_id') for s in specs}!=set(source_roles):
        raise SafetyError('Shared XML inspection must contain exactly the four captured archives')
    for spec in specs:
        members=spec.get('members',[])
        if (len(members)!=1 or spec.get('format')!='7z' or spec.get('max_files')!=1 or
                type(spec.get('max_bytes')) is not int or spec['max_bytes']<=0 or
                type(spec.get('timeout_seconds')) is not int or spec['timeout_seconds'] not in range(1,3601) or
                members[0].get('size_bytes')!=spec['max_bytes'] or
                members[0].get('path')!=ROLES.get(source_roles[spec['source_id']]) or
                members[0].get('id')!=spec['source_id']+'_xml'):
            raise SafetyError('Shared XML allowlist differs from its measured role or finite bounds')
    measured=sum(s['max_bytes'] for s in specs)
    if inspection.get('xml_bytes')!=measured or inspection.get('expanded_bytes')!=measured+131072*4:
        raise SafetyError('Shared XML measured expansion accounting changed')
    amounts=(expanded_bytes,scratch_bytes,preview_bytes,budget_bytes,reserve_bytes)
    if any(type(value) is not int or value<0 for value in amounts):
        raise SafetyError('Shared XML phase requires explicit nonnegative byte budgets')
    if expanded_bytes<inspection['expanded_bytes']:
        raise SafetyError('Shared XML expansion exceeds its measured allowance')
    phase={**manifest['budget'],'expanded_bytes':expanded_bytes,'scratch_bytes':scratch_bytes,'preview_bytes':preview_bytes}
    peak=sum(phase.values())+manifest['metadata_allowance_bytes']
    if budget_bytes<peak:raise SafetyError('Explicit phase budget omits its source, expansion, scratch, preview or metadata bytes')
    folder=safe_path(path,'previews/'+SHARED_ID)
    marker=folder/'owner.json'
    owner={'owner':'owl-acquisition-preview','schema_version':1,'manifest_sha256':capture._digest(manifest),
        'preview_id':SHARED_ID,'shared_inputs':True,'phase_budget':phase,'storage_peak_bytes':peak,
        'reserve_bytes':reserve_bytes,'inspection_sha256':capture._digest(inspection)}
    by_id={r['source_id']:r for r in receipts}
    rows=[];specs=deepcopy(specs)
    with guard_directory(path),file_lock(path/'capture.lock'):
        capture._space(path,peak,reserve_bytes)
        if folder.exists() and not marker.exists():raise SafetyError('Unowned shared XML directory')
        capture._bounded_immutable(path,marker,owner,peak=peak,reserve=reserve_bytes)
        def before_write(size):
            if shutil.disk_usage(path).free<size+reserve_bytes:
                raise SafetyError('Shared XML write would cross the live free-space reserve')
        for spec in specs:
            receipt=by_id[spec['source_id']]
            observed=sevenzip.observe_members(safe_path(path,receipt['relative_path']),receipt,
                [{key:value for key,value in m.items() if key!='id'} for m in spec['members']],
                safe_path(folder,'expanded/'+spec['source_id']),max_bytes=spec['max_bytes'],max_files=spec['max_files'],
                timeout=spec.get('timeout_seconds',3600),before_write=before_write,progress=progress)
            for member in spec['members']:
                row=next(row for row in observed['members'] if row['path']==member['path'])
                member['sha256']=row['sha256']
                rows.append({'id':member['id'],**row,'source_id':spec['source_id'],
                    'relative_path':str(observed['paths'][row['path']].relative_to(path))})
        report={'schema_version':1,'kind':'acquisition-shared-expansion','content_ready':False,
            'manifest_sha256':capture._digest(manifest),'source_receipts':bindings,'owner_sha256':capture._digest(owner),
            'build_input_extractions':specs,'input_roles':inspection['input_roles'],'expanded_sources':rows,
            'phase_budget':phase,'storage_peak_bytes':peak,'reserve_bytes':reserve_bytes}
        destination=folder/'expanded-receipt.json'
        capture._bounded_immutable(path,destination,report,peak=peak,reserve=reserve_bytes)
        capture._space(path,peak,reserve_bytes)
        return {'status':'awaiting_selection_review','content_ready':False,'receipt':str(destination),
                'xml_bytes':sum(r['size_bytes'] for r in rows),'storage_peak_bytes':peak,'members':len(rows)}


def verified_shared(staging, receipt_path, manifest, receipts):
    """Verify ownership, archive bindings and every complete expanded XML pin."""
    from ..download import verified
    path=Path(staging);receipt_path=Path(receipt_path).absolute()
    reject_symlinks(receipt_path)
    if '..' in receipt_path.parts or not receipt_path.is_relative_to(path/'previews') or receipt_path.name!='expanded-receipt.json':
        raise SafetyError('Shared expansion receipt must be inside this capture previews tree')
    record=capture._read(receipt_path)
    owner=capture._read(receipt_path.parent/'owner.json')
    bindings={r['source_id']:capture._digest(r) for r in receipts}
    if (record.get('kind')!='acquisition-shared-expansion' or record.get('content_ready') is not False
            or owner.get('owner')!='owl-acquisition-preview' or owner.get('shared_inputs') is not True
            or owner.get('manifest_sha256')!=capture._digest(manifest) or record.get('manifest_sha256')!=capture._digest(manifest)
            or record.get('owner_sha256')!=capture._digest(owner) or record.get('source_receipts')!=bindings):
        raise SafetyError('Shared XML ownership or captured source binding changed')
    capture._effective_peak(path,manifest)
    members={}
    for spec in record.get('build_input_extractions',[]):
        if spec.get('source_id') not in bindings:raise SafetyError('Unknown shared XML archive source')
        for member in spec.get('members',[]):
            if member['id'] in members:raise SafetyError('Duplicate shared XML identity')
            members[member['id']]={**member,'source_id':spec['source_id']}
    seen=set()
    for row in record.get('expanded_sources',[]):
        member=members.get(row.get('id'),{})
        candidate=safe_path(path,row['relative_path'])
        if (row.get('id') in seen or any(row.get(k)!=member.get(k) for k in ('id','path','size_bytes','sha256','source_id'))
                or candidate!=safe_path(receipt_path.parent,'expanded/'+row['source_id']+'/files/'+row['path'])
                or not verified(candidate,row['size_bytes'],row['sha256'])):
            raise SafetyError('Shared XML source differs from its allowlist, location or whole-file pin')
        seen.add(row['id'])
    if not members or seen!=members.keys():raise SafetyError('Shared XML receipt is incomplete')
    return record


def select(staging, receipt_path, *, cache_dir, limit=100000):
    """Propose bounded deterministic candidates; classification is not approval."""
    from . import corpus
    path,_=capture._staging(staging)
    manifest,receipts=capture.load_capture_sources(path)
    shared=verified_shared(path,receipt_path,manifest,receipts)
    posts=next(row for row in shared['expanded_sources'] if row['id']==shared['input_roles']['posts'])
    rules={'allow_tags':sorted(corpus.DEFAULT_DURABLE_TAGS),'legacy_tags':sorted(corpus.DEFAULT_LEGACY_TAGS),
           'deny_tags':sorted(corpus.DEFAULT_EXCLUDED_TAGS),'version_rules':deepcopy(list(corpus.DEFAULT_VERSION_RULES))}
    result=corpus.select_candidates(safe_path(path,posts['relative_path']),source_asset=posts,
        cache_dir=Path(cache_dir),limit=limit,rules=rules)
    return {'schema_version':1,'kind':'stackoverflow-candidate-selection','content_ready':False,
        'corpus_version':corpus.VERSION,'shared_expansion_sha256':capture._digest(shared),
        'selection_limit':limit,'classification_rules':rules,'pending':['Canonical duplicate review','Illustration and attribution dependency review',
            'Complete selected outputs and explicit collection coverage review'],**result}
