"""Offline scheduling, fail-closed bindings and sparse review contracts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition.supervisor import Supervisor, brief, digest, save, validate_plan
from owl.acquisition.sampling import sampling_plan, excerpt_windows
from owl.safety import SafetyError


class Backend:
    def __init__(self): self.states={};self.started=[];self.cancelled=[]
    def start_trial_step(self,script,argv,*,job_dir,target,inputs,working_directory):
        job_dir.mkdir(parents=True);save(job_dir/'owner.json',{})
        save(job_dir/'recipe.json',{'kind':'trial_step','target':str(target),
            'trial_step':{'script':script,'argv':argv,'cwd':str(working_directory)}})
        self.states[str(job_dir)]={'state':'running','worker_active':True};self.started.append(job_dir)
    def status_job(self,path):return self.states[str(path)]
    def cancel_job(self,path):
        self.cancelled.append(path);self.states[str(path)]={'state':'cancelled','worker_active':False}
    def resume_job(self,path):self.states[str(path)]={'state':'running','worker_active':True}
    def finish(self,path,**changes):
        self.states[str(path)]={'state':'awaiting_review','worker_active':False,**changes}
        save(path/'result.json',{'status':'awaiting_review','content_ready':False})


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.staging=self.root/'staging';self.staging.mkdir()
        self.backend=Backend();self.registry={'batches':[{'id':i,'staging':i} for i in ['a','b','c']]}
        self.plan={'schema_version':1,'id':'test','concurrency':{'review':2},'tasks':[
            {'id':i,'kind':'script','lane':'review','batch':i,'script':'prepare_review_packets.py','argv':[]}
            for i in ['a','b','c']]}
    def supervisor(self,space=True):
        return Supervisor(self.plan,self.registry,self.root,self.staging,self.root/'state',backend=self.backend,
            space_reader=lambda:{'combined_declared_phases_fit':space,'reserved_remaining_bytes':0})
    def test_dependency_scheduling_and_review_never_admits(self):
        self.plan['tasks'][1]['depends']=['a'];self.plan['tasks'][2]['depends']=['b']
        self.plan['tasks'][2]['review']='Substantive review is pending'
        s=self.supervisor();s.restore();s.tick();self.assertEqual(len(self.backend.started),1)
        self.backend.finish(s.job_path(self.plan['tasks'][0]));s.tick()
        self.assertEqual(len(self.backend.started),2)
        self.backend.finish(s.job_path(self.plan['tasks'][1]),state='failed',error='changed source');s.tick()
        self.assertEqual(s.state['state'],'awaiting_review')
        self.assertEqual(s.state['tasks']['c']['state'],'blocked')
        self.assertFalse(brief(s.state)['content_complete'])
        self.assertEqual(len(self.backend.started),2)
    def test_lane_limit_and_same_batch_lock(self):
        self.plan['tasks'][1]['batch']='a';s=self.supervisor();s.restore();s.tick()
        self.assertEqual([p.name for p in self.backend.started],['a','c'])
    def test_pause_resume_and_unchanged_revision(self):
        s=self.supervisor();s.restore();s.tick();revision=s.state['revision'];s.tick()
        self.assertEqual(s.state['revision'],revision);s.pause()
        self.assertEqual(len(self.backend.cancelled),2)
        resumed=self.supervisor();resumed.restore();resumed.tick()
        self.assertEqual(resumed.state['tasks']['a']['state'],'running')
    def test_changed_inputs_and_report_gate(self):
        control=self.root/'control.json';save(control,{'edition':1})
        self.plan['tasks'][0]['inputs']=[str(control)]
        self.plan['tasks'][1]['checks']=[{'path':str(self.root/'result.json'),'equals':{'complete':True}}]
        s=self.supervisor();s.restore();save(control,{'edition':2});s.tick()
        self.assertEqual(s.state['tasks']['a']['state'],'needs_review')
        save(self.root/'result.json',{'complete':False});self.backend.finish(s.job_path(self.plan['tasks'][1]));s.tick()
        self.assertEqual(s.state['tasks']['b']['state'],'needs_review')
    def test_resume_rejects_changed_done_evidence(self):
        report=self.root/'result.json';save(report,{'complete':True})
        self.plan['tasks'][0]['checks']=[{'path':str(report),'equals':{'complete':True}}]
        s=self.supervisor();s.restore();s.tick();self.backend.finish(s.job_path(self.plan['tasks'][0]));s.tick()
        save(report,{'complete':False});s=self.supervisor();s.restore()
        self.assertEqual(s.state['tasks']['a']['state'],'needs_review')
    def test_storage_failure_starts_nothing(self):
        s=self.supervisor(False);s.restore();s.tick();self.assertEqual(self.backend.started,[])
        self.assertTrue(all(r['state']=='needs_review' for r in s.state['tasks'].values()))
    def test_changed_queue_or_volume_identity_rejected(self):
        self.supervisor();self.plan['concurrency']['review']=1
        with self.assertRaises(SafetyError):self.supervisor()
    def test_unrelated_existing_job_rejected(self):
        s=self.supervisor();s.restore();s.tick();s.pause()
        save(s.job_path(self.plan['tasks'][0])/'recipe.json',{'kind':'build','target':str(self.staging/'a')})
        s.restore();s.tick();self.assertEqual(s.state['tasks']['a']['state'],'needs_review')
    def test_capture_bound_to_effective_selection_and_registered_target(self):
        from owl.safety import sha256_file
        task=self.plan['tasks'][0];task['kind']='capture'
        batch=self.registry['batches'][0];batch.update(job='capture-job',manifest='candidate.json')
        s=self.supervisor();job=s.job_path(task);job.mkdir()
        frozen=job/'snapshot/inputs/candidate.json';frozen.parent.mkdir(parents=True)
        save(frozen,{'sources':['one']});save(self.root/'candidate.json',{'sources':['one']})
        recipe={'kind':'acquisition','target':str(self.staging/'a'),
            'acquisition':{'manifest':str(frozen),'kwargs':{'profile':'full-1tb','resource_ids':[]}},
            'snapshot_files':{'inputs/candidate.json':sha256_file(frozen)}}
        save(job/'recipe.json',recipe)
        with patch('owl.acquisition.capture.load_manifest',side_effect=lambda p,**kw:json.loads(p.read_text())):
            s.verify_job(task,job)  # Redundant profile filter is equivalent.
            save(self.root/'candidate.json',{'sources':['different']})
            with self.assertRaisesRegex(SafetyError,'manifest differs'):s.verify_job(task,job)
        recipe['target']=str(self.root/'production');save(job/'recipe.json',recipe)
        with self.assertRaisesRegex(SafetyError,'target differs'):s.verify_job(task,job)
    def test_success_status_without_pending_receipt_cannot_close_step(self):
        s=self.supervisor();s.restore();s.tick();job=s.job_path(self.plan['tasks'][0])
        self.backend.finish(job);save(job/'result.json',{'content_ready':True,'status':'complete'});s.tick()
        self.assertEqual(s.state['tasks']['a']['state'],'needs_review')
    def test_mutating_actions_cycles_and_unbounded_lane_rejected(self):
        for script,argv in [('acquire_content.py',['stage']),('prepare_stackoverflow.py',['expand']),('trial_supervisor.py',['run'])]:
            self.plan['tasks'][0].update(script=script,argv=argv)
            with self.assertRaises(SafetyError):validate_plan(self.plan)
        self.plan['tasks'][0].update(script='prepare_review_packets.py',argv=[],depends=['c'])
        self.plan['tasks'][2]['depends']=['a']
        with self.assertRaises(SafetyError):validate_plan(self.plan)
    def test_status_delta_does_not_hide_an_unexpected_manager_exit(self):
        import contextlib,io,sys
        path=Path(__file__).resolve().parents[1]/'scripts/trial_supervisor.py'
        spec=importlib.util.spec_from_file_location('supervisor_cli',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        s=self.supervisor();s.restore();manager=s.directory/'manager-job';manager.mkdir();save(manager/'owner.json',{})
        arguments=['trial_supervisor.py','status','--state-dir',str(s.directory),'--since-revision',str(s.state['revision'])]
        output=io.StringIO()
        with patch.object(sys,'argv',arguments),patch.object(module.jobs,'status_job',return_value={'worker_active':False,'state':'interrupted'}),contextlib.redirect_stdout(output):module.main()
        result=json.loads(output.getvalue());self.assertNotIn('unchanged',result)
        self.assertEqual(result['worker_state'],'interrupted')

    def test_brief_bounded_even_with_many_long_identities(self):
        state={'state':'running','tasks':{str(i)+'x'*60:{'state':'running'} for i in range(100)},'detail':'x'*2000}
        self.assertLessEqual(len(json.dumps(brief(state)).encode()),2048)


class SamplingTests(unittest.TestCase):
    def test_exact_determinism_and_honest_detection_scope(self):
        units=[str(i) for i in range(10000)]
        p=sampling_plan(units,'a'*64,targeted=['1','2'])
        self.assertEqual(p,sampling_plan(reversed(units),'a'*64,targeted=['2','1']))
        self.assertEqual(len(p['screening_units']),8)
        self.assertEqual(len(p['escalation_units']),51)
        self.assertLess(p['screening_encounter_probability'],.95)
        self.assertGreaterEqual(p['full_sample_encounter_probability'],.95)
        self.assertFalse(p['content_ready']);self.assertFalse(p['completeness_proven'])
        self.assertNotEqual(p['screening_units'],sampling_plan(units,'b'*64)['screening_units'])
    def test_small_populations_targets_and_invalid_units(self):
        p=sampling_plan(['a','b'],'a'*64,targeted=['a']);self.assertEqual(p['full_sample_encounter_probability'],1)
        for units in [[],['a','a'],['a',None]]:
            with self.assertRaises(SafetyError):sampling_plan(units,'a'*64)
        with self.assertRaises(SafetyError):sampling_plan(['a'],'a'*64,targeted=['absent'])
        self.assertEqual(excerpt_windows('short'),[{'offset':0,'total_characters':5,'text':'short'}])
        windows=excerpt_windows('x'*5000);self.assertEqual(len(windows),3)
        self.assertEqual(sum(len(w['text']) for w in windows),1500)
    def test_review_packet_offline_reuse_and_changed_evidence(self):
        path=Path(__file__).resolve().parents[1]/'scripts/prepare_review_packets.py'
        spec=importlib.util.spec_from_file_location('packet',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();report=root/'report.json';output=root/'packet.json'
            save(report,{'records':[{'asset_id':'one','structural_pass':False,'utility_excerpts':excerpt_windows('example')}]})
            with patch('socket.create_connection',side_effect=AssertionError('offline')):
                first=module.prepare(report,output);self.assertEqual(first,module.prepare(report,output))
            self.assertEqual(first['flagged_units'],1)
            self.assertFalse(json.loads(output.read_text())['content_ready'])
            save(report,{'records':[{'asset_id':'two','structural_pass':True}]})
            with self.assertRaises(SafetyError):module.prepare(report,output)


if __name__=='__main__':unittest.main()
