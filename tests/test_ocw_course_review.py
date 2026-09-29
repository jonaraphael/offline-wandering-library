import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('ocw_review',Path(__file__).resolve().parents[1]/'scripts/review_ocw_course.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
preview_spec=importlib.util.spec_from_file_location('ocw_complete_preview',Path(__file__).resolve().parents[1]/'scripts/prepare_ocw_complete_preview.py')
preview=importlib.util.module_from_spec(preview_spec);preview_spec.loader.exec_module(preview)


class CaptionEvidenceTests(unittest.TestCase):
    def test_hour_and_minute_cues_are_reconciled(self):
        evidence=module.caption_evidence('WEBVTT\n\n00:01.500 --> 00:04.250\nA caption.\n\n01:02:03.000 --> 01:02:04.000\nLast caption.\n')
        self.assertEqual(evidence['cues'],2)
        self.assertEqual(evidence['first_seconds'],1.5)
        self.assertEqual(evidence['last_seconds'],3724)
        self.assertTrue(evidence['ordered'])

    def test_reversed_and_absent_cues_stay_failed_evidence(self):
        self.assertFalse(module.caption_evidence('00:03.000 --> 00:01.000\nWrong order')['ordered'])
        self.assertEqual(module.caption_evidence('A transcript with no timings')['cues'],0)

    def test_course_scope_verifies_every_used_source_and_no_other_course(self):
        manifest={'sources':[{'id':'package'},{'id':'video'},{'id':'other-video'},
            {'id':'poster','publisher_course_bindings':[{'source_id':'package'}]}]}
        inventory={'source_id':'package','media':[{'id':'video'}]}
        checked=[]
        def receipt(staging,source,digest):checked.append(source['id']);return {'sha256':'a'*64}
        with patch.object(preview,'load_manifest',return_value=manifest),patch.object(preview,'_owner'),patch.object(preview,'_receipt',side_effect=receipt):
            sources,observed=preview.captured_course_sources(Path('/tmp/staging'),inventory)
        self.assertEqual(set(checked),{'package','video','poster'})
        self.assertEqual(set(sources),set(observed))

    def test_course_scope_refuses_missing_required_media(self):
        with patch.object(preview,'load_manifest',return_value={'sources':[{'id':'package'}]}),patch.object(preview,'_owner'):
            with self.assertRaises(ValueError):preview.captured_course_sources(Path('/tmp/staging'),{'source_id':'package','media':[{'id':'missing'}]})


if __name__=='__main__':unittest.main()
