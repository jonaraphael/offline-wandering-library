"""Automatic local-search publication stays resumable and preserves owned data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from owl.safety import SafetyError
from owl.search_pack import CHUNK_BYTES, chunk_path, publish_pack, read_chunk


class SearchPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "SEARCH").mkdir()
        self.binary = self.root / "scratch.bin"

    def source(self, suffix=b"first"):
        data = (b'UTF-8 and unsafe source text: ");globalThis.attack(); //\n' * 50000) + suffix
        self.binary.write_bytes(data)
        return data, hashlib.sha256(data).hexdigest()

    def test_roundtrip_multiple_chunks_is_deterministic_and_has_no_raw_duplicate(self):
        data, digest = self.source()
        report = publish_pack(self.root, self.binary, digest)
        manifest = report["transport"]
        self.assertGreater(manifest["chunk_count"], 2)
        decoded = b"".join(read_chunk(self.root, manifest, n)[0] for n in range(manifest["chunk_count"]))
        self.assertEqual(decoded, data)
        self.assertGreater(report["transport_bytes"], len(data) * 4 // 3)
        self.assertFalse((self.root / "SEARCH/library.owl").exists())
        for name, expected in report["file_integrity"].items():
            raw = (self.root / name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])
            self.assertEqual(len(raw), expected["size_bytes"])
        self.assertEqual(publish_pack(self.root, self.binary, digest), report)

    def test_interrupted_publication_preserves_previous_manifest_and_resumes_chunks(self):
        _, first_digest = self.source()
        previous = publish_pack(self.root, self.binary, first_digest)
        manifest_file = self.root / "SEARCH/manifest.js"
        previous_manifest = manifest_file.read_bytes()
        data, digest = self.source(b"changed")
        def stop(message):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            publish_pack(self.root, self.binary, digest, notify=stop)
        self.assertEqual(manifest_file.read_bytes(), previous_manifest)
        first = self.root / f"SEARCH/chunks/{digest}/00000000.js.part"
        mtime = first.stat().st_mtime_ns
        report = publish_pack(self.root, self.binary, digest)
        self.assertEqual(first.with_suffix("").stat().st_mtime_ns, mtime)
        self.assertNotEqual(manifest_file.read_bytes(), previous_manifest)
        self.assertEqual(b"".join(read_chunk(self.root, report["transport"], n)[0]
                                  for n in range(report["transport"]["chunk_count"])), data)
        for relative in previous["file_integrity"]:
            self.assertTrue((self.root / relative).is_file())

    def test_unowned_generation_and_symlink_chunks_are_not_overwritten(self):
        _, digest = self.source()
        generation = self.root / "SEARCH/chunks" / digest
        generation.mkdir(parents=True)
        unrelated = generation / "personal.txt"
        unrelated.write_text("keep me")
        with self.assertRaisesRegex(SafetyError, "unowned"):
            publish_pack(self.root, self.binary, digest)
        self.assertEqual(unrelated.read_text(), "keep me")
        unrelated.unlink()
        report = publish_pack(self.root, self.binary, digest)
        chunk = self.root / chunk_path(report["transport"], 0)
        chunk.unlink()
        chunk.symlink_to(self.binary)
        before = self.binary.read_bytes()
        with self.assertRaises(SafetyError):
            publish_pack(self.root, self.binary, digest)
        self.assertEqual(self.binary.read_bytes(), before)

    def test_owned_damaged_chunk_is_repaired_without_accepting_wrong_data(self):
        data, digest = self.source()
        report = publish_pack(self.root, self.binary, digest)
        chunk = self.root / chunk_path(report["transport"], 0)
        chunk.write_bytes(b"x" * (2 * CHUNK_BYTES))
        with self.assertRaises(ValueError):
            read_chunk(self.root, report["transport"], 0)
        publish_pack(self.root, self.binary, digest)
        self.assertEqual(read_chunk(self.root, report["transport"], 0)[0], data[:CHUNK_BYTES])

    def test_changed_binary_cannot_publish_a_manifest_under_wrong_checksum(self):
        _, digest = self.source()
        self.binary.write_bytes(self.binary.read_bytes()[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            publish_pack(self.root, self.binary, digest)
        self.assertFalse((self.root / "SEARCH/manifest.js").exists())

    def test_bad_republish_cannot_damage_an_active_generation_and_correct_retry_repairs(self):
        data, digest = self.source()
        report = publish_pack(self.root, self.binary, digest)
        before = {name: (self.root / name).read_bytes() for name in report["file_integrity"]}
        self.binary.write_bytes(b"!" + data[1:])
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            publish_pack(self.root, self.binary, digest)
        for name, expected in before.items():
            self.assertEqual((self.root / name).read_bytes(), expected)
        self.binary.write_bytes(data)
        publish_pack(self.root, self.binary, digest)
        self.assertFalse(list((self.root / "SEARCH/chunks" / digest).glob("*.part")))

    def test_mid_read_source_mutation_keeps_prior_active_chunks_unchanged(self):
        data, digest = self.source()
        report = publish_pack(self.root, self.binary, digest)
        before = {name: (self.root / name).read_bytes() for name in report["file_integrity"]}
        calls = 0
        def mutate(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                with self.binary.open("r+b") as handle:
                    handle.seek(CHUNK_BYTES + 16384)
                    handle.write(b"!")
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            publish_pack(self.root, self.binary, digest, notify=mutate)
        for name, expected in before.items():
            self.assertEqual((self.root / name).read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
