"""Verify selected sources, bounded local scripts, and real directory locations."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import tempfile
import unittest

from owl.filesystem import FAT_FILE_LIMIT, fat_file_limit
from owl.search_shards import (compose_shards, load_manifest,
                               output_bytes, output_size, payload, terms)


class SourceShardTests(unittest.TestCase):
    def test_selection_is_bound_to_the_source_digest(self):
        manifest = load_manifest()
        digest, shard = next((key, value) for key, value in manifest["sources"].items()
                             if value["format"] == "pdf" and len(value["parts"]) == 1)
        asset = {"id": "exact-edition", "title": "Asset", "format": "pdf", "destination": "BOOKS/source.pdf",
                 "sha256": digest}
        files, coverage = compose_shards([asset, {**asset, "id": "new-edition", "sha256": "f" * 64}], 10_000_000)
        self.assertEqual([item["id"] for item in coverage], ["exact-edition"])
        body = next(value for path, value in files.items() if path.startswith("SEARCH/sources/"))
        self.assertEqual(output_size(body), shard["parts"][0]["bytes"])
        self.assertEqual(sha256(output_bytes(body)).hexdigest(), shard["sha256"])
        self.assertEqual(payload(output_bytes(body), "OWLShardPart")[:2], [digest, 0])
        self.assertEqual(compose_shards([asset], 1_000), ({}, []))

    def test_stems_and_fat32_limit(self):
        self.assertEqual(terms("How to stop BLEEDING"), {"stop", "bleed"})
        self.assertEqual(fat_file_limit("msdos"), FAT_FILE_LIMIT)
        self.assertIsNone(fat_file_limit("exfat"))

    @unittest.skipUnless(importlib.util.find_spec("libzim"), "libzim needed for a real ZIM fixture")
    def test_directory_rows_match_libzim(self):
        from libzim.reader import Archive
        from owl.zim_directory import Directory
        from scripts.build_device_test_kit import Article
        from libzim.writer import Creator
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.zim"
            writer = Creator(path)
            writer.config_indexing(False, "")
            with writer as creator:
                creator.add_item(Article())
                creator.set_mainpath("owl-test")
            with path.open("rb") as f:
                def read(start, count):
                    f.seek(start)
                    return f.read(count)
                directory = Directory(read, path.stat().st_size)
                entries = list(directory)
            fixture = Archive(path).get_entry_by_path("owl-test")
            self.assertIn((fixture.title, fixture.path), {(row.title, row.path) for row in entries})
            self.assertTrue(directory.main_path)
