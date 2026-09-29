import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.supervisor import digest
from owl.safety import SafetyError

spec=importlib.util.spec_from_file_location('direct_trial',Path(__file__).parents[1]/'scripts/trial_direct_previews.py')
trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)


class DirectTrialWaitTests(unittest.TestCase):
    def test_waits_for_bound_prior_tasks_and_rejects_changed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();plan={'tasks':[{'id':'direct'}]}
            (root/'plan.json').write_text(json.dumps(plan))
            (root/'owner.json').write_text(json.dumps({'plan_sha256':digest(plan)}))
            state={'state':'running','tasks':{'direct':{'state':'running'}}}
            (root/'state.json').write_text(json.dumps(state));waits=[]
            def sleep(seconds):
                waits.append(seconds);state['tasks']['direct']['state']='needs_review'
                (root/'state.json').write_text(json.dumps(state))
            trial.wait_for_prior_queue(root,root/'plan.json',['direct'],sleep=sleep)
            self.assertEqual(waits,[30])
            (root/'owner.json').write_text(json.dumps({'plan_sha256':'changed'}))
            with self.assertRaisesRegex(SafetyError,'different frozen plan'):
                trial.wait_for_prior_queue(root,root/'plan.json',['direct'],sleep=sleep)

    def test_does_not_bypass_paused_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();plan={'tasks':[{'id':'direct'}]}
            (root/'plan.json').write_text(json.dumps(plan));(root/'owner.json').write_text(json.dumps({'plan_sha256':digest(plan)}))
            (root/'state.json').write_text(json.dumps({'state':'paused','tasks':{'direct':{'state':'paused'}}}))
            with self.assertRaisesRegex(SafetyError,'paused'):
                trial.wait_for_prior_queue(root,root/'plan.json',['direct'])
