"""Durable local transfers never trust a partial prefix or replace failed data."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from owl.download import DownloadError, download
from owl.safety import SafetyError
from owl.transfer import TransferError, resume_copy
import owl.transfer as transfer


class FileProxy:
    def __init__(self, handle, write):
        self.handle, self.write = handle, write

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)


class TransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.destination = self.root / "copy"
        self.part = self.root / "copy.part"
        self.payload = bytes(range(256)) * 12289
        self.source.write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def copy(self, **options):
        return resume_copy(self.source, self.destination, size=len(self.payload),
                           checksum=self.digest, progress=options.pop("progress", lambda _: None), **options)

    def track_writes(self, writes, *, fail_after=None):
        original = transfer._open_regular

        def open_file(path, *, writable=False):
            handle = original(path, writable=writable)
            if not writable:
                return handle

            def write(block):
                if fail_after is not None and sum(writes) >= fail_after:
                    raise OSError("device disconnected")
                result = handle.write(block)
                writes.append(result)
                return result

            return FileProxy(handle, write)

        return patch("owl.transfer._open_regular", open_file)

    def test_interruption_checkpoints_and_next_run_only_writes_suffix(self):
        def interrupt(message):
            if message == f"copy: {1024 * 1024:,} / {len(self.payload):,} bytes":
                raise KeyboardInterrupt

        real_fsync = os.fsync
        with patch("owl.transfer.CHECKPOINT_BYTES", 1024 * 1024), \
                patch("owl.transfer.os.fsync", wraps=real_fsync) as synced:
            with self.assertRaises(KeyboardInterrupt):
                self.copy(progress=interrupt)
        self.assertGreaterEqual(synced.call_count, 2)  # Periodic and interruption checkpoints.
        prefix = self.part.read_bytes()
        self.assertEqual(prefix, self.payload[:1024 * 1024])
        self.assertFalse(self.destination.exists())
        writes = []
        with self.track_writes(writes):
            self.assertEqual(self.copy(), self.digest)
        self.assertEqual(sum(writes), len(self.payload) - len(prefix))
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertFalse(self.part.exists())

    def test_io_error_retains_partial_and_previous_destination(self):
        self.destination.write_bytes(b"previous good version")
        writes = []
        with self.track_writes(writes, fail_after=1024 * 1024):
            with self.assertRaisesRegex(OSError, "device disconnected"):
                self.copy()
        self.assertEqual(self.part.read_bytes(), self.payload[:1024 * 1024])
        self.assertEqual(self.destination.read_bytes(), b"previous good version")
        self.assertEqual(self.copy(), self.digest)

    def test_corrupt_and_oversized_partials_restart_without_mixing_data(self):
        for old in (b"wrong" + self.payload[5:100], self.payload + b"too long"):
            with self.subTest(partial_size=len(old)):
                self.destination.unlink(missing_ok=True)
                self.part.write_bytes(old)
                writes = []
                with self.track_writes(writes):
                    self.copy()
                self.assertEqual(sum(writes), len(self.payload))
                self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_complete_partial_is_checked_and_promoted_without_rewriting(self):
        self.part.write_bytes(self.payload)
        writes = []
        with self.track_writes(writes):
            self.assertEqual(self.copy(), self.digest)
        self.assertEqual(writes, [])
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_checksum_failure_preserves_partial_and_previous_destination(self):
        self.destination.write_bytes(b"previous")
        with self.assertRaisesRegex(TransferError, "SHA-256 mismatch"):
            resume_copy(self.source, self.destination, size=len(self.payload), checksum="0" * 64,
                        progress=lambda _: None)
        self.assertEqual(self.destination.read_bytes(), b"previous")
        self.assertEqual(self.part.read_bytes(), self.payload)
        self.assertEqual(self.copy(), self.digest)

    def test_digest_is_read_back_from_written_file(self):
        original = transfer._open_regular

        def corrupt_open(path, *, writable=False):
            handle = original(path, writable=writable)
            if not writable:
                return handle

            def corrupt_write(block):
                return handle.write(bytes([block[0] ^ 1]) + block[1:])

            return FileProxy(handle, corrupt_write)

        with patch("owl.transfer._open_regular", corrupt_open):
            with self.assertRaisesRegex(TransferError, "SHA-256 mismatch"):
                self.copy()
        self.assertFalse(self.destination.exists())

    def test_unpinned_copy_returns_observed_digest(self):
        self.part.write_bytes(self.payload[:313])
        digest = resume_copy(self.source, self.destination, size=len(self.payload), checksum=None,
                             progress=lambda _: None)
        self.assertEqual(digest, self.digest)

    def test_pinned_destination_reused_without_creating_partial(self):
        self.destination.write_bytes(self.payload)
        writes = []
        with self.track_writes(writes):
            self.copy()
        self.assertEqual(writes, [])
        self.assertFalse(self.part.exists())

    def test_explicit_owned_partial_in_separate_directory(self):
        partial = self.root / "staging" / "owned-copy.part"
        partial.parent.mkdir()
        partial.write_bytes(self.payload[:277])
        self.assertEqual(self.copy(part=partial), self.digest)
        self.assertFalse(partial.exists())

    def test_atomic_rename_failure_keeps_complete_partial(self):
        self.destination.write_bytes(b"previous")
        with patch("owl.transfer.os.replace", side_effect=OSError("rename unavailable")):
            with self.assertRaisesRegex(OSError, "rename unavailable"):
                self.copy()
        self.assertEqual(self.part.read_bytes(), self.payload)
        self.assertEqual(self.destination.read_bytes(), b"previous")

    def test_replaced_destination_directory_is_not_used_for_promotion(self):
        directory = self.root / "destination"
        directory.mkdir()
        self.destination = directory / "copy"
        retained = self.root / "original-directory"
        separate_part = self.root / "staging.part"

        def replace_directory(message):
            if message == f"copy: {1024 * 1024:,} / {len(self.payload):,} bytes":
                directory.rename(retained)
                directory.mkdir()

        with patch("owl.transfer.CHECKPOINT_BYTES", 1024 * 1024):
            with self.assertRaisesRegex(SafetyError, "directory changed"):
                self.copy(part=separate_part, progress=replace_directory)
        self.assertEqual(list(directory.iterdir()), [])
        self.assertEqual(separate_part.read_bytes(), self.payload)

    def test_source_size_mismatch_and_mutation_are_rejected(self):
        with self.assertRaisesRegex(TransferError, "size differs"):
            resume_copy(self.source, self.destination, size=1, checksum=None)
        self.assertFalse(self.part.exists())

        def mutate(message):
            if message == f"copy: {1024 * 1024:,} / {len(self.payload):,} bytes":
                with self.source.open("ab") as handle:
                    handle.write(b"changed")

        with patch("owl.transfer.CHECKPOINT_BYTES", 1024 * 1024):
            with self.assertRaisesRegex(TransferError, "changed during transfer"):
                self.copy(progress=mutate)
        self.assertFalse(self.destination.exists())

    def test_symlinks_and_aliases_do_not_touch_unrelated_data(self):
        unrelated = self.root / "unrelated"
        unrelated.write_bytes(b"untouched")
        for path in (self.destination, self.part):
            with self.subTest(path=path):
                path.symlink_to(unrelated)
                with self.assertRaises(SafetyError):
                    self.copy()
                self.assertEqual(unrelated.read_bytes(), b"untouched")
                path.unlink()
        with self.assertRaises(SafetyError):
            self.copy(part=self.source)
        with self.assertRaises(SafetyError):
            self.copy(part=self.destination)
        with self.assertRaises(SafetyError):
            self.copy(part=self.root / "COPY")
        parent_link = self.root / "linked"
        parent_link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SafetyError):
            self.copy(part=parent_link / "new.part")
        self.assertFalse((self.root / "new.part").exists())

    def test_hardlinked_partial_and_nonregular_destination_rejected(self):
        unrelated = self.root / "unrelated"
        unrelated.write_bytes(b"untouched")
        os.link(unrelated, self.part)
        with self.assertRaises(SafetyError):
            self.copy()
        self.assertEqual(unrelated.read_bytes(), b"untouched")
        self.part.unlink()
        self.destination.mkdir()
        with self.assertRaises(SafetyError):
            self.copy()

    def test_local_download_uses_resume_for_file_and_repo_urls(self):
        for url in (self.source.as_uri(), "repo://source"):
            with self.subTest(url=url):
                self.destination.unlink(missing_ok=True)
                self.part.write_bytes(self.payload[:211])
                writes = []
                with self.track_writes(writes):
                    digest = download({"id": "local", "source_url": url,
                                       "size_bytes": len(self.payload), "sha256": self.digest},
                                      self.destination, repo_root=self.root, retries=0, progress=lambda _: None)
                self.assertEqual(digest, self.digest)
                self.assertEqual(sum(writes), len(self.payload) - 211)

    def test_local_download_bad_checksum_retains_owned_partial(self):
        with self.assertRaisesRegex(DownloadError, "SHA-256 mismatch"):
            download({"id": "local", "source_url": self.source.as_uri(),
                      "size_bytes": len(self.payload), "sha256": "0" * 64},
                     self.destination, repo_root=self.root, retries=0, progress=lambda _: None)
        self.assertEqual(self.part.read_bytes(), self.payload)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
