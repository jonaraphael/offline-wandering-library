import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('staged_admission', Path(__file__).resolve().parents[1] / 'scripts/check_staged_admission.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AdmissionDeltaTests(unittest.TestCase):
    def test_fixed_preset_cannot_swap_equal_sized_assets(self):
        with patch.dict(module.FIXED, {'tiny': (1, 3)}):
            with self.assertRaisesRegex(module.SafetyError, 'Fixed small-preset'):
                module.compare_selection('tiny', [{'id': 'old', 'size_bytes': 3}], [{'id': 'new', 'size_bytes': 3}])

    def test_fixed_preset_cannot_change_only_hash(self):
        with patch.dict(module.FIXED, {'tiny': (1, 3)}):
            with self.assertRaisesRegex(module.SafetyError, 'Fixed small-preset'):
                module.compare_selection('tiny', [{'id': 'a', 'size_bytes': 3, 'sha256': 'old'}],
                                         [{'id': 'a', 'size_bytes': 3, 'sha256': 'new'}])

    def test_reading_profile_records_precise_changes(self):
        old = [{'id': 'a', 'size_bytes': 3}, {'id': 'b', 'size_bytes': 2}]
        new = [{'id': 'b', 'size_bytes': 4}, {'id': 'c', 'size_bytes': 9}]
        row = module.compare_selection('full-1tb', old, new)
        self.assertEqual((row['added_ids'], row['removed_ids'], row['changed_ids']), (['c'], ['a'], ['b']))
        self.assertEqual(row, module.compare_selection('full-1tb', old[::-1], new[::-1]))
