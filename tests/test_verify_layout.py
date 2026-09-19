"""The independent verifier always starts at the public outer drive root."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from owl import verify


class VerifyLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "Emergency library"
        self.library = self.root / "LIBRARY"
        self.library.mkdir(parents=True)
        (self.root / "START_HERE.html").write_text("<h1>Offline library</h1>", encoding="utf-8")
        (self.library / "README.txt").write_text("Offline knowledge π\n", encoding="utf-8")
        shutil.copyfile(verify.__file__, self.library / "VERIFY.py")
        self.entries = ["START_HERE.html", "LIBRARY/README.txt", "LIBRARY/VERIFY.py"]
        self.write_manifest()

    def write_manifest(self, entries=None):
        lines = []
        for relative in self.entries if entries is None else entries:
            digest = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
            lines.append(f"{digest}  {relative}\n")
        (self.library / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")

    def check(self, **kwargs):
        messages = []
        result = verify.verify_drive(self.root, emit=messages.append, **kwargs)
        return result, messages

    def test_outer_manifest_covers_start_and_library_files(self):
        result, messages = self.check()
        self.assertEqual(result, {"OK": 3, "MISSING": 0, "FAILED": 0, "UNKNOWN": 0})
        self.assertTrue(any("OK" in line and "START_HERE.html" in line for line in messages))
        (self.root / "START_HERE.html").write_text("modified landing page", encoding="utf-8")
        result, messages = self.check()
        self.assertEqual(result["FAILED"], 1)
        self.assertTrue(any(line.startswith("FAILED") and "START_HERE.html" in line for line in messages))

    def test_missing_content_is_reported(self):
        (self.library / "README.txt").unlink()
        result, messages = self.check()
        self.assertEqual(result["MISSING"], 1)
        self.assertTrue(any(line.startswith("MISSING") and "LIBRARY/README.txt" in line for line in messages))

    def test_only_nested_private_workspace_is_ignored(self):
        private = self.library / ".owl"
        private.mkdir()
        (private / "state.json").write_text(json.dumps({"complete": True}), encoding="utf-8")
        (private / "scratch.bin").write_bytes(b"private work")
        (self.root / ".owl").mkdir()
        (self.root / ".owl/unrelated.txt").write_text("unrelated", encoding="utf-8")
        (self.root / "SHA256SUMS.txt").write_text("unrelated manifest", encoding="utf-8")
        (self.library / "unmanaged.txt").write_text("unrelated", encoding="utf-8")
        result, messages = self.check()
        self.assertEqual(result["FAILED"], 0)
        self.assertEqual(result["UNKNOWN"], 3)
        self.assertFalse(any("scratch.bin" in line for line in messages))

    def test_incomplete_and_malformed_nested_state_fail(self):
        private = self.library / ".owl"
        private.mkdir()
        for state in [{"complete": False}, {}, [], None, "malformed"]:
            with self.subTest(state=state):
                (private / "state.json").write_text(json.dumps(state), encoding="utf-8")
                self.assertEqual(self.check()[0]["FAILED"], 1)
                self.assertEqual(self.check(allow_incomplete=True)[0]["FAILED"], 0)

    def test_flat_layout_is_not_accepted_and_inner_root_is_not_autodetected(self):
        self.assertEqual(verify.verify_drive(self.library, emit=lambda _: None)["MISSING"], 1)
        manifest = self.library / "SHA256SUMS.txt"
        manifest.replace(self.root / "SHA256SUMS.txt")
        self.assertEqual(self.check()[0]["MISSING"], 1)

    def test_manifest_requires_outer_start_entry(self):
        self.write_manifest(["LIBRARY/README.txt", "LIBRARY/VERIFY.py"])
        result, messages = self.check()
        self.assertEqual(result["FAILED"], 1)
        self.assertTrue(any("must include outer START_HERE.html" in line for line in messages))

    def test_manifest_rejects_unsafe_self_internal_and_nonlayout_paths(self):
        manifest = self.library / "SHA256SUMS.txt"
        baseline = manifest.read_text(encoding="utf-8")
        invalid = ["../outside.txt", "/absolute.txt", "LIBRARY/../outside.txt",
                   "LIBRARY\\outside.txt", "LIBRARY/C:secret", "LIBRARY//file",
                   "LIBRARY/./file", "LIBRARY/.owl/state.json", "LIBRARY/.OWL/secret",
                   "LIBRARY/SHA256SUMS.txt", "LIBRARY/sha256sums.txt", "other.txt",
                   "LIBRARY/README.txt", "LIBRARY/readme.txt", "LIBRARY/control\x7f"]
        for relative in invalid:
            with self.subTest(relative=relative):
                manifest.write_text(baseline + "0" * 64 + "  " + relative + "\n", encoding="utf-8")
                self.assertEqual(self.check()[0]["FAILED"], 1)

    def test_symlinked_manifest_content_and_unknown_directories_are_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside", encoding="utf-8")
        link = self.library / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable")
        result, messages = self.check()
        self.assertEqual(result["FAILED"], 1)
        self.assertFalse(any("secret.txt" in line for line in messages))
        manifest = self.library / "SHA256SUMS.txt"
        original = manifest.read_text(encoding="utf-8")
        manifest.write_text(original + "0" * 64 + "  LIBRARY/linked/secret.txt\n", encoding="utf-8")
        self.assertEqual(self.check()[0]["FAILED"], 1)
        manifest.unlink()
        (outside / "checksums.txt").write_text(original, encoding="utf-8")
        manifest.symlink_to(outside / "checksums.txt")
        self.assertEqual(self.check()[0]["FAILED"], 1)

    def test_copied_verifier_isolated_no_argument_from_arbitrary_cwd(self):
        command = [sys.executable, "-I", str(self.library / "VERIFY.py"), "--strict"]
        result = subprocess.run(command, cwd=self.base, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK=3", result.stdout)
        (self.root / "START_HERE.html").write_text("tampered", encoding="utf-8")
        failed = subprocess.run(command, cwd=self.base, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertIn("FAILED  START_HERE.html", failed.stdout)

    def test_repository_script_accepts_explicit_outer_root(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify.py"
        result = subprocess.run([sys.executable, "-I", str(script), str(self.root), "--strict"],
                                cwd=self.base, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
