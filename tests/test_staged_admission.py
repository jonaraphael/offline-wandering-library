import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.acquisition.capture import _digest
from owl.acquisition.cli import main as acquire

spec = importlib.util.spec_from_file_location('staged_admission', Path(__file__).resolve().parents[1] / 'scripts/check_staged_admission.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AdmissionDeltaTests(unittest.TestCase):
    def test_fixed_preset_cannot_swap_equal_sized_assets(self):
        with self.assertRaisesRegex(module.SafetyError, 'Fixed small-preset'):
            module.compare_selection('flash-16gb', [{'id': 'old', 'size_bytes': 3}], [{'id': 'new', 'size_bytes': 3}])

    def test_fixed_preset_cannot_change_only_hash(self):
        with self.assertRaisesRegex(module.SafetyError, 'Fixed small-preset'):
            module.compare_selection('critical-64gb', [{'id': 'a', 'size_bytes': 3, 'sha256': 'old'}],
                                     [{'id': 'a', 'size_bytes': 3, 'sha256': 'new'}])

    def test_reading_profile_records_precise_changes(self):
        old = [{'id': 'a', 'size_bytes': 3}, {'id': 'b', 'size_bytes': 2}]
        new = [{'id': 'b', 'size_bytes': 4}, {'id': 'c', 'size_bytes': 9}]
        row = module.compare_selection('full-1tb', old, new)
        self.assertEqual((row['added_ids'], row['removed_ids'], row['changed_ids']), (['c'], ['a'], ['b']))
        self.assertEqual(row, module.compare_selection('full-1tb', old[::-1], new[::-1]))

    def test_production_noop_staging_passes_admission_with_per_asset_navigation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fragment = {'schema_version': 1, 'assets': [], 'resource_updates': [],
                        'acquisition_capture': {'capture_id': 'noop', 'manifest_sha256': 'a' * 64}}
            receipt = {'schema_version': 1, 'kind': 'acquisition-review',
                       **fragment['acquisition_capture'], 'fragment_sha256': _digest(fragment),
                       'review': {'status': 'approved', 'evidence': ['No-op fixture'], 'reviewer': 'test'},
                       'artifacts': {}}
            fragment_path, receipt_path = root / 'fragment.json', root / 'receipt.json'
            fragment_path.write_text(json.dumps(fragment))
            receipt_path.write_text(json.dumps(receipt))
            candidate = root / 'candidate'
            with redirect_stdout(io.StringIO()):
                status = acquire(['stage', '--fragment', str(fragment_path), '--output', str(candidate),
                                  '--review-receipt', str(receipt_path), '--cache-dir', str(root / 'cache')])
            self.assertEqual(status, 0)
            report = module.inspect(candidate, fragment_path, receipt_path)
            self.assertTrue(report['checks_passed'])
            self.assertFalse(report['published'])
            self.assertGreater(len(report['candidate_files']), 100)
            assignments = list((candidate / 'navigation/assignments').glob('*.yaml'))
            self.assertGreater(len(assignments), 100)
            for path in assignments:
                self.assertIn(path.relative_to(candidate).as_posix(), report['candidate_files'])
            self.assertEqual({r['profile'] for r in report['profiles']}, set(module.PROFILES))
            for row in report['profiles']:
                self.assertEqual(row['before_sha256'], row['after_sha256'])
                self.assertFalse(row['added_ids'] or row['removed_ids'] or row['changed_ids'])

    def test_control_bundle_retains_count_and_byte_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary).resolve()
            (candidate / 'one.json').write_bytes(b'123')
            with patch.object(module, 'MAX_CONTROL_FILES', 1), patch.object(module, 'MAX_CONTROL_BYTES', 3):
                self.assertEqual(len(module.control_members(candidate)), 1)
                (candidate / 'two.json').write_bytes(b'')
                with self.assertRaisesRegex(module.SafetyError, 'control-file count or byte budget'):
                    module.control_members(candidate)
                (candidate / 'two.json').unlink()
                (candidate / 'one.json').write_bytes(b'1234')
                with self.assertRaisesRegex(module.SafetyError, 'control-file count or byte budget'):
                    module.control_members(candidate)
