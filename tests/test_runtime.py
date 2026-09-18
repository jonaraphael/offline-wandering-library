from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from owl.runtime import file_lock, interrupt_signals
from owl.safety import SafetyError, atomic_write, guard_directory, safe_path


class RuntimeTests(unittest.TestCase):
    def test_removed_drive_is_not_recreated_by_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            drive = root / "drive"
            drive.mkdir()
            with guard_directory(drive):
                drive.rename(root / "disconnected")
                with self.assertRaisesRegex(SafetyError, "disappeared"):
                    atomic_write(drive / "sub/file.txt", b"must not land on internal disk")
            self.assertFalse(drive.exists())

    def test_replacement_mount_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            drive = root / "drive"
            drive.mkdir()
            with guard_directory(drive):
                drive.rename(root / "disconnected")
                drive.mkdir()
                with self.assertRaisesRegex(SafetyError, "changed"):
                    safe_path(drive, "next-file.txt")
            self.assertEqual(list(drive.iterdir()), [])

    def test_live_process_excluded_and_killed_process_lock_released(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory).resolve() / "build.lock"
            script = ("from pathlib import Path\nfrom owl.runtime import file_lock\n"
                      "import sys\nwith file_lock(Path(sys.argv[1])):\n"
                      " print('locked', flush=True)\n sys.stdin.read()\n")
            child = subprocess.Popen([sys.executable, "-c", script, str(lock)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                with self.assertRaises(SafetyError):
                    with file_lock(lock):
                        self.fail("live writer lock was ignored")
                child.kill()
                child.communicate(timeout=10)
                self.assertTrue(lock.exists())
                with file_lock(lock):
                    pass  # No manual stale-file removal after force-kill.
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)

    def test_exception_releases_lock_without_deleting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory).resolve() / "lock"
            with self.assertRaises(KeyboardInterrupt):
                with file_lock(lock):
                    raise KeyboardInterrupt
            with file_lock(lock):
                self.assertTrue(lock.exists())

    def test_signal_uses_cleanup_and_restores_handlers(self):
        previous = signal.getsignal(signal.SIGTERM)
        cleaned = []
        with self.assertRaises(KeyboardInterrupt):
            with interrupt_signals():
                try:
                    signal.raise_signal(signal.SIGTERM)
                finally:
                    cleaned.append(True)
        self.assertEqual(cleaned, [True])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_build_cli_termination_returns_restart_instructions(self):
        from owl.build import main
        def terminate(*args, **kwargs):
            signal.raise_signal(signal.SIGTERM)
        with patch("owl.build.build", side_effect=terminate), patch("sys.stderr") as stderr:
            self.assertEqual(main(["unused-drive"]), 130)
            self.assertIn("Rerun the same command", "".join(c.args[0] for c in stderr.write.call_args_list))

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symlink support")
    def test_lock_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original = root / "original"
            original.write_text("do not touch")
            link = root / "lock"
            try:
                link.symlink_to(original)
            except OSError:
                self.skipTest("symlink privilege unavailable")
            with self.assertRaises(SafetyError):
                with file_lock(link):
                    self.fail("symlink lock accepted")
            self.assertEqual(original.read_text(), "do not touch")


if __name__ == "__main__":
    unittest.main()
