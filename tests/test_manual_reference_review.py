import copy
import importlib.util
from pathlib import Path
import unittest
from owl.safety import SafetyError

spec=importlib.util.spec_from_file_location('manual_refs',Path(__file__).resolve().parents[1]/'scripts/review_manual_references.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ReferenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.row={'document':'improve-page.html','tag':'a','attribute':'href','url':'PAGEURL','kind':'cross-reference'}
        self.audit={'source_sha256':'a'*64,'whole_package_preserved':True,'members_verified':2,
            'members':[{'path':'improve-page.html','original_sha256':'b'*64}],
            'missing_local_links':[self.row,dict(self.row,document='required.html',url='chapter.html')]}
        self.policy={'schema_version':1,'audit_sha256':'c'*64,'source_sha256':'a'*64,'references':[
            {**self.row,'source_member_sha256':'b'*64,'classification':'optional_publisher_feedback','expected_count':1,'reason':'Publisher feedback template'}]}
    def test_exact_reference_only_and_no_readiness_promotion(self):
        r=module.classify(self.audit,self.policy,audit_sha256='c'*64)
        self.assertEqual(len(r['missing_essential_local_links']),1)
        self.assertEqual(len(r['optional_publisher_feedback']),1)
        self.assertFalse(r['content_ready'])
    def test_changed_pin_runtime_reference_and_count_fail_closed(self):
        for edit in ['hash','runtime','duplicate','missing']:
            a=copy.deepcopy(self.audit)
            if edit=='hash':a['members'][0]['original_sha256']='d'*64
            if edit=='runtime':a['missing_local_links'][0]['kind']='active-dependency'
            if edit=='duplicate':a['missing_local_links'].append(a['missing_local_links'][0])
            if edit=='missing':a['missing_local_links'].pop(0)
            with self.assertRaises(SafetyError):module.classify(a,self.policy,audit_sha256='c'*64)
        with self.assertRaises(SafetyError):module.classify(self.audit,self.policy,audit_sha256='d'*64)


if __name__=='__main__':unittest.main()
