"""Portable validation evidence never exports machine details or masks failures."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('owl_validation_script',
    Path(__file__).resolve().parents[1]/'scripts/validate_acquisition.py')
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class PortableValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.raw = self.root/'private-report.json'
        self.raw.write_text('{"log":"/Users/private/workspace/trace.log","failure_excerpt":"PRIVATE LOG BODY"}')
        names = ['catalog','full-tests','selector-freshness','content-docs-freshness','inputs-unchanged',
                 *('plan-'+name for name in validation.PROFILES),'explicit-language-opt-in']
        self.report = dict(schema_version=1,completed_at='2026-09-22T00:00:00+00:00',downloads=0,
            fixed_small_preset_expectations=validation.SMALL_PRESETS,freshness_checked=True,full_tests=True,
            input_sha256={'catalog/library.yaml':'a'*64},simulated_free_bytes_for_plans=10**13,
            passed=True,checks=[dict(name=name,passed=True,log=str(self.raw),command=['/private/python']) for name in names],
            profiles=[dict(profile='full-1tb',assets=3,content_bytes=100,peak_bytes=200,capacity_bytes=1000,
                target_created=False,incomplete_resources=['pending'],unresolved_assets=['missing'])])
        self.report['checks'][1]['tests_run']=123

    def test_export_preserves_schema_and_omits_commands_paths_and_logs(self):
        destination=self.root/'portable.json'
        validation._export_evidence(self.report,self.raw,destination)
        text=destination.read_text()
        evidence=json.loads(text)
        self.assertTrue(evidence['passed'])
        self.assertEqual(evidence['checks'][1],dict(name='full-tests',passed=True,tests_run=123))
        self.assertEqual(evidence['profiles'],self.report['profiles'])
        self.assertEqual(evidence['raw_report'],dict(sha256=hashlib.sha256(self.raw.read_bytes()).hexdigest(),size_bytes=self.raw.stat().st_size))
        for private in ('/Users/','/private/',str(self.root),'PRIVATE LOG BODY','failure_excerpt','command','"log"'):
            self.assertNotIn(private,text)
        self.assertLess(destination.stat().st_size,validation.MAX_PORTABLE_EVIDENCE_BYTES)

    def test_failed_check_and_missing_checks_cannot_export_success(self):
        report=deepcopy(self.report)
        report['checks'][1].update(passed=False,exit_code=1,failure_excerpt='PRIVATE LOG BODY')
        result=validation._portable_evidence(report,self.raw)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks'][1]['failure_kind'],'nonzero_exit')
        self.assertEqual(result['checks'][1]['exit_code'],1)
        report['checks']=[]
        result=validation._portable_evidence(report,self.raw)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks'][-1]['failure_kind'],'missing_checks')

    def test_main_exports_failed_tests_and_returns_failure(self):
        def command(name,*_args):
            return dict(name=name,passed=name!='full-tests',exit_code=1 if name=='full-tests' else 0,
                        tests_run=9 if name=='full-tests' else 0,failure_excerpt='PRIVATE LOG BODY '+str(self.raw))
        plan_checks=[dict(name='plan-'+name,passed=True) for name in validation.PROFILES]
        plan_checks.append(dict(name='explicit-language-opt-in',passed=True))
        destination=self.root/'failed-evidence.json'
        with patch.object(validation,'_command',side_effect=command), \
                patch.object(validation,'_plans',return_value=(plan_checks,[])),redirect_stdout(io.StringIO()):
            code=validation.main(['--full','--skip-freshness','--output-dir',str(self.root/'runs'),
                                  '--export-evidence',str(destination)])
        self.assertEqual(code,1)
        evidence=json.loads(destination.read_text())
        self.assertFalse(evidence['passed'])
        self.assertFalse(evidence['freshness_checked'])
        self.assertTrue(evidence['full_tests'])
        self.assertNotIn('PRIVATE LOG BODY',destination.read_text())
        self.assertNotIn(str(self.root),destination.read_text())

    def test_exception_lists_are_bounded_without_hiding_totals(self):
        self.report['profiles'][0]['unresolved_assets']=['pending_'+str(i) for i in range(1000)]
        evidence=validation._portable_evidence(self.report,self.raw)
        profile=evidence['profiles'][0]
        self.assertEqual(len(profile['unresolved_assets']),128)
        self.assertEqual(profile['unresolved_assets_total'],1000)
        self.assertTrue(profile['unresolved_assets_truncated'])
        with patch.object(validation,'MAX_PORTABLE_EVIDENCE_BYTES',100),self.assertRaisesRegex(ValueError,'64 KiB'):
            validation._export_evidence(self.report,self.raw,self.root/'oversized.json')
        self.assertFalse((self.root/'oversized.json').exists())

    def test_changed_inputs_cannot_export_success(self):
        before = {'catalog/library.yaml': 'a'*64}
        after = {'catalog/library.yaml': 'b'*64}
        check = validation._check_inputs(before, after)
        self.assertFalse(check['passed'])
        self.assertEqual(check['changed_inputs'], ['catalog/library.yaml'])
        self.report['checks'].append(check)
        self.assertFalse(validation._portable_evidence(self.report, self.raw)['passed'])
        self.assertTrue(validation._check_inputs(before, before)['passed'])


if __name__=='__main__': unittest.main()
