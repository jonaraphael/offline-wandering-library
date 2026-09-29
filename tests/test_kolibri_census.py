import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('kolibri_census', SCRIPTS/'inspect_kolibri_census.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CensusTests(unittest.TestCase):
    def fixture(self, root):
        staging = root/'capture'; staging.mkdir()
        receipts = []
        for i in range(2):
            path = staging/f'{i}.perseus'
            with ZipFile(path, 'w') as archive:
                archive.writestr('exercise.json', json.dumps({'question': {'content':'Read all the choices.',
                    'widgets': {'radio 1': {'type':'radio'}}}, 'hints': []}))
            receipts.append({'source_id':f'exercise_{i}_perseus','relative_path':path.name,
                'size_bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return staging, receipts

    def test_interrupted_census_resumes_unchanged_evidence_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); staging, receipts = self.fixture(root)
            output = root/'review'
            original = MODULE.inspect_package
            count = 0
            def interrupted(*args):
                nonlocal count
                count += 1
                if count == 2: raise KeyboardInterrupt
                return original(*args)
            with patch.object(MODULE,'load_capture_sources',return_value=({'id':'fixture'},receipts)):
                with patch.object(MODULE,'inspect_package',side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt): MODULE.run(staging,output)
                with patch.object(MODULE,'inspect_package',wraps=original) as inspect:
                    result = MODULE.run(staging,output)
                    self.assertEqual(inspect.call_count,1)
                self.assertEqual(result['inspected_sources'],2)
                self.assertEqual(result['format_errors'],0)
                self.assertFalse(result['content_ready'])
                with patch.object(MODULE,'inspect_package',side_effect=AssertionError('unchanged evidence reused')):
                    self.assertEqual(MODULE.run(staging,output),result)
                detail=output/'exercise_0_perseus.json'
                detail.write_text(detail.read_text()+' ')
                with self.assertRaisesRegex(ValueError,'evidence changed'):
                    MODULE.run(staging,output)

    def test_malformed_package_is_recorded_without_hiding_other_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); staging, receipts=self.fixture(root)
            (staging/receipts[0]['relative_path']).write_bytes(b'invalid')
            with patch.object(MODULE,'load_capture_sources',return_value=({'id':'fixture'},receipts)):
                result=MODULE.run(staging,root/'review')
            self.assertEqual(result['format_errors'],1)
            self.assertEqual(result['inspected_sources'],1)
            self.assertFalse(result['content_ready'])


if __name__ == '__main__': unittest.main()
