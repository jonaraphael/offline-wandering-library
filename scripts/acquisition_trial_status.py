#!/usr/bin/env python3
"""Read bounded job summaries and the combined explicit staging-space ledger.

This read-only snapshot does not authorize a later phase or replace each
writer's live peak/reserve checks. No collection becomes ready from a receipt.
"""
import argparse,json,re,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import load_manifest,_effective_peak,_usage,_read,_digest,COMPONENTS
from owl.jobs import status_job
from owl.safety import atomic_write,reject_symlinks,safe_path


def report(staging,registry,*,workspace=None):
    root=Path(workspace) if workspace is not None else ROOT
    reject_symlinks(staging)
    if not staging.is_dir():raise ValueError('Explicit staging root must exist')
    rows=[]
    reserve_full=registry.get('space_accounting')=='reserve-full-peaks'
    if registry.get('space_accounting','measure-retained') not in {'measure-retained','reserve-full-peaks'}:
        raise ValueError('Unknown staging-space accounting mode')
    batches=registry.get('batches',[])
    if registry.get('schema_version')!=1 or not 1<=len(batches)<=64:
        raise ValueError('Trial registry needs1–64 explicit batches')
    if (len({b['id'] for b in batches})!=len(batches)
            or len({b['staging'] for b in batches})!=len(batches)):
        raise ValueError('Trial registry repeats a batch identity or staging directory')
    for batch in registry['batches']:
        target=safe_path(staging,batch['staging'])
        row={'id':batch['id'],'staging':str(target),'state':'planned'}
        try:
            # Writers atomically retire short-lived transport/checkpoint files.
            # Retry a fresh traversal rather than call that normal race a job
            # failure. Persistent disappearance still remains an exception.
            used=None
            if not reserve_full:
                for attempt in range(3):
                    try:
                        used=_usage(target)
                        break
                    except FileNotFoundError:
                        if attempt==2:raise
            if 'manifest' in batch:
                manifest=load_manifest(safe_path(root,batch['manifest']),profile=batch.get('profile'),
                    resource_ids=batch.get('resource_ids',()))
                if target.exists():
                    owner=_read(target/'owner.json')
                    if owner.get('owner')!='owl-acquisition-capture' or owner.get('manifest_sha256')!=_digest(manifest):
                        raise ValueError('Staging ownership differs from the registered acquisition manifest and filters')
                peak=_effective_peak(target,manifest)
                if 'planned_phase_budget' in batch:
                    budget=batch['planned_phase_budget']
                    if (not isinstance(budget,dict) or set(budget)!=set(COMPONENTS)
                            or any(type(value)is not int or value<manifest['budget'][key]
                                   for key,value in budget.items())):
                        raise ValueError('Planned phase budget must preserve every frozen source budget component')
                    # Reserve successor outputs before their preview owner exists,
                    # without changing source identity or crediting derivatives.
                    peak=max(peak,sum(budget.values())+manifest['metadata_allowance_bytes'])
            else:
                if 'planned_phase_budget' in batch:
                    raise ValueError('Planned phase budget requires a source-bound manifest batch')
                peak=batch['review_peak_bytes']
                if type(peak)is not int or peak<=0:raise ValueError('Invalid review budget')
                if target.exists() and batch.get('review_owner'):
                    owner=_read(target/'owner.json')
                    source_staging=safe_path(staging,batch['source_staging'])
                    source_owner=_read(source_staging/'owner.json')
                    source_manifest=load_manifest(source_staging/'manifest.json')
                    if (owner.get('owner')!=batch['review_owner'] or owner.get('schema_version')!=1
                            or source_owner.get('owner')!='owl-acquisition-capture'
                            or not re.fullmatch('[a-f0-9]{64}',str(owner.get('manifest_sha256','')))
                            or owner.get('manifest_sha256')!=source_owner.get('manifest_sha256')
                            or owner.get('manifest_sha256')!=_digest(source_manifest)
                            or owner.get('output_budget_bytes')!=peak
                            or owner.get('reserve_bytes',-1)<registry.get('shared_reserve_bytes',0)):
                        raise ValueError('Review owner, source binding, budget or reserve differs from its registry')
                    source_ids={s['id'] for s in source_manifest['sources']}
                    row['requested_sources']=len(source_ids)
                    def inspected(evidence):
                        records=evidence.get('rows',[])
                        ids=[r['source_id'] for r in records]
                        if len(ids)!=len(set(ids)) or not set(ids)<=source_ids:
                            raise ValueError('Review progress contains duplicate or unrelated source identities')
                        return sum(r.get('status')=='inspected_awaiting_review' for r in records)
                    checkpoint=target/'checkpoint.json'
                    if checkpoint.exists():
                        evidence=_read(checkpoint)
                        if evidence.get('manifest_sha256')!=owner['manifest_sha256']:
                            raise ValueError('Review checkpoint differs from its owned source scope')
                        row['inspected_sources']=inspected(evidence)
                    final_report=target/'report.json'
                    if final_report.exists():
                        evidence=_read(final_report)
                        if evidence.get('manifest_sha256')!=owner['manifest_sha256'] or evidence.get('content_ready') is not False:
                            raise ValueError('Review report differs from pending source scope')
                        count=inspected(evidence)
                        if (evidence.get('inspected_sources')!=count or evidence.get('requested_sources')!=len(source_ids)
                                or evidence.get('status')=='awaiting_review' and count!=len(source_ids)):
                            raise ValueError('Review report count differs from its exact source scope')
                        row.update(inspection_state=evidence.get('status'),inspected_sources=evidence.get('inspected_sources'),
                            requested_sources=evidence.get('requested_sources'),failed_check_counts=evidence.get('failed_check_counts',{}))
            row.update(retained_bytes=used,storage_peak_bytes=peak,
                remaining_peak_bytes=peak if reserve_full else max(0,peak-used))
            if used is not None and used>peak:raise ValueError('Measured retained bytes exceed recorded phase peak')
            if batch.get('job'):
                job=safe_path(root,batch['job'])
                reject_symlinks(job)
                # A declared future writer has no job directory yet; its full
                # remaining peak is already included above. Existing malformed
                # directories must still fail ownership checks in status_job.
                if job.exists():
                    status=status_job(job)
                    row.update({k:status[k] for k in ('state','phase','completed_assets','total_assets','worker_active') if k in status})
                    if row['state']=='awaiting_review' and 'total_assets' in row:
                        row['completed_assets']=row['total_assets']
                    if 'message' in status:row['message']=status['message'][:240]
            elif target.exists():row['state']='review-evidence'
        except (ValueError,OSError,KeyError) as error:
            row.update(state='exception',error=str(error)[:500])
        rows.append(row)
    reserve=registry.get('shared_reserve_bytes')
    if type(reserve)is not int or reserve<0:raise ValueError('Invalid shared reserve')
    available=shutil.disk_usage(staging).free
    required=sum(r.get('remaining_peak_bytes',0) for r in rows)+reserve
    return {'schema_version':1,'operation':'trial-status','content_complete':False,
        'space_accounting':'reserve-full-peaks' if reserve_full else 'measure-retained',
        'retained_usage_measured':not reserve_full,
        'available_free_bytes':available,'reserved_remaining_bytes':required,'shared_reserve_bytes':reserve,
        'combined_declared_phases_fit':all(r['state']!='exception' for r in rows) and required<=available,
        'batches':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staging-root',type=Path,required=True)
    p.add_argument('--registry',type=Path,default=ROOT/'catalog/acquisition/1tb-trial-batches.json')
    p.add_argument('--output',type=Path,default=ROOT/'.owl/acquisition/trial-status.json')
    a=p.parse_args()
    reject_symlinks(a.registry)
    if a.registry.stat().st_size>65536:raise ValueError('Registry exceeds64KiB')
    result=report(a.staging_root,json.loads(a.registry.read_text()))
    reject_symlinks(a.output);atomic_write(a.output,(json.dumps(result,sort_keys=True,indent=2)+'\n').encode())
    summary={k:v for k,v in result.items() if k!='batches'}
    summary['detail']=str(a.output)
    summary['batches']=[{'id':r['id'],'state':r['state'],**({'error':r['error'][:100]} if r.get('error') else {}),
        **({'completed':r['completed_assets'],'total':r.get('total_assets')} if 'completed_assets'in r else {}),
        **({'inspected':r['inspected_sources'],'requested':r.get('requested_sources')} if 'inspected_sources'in r else {})} for r in result['batches']]
    text=json.dumps(summary,sort_keys=True)
    if len(text.encode())>2048:
        summary['batches']=[{'id':r['id'],'state':r['state']} for r in result['batches']]
        text=json.dumps(summary,sort_keys=True)
    summary['batch_count']=len(result['batches'])
    summary['exception_count']=sum(r['state']=='exception' for r in result['batches'])
    while len(json.dumps(summary).encode())>2048 and summary['batches']:
        summary['batches'].pop()
    text=json.dumps(summary,sort_keys=True)
    print(text)


if __name__=='__main__':main()
