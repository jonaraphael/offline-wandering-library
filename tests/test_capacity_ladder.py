"""Exercise the same default ladder through the Python and browser planners."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from owl.catalog import capacity_plan, load_catalog, load_profiles, resolve_content
from owl.resources import load_resources, resolve_resources, resource_asset_ids
from owl.selection import (BUILTIN_CAPACITIES, CAPACITY_GRID_GB, GB, compile_ladder, fill,
                           load_ladder, recommended_profile, usable_capacity)
from owl.selector import make_model

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog/library.yaml"
REGISTRY = ROOT / "catalog/resources.yaml"


class CapacityLadderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(ROOT / "profiles")
        cls.assets = load_catalog(CATALOG, cls.profiles)
        cls.by_id = {asset["id"]: asset for asset in cls.assets}
        cls.resources = load_resources(REGISTRY, cls.assets)
        cls.ladder = compile_ladder(cls.assets, cls.resources)

    def suggested(self, gb):
        profile = recommended_profile({"id": "capacity"}, gb * GB, self.ladder)
        return profile, resolve_resources(self.assets, profile, self.resources)

    def test_generated_defaults_match_the_compiler(self):
        self.assertEqual(load_ladder(CATALOG), self.ladder)
        for name, gb in BUILTIN_CAPACITIES.items():
            with self.subTest(profile=name):
                profile = self.profiles[name]
                self.assertEqual(profile, recommended_profile(profile, gb * GB, self.ladder))
        self.assertNotEqual(self.profiles["standard-512gb"]["default_resources"],
                            self.profiles["full-1tb"]["default_resources"])

    def test_grid_utilization_balance_and_cap(self):
        full_profile, full = self.suggested(1000)
        _, larger = self.suggested(2000)
        self.assertEqual(larger["effective_editions"], full["effective_editions"])
        self.assertEqual(larger["selected_ids"], full["selected_ids"])
        minimum = self.domain_bytes(full["assets"])
        total = sum(minimum.values())
        previous = set()
        for gb in CAPACITY_GRID_GB:
            with self.subTest(gb=gb):
                profile, selection = self.suggested(gb)
                plan = capacity_plan(selection["assets"], profile, selection)
                self.assertTrue(plan["in_place_target_budget_fits"])
                used = plan["content_bytes"] - plan["pinned_reader_bytes"]
                self.assertGreaterEqual(100 * used, 97 * usable_capacity(gb * GB))
                self.assertTrue(previous <= set(selection["selected_ids"]))
                previous = set(selection["selected_ids"])
                domains = self.domain_bytes(selection["assets"])
                for domain, full_bytes in minimum.items():
                    self.assertGreaterEqual(domains[domain] / full_bytes,
                                            0.075 * sum(domains.values()) / total, domain)
        self.assertEqual(full_profile["nominal_capacity_bytes"], 1000 * GB)

    @staticmethod
    def domain_bytes(assets):
        result = Counter()
        for asset in assets:
            domain = asset["selection"]["domain"]
            if domain != "archive-access" and not asset.get("supporting_file"):
                result[domain] += asset["size_bytes"]
        return result

    def test_every_transition_preserves_depth_and_puts_critical_files_first(self):
        available = defaultdict(set)
        critical = {a["id"] for a in self.assets if a["utility_tier"] == "CRITICAL"}
        for rid, row in self.resources.items():
            if rid == "archive-readers" or row.get("opt_in"):
                continue
            for aid in resource_asset_ids(row):
                step = self.by_id[aid]["selection"]
                available[step["domain"]].add(step["level"])
        depth = defaultdict(lambda: -1)
        selected = {}
        used = 0
        for threshold, rid, name in self.ladder:
            with self.subTest(rid=rid, edition=name):
                resource = self.resources[rid]
                self.assertFalse(resource.get("opt_in"))
                edition = resource if name == "published" else resource["editions"][name]
                members = set(edition["asset_ids"])
                former = selected.get(rid, set())
                if not members <= critical:
                    self.assertTrue(critical <= set().union(*selected.values()))
                if former - members:
                    old = {self.by_id[aid]["selection"].get("edition_group") for aid in former}
                    new = {self.by_id[aid]["selection"].get("edition_group") for aid in members}
                    self.assertEqual(old, {rid})
                    self.assertEqual(new, old)
                self.assertTrue(threshold > used)
                used = threshold
                selected[rid] = members
                for aid in members:
                    step = self.by_id[aid]["selection"]
                    depth[step["domain"]] = max(depth[step["domain"]], step["level"])
                frontier = max(depth.values())
                for domain, levels in available.items():
                    lower = [level for level in levels if level < frontier]
                    if lower:
                        self.assertGreaterEqual(depth[domain], max(lower), domain)
        self.assertIn("wikimed_en", self.selected_ids(16))

    def selected_ids(self, capacity):
        return {asset["id"] for asset in self.suggested(capacity)[1]["assets"]}

    def test_overrides_use_the_normal_resource_resolution(self):
        result = fill(24 * GB, {"exclude": ["wikipedia-en"]}, assets=self.assets, resources=self.resources)
        self.assertNotIn("wikipedia-en", result["selected_ids"])
        self.assertIn("wikimed_en", {asset["id"] for asset in result["assets"]})
        self.assertTrue(result["customized"])

    @unittest.skipUnless(shutil.which("node"), "Node required for planner parity")
    def test_shared_vectors_match_browser_at_exact_and_intermediate_sizes(self):
        model = make_model(CATALOG, ROOT / "profiles", REGISTRY)
        capacities = [gb * GB for gb in (*CAPACITY_GRID_GB, 2000)]
        capacities += [23_999_999_999, 78_550_000_000, 319_999_999_999, 921_000_000_001]
        code = r"""
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8'));
const {model, capacities} = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = capacities.map(capacity => {
  const state = OWLPlanner.preset(model, 'flash-16gb', capacity);
  const profile = OWLPlanner.profileFor(model, state.profile, capacity);
  const plan = OWLPlanner.resolve(model, state);
  return [profile.capacity_bytes, profile.reserve_bytes, plan.selectedAssetIds, plan.canBuild,
    OWLPlanner.command(model, state, {target:'/drive/OWL', shell:'posix', plan:true})];
});
console.log(JSON.stringify(result));
"""
        rows = json.loads(subprocess.run(
            [shutil.which("node"), "-e", code, str(ROOT / "src/owl/templates/selector.js")],
            input=json.dumps({"model": model, "capacities": capacities}), capture_output=True,
            encoding="utf-8", check=True, timeout=30,
        ).stdout)
        for capacity, (ceiling, reserve, ids, fits, command) in zip(capacities, rows, strict=True):
            with self.subTest(capacity=capacity):
                profile = recommended_profile(self.profiles["flash-16gb"], capacity, self.ladder)
                assets, _, _ = resolve_content(self.assets, profile, resources_path=REGISTRY)
                self.assertEqual((ceiling, reserve), (profile["capacity_bytes"], profile["reserve_bytes"]))
                self.assertEqual(ids, sorted(asset["id"] for asset in assets))
                self.assertIn(f"--capacity-bytes {capacity}", command)
                self.assertTrue(fits)
