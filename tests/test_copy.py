"""Offline deployment, resumable copying, and preservation of existing drive data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from owl.build import _json, _owned_directory, build
from owl.catalog import fingerprint
from owl.copy import copy_drive, main
from owl.runtime import file_lock
from owl.safety import SafetyError
from owl.transfer import TransferError
from owl.verify import verify_drive


ROOT = Path(__file__).resolve().parents[1]


class CopyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir()
        self.data = (b"Small offline reference fixture with pictures described in text.\n" * 34000)
        self.write_source(self.data)

    def write_source(self, data, *, partial=False, observed=False):
        (self.source / "BOOKS").mkdir(exist_ok=True)
        (self.source / "BOOKS/book.txt").write_bytes(data)
        self.asset = dict(id="book", destination="BOOKS/book.txt", title="Fixture book", category="reference",
                          format="txt", source_url="https://offline.invalid/book.txt", version="1",
                          size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), license="CC0-1.0",
                          verification="observed" if observed else "pinned", required=True, profiles=["demo"])
        (self.source / "BUILD_INFO.json").write_bytes(_json({"schema_version": 1, "complete": True,
                                                           "content_complete": not partial}))
        (self.source / "INVENTORY.json").write_bytes(_json({"schema_version": 1, "assets": [self.asset],
                                                          "content_complete": not partial}))
        (self.source / "START_HERE.html").write_text('<a href="BOOKS/book.txt">Fixture book</a>', encoding="utf-8")
        self.write_manifest()
        _owned_directory(self.source / ".owl")
        (self.source / ".owl/state.json").write_bytes(_json({"schema_version": 1, "complete": True,
            "managed": ["BOOKS/book.txt", "BUILD_INFO.json", "INVENTORY.json", "START_HERE.html", "SHA256SUMS.txt"],
            "assets": {"book": {"sha256": self.asset["sha256"], "fingerprint": fingerprint(self.asset)}}}))

    def write_manifest(self):
        self.entries = {}
        for path in (self.source / "BOOKS/book.txt", self.source / "BUILD_INFO.json",
                     self.source / "INVENTORY.json", self.source / "START_HERE.html"):
            self.entries[path.relative_to(self.source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.source / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(self.entries.items())), encoding="utf-8")

    def run_copy(self, **kwargs):
        return copy_drive(self.source, self.target, progress=kwargs.pop("progress", lambda _: None), **kwargs)

    def test_byte_identical_offline_copy_and_verified_reuse(self):
        self.target.mkdir()
        (self.target / "personal.txt").write_text("Keep this unrelated file", encoding="utf-8")
        with patch("owl.build.download", side_effect=AssertionError("Copy must not download")):
            result = self.run_copy()
        self.assertEqual(result, dict(copied=5, reused=0, verified=5, complete=True))
        for relative in [*self.entries, "SHA256SUMS.txt"]:
            self.assertEqual((self.target / relative).read_bytes(), (self.source / relative).read_bytes())
        self.assertEqual((self.target / "personal.txt").read_text(), "Keep this unrelated file")
        checked = verify_drive(self.target, emit=lambda _: None)
        self.assertEqual((checked["FAILED"], checked["MISSING"], checked["UNKNOWN"]), (0, 0, 1))
        with patch("owl.copy.resume_copy", side_effect=AssertionError("Verified files must be reused")):
            result = self.run_copy()
        self.assertEqual((result["copied"], result["reused"]), (0, 5))
        state = json.loads((self.target / ".owl/state.json").read_text())
        self.assertEqual(state["phase"], "complete")
        self.assertNotIn("active_path", state)
        self.assertEqual(state["assets"]["book"], {"sha256": self.asset["sha256"], "fingerprint": fingerprint(self.asset)})

    def test_completed_partial_content_library_remains_partial(self):
        self.write_source(self.data, partial=True)
        self.run_copy()
        self.assertFalse(json.loads((self.target / "BUILD_INFO.json").read_text())["content_complete"])
        self.assertFalse(json.loads((self.target / "INVENTORY.json").read_text())["content_complete"])

    def test_observed_hash_keeps_unpinned_fingerprint_for_builder(self):
        self.write_source(self.data, observed=True)
        self.run_copy()
        state = json.loads((self.target / ".owl/state.json").read_text())
        self.assertEqual(state["assets"]["book"]["fingerprint"], fingerprint({**self.asset, "sha256": None}))

    def test_actual_transfer_interrupt_resumes_owned_prefix_and_credits_space(self):
        def interrupt(message):
            if message.startswith("book.txt: 65,536 /"):
                raise KeyboardInterrupt
        with patch("owl.transfer.CHECKPOINT_BYTES", 65536), patch("owl.transfer.CHUNK_BYTES", 65536):
            with self.assertRaises(KeyboardInterrupt):
                self.run_copy(progress=interrupt)
        state = json.loads((self.target / ".owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["phase"], "copy")
        self.assertEqual(state["active_path"], "BOOKS/book.txt")
        self.assertGreater(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)
        parts = list((self.target / ".owl/copies").glob("*.part"))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].stat().st_size, 65536)
        messages, allocations = [], []
        with patch("owl.copy.check_space", side_effect=lambda path, amount: allocations.append(amount)):
            self.run_copy(progress=messages.append)
        self.assertTrue(any("resuming copy at 65,536" in message for message in messages))
        total = sum((self.source / name).stat().st_size for name in [*self.entries, "SHA256SUMS.txt"])
        self.assertEqual(allocations, [total - 65536 + 1024 * 1024])
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)
        self.assertFalse(list((self.target / ".owl/copies").glob("*.part")))
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_corrupt_source_never_overwrites_previous_final_or_manifest(self):
        self.run_copy()
        old_manifest = (self.target / "SHA256SUMS.txt").read_bytes()
        replacement = b"X" * len(self.data)
        self.write_source(replacement)
        (self.source / "BOOKS/book.txt").write_bytes(b"Y" * len(replacement))
        with self.assertRaisesRegex(TransferError, "SHA-256 mismatch"):
            self.run_copy()
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)
        self.assertEqual((self.target / "SHA256SUMS.txt").read_bytes(), old_manifest)
        self.assertFalse(json.loads((self.target / ".owl/state.json").read_text())["complete"])
        self.assertGreater(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_reusing_target_still_checks_source_hash(self):
        self.run_copy()
        (self.source / "BOOKS/book.txt").write_bytes(b"!" * len(self.data))
        with self.assertRaisesRegex(SafetyError, "Source checksum mismatch"):
            self.run_copy()
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)
        self.assertFalse(json.loads((self.target / ".owl/state.json").read_text())["complete"])

    def test_unowned_bad_file_and_case_alias_refused(self):
        (self.target / "BOOKS").mkdir(parents=True)
        path = self.target / "BOOKS/book.txt"
        path.write_bytes(b"Do not overwrite")
        with self.assertRaisesRegex(SafetyError, "unowned destination"):
            self.run_copy()
        self.assertEqual(path.read_bytes(), b"Do not overwrite")
        path.unlink()
        path.with_name("BOOK.txt").write_bytes(self.data)
        with self.assertRaisesRegex(SafetyError, "case-conflicting"):
            self.run_copy()

    def test_unowned_matching_file_can_be_adopted(self):
        (self.target / "BOOKS").mkdir(parents=True)
        (self.target / "BOOKS/book.txt").write_bytes(self.data)
        result = self.run_copy()
        self.assertEqual(result["reused"], 1)

    def test_insufficient_space_does_not_modify_existing_library(self):
        self.run_copy()
        before = (self.target / ".owl/state.json").read_bytes()
        self.write_source(b"X" * len(self.data))
        with patch("owl.copy.check_space", side_effect=SafetyError("Insufficient disk space")):
            with self.assertRaisesRegex(SafetyError, "Insufficient"):
                self.run_copy()
        self.assertEqual((self.target / ".owl/state.json").read_bytes(), before)
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)

    def test_incomplete_source_state_or_buildinfo_rejected(self):
        state_path = self.source / ".owl/state.json"
        state = json.loads(state_path.read_text())
        state["complete"] = False
        state_path.write_bytes(_json(state))
        with self.assertRaisesRegex(SafetyError, "Source library build is incomplete"):
            self.run_copy()
        self.assertFalse(self.target.exists())
        state["complete"] = True
        state_path.write_bytes(_json(state))
        (self.source / "BUILD_INFO.json").write_bytes(_json({"schema_version": 1, "complete": False}))
        self.write_manifest()
        with self.assertRaisesRegex(SafetyError, "completed OWL build"):
            self.run_copy()
        self.assertFalse(self.target.exists())

    def test_source_without_private_state_is_accepted(self):
        shutil.rmtree(self.source / ".owl")
        self.run_copy()
        self.assertFalse((self.source / ".owl").exists())

    def test_overlap_and_active_source_writer_refused(self):
        for target in (self.source, self.source / "child", self.root):
            with self.subTest(target=target), self.assertRaisesRegex(SafetyError, "non-overlapping"):
                copy_drive(self.source, target, progress=lambda _: None)
        with file_lock(self.source / ".owl/build.lock"):
            with self.assertRaisesRegex(SafetyError, "Another OWL process"):
                self.run_copy()
        self.assertFalse(self.target.exists())

    def test_manifest_traversal_case_prefix_and_internal_conflicts_rejected(self):
        original = (self.source / "SHA256SUMS.txt").read_text()
        bad_entries = ["../escape", "BOOKS/book.txt", "books/other.txt", "BOOKS/book.txt/child",
                       ".OWL/state.json", "SHA256SUMS.txt"]
        for name in bad_entries:
            (self.source / "SHA256SUMS.txt").write_text(original + "0" * 64 + "  " + name + "\n")
            with self.subTest(name=name), self.assertRaises(SafetyError):
                self.run_copy()
            self.assertFalse(self.target.exists())

    def test_symlink_cannot_redirect_source_or_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.target.mkdir()
        try:
            (self.target / "BOOKS").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")
        with self.assertRaises(SafetyError):
            self.run_copy()
        self.assertEqual(list(outside.iterdir()), [])
        (self.target / "BOOKS").unlink()
        original = self.source / "BOOKS/book.txt"
        original.unlink()
        original.symlink_to(outside / "missing")
        with self.assertRaises(SafetyError):
            self.run_copy()

    def test_cli_copies_offline_and_reports_interrupt(self):
        command = subprocess.run([sys.executable, str(ROOT / "scripts/copy_drive.py"), str(self.source), str(self.target)],
                                 text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(command.returncode, 0, command.stdout + command.stderr)
        self.assertIn("COPY COMPLETE: all managed destination files verified", command.stdout)
        with patch("owl.copy.copy_drive", side_effect=KeyboardInterrupt), patch("sys.stderr"):
            self.assertEqual(main([str(self.source), str(self.target)]), 130)

    def test_real_demo_build_copy_and_builder_reuse(self):
        local = self.root / "built"
        build(local, catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
              profile_name="demo", allow_local=True, progress=lambda _: None)
        copy_drive(local, self.target, progress=lambda _: None)
        checked = verify_drive(self.target, emit=lambda _: None)
        self.assertEqual((checked["FAILED"], checked["MISSING"], checked["UNKNOWN"]), (0, 0, 0))
        with patch("owl.build.download", side_effect=AssertionError("Copied assets must be reusable")):
            build(self.target, catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
                  profile_name="demo", allow_local=True, progress=lambda _: None)
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_active_target_writer_and_unowned_partial_are_refused(self):
        self.run_copy()
        before = (self.target / ".owl/state.json").read_bytes()
        with file_lock(self.target / ".owl/build.lock"):
            with self.assertRaisesRegex(SafetyError, "Another OWL process"):
                self.run_copy()
        self.assertEqual((self.target / ".owl/state.json").read_bytes(), before)
        self.write_source(b"X" * len(self.data))
        key = hashlib.sha256(("BOOKS/book.txt\0" + self.asset["sha256"]).encode()).hexdigest()
        partial = self.target / ".owl/copies" / (key + ".part")
        partial.write_bytes(b"Unrelated existing data")
        with self.assertRaisesRegex(SafetyError, "Unowned or conflicting copy partial"):
            self.run_copy()
        self.assertEqual(partial.read_bytes(), b"Unrelated existing data")
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)

    def test_inventory_must_agree_with_manifest_and_source_files(self):
        inventory = json.loads((self.source / "INVENTORY.json").read_text())
        inventory["assets"][0]["sha256"] = "0" * 64
        (self.source / "INVENTORY.json").write_bytes(_json(inventory))
        self.write_manifest()
        with self.assertRaisesRegex(SafetyError, "inventory disagrees"):
            self.run_copy()
        self.assertFalse(self.target.exists())

    def test_replaced_target_directory_gets_no_new_writes_and_original_can_resume(self):
        disconnected = self.root / "disconnected"
        replaced = False
        def replace_directory(message):
            nonlocal replaced
            if not replaced and message.startswith("book.txt: 65,536 /"):
                try:
                    self.target.rename(disconnected)
                except OSError as error:
                    if os.name == "nt":
                        self.skipTest(f"OS prevents renaming a directory containing open files: {error}")
                    raise
                self.target.mkdir()
                replaced = True
        with patch("owl.transfer.CHECKPOINT_BYTES", 65536), patch("owl.transfer.CHUNK_BYTES", 65536):
            with self.assertRaisesRegex(SafetyError, "directory changed"):
                self.run_copy(progress=replace_directory)
        self.assertTrue(replaced)
        self.assertEqual(list(self.target.iterdir()), [])
        state = json.loads((disconnected / ".owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["phase"], "copy")
        self.assertEqual(state["active_path"], "BOOKS/book.txt")
        self.assertTrue(list((disconnected / ".owl/copies").glob("*.part")))
        self.assertGreater(verify_drive(disconnected, emit=lambda _: None)["FAILED"], 0)
        self.target.rmdir()
        disconnected.rename(self.target)
        self.run_copy()
        self.assertEqual((self.target / "BOOKS/book.txt").read_bytes(), self.data)
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)


if __name__ == "__main__":
    unittest.main()
