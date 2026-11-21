"""Verify selected sources, bounded local scripts, and real directory locations."""
from __future__ import annotations

from base64 import b64decode
from gzip import decompress, open as gzip_open
from hashlib import sha256
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from owl.filesystem import FAT_FILE_LIMIT, fat_file_limit
from owl.search_model import Potion
from owl.search_shards import (MODEL_FILE, SEARCH_ROOT, Record, compose_shards, load_manifest,
                               encode, info, output_bytes, output_size, packed_part, part_path, payload, terms)

from scripts.build_search_shards import Article, html_records, prioritized_leads


class SourceShardTests(unittest.TestCase):
    def test_selection_is_bound_to_the_source_digest(self):
        manifest = load_manifest()
        digest, shard = next((key, value) for key, value in manifest["sources"].items()
                             if value["format"] == "pdf" and len(value["parts"]) == 1)
        asset = {"id": "exact-edition", "title": "Asset", "format": "pdf", "destination": "BOOKS/source.pdf",
                 "sha256": digest, "critical": True, "category": "medical"}
        files, coverage = compose_shards([asset, {**asset, "id": "new-edition", "sha256": "f" * 64}], 10_000_000)
        self.assertEqual([item["id"] for item in coverage], ["exact-edition"])
        selected, = payload(files["SEARCH/shards.js"], "OWLShardSelection")["sources"]
        self.assertTrue(selected["critical"])
        self.assertEqual(selected["category"], "medical")
        self.assertFalse(selected["discussion"])
        body = next(value for path, value in files.items() if path.startswith("SEARCH/sources/"))
        self.assertEqual(output_size(body), shard["parts"][0]["bytes"])
        self.assertEqual(sha256(output_bytes(body)).hexdigest(), shard["sha256"])
        self.assertEqual(payload(output_bytes(body), "OWLShardPart")[:2], [digest, 0])
        self.assertEqual(compose_shards([asset], 1_000), ({}, []))

    def test_two_source_digests_can_reference_one_verified_title_pool(self):
        model = Potion(payload((SEARCH_ROOT / MODEL_FILE).read_bytes(), "OWLShardModel"))
        pool = "a" * 64
        digests = ["b" * 64, "c" * 64]
        data, vectors, bloom, _ = packed_part(pool, 0, [Record("A title", "A_title")], model, title_paths=True)
        pool_pin = {**info(data), "records": 1, "vectors": vectors, "bloom": bloom,
                    "passages": 0, "lead_vectors": 0}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / part_path(pool, 0)
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            manifest = load_manifest()
            for name in (MODEL_FILE, "model-license.txt"):
                (folder / name).write_bytes((SEARCH_ROOT / name).read_bytes())
            manifest["sources"] = {digest: {"shared": [pool], "records": 1, "sha256": info(data)["sha256"]}
                                   for digest in digests}
            manifest["shared"] = {pool: {"parts": [pool_pin]}}
            (folder / "manifest.json").write_bytes(encode(manifest))
            assets = [{"id": f"source-{index}", "sha256": digest, "destination": f"ZIM/{index}.zim",
                       "title": "Archive", "format": "zim"} for index, digest in enumerate(digests)]
            files, _ = compose_shards(assets, 5_000_000, folder)
        self.assertEqual(sum(path.startswith("SEARCH/sources/") for path in files), 1)
        selection = payload(files["SEARCH/shards.js"], "OWLShardSelection")
        self.assertEqual([source["sha256"] for source in selection["sources"]], digests)
        self.assertTrue(all(source["parts"][0]["pool"] == pool for source in selection["sources"]))

    def test_body_vector_and_postings_survive_snippet_redaction(self):
        model = Potion(payload((SEARCH_ROOT / MODEL_FILE).read_bytes(), "OWLShardModel"))
        title = "Page 14"
        body = "The birch bark kept the kindling dry."
        data, vectors, bloom, passages = packed_part("a" * 64, 0, [
            Record(title, 14, lead=body, body=body, show_lead=False, accepted_answer=True),
            Record("Fallen birch tree", "Fallen_birch_tree"),
        ], model, title_paths=True)
        _, _, encoded = payload(data, "OWLShardPart")
        chunk = json.loads(decompress(b64decode(encoded)))
        self.assertEqual((vectors, passages), (2, 1))
        self.assertNotIn(body, json.dumps(chunk))
        self.assertEqual(chunk["records"][0][2], "")
        self.assertEqual(chunk["records"][0][6], 1)
        self.assertEqual(len(chunk["records"][1]), 6)
        self.assertIn("kindl", chunk["postings"])
        self.assertNotEqual(chunk["records"][0][3], model.encode(title))
        self.assertEqual(len(b64decode(chunk["records"][1][3])), 4)
        self.assertIsNone(chunk["records"][1][0])
        self.assertNotIn("fallen", chunk["postings"])
        self.assertLess(len(b64decode(bloom)), 8192)

    def test_html_section_anchors_and_accepted_answer(self):
        html = """<h1>Repair guide</h1><p>Introduction</p>
        <section id="bearing"><h2>Check the bearing</h2>
        <p>Inspect the race</p><script>Ignore this text</script></section>"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "guide.html"
            path.write_text(html)
            _, section = list(html_records(path, {"title": "Guide", "redistributable": False}))
        self.assertEqual((section.title, section.locator, section.body), ("Check the bearing", "bearing", "Inspect the race"))
        self.assertFalse(section.show_lead)
        article = Article()
        article.feed('<p>Question</p><div class="answer accepted-answer"><p>Accepted <b>answer</b></p></div>')
        self.assertEqual(" ".join(article.accepted), "Accepted answer")

    def test_archive_lead_limit_uses_direct_redirect_count(self):
        rows = [
            ["A", "A", "text/html", False, 10, None],
            ["B", "B", "text/html", False, 20, None],
            ["Alias B", "Alias_B", "redirect", True, 30, 20],
            ["Alias A", "Alias_A", "redirect", True, 40, 10],
            ["Another B", "Another_B", "redirect", True, 50, 20],
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rows.jsonl.gz"
            with gzip_open(path, "wt", encoding="utf-8") as file:
                for row in rows:
                    file.write(json.dumps(row) + "\n")
            self.assertEqual(prioritized_leads(path, 1), {"B"})

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
