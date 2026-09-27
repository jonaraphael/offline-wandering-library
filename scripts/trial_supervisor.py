#!/usr/bin/env python3
"""Start/status/pause/resume the bounded Python-only acquisition queue."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl import jobs
from owl.acquisition.supervisor import Supervisor,read,brief,validate_plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['start','run','status','pause','resume','plan'])
    p.add_argument('--state-dir',type=Path,required=True)
    p.add_argument('--plan-file',type=Path,default=ROOT/'catalog/acquisition/1tb-supervisor-plan.json')
    p.add_argument('--registry',type=Path,default=ROOT/'catalog/acquisition/1tb-trial-batches.json')
    p.add_argument('--workspace',type=Path,default=ROOT);p.add_argument('--staging-root',type=Path)
    p.add_argument('--since-revision',type=int)
    a=p.parse_args();directory=a.state_dir.absolute();manager=directory/'manager-job'
    if a.command=='status':
        state=read(directory/'state.json');result=brief(state)
        if (manager/'owner.json').exists():
            live=jobs.status_job(manager);result['supervisor_active']=live['worker_active'];result['worker_state']=live['state']
        stable_worker=(result.get('supervisor_active') is True or
            (result['state']=='awaiting_review' and result.get('worker_state')=='awaiting_review') or
            (result['state']=='paused' and result.get('worker_state')=='cancelled'))
        if a.since_revision==result['revision'] and stable_worker and not result.get('exception'):
            result={'operation':'trial-supervisor','unchanged':True,'revision':result['revision']}
    elif a.command in {'pause','resume'}:result={'operation':a.command,**getattr(jobs,'cancel_job' if a.command=='pause' else 'resume_job')(manager)}
    else:
        if not a.staging_root:p.error('--staging-root is required')
        plan=validate_plan(read(a.plan_file));registry=read(a.registry)
        if a.command=='start':
            inputs=[a.plan_file.absolute(),a.registry.absolute()]
            inputs.extend(a.workspace/b['manifest'] for b in registry['batches'] if b.get('manifest'))
            for task in plan['tasks']:
                for name in task.get('inputs',[]):
                    from owl.acquisition.supervisor import expand
                    path=Path(expand(name,a.workspace.absolute(),a.staging_root.absolute()))
                    if path.is_file():inputs.append(path)
            inputs=list(dict.fromkeys(inputs))
            result=jobs.start_trial_step('trial_supervisor.py',['run','--state-dir',str(directory),
                '--plan-file',str(a.plan_file.absolute()),'--registry',str(a.registry.absolute()),
                '--workspace',str(a.workspace.absolute()),'--staging-root',str(a.staging_root.absolute())],
                job_dir=manager,target=a.staging_root,inputs=inputs)
        else:
            supervisor=Supervisor(plan,registry,a.workspace.absolute(),a.staging_root.absolute(),directory)
            if a.command=='plan':
                supervisor.space(refresh=True)
                result={'operation':'plan','tasks':len(plan['tasks']),'content_complete':False,
                    'space':supervisor.space_cache['combined_declared_phases_fit'],'concurrency':plan['concurrency']}
            else:result=supervisor.run()
    print(json.dumps(result,sort_keys=True))
    if a.command=='run' and result.get('state')=='paused':raise KeyboardInterrupt


if __name__=='__main__':main()
