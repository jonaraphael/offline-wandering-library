"""Acquisition automation uses fixtures; it must never need library downloads."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import yaml

from owl.acquisition.cli import main
from owl.acquisition.metadata import Fetcher
from owl.acquisition.model import AcquisitionError, validate_generation, validate_recipes


def asset(identity, data=b"source"):
    return dict(id=identity, title=identity, category="reference", format="txt",
                source_url=f"https://example.org/{identity}.txt", destination=f"BOOKS/{identity}.txt",
                version="1", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                license="CC0-1.0", redistributable=True, required=True, profiles=[])


def recipe(**changes):
    return dict(id="recipe", resource_id="core", adapter="html_snapshot", version="1",
                source_asset_ids=["source"], output_asset_ids=["output"], selection={},
                review={"status": "approved", "evidence": ["reviewed fixture"]}, blockers=[], **changes)


class RecipeTests(unittest.TestCase):
    def test_pending_empty_recipe_is_valid_but_cannot_generate(self):
        row = recipe()
        row.update(source_asset_ids=[], output_asset_ids=[], review={"status": "pending", "evidence": []}, blockers=["Needs source"])
        self.assertIn("recipe", validate_recipes([row]))
        output = {**asset("output"), "generation": {"recipe_id": "recipe"}}
        with self.assertRaises(AcquisitionError):
            validate_generation([output], {"recipe": row})

    def test_generated_output_must_be_bound_to_approved_recipe(self):
        source = asset("source")
        output = {**asset("output"), "generation": {"recipe_id": "recipe", "question_id": 42}}
        validate_generation([source, output], {"recipe": recipe()})
        output["generation"]["recipe_id"] = "unknown"
        with self.assertRaises(AcquisitionError):
            validate_generation([source, output], {"recipe": recipe()})

    def test_approved_needs_evidence_no_blockers_and_pinned_source(self):
        for field, value in (("review", {"status": "approved", "evidence": []}), ("blockers", ["Review missing"])):
            row = recipe()
            row[field] = value
            with self.assertRaises(AcquisitionError):
                validate_recipes([row])
        with self.assertRaises(AcquisitionError):
            validate_recipes([recipe()], assets=[])

    def test_generation_archive_conflicts_and_recipe_cycles_are_rejected(self):
        output = {**asset("output"), "generation": {"recipe_id": "recipe"}, "archive_member": {"source_asset_id": "source"}}
        with self.assertRaises(AcquisitionError):
            validate_generation([asset("source"), output], [recipe()])
        first = recipe()
        first["source_asset_ids"] = ["second"]
        second = recipe()
        second.update(id="second_recipe", source_asset_ids=["output"], output_asset_ids=["second"])
        outputs = [{**asset("output"), "generation": {"recipe_id": "recipe"}},
                   {**asset("second"), "generation": {"recipe_id": "second_recipe"}}]
        with self.assertRaisesRegex(AcquisitionError, "Cycle"):
            validate_generation(outputs, [first, second])
        first["workspace_bytes"] = True
        with self.assertRaises(AcquisitionError):
            validate_recipes([first])

    def test_recipe_workspace_identity_is_bound_to_source_pins(self):
        from owl.acquisition.runtime import recipe_digest
        source = asset("source")
        original = recipe_digest(recipe(), [source])
        for field, value in (("sha256", "f" * 64), ("size_bytes", 99), ("destination", "BOOKS/changed.txt"),
                             ("license", "Different terms")):
            self.assertNotEqual(original, recipe_digest(recipe(), [{**source, field: value}]))
        self.assertEqual(original, recipe_digest(recipe(), {"source": source}))

    def test_link_dependencies_are_pinned_selected_ordered_and_source_bound(self):
        from owl.acquisition.runtime import order_assets, recipe_digest, selected_recipes
        row = recipe()
        row["dependency_asset_ids"] = ["linked"]
        source, linked = asset("source"), asset("linked")
        output = {**asset("output"), "generation": {"recipe_id": "recipe"}}
        validate_generation([source, linked, output], [row])
        with self.assertRaises(AcquisitionError):
            validate_generation([source, output], [row])
        with self.assertRaises(ValueError):
            selected_recipes([source, output], {"recipe": row})
        ordered = order_assets([output, source, linked], {"recipe": row})
        self.assertEqual([asset["id"] for asset in ordered], ["source", "linked", "output"])
        self.assertNotEqual(recipe_digest(row, [source, linked]),
                            recipe_digest(row, [source, {**linked, "sha256": "f" * 64}]))


class Response(io.BytesIO):
    status = 200

    def __init__(self, body, url="https://example.org/index.json", mime="application/json"):
        super().__init__(body)
        self.url = url
        self.headers = {"Content-Type": mime, "Content-Length": str(len(body))}

    def geturl(self):
        return self.url


class MetadataTests(unittest.TestCase):
    def test_permanent_metadata_failure_is_cached_without_reading_body(self):
        with tempfile.TemporaryDirectory() as directory:
            def missing(*args, **kwargs):
                raise HTTPError("https://example.org/index.json", 404, "Missing", {}, None)
            cache = Path(directory).resolve()
            with self.assertRaises(AcquisitionError):
                Fetcher(cache, opener=missing).fetch("https://example.org/index.json")
            with self.assertRaisesRegex(AcquisitionError, "Cached HTTP 404"):
                Fetcher(cache, opener=lambda *a, **k: self.fail("Do not repeat known failure")).fetch("https://example.org/index.json")
            self.assertFalse(list(cache.glob("*.bin")))

    def test_cached_rerun_verifies_hash_without_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory).resolve()
            fetcher = Fetcher(cache, opener=lambda *a, **k: Response(b'{"files":[]}'))
            expected = fetcher.fetch("https://example.org/index.json")
            offline = Fetcher(cache, offline=True, opener=lambda *a, **k: self.fail("No request expected"))
            self.assertEqual(offline.fetch("https://example.org/index.json"), expected)
            next((cache / "objects").glob("*.bin")).write_bytes(b"changed")
            with self.assertRaises(AcquisitionError):
                offline.fetch("https://example.org/index.json")

    def test_refresh_preserves_previous_metadata_and_latest_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory).resolve()
            url = "https://example.org/index.json"
            Fetcher(cache, opener=lambda *a, **k: Response(b"first")).fetch(url)
            Fetcher(cache, refresh=True, opener=lambda *a, **k: Response(b"second")).fetch(url)
            self.assertEqual(len(list((cache / "objects").glob("*.bin"))), 2)
            def missing(*args, **kwargs):
                raise HTTPError(url, 404, "Missing", {}, None)
            with self.assertRaises(AcquisitionError):
                Fetcher(cache, refresh=True, opener=missing).fetch(url)
            with self.assertRaisesRegex(AcquisitionError, "Cached HTTP 404"):
                Fetcher(cache, offline=True).fetch(url)

    def test_bodies_bounds_and_redirects_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for url in ("https://example.org/book.pdf", "http://example.org/index.json"):
                with self.assertRaises(AcquisitionError):
                    Fetcher(Path(directory).resolve(), opener=lambda *a, **k: self.fail("Must reject before network")).fetch(url)
            for response in (Response(b"x" * 11), Response(b"%PDF-body"), Response(b"data", mime="application/pdf"),
                             Response(b"x", url="http://example.org/index.json")):
                with self.subTest(response=response), self.assertRaises(AcquisitionError):
                    Fetcher(Path(directory).resolve(), opener=lambda *a, **k: response).fetch("https://example.org/index.json", max_bytes=10)


class CommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source = asset("source")
        self.other = asset("other", b"alternate")
        self.catalog = self.root / "library.yaml"
        self.resources = self.root / "resources.yaml"
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.write(self.catalog, {"schema_version": 1, "assets": [self.source, self.other]})
        self.write(self.resources, {"schema_version": 1, "resources": [dict(id="core", title="Core", status="partial",
            reason="Published scope unfinished", target_bytes=500, asset_ids=["source"],
            editions={"direct": dict(status="ready", reason="Reviewed direct scope", target_bytes=9, asset_ids=["other"])})]})
        self.write(self.profiles / "test.yaml", dict(id="test", capacity_bytes=100000000, reserve_bytes=0,
            search_budget_bytes=10000, default_resources=["core"], default_editions={"core": "direct"},
            content_target_min_bytes=100, content_target_max_bytes=1000))
        self.recipes = self.root / "recipes.yaml"
        self.write(self.recipes, {"schema_version": 1, "recipes": []})

    def write(self, path, value):
        path.write_text(yaml.safe_dump(value), encoding="utf-8")

    def run_cli(self, command, *extra, code=0):
        out, err = io.StringIO(), io.StringIO()
        argv = [command, "--catalog", str(self.catalog), "--resources", str(self.resources),
                "--profiles-dir", str(self.profiles), "--recipes", str(self.recipes),
                "--cache-dir", str(self.root / "cache"), *map(str, extra)]
        with redirect_stdout(out), redirect_stderr(err):
            result = main(argv)
        self.assertEqual(result, code, err.getvalue())
        if code:
            return json.loads(err.getvalue())
        self.assertLessEqual(len(out.getvalue().encode()), 2048)
        summary = json.loads(out.getvalue())
        return summary, json.loads(Path(summary["detail"]).read_text())

    def test_audit_uses_actual_default_edition_and_content_floor(self):
        _, detail = self.run_cli("audit")
        profile = detail["profiles"][0]
        self.assertEqual(profile["effective_editions"], {"core": "direct"})
        self.assertEqual(profile["incomplete_resources"], [])
        self.assertEqual(profile["pinned_bytes"], 9)
        self.assertEqual(profile["target_shortfall_bytes"], 91)
        self.assertFalse(profile["complete"])
        self.assertEqual(detail["gaps"], [])

    def test_audit_omits_optional_and_broad_scope_until_explicitly_requested(self):
        resources = yaml.safe_load(self.resources.read_text())
        resources["resources"].append(dict(id="optional", title="Optional scope", status="partial",
            reason="Optional broader collection", target_bytes=50, asset_ids=["source"]))
        self.write(self.resources, resources)
        _, detail = self.run_cli("audit")
        self.assertEqual(detail["gaps"], [])
        _, detail = self.run_cli("audit", "--resource", "core")
        self.assertEqual([row["resource_id"] for row in detail["gaps"]], ["core"])
        _, detail = self.run_cli("audit", "--resource", "optional")
        self.assertEqual([row["resource_id"] for row in detail["gaps"]], ["optional"])

    def test_inspect_uses_local_hash_and_reports_mismatch(self):
        local = self.root / "local"
        (local / "BOOKS").mkdir(parents=True)
        (local / "BOOKS/source.txt").write_bytes(b"changed")
        _, detail = self.run_cli("inspect-local", "--local-root", local, "--resource", "core")
        self.assertEqual(detail["results"][0]["status"], "mismatch")

    def test_stage_rejects_false_readiness_and_existing_output(self):
        fragment = self.root / "fragment.yaml"
        self.write(fragment, {"schema_version": 1, "assets": [], "resource_updates": [{"id": "core", "status": "ready"}]})
        candidate = self.root / "candidate"
        error = self.run_cli("stage", "--fragment", fragment, "--output", candidate, code=2)
        self.assertIn("review evidence", error["error"])
        self.assertFalse(candidate.exists())

    def test_stage_new_bundle_preserves_source_and_checks_capacity(self):
        before = self.catalog.read_bytes()
        fragment = self.root / "fragment.yaml"
        self.write(fragment, {"schema_version": 1, "assets": [asset("addition")], "resource_updates": [
            {"id": "core", "asset_ids": ["source", "addition"], "status": "partial", "reason": "Still needs review"}]})
        self.write(self.profiles / "demo.yaml", dict(id="demo", capacity_bytes=100000000, reserve_bytes=0,
            search_budget_bytes=10000, minimum_coverage={"textbooks": 1}))
        candidate = self.root / "candidate"
        summary, _ = self.run_cli("stage", "--fragment", fragment, "--output", candidate)
        self.assertEqual(summary["added_assets"], 1)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertTrue((candidate / "library.yaml").is_file())
        self.run_cli("stage", "--fragment", fragment, "--output", candidate, code=2)

    def test_stage_rejects_conflicting_pins_and_peak_overflow(self):
        fragment = self.root / "fragment.yaml"
        self.write(fragment, {"schema_version": 1, "assets": [{**self.source, "sha256": "0" * 64}]})
        self.run_cli("stage", "--fragment", fragment, "--output", self.root / "candidate", code=2)
        self.write(fragment, {"schema_version": 1, "assets": [{**asset("large"), "size_bytes": 100000000}],
            "resource_updates": [{"id": "core", "editions": {"direct": dict(status="partial", reason="Still reviewing",
                target_bytes=100000000, asset_ids=["large"])}}]})
        error = self.run_cli("stage", "--fragment", fragment, "--output", self.root / "candidate", code=2)
        self.assertIn("capacity", error["error"])

    def test_approved_subset_recipe_does_not_close_parent_scope(self):
        fragment = self.root / "fragment.yaml"
        output = {**asset("output"), "generation": {"recipe_id": "recipe"}}
        self.write(fragment, {"schema_version": 1, "assets": [output], "acquisition_recipes": [recipe()],
            "resource_updates": [{"id": "core", "asset_ids": ["source", "output"], "status": "ready"}]})
        error = self.run_cli("stage", "--fragment", fragment, "--output", self.root / "candidate", code=2)
        self.assertIn("review evidence", error["error"])

    def test_stage_navigation_assignment_is_validated_and_written(self):
        navigation = self.root / "navigation"
        navigation.mkdir()
        self.write(navigation / "topics.yaml", {"schema_version": 1, "topics": [dict(id="reading", title="Reading", description="Books")],
            "entrances": {"subjects": ["reading"], "tasks": [], "learn": []}})
        self.write(navigation / "assignments.yaml", {"schema_version": 1, "assignments": []})
        fragment = self.root / "fragment.yaml"
        assignment = {"topic_id": "reading", "asset_id": "addition"}
        self.write(fragment, {"schema_version": 1, "assets": [asset("addition")], "resource_updates": [
            {"id": "core", "asset_ids": ["source", "addition"]}], "navigation_assignments": [assignment]})
        self.run_cli("stage", "--fragment", fragment, "--output", self.root / "candidate")
        saved = yaml.safe_load((self.root / "candidate/navigation/assignments.yaml").read_text())
        self.assertEqual(saved["assignments"], [assignment])

    def test_discover_is_filtered_and_never_downloads_local_bodies(self):
        row = recipe()
        row.update(review={"status": "pending", "evidence": []}, source_asset_ids=[], output_asset_ids=[], blockers=["Unreviewed"])
        self.write(self.recipes, {"schema_version": 1, "recipes": [row]})
        provider = type("Provider", (), {"discover": staticmethod(lambda recipe, fetcher: {"candidates": [], "blockers": ["Unreviewed"]})})
        with patch("owl.acquisition.cli.importlib.import_module", return_value=provider):
            _, detail = self.run_cli("discover", "--offline", "--resource", "core", "--profile", "test")
        self.assertEqual(detail["results"][0]["resource_id"], "core")

    def test_report_merges_matching_history_and_ignores_changed_recipes(self):
        row = recipe()
        row.update(review={"status": "pending", "evidence": []}, source_asset_ids=[], output_asset_ids=[], blockers=["Needs review"])
        self.write(self.recipes, {"schema_version": 1, "recipes": [row]})
        provider = type("Provider", (), {"discover": staticmethod(lambda recipe, fetcher: {"candidates": [], "blockers": ["Metadata missing"]})})
        with patch("owl.acquisition.cli.importlib.import_module", return_value=provider):
            self.run_cli("discover", "--offline")
        summary, detail = self.run_cli("report")
        self.assertEqual(summary["counts"], {"blocked": 1})
        self.assertEqual(detail["results"][0]["blockers"], ["Metadata missing"])
        row["version"] = "2"
        self.write(self.recipes, {"schema_version": 1, "recipes": [row]})
        _, detail = self.run_cli("report")
        self.assertEqual(detail["results"], [])

    def test_only_changed_suppresses_repeated_status_but_preserves_detail(self):
        first, _ = self.run_cli("audit", "--only-changed")
        second, _ = self.run_cli("audit", "--only-changed")
        self.assertNotIn("status", first)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(first["detail"], second["detail"])

    def test_prepare_local_pins_original_and_rejects_recorded_mismatch(self):
        source = self.root / "original.txt"
        source.write_bytes(b"reviewed publisher original")
        manifest = self.root / "local.yaml"
        self.write(manifest, {"addition": "original.txt"})
        template = self.root / "template.yaml"
        original = {**asset("addition"), "size_bytes": None, "sha256": None}
        self.write(template, {"schema_version": 1, "assets": [original], "resource_updates": [
            {"id": "core", "add_asset_ids": ["addition"]}]})
        prepared = self.root / "prepared.yaml"
        self.run_cli("prepare-local", "--fragment", template, "--local-manifest", manifest, "--output", prepared)
        pinned = yaml.safe_load(prepared.read_text())["assets"][0]
        self.assertEqual(pinned["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.run_cli("stage", "--fragment", prepared, "--output", self.root / "candidate")
        staged = yaml.safe_load((self.root / "candidate/resources.yaml").read_text())
        self.assertEqual(staged["resources"][0]["asset_ids"], ["source", "addition"])
        source.write_bytes(b"changed")
        error = self.run_cli("prepare-local", "--fragment", prepared, "--local-manifest", manifest,
            "--output", self.root / "second.yaml", code=2)
        self.assertIn("disagrees", error["error"])

    def test_filtered_stage_keeps_selected_edition_assets_only(self):
        fragment = self.root / "fragment.yaml"
        self.write(fragment, {"schema_version": 1, "assets": [asset("edition_output"), asset("unselected")],
            "resource_updates": [{"id": "core", "editions": {"direct": dict(asset_ids=["edition_output"],
                target_bytes=6, status="partial", reason="Awaiting complete review")}}]})
        self.run_cli("stage", "--fragment", fragment, "--output", self.root / "candidate", "--resource", "core")
        staged = yaml.safe_load((self.root / "candidate/library.yaml").read_text())
        self.assertIn("edition_output", {row["id"] for row in staged["assets"]})
        self.assertNotIn("unselected", {row["id"] for row in staged["assets"]})


if __name__ == "__main__":
    unittest.main()
