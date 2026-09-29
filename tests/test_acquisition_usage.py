import os
from pathlib import Path
import tempfile
import unittest

from owl.acquisition.capture import _usage
from owl.safety import SafetyError


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_complete_nested_measurement(self):
        (self.root/'nested/deeper').mkdir(parents=True)
        (self.root/'a').write_bytes(b'a'*13)
        (self.root/'nested/b').write_bytes(b'b'*21)
        (self.root/'nested/deeper/c').write_bytes(b'c'*34)
        self.assertEqual(_usage(self.root), 68)

    def test_file_symlink_is_not_counted_as_owned(self):
        (self.root/'a').write_bytes(b'private')
        (self.root/'link').symlink_to(self.root/'a')
        with self.assertRaises(SafetyError):
            _usage(self.root)

    def test_directory_symlink_is_rejected(self):
        (self.root/'nested').mkdir()
        (self.root/'link').symlink_to(self.root/'nested', target_is_directory=True)
        with self.assertRaises(SafetyError):
            _usage(self.root)

    def test_hardlink_is_rejected(self):
        (self.root/'a').write_bytes(b'private')
        os.link(self.root/'a', self.root/'link')
        with self.assertRaises(SafetyError):
            _usage(self.root)


if __name__ == '__main__':
    unittest.main()
