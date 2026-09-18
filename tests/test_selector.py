"""The browser planner and its copyable commands must describe the real CLI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import tempfile
import unittest

from owl.catalog import CatalogError, capacity_plan, load_catalog, load_profiles, resolve_content
from owl.resources import load_resources
from owl.selector import make_model, render_selector

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src/owl/templates/selector.js"


@unittest.skipUnless(shutil.which("node"), "Node is required for browser planner parity")
class SelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = ROOT / "catalog/library.yaml"
        cls.registry = ROOT / "catalog/resources.yaml"
        cls.profiles = load_profiles(ROOT / "profiles")
        cls.assets = load_catalog(cls.catalog, cls.profiles)
        cls.model = make_model(cls.catalog, ROOT / "profiles", cls.registry)

    def javascript(self, cases, model=None):
        script = r'''
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8'));
const input = JSON.parse(fs.readFileSync(0,'utf8'));
const results = input.cases.map(c => {
  const state = OWLPlanner.preset(input.model,c.profile);
  for (const [id,changes] of Object.entries(c.items || {})) Object.assign(state.items[id],changes);
  if (c.allowIncomplete) state.allowIncomplete=true;
  const report = OWLPlanner.resolve(input.model,state);
  return {state,report,build:OWLPlanner.command(input.model,state,{target:c.target || '/media/SSD/OWL',shell:c.shell || 'posix'}),
    plan:OWLPlanner.command(input.model,state,{target:c.target || '/media/SSD/OWL',shell:c.shell || 'posix',plan:true})};
});
process.stdout.write(JSON.stringify(results));
'''
        completed = subprocess.run([shutil.which("node"), "-e", script, str(ENGINE)],
            input=json.dumps({"model": model or self.model, "cases": cases}), text=True,
            encoding="utf-8", capture_output=True, check=True, timeout=30)
        return json.loads(completed.stdout)

    def compare_to_python(self, result):
        report, state = result["report"], result["state"]
        args = report["selectionArgs"]
        kwargs = {"include": args["include"], "exclude": args["exclude"]}
        if args["editions"]:
            kwargs["editions"] = [f"{identity}={mode}" for identity, mode in args["editions"].items()]
        try:
            assets, unresolved, selection = resolve_content(self.assets, self.profiles[state["profile"]],
                resources_path=self.registry, **kwargs)
        except CatalogError:
            self.assertTrue(report["errors"], result)
            return
        estimate = report["estimates"]
        self.assertEqual(report["selectedAssetIds"], sorted(a["id"] for a in assets))
        known = sum(a["size_bytes"] for a in assets)
        self.assertEqual(estimate["knownBytes"], known)
        content = selection["content_target_bytes"] if selection else known
        readers = selection["readers_budget_bytes"] if selection else 0
        self.assertEqual(estimate["contentTargetBytes"], content)
        self.assertEqual(estimate["readerBytes"], readers)
        expected_incomplete = [row["id"] for row in selection["incomplete_resources"]] if selection else []
        self.assertEqual(sorted(row["id"] for row in report["incomplete"]), sorted(expected_incomplete))
        profile = self.profiles[state["profile"]]
        intended = max(known, content + readers)
        final = intended + profile["search_budget_bytes"] + 16 * 1024**2
        self.assertEqual(estimate["finalBytes"], final)
        self.assertEqual(estimate["peakBytes"], final + 2 * profile["search_budget_bytes"] + profile["reserve_bytes"])
        try:
            plan = capacity_plan(assets, profile, selection)
        except CatalogError:
            self.assertFalse(report["canBuild"])
        else:
            self.assertEqual(estimate["finalBytes"], plan.get("planned_final_bytes", plan["estimated_final_bytes"]))

    def test_all_presets_match_cli_selection_and_storage(self):
        results = self.javascript([{"profile": p["id"]} for p in self.model["profiles"]])
        self.assertEqual(len(results), 5)
        for result in results:
            with self.subTest(profile=result["state"]["profile"]):
                self.compare_to_python(result)
        flash = next(r for r in results if r["state"]["profile"] == "flash-16gb")
        self.assertTrue(flash["build"])
        self.assertEqual(len(flash["report"]["selectedAssetIds"]), 25)
        self.assertEqual(flash["report"]["estimates"]["peakBytes"], 9_591_322_812)
        self.assertTrue(all(not r["build"] for r in results if r["report"]["incomplete"]))

    def test_many_custom_selections_match_python_without_network(self):
        rng = random.Random(402)
        cases = []
        for profile in self.model["profiles"]:
            for _ in range(10):
                changes = {resource["id"]: {"included": bool(rng.randrange(2))}
                           for resource in rng.sample(self.model["resources"], 9)}
                cases.append({"profile": profile["id"], "items": changes, "allowIncomplete":True})
        for result in self.javascript(cases):
            with self.subTest(profile=result["state"]["profile"], args=result["report"]["selectionArgs"]):
                self.compare_to_python(result)

    def test_small_preset_expansion_is_explicit_and_exclusion_reduces_bytes(self):
        results = self.javascript([
            {"profile":"flash-16gb"},
            {"profile":"flash-16gb", "items":{"openstax-core":{"included":False}}},
            {"profile":"flash-16gb", "items":{"openstax-core":{"edition":"published"}}},
        ])
        for result in results:
            self.compare_to_python(result)
        self.assertLess(results[1]["report"]["estimates"]["knownBytes"], results[0]["report"]["estimates"]["knownBytes"])
        self.assertIn("openstax-core", results[2]["report"]["selectionArgs"]["include"])
        self.assertGreater(results[2]["report"]["estimates"]["contentTargetBytes"], 12 * 10**9)
        self.assertFalse(results[2]["build"])

    def test_missing_editions_never_invent_savings_or_emit_a_build(self):
        result = self.javascript([{"profile":"compact-256gb", "items":{"wikipedia-en":{"edition":"direct"}}, "allowIncomplete":True}])[0]
        self.assertFalse(result["build"])
        self.assertTrue(any("no verified direct edition" in message for message in result["report"]["errors"]))
        self.compare_to_python(result)
        row = next(row for row in result["report"]["rows"] if row["id"] == "wikipedia-en")
        self.assertFalse(next(option for option in row["options"] if option["value"] == "direct")["available"])

    def test_partial_build_requires_explicit_choice_and_retains_real_target_budget(self):
        before, after = self.javascript([{"profile":"standard-512gb"}, {"profile":"standard-512gb", "allowIncomplete":True}])
        self.assertFalse(before["build"])
        self.assertIn("--allow-incomplete", after["build"])
        self.assertEqual(before["report"]["estimates"], after["report"]["estimates"])
        self.assertGreater(after["report"]["estimates"]["peakBytes"], 512 * 10**9)
        self.assertLess(after["report"]["estimates"]["actualPeakBytes"], 512 * 10**9)

    def test_registered_editions_use_exact_files_and_recalculate_readers(self):
        from test_resource_editions import EditionTests
        fixture = EditionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        resources = fixture.registry()
        model = {"profiles":[{**fixture.profile, "preset_resource_ids":["collection"], "baseline_asset_ids":[]}],
                 "resources":list(resources.values()), "assets":fixture.assets}
        results = self.javascript([{"profile":"test", "items":{"collection":{"edition":mode}}}
                                   for mode in ("published", "direct", "compact")], model)
        for mode, result in zip(("published", "direct", "compact"), results):
            selected, _, selection = resolve_content(fixture.assets, fixture.profile,
                resources_path=fixture.registry_path, editions=[f"collection={mode}"])
            self.assertEqual(result["report"]["selectedAssetIds"], sorted(a["id"] for a in selected))
            self.assertEqual(result["report"]["estimates"]["contentTargetBytes"], selection["content_target_bytes"])
            self.assertEqual(result["report"]["estimates"]["readerBytes"], selection["readers_budget_bytes"])
        self.assertIn("--edition collection=direct", results[1]["build"])
        self.assertEqual(results[1]["report"]["selectedAssetIds"], ["critical", "direct"])
        self.assertEqual(results[2]["report"]["selectedAssetIds"], ["archive", "critical", "reader"])

    def test_fixed_preset_edition_only_members_are_visible_and_excludable(self):
        from test_resource_editions import EditionTests
        fixture = EditionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.profile.pop("default_resources")
        fixture.assets[1]["profiles"] = ["test"]  # Only the alternate direct file belongs to this preset.
        fixture.registry()
        catalog = fixture.root / "library.yaml"
        catalog.write_text(json.dumps({"schema_version":1, "assets":fixture.assets}), encoding="utf-8")
        profiles = fixture.root / "profiles"
        profiles.mkdir()
        (profiles / "test.yaml").write_text(json.dumps(fixture.profile), encoding="utf-8")
        model = make_model(catalog, profiles, fixture.registry_path)
        self.assertEqual(model["profiles"][0]["preset_resource_ids"], ["collection"])
        default, excluded, compact = self.javascript([{"profile":"test"},
            {"profile":"test", "items":{"collection":{"included":False}}},
            {"profile":"test", "items":{"collection":{"edition":"compact"}}}], model)
        row = next(r for r in default["report"]["rows"] if r["id"] == "collection")
        self.assertTrue(row["included"])
        self.assertEqual((row["edition"], row["assetCount"], row["knownBytes"]), ("preset", 1, 30))
        self.assertEqual(default["report"]["selectedAssetIds"], ["direct"])
        self.assertEqual(excluded["report"]["selectionArgs"]["exclude"], ["collection"])
        selected, _, _ = resolve_content(fixture.assets, fixture.profile, resources_path=fixture.registry_path,
                                          exclude=excluded["report"]["selectionArgs"]["exclude"])
        self.assertEqual(excluded["report"]["selectedAssetIds"], sorted(a["id"] for a in selected))
        self.assertEqual(selected, [])
        compact_args = compact["report"]["selectionArgs"]
        selected, _, selection = resolve_content(fixture.assets, fixture.profile, resources_path=fixture.registry_path,
            include=compact_args["include"], editions=[f"{identity}={mode}" for identity, mode in compact_args["editions"].items()])
        self.assertEqual(compact["report"]["selectedAssetIds"], ["archive", "critical", "reader"])
        self.assertEqual(compact["report"]["selectedAssetIds"], sorted(a["id"] for a in selected))
        self.assertEqual(compact["report"]["estimates"]["contentTargetBytes"], selection["content_target_bytes"])
        self.assertEqual(compact["report"]["estimates"]["readerBytes"], selection["readers_budget_bytes"])

    def test_commands_round_trip_paths_without_shell_expansion(self):
        path = "/media/Pat's SSD/$(touch OWL_BAD);`echo bad`/OWL"
        result = self.javascript([{"profile":"flash-16gb", "target":path}])[0]
        words = shlex.split(result["build"])
        self.assertEqual(words[:3], ["python", "scripts/build_drive.py", path])
        self.assertIn("--navigation-dir", words)
        windows = self.javascript([{"profile":"flash-16gb", "target":"E:\\Pat's SSD\\OWL", "shell":"powershell"}])[0]
        self.assertIn("'E:\\Pat''s SSD\\OWL'", windows["build"])
        for unsafe in ("/media/a\nwhoami", "--plan", "/media/a\x00bad"):
            invalid = self.javascript([{"profile":"flash-16gb", "target":unsafe}])[0]
            self.assertFalse(invalid["build"])
            self.assertFalse(invalid["plan"])

    def test_empty_selection_never_advertises_a_build(self):
        model = deepcopy(self.model)
        changes = {resource["id"]: {"included":False} for resource in model["resources"]}
        result = self.javascript([{"profile":"flash-16gb", "items":changes}])[0]
        self.assertEqual(result["report"]["selectedAssetIds"], [])
        self.assertFalse(result["build"])

    def test_default_coverage_floor_matches_cli_and_customization_can_remove_it(self):
        model = deepcopy(self.model)
        profile = next(p for p in model["profiles"] if p["id"] == "flash-16gb")
        profile["minimum_coverage"] = {"textbooks":100}
        default, customized = self.javascript([{"profile":"flash-16gb"},
            {"profile":"flash-16gb", "items":{"food-preservation":{"included":False}}}], model)
        self.assertFalse(default["build"])
        self.assertTrue(any("requires at least 100" in error for error in default["report"]["errors"]))
        self.assertTrue(customized["build"])

    def test_generated_html_is_self_contained_and_escapes_embedded_metadata(self):
        model = deepcopy(self.model)
        model["resources"][0]["title"] = '</script><script src="https://example.invalid/evil">'
        page = render_selector(model)
        self.assertNotIn(model["resources"][0]["title"], page)
        self.assertNotIn("__OWL_", page)
        self.assertNotRegex(page, r'<script[^>]+src=')
        self.assertNotRegex(page, r'<link[^>]+href=')
        self.assertEqual(page, render_selector(model))

    def test_committed_selector_matches_current_inputs(self):
        self.assertEqual((ROOT / "SELECT.html").read_text(encoding="utf-8"), render_selector(self.model))


if __name__ == "__main__":
    unittest.main()
