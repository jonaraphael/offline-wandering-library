import copy
import importlib.util
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('survivor_batch',Path(__file__).resolve().parents[1]/'scripts/prepare_survivor_batch.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)


class SurvivorTrialBatchTests(unittest.TestCase):
    def report(self):
        def row(title,url):return {'title':title,'source_url':url,'topics':['rope'],'title_source':'publisher-table-title','discovered_on':'https://www.survivorlibrary.com/category/'}
        return {'results':[{'resource_id':'survivor-tier-a','metadata_evidence':[], 'selection_report':{
            'pending':[row('Practical Rope Making1912','https://www.survivorlibrary.com/rope.pdf'),
                row('Steam Propellers1900','https://www.survivorlibrary.com/propellers.pdf'),
                row('Old Surgery1900','https://www.survivorlibrary.com/medical.pdf'),
                row('Excluded Work','https://www.survivorlibrary.com/excluded.pdf'),
                row('Already Selected Work','https://www.survivorlibrary.com/selected.pdf')],
            'selected':[],'rejected':[],'missing_topics':['rope']}},
            {'resource_id':'survivor-tier-b','metadata_evidence':[], 'selection_report':{
                'pending':[],'selected':[{'source_url':'https://www.survivorlibrary.com/selected.pdf'}],
                'rejected':[{'source_url':'https://www.survivorlibrary.com/excluded.pdf'}],'missing_topics':[]}}]}

    def test_exact_title_suggestions_and_global_exclusion_propagation(self):
        report=self.report();rows=MODULE.candidates(report)
        self.assertEqual({row['title'] for row in rows.values()},
            {'Practical Rope Making1912','Steam Propellers1900'})
        result=MODULE.shortlist(report)
        self.assertEqual(len(result['topic_suggestions']['rope']),1)
        self.assertEqual(result['topic_suggestions']['rope'][0]['title'],'Practical Rope Making1912')
        self.assertFalse(result['content_ready'])
        self.assertEqual(result,MODULE.shortlist(report))

    def test_exact_head_sizes_pending_pins_and_changed_selection_rejection(self):
        report=self.report();identity=next(iter(MODULE.candidates(report)))
        selection={'id':'trial','report_sha256':MODULE._digest(report),'candidate_ids':[identity]}
        class Probe:
            def probe(self,row):return {'size_bytes':123,'sha256':None,'evidence':[{'status':200,'cached':True,
                'headers':{'last-modified':'date'},'url':row['url'],'body_read':False}]}
        result=MODULE.freeze(report,selection,Probe())
        self.assertEqual(result['budget']['download_bytes'],123)
        self.assertIsNone(result['sources'][0]['sha256']);self.assertFalse(result['content_ready'])
        self.assertEqual(result,MODULE.freeze(report,selection,Probe()))
        bad=copy.deepcopy(selection);bad['candidate_ids']*=2
        with self.assertRaises(ValueError):MODULE.freeze(report,bad,Probe())
        bad=copy.deepcopy(selection);bad['report_sha256']='0'*64
        with self.assertRaises(ValueError):MODULE.freeze(report,bad,Probe())


if __name__=='__main__':unittest.main()
