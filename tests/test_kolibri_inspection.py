import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

SPEC = importlib.util.spec_from_file_location('kolibri_inspection', Path(__file__).resolve().parents[1] / 'scripts/inspect_kolibri_capture.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class KolibriInspectionTests(unittest.TestCase):
    def test_duplicate_keys_and_nonfinite_values_are_never_silently_replaced(self):
        for body in (b'{"question":"original","question":"replacement"}', b'{"answer":NaN}'):
            with self.assertRaises(ValueError): MODULE.decode_document('exercise.json', body)

    def test_svg_label_wrapper_is_parsed_as_data_with_exact_callback_identity(self):
        key = 'a'*40
        name = 'images/'+key+'-data.json'
        payload = ('svgData'+key+'({"labels":[{"content":"Axis label"}]});').encode()
        value, encoding = MODULE.decode_document(name, payload)
        self.assertEqual(value['labels'][0]['content'], 'Axis label')
        self.assertEqual(encoding, 'publisher-svg-label-json-wrapper')
        for invalid in (payload.replace(b'svgData', b'other'), payload+b'alert(1);',
                        payload.replace(b'({"labels"', b'({"unexpected"')):
            with self.assertRaises(ValueError):
                MODULE.decode_document(name, invalid)
        with self.assertRaises(ValueError):
            MODULE.decode_document('exercise.json', payload)

    def package(self, path, name):
        with ZipFile(path, 'w') as archive:
            archive.writestr(name, json.dumps({'question': {'content': 'A complete question and explanation preserved in its source package.',
                'widgets': {'answer': {'type': 'numeric-input'}}}, 'hints': ['Count the objects.']}))
        return {'size_bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_package_inventory_hashes_every_member(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'exercise.perseus'
            result=MODULE.inspect_package(path,self.package(path,'exercise.json'))
        self.assertEqual(len(result['members']),1)
        self.assertEqual(result['json_documents'][0]['widget_types'],{'numeric-input':1})
        self.assertTrue(result['members'][0]['sha256'])

    def test_unsafe_unselected_member_rejected_by_shared_archive_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'exercise.perseus'
            receipt=self.package(path,'../escape.json')
            with self.assertRaises(ValueError):
                MODULE.inspect_package(path,receipt)

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'exercise.perseus'
            receipt=self.package(path,'exercise.json'); receipt['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                MODULE.inspect_package(path,receipt)


if __name__ == '__main__':
    unittest.main()
