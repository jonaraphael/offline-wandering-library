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
import yaml

from owl.catalog import CatalogError, capacity_plan, is_document, load_catalog, load_profiles, resolve_content
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
        from owl.content_policy import load_policy
        model = {**(model or self.model), "direct_reading_formats":load_policy()["direct_reading_formats"]}
        script = r'''
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8'));
const input = JSON.parse(fs.readFileSync(0,'utf8'));
const results = input.cases.map(c => {
  const state = OWLPlanner.preset(input.model,c.profile);
  for (const [id,changes] of Object.entries(c.items || {})) Object.assign(state.items[id],changes);
  if (c.allowIncomplete) state.allowIncomplete=true;
  Object.assign(state, c.indexStorage || {});
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

    def test_build_only_inputs_count_peak_and_downloads_but_not_content(self):
        from test_acquisition_build_inputs import BuildInputTests
        fixture = BuildInputTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        registry = fixture.root / 'resources.yaml'
        registry.write_text(yaml.safe_dump({'schema_version':1,'resources':[{
            'id':'reference','title':'Reference','status':'ready','target_bytes':fixture.output['size_bytes'],
            'asset_ids':['guide']}]}))
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            make_model(fixture.catalog, fixture.profiles, registry, allow_local=True)

    def test_above_maximum_default_preset_cannot_be_complete(self):
        model = deepcopy(self.model)
        profile = next(p for p in model['profiles'] if p['id']=='flash-16gb')
        profile['content_target_min_bytes'] = 1
        profile['content_target_max_bytes'] = 2
        result = self.javascript([{'profile':'flash-16gb'}],model=model)[0]['report']
        self.assertTrue(result['coverage']['presetAboveTarget'])
        self.assertFalse(result['canBuild'])

    def test_duplicate_zim_entries_use_extracted_source_pins(self):
        from test_acquisition_build_inputs import BuildInputTests
        fixture=BuildInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.sevenzip_recipe()
        recipes=[];outputs=[]
        for index in range(2):
            recipe=deepcopy(fixture.recipe)
            source_id=f'virtual-zim-{index}'
            output_id=f'direct-{index}'
            recipe.update(id=f'direct-recipe-{index}',adapter='zim_direct',source_asset_ids=[source_id],output_asset_ids=[output_id])
            recipe['build_input_extractions'][0]['members']=[{
                **recipe['build_input_extractions'][0]['members'][0],'id':source_id,'path':f'copy-{index}.zim'}]
            destination=f'REFERENCE/direct-{index}.html'
            recipe['selection']={'source_asset_id':source_id,'entries':['A/SameWork'],
                                 'output_paths':{output_id:destination}}
            recipes.append(recipe)
            outputs.append({**fixture.output,'id':output_id,'destination':destination,
                            'generation':{'recipe_id':recipe['id']}})
        fixture.catalog.write_text(yaml.safe_dump({'schema_version':1,'assets':outputs,'acquisition_recipes':recipes}))
        registry=fixture.root/'resources.yaml'
        registry.write_text(yaml.safe_dump({'schema_version':1,'resources':[{
            'id':'reference','title':'Direct works','status':'ready','target_bytes':sum(a['size_bytes'] for a in outputs),
            'asset_ids':[a['id'] for a in outputs]}]}))
        with self.assertRaisesRegex(CatalogError, 'Content policy'):
            make_model(fixture.catalog,fixture.profiles,registry,allow_local=True)

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
        generation_work = {a['generation']['recipe_id']: a.get('generation_workspace_bytes', 0)
                           for a in assets if 'generation' in a}
        acquisition = sum(generation_work.values()) + 65536 * len(generation_work) + sum(
            a['size_bytes'] for a in assets if 'generation' in a)
        acquisition += sum({a['generation']['recipe_id']: a.get('generation_build_input_metadata_bytes', 0)
            for a in assets if 'generation' in a}.values())
        final = intended + profile["discovery_budget_bytes"] + 16 * 1024**2 + acquisition
        self.assertEqual(estimate["finalBytes"], final)
        working = profile["discovery_budget_bytes"]
        build_inputs = {source['id']: source for a in assets for source in a.get('generation_build_inputs', [])}
        build_input_bytes = sum({source['sha256']: source['size_bytes'] for source in build_inputs.values()}.values())
        expanded_inputs = {source['id']: source for a in assets for source in a.get('generation_build_input_members', [])}
        build_input_work_bytes = build_input_bytes + sum(source['size_bytes'] for source in expanded_inputs.values())
        self.assertEqual(estimate["phaseWorkingBytes"], working)
        self.assertEqual(estimate["buildInputBytes"], build_input_bytes)
        self.assertEqual(estimate["buildInputWorkBytes"], build_input_work_bytes)
        self.assertEqual(estimate["peakBytes"], intended + 16 * 1024**2 + max(working, build_input_work_bytes) + profile["reserve_bytes"] + acquisition)
        self.assertEqual(estimate["actualPeakBytes"], known + 16 * 1024**2 + max(working, build_input_work_bytes) + profile["reserve_bytes"] + acquisition)
        coverage = report["coverage"]
        readers_actual = sum(a["size_bytes"] for a in assets if a["destination"].startswith("SOFTWARE/"))
        supporting_actual = sum(a["size_bytes"] for a in assets if not is_document(a) and not a["destination"].startswith("SOFTWARE/"))
        self.assertEqual(coverage["knowledgeBytes"], known - readers_actual - supporting_actual)
        self.assertEqual(coverage["softwareBytes"], readers_actual)
        self.assertEqual(coverage["supportingBytes"], supporting_actual)
        self.assertEqual(sum(row["assetCount"] for row in coverage["categories"]), coverage["knowledgeCount"])
        try:
            plan = capacity_plan(assets, profile, selection)
        except CatalogError:
            self.assertFalse(report["canBuild"])
        else:
            self.assertEqual(estimate["finalBytes"], plan.get("planned_final_bytes", plan["estimated_final_bytes"]))
            self.assertEqual(estimate["phaseWorkingBytes"], plan["discovery_budget_bytes"])
            self.assertEqual(estimate["peakBytes"], plan["in_place_peak_budget_bytes"])
            self.assertEqual(estimate["downloadBytes"], plan["download_bytes"])
            self.assertEqual(estimate["archiveOutputBytes"], plan["archive_output_bytes"])
            self.assertEqual(estimate["generatedOutputBytes"], plan["generated_output_bytes"])
            self.assertEqual(estimate["acquisitionBytes"], plan["acquisition_workspace_budget_bytes"])

    def test_all_presets_match_cli_selection_and_storage(self):
        results = self.javascript([{"profile": p["id"]} for p in self.model["profiles"]])
        self.assertEqual(len(results), 5)
        for result in results:
            with self.subTest(profile=result["state"]["profile"]):
                self.compare_to_python(result)
        for identity in ("flash-16gb", "critical-64gb"):
            fixed = next(r for r in results if r["state"]["profile"] == identity)
            self.assertTrue(fixed["build"], fixed["report"]["errors"])
            baseline = resolve_content(self.assets, self.profiles[identity], resources_path=self.registry)[0]
            self.assertEqual(set(fixed["report"]["selectedAssetIds"]), {a["id"] for a in baseline})
            self.assertNotIn("content_target_min_bytes", self.profiles[identity])
            self.assertFalse(fixed["report"]["coverage"]["underfilled"])
        self.assertTrue(all(not r["build"] for r in results if r["report"]["incomplete"]))

    def test_archive_outputs_count_disk_space_without_inflating_downloads_or_documents(self):
        from test_archive import ArchiveTests
        fixture = ArchiveTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        profiles = fixture.root / "profiles"
        profiles.mkdir()
        (profiles / "test.yaml").write_text(yaml.safe_dump(fixture.profile))
        catalog, registry = fixture.root / "catalog.yaml", fixture.root / "resources.yaml"
        catalog.write_text(yaml.safe_dump({"schema_version": 1, "assets": [fixture.source, *fixture.members]}))
        registry.write_text(yaml.safe_dump({"schema_version": 1, "resources": [
            {"id": "manual", "title": "Manual", "status": "ready", "target_bytes": 1000,
             "asset_ids": [a["id"] for a in fixture.members]},
            {"id": "input", "title": "Required ZIP source", "status": "ready", "target_bytes": 1000,
             "asset_ids": [fixture.source["id"]]},
        ]}))
        model = make_model(catalog, profiles, registry, allow_local=True)
        source = next(a for a in model["assets"] if a["id"] == "source")
        self.assertTrue(source["supporting_file"])
        self.assertIn("archive_member", next(a for a in model["assets"] if a["id"] == "member0"))
        complete, omitted = self.javascript([
            {"profile": "test"},
            {"profile": "test", "items": {"input": {"included": False}}},
        ], model)
        plan = capacity_plan(load_catalog(catalog, allow_local=True), fixture.profile)
        estimate, coverage = complete["report"]["estimates"], complete["report"]["coverage"]
        self.assertEqual(estimate["knownBytes"], plan["content_bytes"])
        self.assertEqual(estimate["downloadBytes"], plan["download_bytes"])
        self.assertEqual(estimate["archiveOutputBytes"], plan["archive_output_bytes"])
        self.assertEqual(coverage["knowledgeBytes"], plan["pinned_knowledge_bytes"])
        self.assertEqual(coverage["supportingBytes"], plan["supporting_file_bytes"])
        self.assertEqual((coverage["directCount"], coverage["knowledgeCount"], coverage["softwareCount"]), (1, 1, 0))
        self.assertEqual(coverage["supportingCount"], 4)
        self.assertTrue(complete["build"])
        self.assertFalse(omitted["build"])
        self.assertTrue(any("ZIP source" in error for error in omitted["report"]["errors"]))

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
            {"profile":"flash-16gb", "items":{"school-education":{"included":False}}},
            {"profile":"flash-16gb", "items":{"openstax-core":{"included":True,"edition":"published"}}},
        ])
        for result in results:
            self.compare_to_python(result)
        self.assertLess(results[1]["report"]["estimates"]["knownBytes"], results[0]["report"]["estimates"]["knownBytes"])
        self.assertIn("openstax-core", results[2]["report"]["selectionArgs"]["include"])
        self.assertGreaterEqual(results[2]["report"]["estimates"]["contentTargetBytes"], results[0]["report"]["estimates"]["contentTargetBytes"])
        self.assertEqual(bool(results[2]["build"]), results[2]["report"]["canBuild"])

    def test_missing_editions_never_invent_savings_or_emit_a_build(self):
        result = self.javascript([{"profile":"compact-256gb", "items":{"wikipedia-en":{"edition":"direct"}}, "allowIncomplete":True}])[0]
        self.assertFalse(result["build"])
        self.assertTrue(any("no verified direct edition" in message for message in result["report"]["errors"]))
        self.compare_to_python(result)
        row = next(row for row in result["report"]["rows"] if row["id"] == "wikipedia-en")
        self.assertFalse(next(option for option in row["options"] if option["value"] == "direct")["available"])

    def test_partial_build_requires_explicit_choice_and_retains_real_target_budget(self):
        before, after = self.javascript([{"profile":"standard-512gb"}, {"profile":"standard-512gb", "allowIncomplete":True}])
        self.assertTrue(before["build"])
        self.assertIn("--allow-incomplete", after["build"])
        self.assertEqual(before["report"]["estimates"], after["report"]["estimates"])
        self.assertGreaterEqual(after["report"]["estimates"]["peakBytes"], after["report"]["estimates"]["actualPeakBytes"])
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

    def test_exact_coverage_deduplicates_assets_and_separates_source_gaps(self):
        from test_resource_editions import EditionTests
        fixture = EditionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.assets[0].update(resource_type="textbook", illustrated=True, category="electrical")
        fixture.assets[2].update(resource_type="textbook", illustrated=True, category="reference")
        fixture.profile.update(capacity_bytes=10**10, discovery_budget_bytes=1000,
                               readers_budget_bytes=5)
        fixture.resource["target_bytes"] = 2 * 10**9
        resources = list(fixture.registry().values())
        # Two resource routes to one document must not inflate actual content or learning counts.
        resources.append({"id":"duplicate", "title":"Another route", "target_bytes":10,
                          "status":"ready", "asset_ids":["critical"]})
        fixture.profile["default_resources"].append("duplicate")
        model = {"profiles":[{**fixture.profile, "preset_resource_ids":["collection", "duplicate"], "baseline_asset_ids":[]}],
                 "resources":resources, "assets":fixture.assets}
        report = self.javascript([{"profile":"test", "allowIncomplete":True}], model)[0]["report"]
        coverage = report["coverage"]
        self.assertEqual((coverage["knowledgeBytes"], coverage["softwareBytes"]), (30, 2))
        self.assertEqual((coverage["knowledgeCount"], coverage["assetCount"]), (2, 3))
        self.assertEqual((coverage["directCount"], coverage["directBytes"]), (1, 10))
        self.assertEqual((coverage["archiveCount"], coverage["archiveBytes"]), (1, 20))
        self.assertEqual((coverage["textbookCount"], coverage["illustratedCount"]), (1, 1))
        self.assertEqual(coverage["unmetContentBytes"], coverage["knowledgeTargetBytes"] - 30)
        self.assertTrue(coverage["underfilled"])
        self.assertEqual(report["estimates"]["phaseWorkingBytes"], 1000)
        self.assertEqual(coverage["capacityFraction"], 32 / 10**10)
        self.assertEqual(coverage["categories"], [
            {"id":"electrical", "assetCount":1, "directCount":1, "bytes":10},
            {"id":"reference", "assetCount":1, "directCount":0, "bytes":20}])

    def test_fixed_preset_floor_uses_knowledge_not_reader_or_reserved_bytes(self):
        from test_resource_editions import EditionTests
        fixture = EditionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.profile.pop("default_resources")
        fixture.profile.update(content_target_min_bytes=31, content_target_max_bytes=100)
        model = {"profiles":[{**fixture.profile, "preset_resource_ids":["collection", "archive-readers"],
                             "baseline_asset_ids":["critical", "archive", "reader"]}],
                 "resources":list(fixture.registry().values()), "assets":fixture.assets}
        before, partial = self.javascript([{"profile":"test"}, {"profile":"test", "allowIncomplete":True}], model)
        self.assertEqual(before["report"]["estimates"]["knownBytes"], 32)
        self.assertEqual(before["report"]["coverage"]["knowledgeBytes"], 30)
        self.assertTrue(before["report"]["coverage"]["presetBelowTarget"])
        self.assertTrue(before["report"]["coverage"]["underfilled"])
        self.assertFalse(before["build"])
        self.assertTrue(partial["build"])
        self.assertEqual(before["report"]["coverage"], partial["report"]["coverage"])
        self.assertFalse(any("direct" in option["label"] for option in before["report"]["rows"][0]["options"] if option["value"] == "preset"))

    def test_default_editions_are_not_customizations_and_can_be_overridden(self):
        from test_resource_editions import EditionTests
        fixture = EditionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.profile["default_editions"] = {"collection":"compact"}
        resources = fixture.registry()
        model = {"profiles":[{**fixture.profile, "preset_resource_ids":["collection"], "baseline_asset_ids":[]}],
                 "resources":list(resources.values()), "assets":fixture.assets}
        default, published, direct = self.javascript([{"profile":"test"},
            {"profile":"test", "items":{"collection":{"edition":"published"}}, "allowIncomplete":True},
            {"profile":"test", "items":{"collection":{"edition":"direct"}}}], model)
        self.assertEqual(default["state"]["items"]["collection"]["edition"], "compact")
        self.assertEqual(default["report"]["selectionArgs"]["editions"], {})
        self.assertNotIn("--edition", default["build"])
        self.assertEqual(default["report"]["estimates"]["contentTargetBytes"], 30)
        self.assertIn("--edition collection=published", published["build"])
        self.assertIn("--edition collection=direct", direct["build"])
        for result in (default, published, direct):
            editions = [f"{key}={value}" for key, value in result["report"]["selectionArgs"]["editions"].items()]
            selected, _, selection = resolve_content(fixture.assets, fixture.profile,
                resources_path=fixture.registry_path, editions=editions)
            self.assertEqual(result["report"]["selectedAssetIds"], sorted(asset["id"] for asset in selected))
            self.assertEqual(result["report"]["estimates"]["contentTargetBytes"], selection["content_target_bytes"])

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
        self.assertIn("--detach", words)
        self.assertNotIn("--detach", shlex.split(result["plan"]))
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

    def test_rich_fixed_presets_cannot_drop_readers_while_keeping_archives(self):
        for result in self.javascript([{"profile":identity, "items":{"archive-readers":{"included":False}}}
                                       for identity in ("flash-16gb", "critical-64gb")]):
            self.compare_to_python(result)
            self.assertFalse(result["build"])
            self.assertTrue(any("reader" in error.lower() for error in result["report"]["errors"]))
            self.assertGreater(result["report"]["coverage"]["softwareBytes"], 0)  # Required dependency remains represented; conflicting exclusion blocks the command.
            self.assertGreater(result["report"]["coverage"]["archiveCount"], 0)

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
