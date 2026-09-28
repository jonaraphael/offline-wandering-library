"""Synthetic pinned XML/media fixtures exercise bounded, offline adapters."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from owl.acquisition import corpus, lessons
from owl.safety import sha256_file


class CorpusTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.sources, self.assets = {}, {}
        self.question = {"Id": "10", "PostTypeId": "1", "Title": "Preserve Unicode and tables", "Score": "4", "AnswerCount": "5", "AcceptedAnswerId": "20", "OwnerUserId": "1", "ContentLicense": "CC BY-SA 4.0", "CreationDate": "2009-01-01", "Tags": "<python><unicode>", "Body": '<p>Complete question.</p><table><tr><td>Cell</td></tr></table><math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>'}
        self.posts = [self.question] + [{"Id": str(identity), "PostTypeId": "2", "ParentId": "10", "Score": str(score), "OwnerUserId": "2", "ContentLicense": "CC BY-SA 3.0", "CreationDate": "2014-02-03", "Body": f"<p>Answer {identity} complete instructions.</p>"} for identity, score in [(20, 0), (21, 7), (22, 7), (23, 3), (24, -1)]]
        self.write_xml("posts", self.posts)
        self.write_xml("comments", [{"Id": "30", "PostId": "20", "UserId": "1", "Text": "Correction: this assumes UTF-8 input; check the byte order before decoding.", "CreationDate": "2015-01-01", "ContentLicense": "CC BY-SA 4.0"}, {"Id": "31", "PostId": "10", "UserId": "1", "Text": "Thanks!", "ContentLicense": "CC BY-SA 4.0"}])
        self.write_xml("users", [{"Id": "1", "DisplayName": "Ada"}, {"Id": "2", "DisplayName": "Grace"}])
        self.write_xml("links", [])
        self.output = {"id": "question_10", "title": "Preserve Unicode and tables", "destination": "REFERENCE/PROGRAMMING/10.html", "legacy": False, "generation": {"recipe_id": "stack_fixture", "question_id": 10}}
        self.assets[self.output["id"]] = self.output
        self.recipe = {"id": "stack_fixture", "adapter": "stackexchange", "version": "1", "workspace_bytes": 4 * 1024 * 1024, "source_asset_ids": ["posts", "comments", "users", "links"], "output_asset_ids": ["question_10"], "selection": {"reviewed": True, "input_roles": {key: key for key in self.sources}, "questions": [{"id": 10, "bucket": "durable"}]}}
        self.output_dir = self.root / "out"

    def source(self, identity, data, destination=None):
        path = self.root / identity
        path.write_bytes(data)
        self.sources[identity] = path
        self.assets[identity] = {"id": identity, "size_bytes": len(data), "sha256": sha256_file(path), "destination": destination or f"SOURCE/{identity}"}

    def write_xml(self, identity, rows):
        root = ET.Element(identity)
        for row in rows:
            ET.SubElement(root, "row", row)
        self.source(identity, ET.tostring(root, encoding="utf-8"))

    def render(self):
        return corpus.render(self.recipe, self.sources, self.assets, self.output_dir)

    def test_accepted_zero_two_alternatives_comments_attribution_and_semantics(self):
        result = self.render()
        self.assertEqual(set(result), {"question_10"})
        body = result["question_10"].read_text(encoding="utf-8")
        for value in ("Answer 20", "Answer 21", "Answer 22", "Correction:", "Ada", "Grace", "CC BY-SA 3.0", "2014-02-03", "<table>", "<math>", "<mfrac>"):
            self.assertIn(value, body)
        for value in ("Answer 23", "Answer 24", "Thanks!", corpus.LEGACY_WARNING):
            self.assertNotIn(value, body)

    def test_discovery_is_bounded_deterministic_and_age_is_not_legacy(self):
        old = deepcopy(self.question)
        self.assertEqual(corpus.classify_question(old), "durable")
        old["Tags"] = "<python><python-2.7>"
        self.assertEqual(corpus.classify_question(old, {"durable_ids": [10]}), "legacy")
        another = deepcopy(self.question); another.update(Id="11", Score="5")
        excluded = deepcopy(self.question); excluded.update(Id="12", Tags="<firebase><python>", Score="999")
        self.write_xml("posts", [old, another, excluded])
        first = corpus.discover_questions(self.sources["posts"], limit=1)
        self.assertEqual(first, corpus.discover_questions(self.sources["posts"], limit=1))
        self.assertEqual(first[0]["id"], 11)
        self.assertEqual(first[0]["review_status"], "pending")

    def test_duplicate_canonical_merge_preserves_explicit_legacy_and_links(self):
        self.write_xml("links", [{"Id": "1", "PostId": "11", "RelatedPostId": "10", "LinkTypeId": "3"}])
        self.recipe["selection"]["questions"].append({"id": 11, "bucket": "legacy"})
        self.output["legacy"] = True
        body = self.render()["question_10"].read_text(encoding="utf-8")
        self.assertIn(corpus.LEGACY_WARNING, body)
        self.assertIn("Canonical question for duplicates", body)
        self.assertIn("https://stackoverflow.com/q/11", body)

    def test_version_ambiguity_stays_in_review_queue_and_cache_skips_xml(self):
        rows = []
        for identity, title in [(10, "Python 2.7 filesystem encoding"), (11, "Python 2 and Python 3 encoding migration"), (12, "Old Python runtime encoding"), (13, "Modern Unicode encoding")]:
            row = deepcopy(self.question)
            row.update(Id=str(identity), Title=title)
            rows.append(row)
        self.write_xml("posts", list(reversed(rows)))
        options = {"source_asset": self.assets["posts"], "cache_dir": self.root / "candidate-cache"}
        result = corpus.select_candidates(self.sources["posts"], **options)
        self.assertEqual([(row["id"], row["bucket"]) for row in result["candidates"]], [(10, "legacy"), (13, "durable")])
        self.assertEqual([row["id"] for row in result["review_queue"]], [11, 12])
        self.assertTrue(all(row["reasons"] for row in result["candidates"] + result["review_queue"]))
        with patch.object(corpus, "xml_rows", side_effect=AssertionError("cache should avoid XML parsing")):
            cached = corpus.select_candidates(self.sources["posts"], **options)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(cached["candidates"], result["candidates"])

    def test_declared_allow_deny_tags_and_legacy_id_override(self):
        row = deepcopy(self.question)
        row["Tags"] = "<special-topic>"
        self.assertEqual(corpus.classify_question(row, {"allow_tags": ["special-topic"]}), "durable")
        self.assertIsNone(corpus.classify_question(row, {"allow_tags": ["special-topic"], "deny_tags": ["special-topic"]}))
        self.assertEqual(corpus.classify_question(row, {"durable_ids": [10], "legacy_ids": [10]}), "legacy")

    def test_duplicate_cycle_is_not_silently_dropped(self):
        self.write_xml("links", [{"Id": "1", "PostId": "10", "RelatedPostId": "11", "LinkTypeId": "3"}, {"Id": "2", "PostId": "11", "RelatedPostId": "10", "LinkTypeId": "3"}])
        with self.assertRaisesRegex(corpus.CorpusError, "Cyclic"):
            self.render()

    def test_unselected_duplicate_ambiguity_keeps_all_edges_without_blocking_selection(self):
        self.write_xml('links',[{'Id':str(index),'PostId':'99','RelatedPostId':str(target),'LinkTypeId':'3'}
            for index,target in enumerate((100,101,101),1)])
        self.assertIn('question_10',self.render())
        with closing(sqlite3.connect(self.output_dir/'corpus-work/index.sqlite')) as db:
            self.assertEqual(db.execute('SELECT id,target FROM links ORDER BY id,target').fetchall(),[(99,100),(99,101)])

    def test_selected_duplicate_ambiguity_reports_affected_chain_and_targets(self):
        self.write_xml('links',[{'Id':str(index),'PostId':str(source),'RelatedPostId':str(target),'LinkTypeId':'3'}
            for index,(source,target) in enumerate(((10,99),(99,100),(99,101)),1)])
        with self.assertRaisesRegex(corpus.CorpusError,'Selected question 10.*at 99: 100, 101; review required'):
            self.render()
        self.assertFalse((self.output_dir/self.output['destination']).exists())

    def test_durable_alias_cannot_hide_canonical_legacy_or_ambiguous_versions(self):
        self.recipe['selection']['questions']=[{'id':11,'bucket':'durable'}]
        self.write_xml('links',[{'Id':'1','PostId':'11','RelatedPostId':'10','LinkTypeId':'3'}])
        for title,tags,bucket in [('Python 2.7 Unicode','<python><python-2.7>','legacy'),
                                  ('Python 2 and Python 3 migration','<python>','review')]:
            with self.subTest(bucket=bucket):
                if self.output_dir.exists():shutil.rmtree(self.output_dir)
                self.posts[0].update(Title=title,Tags=tags);self.write_xml('posts',self.posts)
                with self.assertRaisesRegex(corpus.CorpusError,'Canonical question 10.*durable to '+bucket):
                    self.render()
                self.assertFalse((self.output_dir/self.output['destination']).exists())

    def test_canonical_reclassification_uses_explicit_frozen_legacy_rules(self):
        self.recipe['selection']['classification_rules']={'legacy_ids':[10]}
        with self.assertRaisesRegex(corpus.CorpusError,'durable to legacy'):
            self.render()

    def test_whole_source_hash_checks_trailing_bytes(self):
        with self.sources["posts"].open("ab") as handle:
            handle.write(b"changed after the XML body")
        self.assets["posts"]["size_bytes"] = self.sources["posts"].stat().st_size
        with self.assertRaisesRegex(corpus.CorpusError, "SHA-256 mismatch"):
            self.render()

    def test_missing_illustration_blocks_until_pinned_and_preserves_caption(self):
        self.posts[0]["Body"] += '<figure><img src="https://images.invalid/diagram.png" alt="Diagram"><figcaption>Original figure caption</figcaption></figure>'
        self.write_xml("posts", self.posts)
        with self.assertRaisesRegex(corpus.CorpusError, "Unpinned illustration"):
            self.render()
        shutil.rmtree(self.output_dir)
        self.source("diagram", b"synthetic png", "REFERENCE/PROGRAMMING/diagram.png")
        self.recipe["source_asset_ids"].append("diagram")
        self.recipe["selection"]["dependencies"] = {"https://images.invalid/diagram.png": "diagram"}
        body = self.render()["question_10"].read_text(encoding="utf-8")
        self.assertIn('src="diagram.png"', body)
        self.assertIn("Original figure caption", body)

    def test_completed_source_checkpoints_skip_xml_rereads(self):
        first = self.render()["question_10"].read_bytes()
        with patch.object(corpus, "xml_rows", side_effect=AssertionError("completed source reread")):
            second = self.render()["question_10"].read_bytes()
        self.assertEqual(first, second)
        self.assertLess(sum(path.stat().st_size for path in (self.output_dir / "corpus-work").iterdir()), self.recipe["workspace_bytes"])

    def test_interrupted_input_rolls_back_and_reuses_completed_sources(self):
        original = corpus.xml_rows
        def interrupted(path):
            for index, row in enumerate(original(path)):
                yield row
                if path == self.sources["posts"] and index == 1:
                    raise KeyboardInterrupt()
        with patch.object(corpus, "xml_rows", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.render()
        with closing(sqlite3.connect(self.output_dir / "corpus-work/index.sqlite")) as db:
            self.assertEqual(db.execute("SELECT role FROM checkpoints").fetchall(), [("links",)])
            self.assertEqual(db.execute("SELECT count(*) FROM posts").fetchone()[0], 0)
        def no_links(path):
            self.assertNotEqual(path, self.sources["links"])
            yield from original(path)
        with patch.object(corpus, "xml_rows", side_effect=no_links):
            self.assertIn("question_10", self.render())

    def test_missing_license_and_nonpositive_answers_block_completion(self):
        self.posts[1].pop("ContentLicense")
        self.write_xml("posts", self.posts)
        with self.assertRaisesRegex(corpus.CorpusError, "license"):
            self.render()
        shutil.rmtree(self.output_dir)
        self.write_xml("posts", [self.question])
        with self.assertRaisesRegex(corpus.CorpusError, "qualifying answer"):
            self.render()

    def test_output_classification_and_review_are_required(self):
        self.output["legacy"] = True
        with self.assertRaisesRegex(corpus.CorpusError, "legacy metadata"):
            self.render()
        self.recipe["selection"]["reviewed"] = False
        with self.assertRaisesRegex(corpus.CorpusError, "recorded review"):
            self.render()

    def test_workspace_capacity_stops_ingestion(self):
        self.posts[0]["Body"] = "x" * 300000
        self.write_xml("posts", self.posts)
        self.recipe["workspace_bytes"] = 262144
        with self.assertRaisesRegex(corpus.CorpusError, "workspace"):
            self.render()

    def test_short_warning_comments_are_kept_without_trivial_thanks(self):
        self.assertTrue(corpus.substantive_comment("Do not use this in Python 3!"))
        self.assertTrue(corpus.substantive_comment("This API is deprecated."))
        self.assertFalse(corpus.substantive_comment("Thanks!"))
        self.assertFalse(corpus.substantive_comment("+1"))

    def test_changed_recipe_cannot_reuse_previous_source_index(self):
        self.render()
        self.recipe["selection"]["questions"][0]["bucket"] = "legacy"
        self.output["legacy"] = True
        with self.assertRaisesRegex(corpus.CorpusError, "checkpoint does not match"):
            self.render()


class LessonsTests(unittest.TestCase):
    source = CorpusTests.source

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.sources, self.assets = {}, {}
        self.source("video", b"synthetic large media" * 100000, "EDUCATION/media.mp4")
        self.source("captions", b"WEBVTT\n\n00:00.000 --> 00:02.000\nComplete caption text.\n", "EDUCATION/captions.vtt")
        self.source("figure", b"synthetic image", "EDUCATION/figure.png")
        self.lesson = {"id": "fractions", "course_id": "arithmetic", "title": "Fractions", "source_url": "https://publisher.invalid/lesson/fractions", "license": "CC BY-NC-SA 4.0", "attribution": "Original lesson authors", "language": "en", "kind": "video", "content_html": '<p>Full lesson introduction.</p><img src="figure" alt="Fractions"><table><tr><td>One half</td></tr></table>', "media": [{"asset_id": "video", "mime_type": "video/mp4", "captions": [{"asset_id": "captions", "language": "en", "label": "English"}]}]}
        self.lesson_output = {"id": "fractions_html", "title": "Fractions", "destination": "EDUCATION/fractions.html", "generation": {"recipe_id": "lessons_fixture", "lesson_id": "fractions"}}
        self.assets["fractions_html"] = self.lesson_output
        self.lesson_recipe = {"id": "lessons_fixture", "adapter": "lessons", "version": "1", "source_asset_ids": ["video", "captions", "figure"], "output_asset_ids": ["fractions_html"], "selection": {"reviewed": True, "dependencies": {"figure": "figure"}, "lessons": [self.lesson]}}

    def test_media_is_linked_without_full_memory_read_or_duplicate_copy(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole file read")):
            outputs = lessons.render(self.lesson_recipe, self.sources, self.assets, self.root / "lessons")
        body = outputs["fractions_html"].read_text(encoding="utf-8")
        for value in ('<video controls', 'src="media.mp4"', 'src="data:text/vtt;base64,', 'href="captions.vtt"', 'src="figure.png"', "Complete caption text.", "Original lesson authors", "<table>"):
            self.assertIn(value, body)
        self.assertEqual(list((self.root / "lessons").rglob("*.mp4")), [])

    def test_unsupported_essential_exercise_is_an_explicit_gap(self):
        self.lesson["kind"] = "perseus-exercise"
        self.assertTrue(any("unsupported essential" in gap for gap in lessons.lesson_gaps(self.lesson_recipe["selection"])))
        with self.assertRaisesRegex(corpus.CorpusError, "unsupported essential"):
            lessons.render(self.lesson_recipe, self.sources, self.assets, self.root / "lessons")

    def test_missing_or_invalid_captions_block(self):
        self.source("captions", b"not a complete VTT file", "EDUCATION/captions.vtt")
        with self.assertRaisesRegex(corpus.CorpusError, "WebVTT"):
            lessons.render(self.lesson_recipe, self.sources, self.assets, self.root / "lessons")
        self.lesson["media"][0]["captions"] = []
        self.assertTrue(any("captions" in gap for gap in lessons.lesson_gaps(self.lesson_recipe["selection"])))


@unittest.skipUnless(shutil.which("node"), "Node is required for the portable QA CLI")
class PhetTests(unittest.TestCase):
    def test_validate_only_reports_browser_and_physical_testing_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "simulation.html"
            source.write_text("<!doctype html><title>Synthetic fixture</title>")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"assets": [{"id": "phet_fixture", "destination": source.name, "sha256": sha256_file(source)}]}))
            report = root / "report.json"
            script = Path(__file__).resolve().parents[1] / "scripts/check_phet.cjs"
            command = ["node", str(script), "--manifest", str(manifest), "--root", str(root), "--output", str(report), "--validate-only"]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["browser_qa"], "pending")
            self.assertEqual(result["physical_device_certification"], "pending")
            self.assertNotIn("success", result)
            source.write_text("changed")
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn("checksum changed", run.stderr)


if __name__ == "__main__":
    unittest.main()
