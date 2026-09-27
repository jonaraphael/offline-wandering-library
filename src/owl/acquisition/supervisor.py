"""Deterministic trial scheduling. No model calls, content admission or deletion.

Long operations use the existing snapshot/lock/retry/cancellation job runner.
The supervisor persists only bounded control state and evidence fingerprints.
Source and output bodies stay in each operation's explicitly budgeted staging
area. A finished queue is always awaiting content review, never library-ready.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import time

from .. import jobs
from ..runtime import file_lock, interrupt_signals
from ..safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file

LIMIT = 2 * 1024 * 1024
FINISHED = {'done', 'needs_review', 'blocked'}


def read(path, limit=LIMIT):
    path=Path(path);reject_symlinks(path)
    if not path.is_file() or path.stat().st_size>limit:raise SafetyError('Invalid or excessive control record: '+str(path))
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def save(path,value):
    data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    if len(data)>LIMIT:raise SafetyError('Supervisor state exceeded2MiB')
    reject_symlinks(path);atomic_write(path,data)


def validate_plan(plan):
    if plan.get('schema_version')!=1 or not re.fullmatch('[a-z0-9_-]{1,64}',plan.get('id','')):
        raise SafetyError('Trial plan requires schema1 and a portable identity')
    if not 1<=len(plan.get('tasks',[]))<=100:raise SafetyError('Trial queue requires1–100 tasks')
    limits=plan.get('concurrency',{})
    if not limits or any(type(v)is not int or not 1<=v<=4 for v in limits.values()):
        raise SafetyError('Trial concurrency must be bounded1–4 per lane')
    ids=set()
    for task in plan['tasks']:
        identity=task.get('id','')
        if not re.fullmatch('[a-z0-9_-]{1,64}',identity) or identity in ids:raise SafetyError('Duplicate or unsafe task identity')
        ids.add(identity)
        if task.get('kind') not in {'capture','script'} or task.get('lane') not in limits:
            raise SafetyError('Unknown task kind/lane')
        if task['kind']=='script':
            if task.get('script') not in jobs.TRIAL_SCRIPTS or task['script']=='trial_supervisor.py':
                raise SafetyError('Unsupported or recursive supervisor command')
            argv=task.get('argv');allowed=jobs.TRIAL_SCRIPTS[task['script']]
            if not isinstance(argv,list) or any(not isinstance(a,str) for a in argv):raise SafetyError('Task argv must be strings')
            if allowed is not None and (not argv or argv[0] not in allowed):raise SafetyError('Task action cannot admit or build production content')
        if not isinstance(task.get('depends',[]),list):raise SafetyError('Dependencies must be a list')
    visiting,done=set(),set();by_id={r['id']:r for r in plan['tasks']}
    def visit(identity):
        if identity in visiting:raise SafetyError('Cyclic trial dependencies')
        if identity not in ids:raise SafetyError('Unknown trial dependency')
        if identity in done:return
        visiting.add(identity)
        for parent in by_id[identity].get('depends',[]):visit(parent)
        visiting.remove(identity);done.add(identity)
    for identity in ids:visit(identity)
    return plan


def expand(value,workspace,staging):
    result=value.replace('{workspace}',str(workspace)).replace('{staging}',str(staging))
    if '{' in result or '}' in result:raise SafetyError('Unknown trial path placeholder')
    return result


def field(value,key):
    for part in key.split('.'):value=value[part]
    return value


def check_results(task,workspace,staging):
    pins={}
    for check in task.get('checks',[]):
        path=Path(expand(check['path'],workspace,staging));value=read(path,64*1024*1024)
        for key,expected in check.get('equals',{}).items():
            if field(value,key)!=expected:raise SafetyError('Review condition failed: '+str(path)+' '+key)
        for left,right in check.get('equal_fields',[]):
            if field(value,left)!=field(value,right):raise SafetyError('Incomplete review coverage: '+str(path))
        for key,count in check.get('lengths',{}).items():
            if len(field(value,key))!=count:raise SafetyError('Incomplete expected output count: '+str(path))
        pins[str(path)]=sha256_file(path)
    return pins


def brief(state):
    result={'operation':'trial-supervisor','state':state['state'],'content_complete':False,
        'counts':dict(Counter(r['state'] for r in state['tasks'].values())),
        'running':[k for k,v in state['tasks'].items() if v['state']=='running'][:8],
        'review_items':len(state.get('review_queue',[])),'revision':state.get('revision',0),
        'detail':state['detail']}
    if state.get('exception'):result['exception']=state['exception'][:300]
    if len(json.dumps(result).encode())>2048:
        result['detail']='See state.json in the supplied state directory'
        result['running']=result['running'][:4]
    return result


class Supervisor:
    def __init__(self,plan,registry,workspace,staging,state_dir,*,backend=jobs,space_reader=None,now=time.time):
        self.plan=validate_plan(plan);self.registry=registry;self.workspace=Path(workspace);self.staging=Path(staging)
        self.directory=Path(state_dir);reject_symlinks(self.directory);self.backend=backend;self.now=now;self.space_reader=space_reader
        self.batches={b['id']:b for b in registry['batches']};self.space_cache=None;self.last_space=0
        reject_symlinks(self.staging)
        if not self.staging.is_dir():raise SafetyError('Explicit staging volume is unavailable')
        self.device=self.staging.stat().st_dev
        self.owner={'owner':'owl-trial-supervisor','schema_version':1,'plan_sha256':digest(plan),
            'registry_sha256':digest(registry),'workspace':str(self.workspace),'staging_root':str(self.staging),'staging_device':self.device}
        self.directory.mkdir(parents=True,exist_ok=True);owner=self.directory/'owner.json'
        if owner.exists() and read(owner)!=self.owner:raise SafetyError('Supervisor belongs to another plan/volume; use a new state directory')
        if not owner.exists():save(owner,self.owner)
        existing=self.directory/'state.json'
        self.state=read(existing) if existing.exists() else {'schema_version':1,'state':'prepared','content_complete':False,
            'tasks':{t['id']:{'state':'pending','launches':0} for t in plan['tasks']},'revision':0,
            'detail':str(existing),'review_queue':[],'input_pins':{}}
        if set(self.state['tasks'])!={t['id'] for t in plan['tasks']}:raise SafetyError('Supervisor state differs from frozen queue')
        for task in plan['tasks']:
            if task.get('batch') not in self.batches:raise SafetyError('Task has no declared staging-space batch')
            for name in task.get('inputs',[]):
                path=Path(expand(name,self.workspace,self.staging))
                # Freeze existing controls before the first child starts. Inputs
                # generated by predecessors instead bind to their checked report.
                if path.exists() and str(path) not in self.state['input_pins']:
                    if path.stat().st_size>64*1024*1024:raise SafetyError('Excessive trial control input')
                    reject_symlinks(path);self.state['input_pins'][str(path)]=sha256_file(path)

    def job_path(self,task):
        if task['kind']=='capture':return safe_path(self.workspace,self.batches[task['batch']]['job'])
        return self.directory/'steps'/task['id']

    def verify_job(self,task,path):
        recipe=read(path/'recipe.json',4*1024*1024)
        target=safe_path(self.staging,self.batches[task['batch']]['staging'])
        if Path(recipe.get('target',''))!=target:raise SafetyError('Trial job target differs from registered staging')
        if task['kind']=='capture':
            from .capture import load_manifest,_digest
            if recipe.get('kind')!='acquisition':raise SafetyError('Capture task cannot resume a production build')
            batch=self.batches[task['batch']];config=recipe['acquisition'];kw=config['kwargs']
            frozen=Path(config['manifest']);reject_symlinks(frozen)
            relative=str(frozen.relative_to(path/'snapshot'))
            if recipe['snapshot_files'].get(relative)!=sha256_file(frozen):raise SafetyError('Frozen capture manifest changed')
            options={'profile':batch.get('profile'),'resource_ids':batch.get('resource_ids',[])}
            if _digest(load_manifest(frozen,profile=kw.get('profile'),resource_ids=kw.get('resource_ids',[])))!=_digest(load_manifest(safe_path(self.workspace,batch['manifest']),**options)):
                raise SafetyError('Capture job manifest differs from registered selection')
        else:
            step=recipe.get('trial_step',{})
            if (recipe.get('kind')!='trial_step' or step.get('script')!=task['script']
                    or step.get('argv')!=[expand(a,self.workspace,self.staging) for a in task['argv']]
                    or step.get('cwd')!=str(self.workspace)):
                raise SafetyError('Saved trial step differs from frozen queue')
        return recipe

    def completed_evidence(self,task,path):
        self.verify_job(task,path);self.verify_inputs(task)
        pins=check_results(task,self.workspace,self.staging)
        receipt=path/'result.json';result=read(receipt,64*1024*1024)
        if result.get('content_ready') is not False or result.get('status')!='awaiting_review':
            raise SafetyError('Trial completion requires a pending-review receipt')
        pins[str(receipt)]=sha256_file(receipt)
        return pins

    def verify_inputs(self,task):
        for name in task.get('inputs',[]):
            path=Path(expand(name,self.workspace,self.staging));reject_symlinks(path)
            expected=self.state['input_pins'].get(str(path))
            if expected is None:
                for parent in task.get('depends',[]):
                    expected=self.state['tasks'][parent].get('evidence',{}).get(str(path),expected)
            if expected is None or not path.is_file() or sha256_file(path)!=expected:
                raise SafetyError('Trial input changed or lacks predecessor evidence: '+str(path))

    def persist(self):
        queue=list(self.plan.get('review_items',[]))
        for task in self.plan['tasks']:
            row=self.state['tasks'][task['id']]
            if row['state'] in {'needs_review','blocked'}:
                queue.append({'id':task['id'],'reason':row.get('reason','Review required'),'job':str(self.job_path(task))})
            elif row['state']=='done' and task.get('review'):
                queue.append({'id':task['id'],'reason':task['review'],'job':str(self.job_path(task))})
        self.state['review_queue']=queue;self.state['heartbeat_at']=self.now()
        # Progress counters do not create model-facing revisions. Only task
        # state/reason changes and new evidence affect the compact digest.
        marker=digest({'state':self.state['state'],'tasks':{k:{x:v.get(x) for x in ('state','reason','evidence')} for k,v in self.state['tasks'].items()},'queue':queue})
        if marker!=self.state.get('change_sha256'):
            self.state['change_sha256']=marker;self.state['revision']+=1
        save(self.directory/'state.json',self.state)
        save(self.directory/'review-queue.json',{'content_complete':False,'items':queue})
        save(self.directory/'summary.json',brief(self.state))

    def space(self,refresh=False):
        reject_symlinks(self.staging)
        if not self.staging.is_dir() or self.staging.stat().st_dev!=self.device:
            raise SafetyError('Staging volume disappeared or changed identity')
        if refresh or self.space_cache is None or self.now()-self.last_space>300:
            if self.space_reader:report=self.space_reader()
            else:
                path=Path(__file__).resolve().parents[3]/'scripts/acquisition_trial_status.py'
                spec=importlib.util.spec_from_file_location('owl_trial_space',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                report=module.report(self.staging,self.registry,workspace=self.workspace)
            save(self.directory/'storage.json',report)
            if not report['combined_declared_phases_fit']:raise SafetyError('Combined phase ownership/budget check failed; inspect storage.json')
            self.space_cache=report;self.last_space=self.now()
        # The cached remaining peak is conservative as files accumulate. Free
        # space is measured on every scheduling tick, not cached.
        if shutil.disk_usage(self.staging).free<self.space_cache['reserved_remaining_bytes']:
            if not refresh:return self.space(refresh=True)
            raise SafetyError('Free space no longer covers remaining phases and reserve')

    def restore(self):
        for task in self.plan['tasks']:
            row=self.state['tasks'][task['id']]
            if row['state']=='paused':row['state']='pending'
            if row['state']=='done':
                if any(not Path(p).is_file() or sha256_file(Path(p))!=sha for p,sha in row.get('evidence',{}).items()):
                    row.update(state='needs_review',reason='Previously completed evidence changed; rerun requires a reviewed plan')
        self.state.pop('exception',None);self.state['state']='running';self.persist()

    def tick(self):
        active=Counter();locked=set()
        for task in self.plan['tasks']:
            row=self.state['tasks'][task['id']]
            if row['state']!='running':continue
            path=self.job_path(task)
            try:
                status=self.backend.status_job(path)
                if status.get('worker_active') or status['state'] in {'starting','running','retry_wait','cancelling'}:
                    active[task['lane']]+=1;locked.add(task['batch']);continue
                if status['state'] in {'awaiting_review','complete'}:
                    row.update(state='done',evidence=self.completed_evidence(task,path))
                else:row.update(state='needs_review',reason=(status.get('error') or status.get('message') or status['state'])[:500])
            except (OSError,ValueError,RuntimeError,KeyError) as error:
                row.update(state='needs_review',reason=str(error)[:500])
        for task in self.plan['tasks']:
            row=self.state['tasks'][task['id']]
            if row['state']!='pending':continue
            parents=[self.state['tasks'][i]['state'] for i in task.get('depends',[])]
            if any(s in {'needs_review','blocked'} for s in parents):
                row.update(state='blocked',reason='A required predecessor needs review');continue
            if any(s!='done' for s in parents) or active[task['lane']]>=self.plan['concurrency'][task['lane']] or task['batch'] in locked:continue
            try:
                self.space();self.verify_inputs(task);path=self.job_path(task)
                if (path/'owner.json').exists():
                    self.verify_job(task,path)
                    status=self.backend.status_job(path)
                    if status['state'] in {'complete','awaiting_review'} and not status.get('worker_active'):
                        row.update(state='done',evidence=self.completed_evidence(task,path));continue
                    if status['state']=='failed' and not status.get('worker_active'):
                        row.update(state='needs_review',reason=(status.get('error') or 'Existing job failed; no blind restart')[:500]);continue
                    if status['state'] not in {'complete','awaiting_review'} and not status.get('worker_active'):
                        self.backend.resume_job(path)
                elif task['kind']=='capture':raise SafetyError('Expected owned capture job is absent')
                else:
                    args=[expand(a,self.workspace,self.staging) for a in task['argv']]
                    inputs=[expand(a,self.workspace,self.staging) for a in task.get('inputs',[])]
                    self.backend.start_trial_step(task['script'],args,job_dir=path,
                        target=safe_path(self.staging,self.batches[task['batch']]['staging']),inputs=inputs,working_directory=self.workspace)
                row.update(state='running',launches=row['launches']+1)
                active[task['lane']]+=1;locked.add(task['batch'])
            except (OSError,ValueError,RuntimeError,KeyError) as error:
                row.update(state='needs_review',reason=str(error)[:500])
        if all(r['state'] in FINISHED for r in self.state['tasks'].values()):self.state['state']='awaiting_review'
        self.persist();return self.state['state']!='awaiting_review'

    def pause(self):
        stopping=[]
        for task in self.plan['tasks']:
            row=self.state['tasks'][task['id']]
            if row['state']=='running':
                try:
                    self.backend.cancel_job(self.job_path(task));stopping.append(self.job_path(task))
                except (OSError,ValueError,RuntimeError) as error:row['reason']='Pause needs attention: '+str(error)[:350]
                row['state']='paused'
        self.state['state']='paused';self.persist()
        # Child workers stop at their own safe interruption boundaries. Keep
        # this manager alive briefly so a resumed manager cannot race their exit.
        deadline=time.monotonic()+60
        while stopping and time.monotonic()<deadline:
            try:stopping=[p for p in stopping if self.backend.status_job(p).get('worker_active')]
            except (OSError,ValueError,RuntimeError):break
            if stopping:time.sleep(.5)

    def run(self):
        with file_lock(self.directory/'supervisor.lock'), interrupt_signals():
            self.restore();deadline=self.now()+7*86400
            try:
                while self.now()<deadline:
                    self.space()
                    if not self.tick():return brief(self.state)
                    time.sleep(15)
                self.state['exception']='Seven-day unattended-run bound reached'
            except KeyboardInterrupt:pass
            except BaseException as error:
                self.state['exception']=str(error)[:500]
            self.pause();return brief(self.state)
