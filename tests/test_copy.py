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
from owl.layout import checksum_name
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
        (self.source / "LIBRARY/BOOKS").mkdir(parents=True, exist_ok=True)
        (self.source / "LIBRARY/BOOKS/book.txt").write_bytes(data)
        self.asset = dict(id="book", destination="BOOKS/book.txt", title="Fixture book", category="reference",
                          format="txt", source_url="https://offline.invalid/book.txt", version="1",
                          size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), license="CC0-1.0",
                          verification="observed" if observed else "pinned", required=True, profiles=["demo"])
        (self.source / "LIBRARY/BUILD_INFO.json").write_bytes(_json({"schema_version": 1, "complete": True,
                                                           "content_complete": not partial}))
        (self.source / "LIBRARY/INVENTORY.json").write_bytes(_json({"schema_version": 1, "assets": [self.asset],
                                                          "content_complete": not partial}))
        (self.source / "START_HERE.html").write_text('<a href="LIBRARY/BOOKS/book.txt">Fixture book</a>', encoding="utf-8")
        self.write_manifest()
        _owned_directory(self.source / "LIBRARY/.owl")
        (self.source / "LIBRARY/.owl/state.json").write_bytes(_json({"schema_version": 1, "complete": True,
            "managed": ["BOOKS/book.txt", "BUILD_INFO.json", "INVENTORY.json", "START_HERE.html", "SHA256SUMS.txt"],
            "assets": {"book": {"sha256": self.asset["sha256"], "fingerprint": fingerprint(self.asset)}}}))

    def write_manifest(self):
        self.entries = {}
        for path in (self.source / "LIBRARY/BOOKS/book.txt", self.source / "LIBRARY/BUILD_INFO.json",
                     self.source / "LIBRARY/INVENTORY.json", self.source / "START_HERE.html"):
            self.entries[path.relative_to(self.source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.source / "LIBRARY/SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(self.entries.items())), encoding="utf-8")

    def add_source_atlas(self, *, generated=None):
        paths = ["INDEX/topics.html", "INDEX/topics/fixture.html", "INDEX/navigation-report.json"]
        for relative in paths[:-1]:
            path = self.source / checksum_name(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<!doctype html><title>Original atlas fixture</title>", encoding="utf-8")
        report = {"schema_version": 1, "generated_files": paths if generated is None else generated}
        (self.source / checksum_name(paths[-1])).write_bytes(_json(report))
        self.write_manifest()
        for relative in paths:
            self.entries[checksum_name(relative)] = hashlib.sha256((self.source / checksum_name(relative)).read_bytes()).hexdigest()
        (self.source / "LIBRARY/SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(self.entries.items())), encoding="utf-8")
        state_path = self.source / "LIBRARY/.owl/state.json"
        state = json.loads(state_path.read_text())
        state["managed"] = sorted(set(state["managed"]) | set(paths))
        state["atlas_managed"] = sorted(paths)
        state_path.write_bytes(_json(state))
        return sorted(paths)

    def run_copy(self, **kwargs):
        return copy_drive(self.source, self.target, progress=kwargs.pop("progress", lambda _: None), **kwargs)

    def test_byte_identical_offline_copy_and_verified_reuse(self):
        self.target.mkdir()
        (self.target / "personal.txt").write_text("Keep this unrelated file", encoding="utf-8")
        with patch("owl.build.download", side_effect=AssertionError("Copy must not download")):
            result = self.run_copy()
        self.assertEqual(result, dict(copied=5, reused=0, verified=5, complete=True))
        for relative in [*self.entries, "LIBRARY/SHA256SUMS.txt"]:
            self.assertEqual((self.target / relative).read_bytes(), (self.source / relative).read_bytes())
        self.assertEqual((self.target / "personal.txt").read_text(), "Keep this unrelated file")
        checked = verify_drive(self.target, emit=lambda _: None)
        self.assertEqual((checked["FAILED"], checked["MISSING"], checked["UNKNOWN"]), (0, 0, 1))
        with patch("owl.copy.resume_copy", side_effect=AssertionError("Verified files must be reused")):
            result = self.run_copy()
        self.assertEqual((result["copied"], result["reused"]), (0, 5))
        state = json.loads((self.target / "LIBRARY/.owl/state.json").read_text())
        self.assertEqual(state["phase"], "complete")
        self.assertNotIn("active_path", state)
        self.assertEqual(state["assets"]["book"], {"sha256": self.asset["sha256"], "fingerprint": fingerprint(self.asset)})

    def test_completed_partial_content_library_remains_partial(self):
        self.write_source(self.data, partial=True)
        self.run_copy()
        self.assertFalse(json.loads((self.target / "LIBRARY/BUILD_INFO.json").read_text())["content_complete"])
        self.assertFalse(json.loads((self.target / "LIBRARY/INVENTORY.json").read_text())["content_complete"])

    def test_fresh_copy_has_two_outer_objects_and_logical_managed_paths(self):
        self.run_copy()
        self.assertEqual({path.name for path in self.target.iterdir()}, {"START_HERE.html", "LIBRARY"})
        state = json.loads((self.target / "LIBRARY/.owl/state.json").read_text(encoding="utf-8"))
        self.assertEqual(set(state["managed"]), {"START_HERE.html", "BOOKS/book.txt", "BUILD_INFO.json",
                                                "INVENTORY.json", "SHA256SUMS.txt"})
        self.assertTrue(all(name.startswith(".owl/copies/") for name in state["copy_parts"]))
        self.assertTrue(all(not record["destination"].startswith("LIBRARY/")
                            for record in state["copy_parts"].values()))
        (self.target / "START_HERE.html").write_text("damaged owned start page", encoding="utf-8")
        self.assertEqual(self.run_copy()["copied"], 1)
        self.assertEqual((self.target / "START_HERE.html").read_bytes(),
                         (self.source / "START_HERE.html").read_bytes())

    def test_flat_source_is_not_adopted(self):
        flat = self.root / "flat"
        flat.mkdir()
        (flat / "START_HERE.html").write_text("old flat layout", encoding="utf-8")
        (flat / "SHA256SUMS.txt").write_text("", encoding="utf-8")
        with self.assertRaises((SafetyError, OSError)):
            copy_drive(flat, self.target, progress=lambda _: None)
        self.assertFalse(self.target.exists())

    def test_observed_hash_keeps_unpinned_fingerprint_for_builder(self):
        self.write_source(self.data, observed=True)
        self.run_copy()
        state = json.loads((self.target / "LIBRARY/.owl/state.json").read_text())
        self.assertEqual(state["assets"]["book"]["fingerprint"], fingerprint({**self.asset, "sha256": None}))

    def test_actual_transfer_interrupt_resumes_owned_prefix_and_credits_space(self):
        def interrupt(message):
            if message.startswith("book.txt: 65,536 /"):
                raise KeyboardInterrupt
        with patch("owl.transfer.CHECKPOINT_BYTES", 65536), patch("owl.transfer.CHUNK_BYTES", 65536):
            with self.assertRaises(KeyboardInterrupt):
                self.run_copy(progress=interrupt)
        state = json.loads((self.target / "LIBRARY/.owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["phase"], "copy")
        self.assertEqual(state["active_path"], "BOOKS/book.txt")
        self.assertGreater(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)
        parts = list((self.target / "LIBRARY/.owl/copies").glob("*.part"))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].stat().st_size, 65536)
        messages, allocations = [], []
        with patch("owl.copy.check_space", side_effect=lambda path, amount: allocations.append(amount)):
            self.run_copy(progress=messages.append)
        self.assertTrue(any("resuming copy at 65,536" in message for message in messages))
        total = sum((self.source / name).stat().st_size for name in [*self.entries, "LIBRARY/SHA256SUMS.txt"])
        self.assertEqual(allocations, [total - 65536 + 1024 * 1024])
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)
        self.assertFalse(list((self.target / "LIBRARY/.owl/copies").glob("*.part")))
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_corrupt_source_never_overwrites_previous_final_or_manifest(self):
        self.run_copy()
        old_manifest = (self.target / "LIBRARY/SHA256SUMS.txt").read_bytes()
        replacement = b"X" * len(self.data)
        self.write_source(replacement)
        (self.source / "LIBRARY/BOOKS/book.txt").write_bytes(b"Y" * len(replacement))
        with self.assertRaisesRegex(TransferError, "SHA-256 mismatch"):
            self.run_copy()
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)
        self.assertEqual((self.target / "LIBRARY/SHA256SUMS.txt").read_bytes(), old_manifest)
        self.assertFalse(json.loads((self.target / "LIBRARY/.owl/state.json").read_text())["complete"])
        self.assertGreater(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_reusing_target_still_checks_source_hash(self):
        self.run_copy()
        (self.source / "LIBRARY/BOOKS/book.txt").write_bytes(b"!" * len(self.data))
        with self.assertRaisesRegex(SafetyError, "Source checksum mismatch"):
            self.run_copy()
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)
        self.assertFalse(json.loads((self.target / "LIBRARY/.owl/state.json").read_text())["complete"])

    def test_unowned_bad_file_and_case_alias_refused(self):
        (self.target / "LIBRARY/BOOKS").mkdir(parents=True)
        path = self.target / "LIBRARY/BOOKS/book.txt"
        path.write_bytes(b"Do not overwrite")
        with self.assertRaisesRegex(SafetyError, "unowned destination"):
            self.run_copy()
        self.assertEqual(path.read_bytes(), b"Do not overwrite")
        path.unlink()
        path.with_name("BOOK.txt").write_bytes(self.data)
        with self.assertRaisesRegex(SafetyError, "case-conflicting"):
            self.run_copy()

    def test_unowned_matching_file_can_be_adopted(self):
        (self.target / "LIBRARY/BOOKS").mkdir(parents=True)
        (self.target / "LIBRARY/BOOKS/book.txt").write_bytes(self.data)
        result = self.run_copy()
        self.assertEqual(result["reused"], 1)

    def test_insufficient_space_does_not_modify_existing_library(self):
        self.run_copy()
        before = (self.target / "LIBRARY/.owl/state.json").read_bytes()
        self.write_source(b"X" * len(self.data))
        with patch("owl.copy.check_space", side_effect=SafetyError("Insufficient disk space")):
            with self.assertRaisesRegex(SafetyError, "Insufficient"):
                self.run_copy()
        self.assertEqual((self.target / "LIBRARY/.owl/state.json").read_bytes(), before)
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)

    def test_incomplete_source_state_or_buildinfo_rejected(self):
        state_path = self.source / "LIBRARY/.owl/state.json"
        state = json.loads(state_path.read_text())
        state["complete"] = False
        state_path.write_bytes(_json(state))
        with self.assertRaisesRegex(SafetyError, "Source library build is incomplete"):
            self.run_copy()
        self.assertFalse(self.target.exists())
        state["complete"] = True
        state_path.write_bytes(_json(state))
        (self.source / "LIBRARY/BUILD_INFO.json").write_bytes(_json({"schema_version": 1, "complete": False}))
        self.write_manifest()
        with self.assertRaisesRegex(SafetyError, "completed OWL build"):
            self.run_copy()
        self.assertFalse(self.target.exists())

    def test_source_without_private_state_is_accepted(self):
        shutil.rmtree(self.source / "LIBRARY/.owl")
        self.run_copy()
        self.assertFalse((self.source / "LIBRARY/.owl").exists())

    def test_overlap_and_active_source_writer_refused(self):
        for target in (self.source, self.source / "child", self.root):
            with self.subTest(target=target), self.assertRaisesRegex(SafetyError, "non-overlapping"):
                copy_drive(self.source, target, progress=lambda _: None)
        with file_lock(self.source / "LIBRARY/.owl/build.lock"):
            with self.assertRaisesRegex(SafetyError, "Another OWL process"):
                self.run_copy()
        self.assertFalse(self.target.exists())

    def test_manifest_traversal_case_prefix_and_internal_conflicts_rejected(self):
        original = (self.source / "LIBRARY/SHA256SUMS.txt").read_text()
        bad_entries = ["../escape", "LIBRARY/BOOKS/book.txt", "LIBRARY/books/other.txt",
                       "LIBRARY/BOOKS/book.txt/child", "LIBRARY/.OWL/state.json",
                       "LIBRARY/SHA256SUMS.txt", "BOOKS/book.txt", "other.txt"]
        for name in bad_entries:
            (self.source / "LIBRARY/SHA256SUMS.txt").write_text(original + "0" * 64 + "  " + name + "\n")
            with self.subTest(name=name), self.assertRaises(SafetyError):
                self.run_copy()
            self.assertFalse(self.target.exists())

    def test_symlink_cannot_redirect_source_or_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.target / "LIBRARY").mkdir(parents=True)
        try:
            (self.target / "LIBRARY/BOOKS").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")
        with self.assertRaises(SafetyError):
            self.run_copy()
        self.assertEqual(list(outside.iterdir()), [])
        (self.target / "LIBRARY/BOOKS").unlink()
        original = self.source / "LIBRARY/BOOKS/book.txt"
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
        before = (self.target / "LIBRARY/.owl/state.json").read_bytes()
        with file_lock(self.target / "LIBRARY/.owl/build.lock"):
            with self.assertRaisesRegex(SafetyError, "Another OWL process"):
                self.run_copy()
        self.assertEqual((self.target / "LIBRARY/.owl/state.json").read_bytes(), before)
        self.write_source(b"X" * len(self.data))
        key = hashlib.sha256(("BOOKS/book.txt\0" + self.asset["sha256"]).encode()).hexdigest()
        partial = self.target / "LIBRARY/.owl/copies" / (key + ".part")
        partial.write_bytes(b"Unrelated existing data")
        with self.assertRaisesRegex(SafetyError, "Unowned or conflicting copy partial"):
            self.run_copy()
        self.assertEqual(partial.read_bytes(), b"Unrelated existing data")
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)

    def test_inventory_must_agree_with_manifest_and_source_files(self):
        inventory = json.loads((self.source / "LIBRARY/INVENTORY.json").read_text())
        inventory["assets"][0]["sha256"] = "0" * 64
        (self.source / "LIBRARY/INVENTORY.json").write_bytes(_json(inventory))
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
        state = json.loads((disconnected / "LIBRARY/.owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["phase"], "copy")
        self.assertEqual(state["active_path"], "BOOKS/book.txt")
        self.assertTrue(list((disconnected / "LIBRARY/.owl/copies").glob("*.part")))
        self.assertGreater(verify_drive(disconnected, emit=lambda _: None)["FAILED"], 0)
        self.target.rmdir()
        disconnected.rename(self.target)
        self.run_copy()
        self.assertEqual((self.target / "LIBRARY/BOOKS/book.txt").read_bytes(), self.data)
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)

    def test_atlas_backup_retains_ownership_and_later_build_retires_old_pages(self):
        local = self.root / "atlas-source"
        build(local, catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
              profile_name="demo", allow_local=True, navigation_dir=ROOT / "catalog/demo-navigation",
              progress=lambda _: None)
        report = json.loads((local / "LIBRARY/INDEX/navigation-report.json").read_text())
        for private_state in (True, False):
            destination = self.root / ("with-private-state" if private_state else "without-private-state")
            if not private_state:
                shutil.rmtree(local / "LIBRARY/.owl")
            with self.subTest(private_state=private_state):
                copy_drive(local, destination, progress=lambda _: None)
                state = json.loads((destination / "LIBRARY/.owl/state.json").read_text())
                self.assertEqual(state["atlas_managed"], sorted(report["generated_files"]))
                build(destination, catalog=ROOT / "catalog/demo.yaml", profiles_dir=ROOT / "profiles",
                      profile_name="demo", allow_local=True, progress=lambda _: None)
                self.assertIn("Unavailable in this build", (destination / "LIBRARY/INDEX/topics/build-process.html").read_text())
                checked = verify_drive(destination, emit=lambda _: None)
                self.assertEqual((checked["FAILED"], checked["MISSING"], checked["UNKNOWN"]), (0, 0, 0))

    def test_copy_preserves_previous_destination_atlas_ownership(self):
        self.run_copy()
        previous = self.target / "LIBRARY/INDEX/topics/previous.html"
        previous.parent.mkdir(parents=True)
        previous.write_text("Previous owned atlas page", encoding="utf-8")
        state_path = self.target / "LIBRARY/.owl/state.json"
        state = json.loads(state_path.read_text())
        relative = previous.relative_to(self.target / "LIBRARY").as_posix()
        state["managed"].append(relative)
        state["atlas_managed"] = [relative]
        state_path.write_bytes(_json(state))
        atlas_paths = self.add_source_atlas()
        self.run_copy()
        state = json.loads(state_path.read_text())
        self.assertEqual(state["atlas_managed"], sorted([*atlas_paths, relative]))
        self.assertEqual(previous.read_text(), "Previous owned atlas page")

    def test_atlas_report_cannot_claim_unverified_or_nonatlas_paths(self):
        report = "INDEX/navigation-report.json"
        for claims in ([report, "personal.txt"], [report, "INDEX/topics/not-copied.html"],
                       [report, "../outside.html"], [report, report], ["INDEX/topics.html"]):
            with self.subTest(claims=claims):
                self.add_source_atlas(generated=claims)
                with self.assertRaises(SafetyError):
                    self.run_copy()
                self.assertFalse(self.target.exists())

    def test_source_private_atlas_ownership_must_agree_with_verified_report(self):
        self.add_source_atlas(generated=["INDEX/topics.html", "INDEX/navigation-report.json"])
        with self.assertRaisesRegex(SafetyError, "ownership is missing"):
            self.run_copy()
        self.assertFalse(self.target.exists())

    def test_atlas_report_hash_verified_before_target_ownership_changes(self):
        self.add_source_atlas()
        (self.source / "LIBRARY/INDEX/navigation-report.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(SafetyError, "Source checksum mismatch"):
            self.run_copy()
        self.assertFalse(self.target.exists())

    def test_interrupted_copy_retains_known_atlas_ownership_before_page_copy(self):
        paths = self.add_source_atlas()
        def interrupt(message):
            if message.startswith("book.txt: 65,536 /"):
                raise KeyboardInterrupt
        with patch("owl.transfer.CHECKPOINT_BYTES", 65536), patch("owl.transfer.CHUNK_BYTES", 65536):
            with self.assertRaises(KeyboardInterrupt):
                self.run_copy(progress=interrupt)
        state = json.loads((self.target / "LIBRARY/.owl/state.json").read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(state["atlas_managed"], paths)
        self.assertFalse((self.target / "LIBRARY/INDEX/topics.html").exists())
        self.run_copy()
        self.assertEqual(verify_drive(self.target, emit=lambda _: None)["FAILED"], 0)


if __name__ == "__main__":
    unittest.main()
