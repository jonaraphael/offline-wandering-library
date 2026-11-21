"""Exercise the same default ladder through the Python and browser planners."""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from owl.catalog import capacity_plan, load_catalog, load_profiles, resolve_content
from owl.resources import load_resources, resolve_resources
from owl.selection import (BUILTIN_CAPACITIES, CAPACITY_GRID_GB, DEFAULT_LIMIT, GB, MIN_CAPACITY,
                           STEP, DomainRetention, attributed_bytes, compile_ladder, fill,
                           is_knowledge, ladder_choices, load_ladder, recommended_profile, usable_capacity)
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

    def files(self, choices):
        for rid, name in choices.items():
            resource = self.resources[rid]
            edition = resource if name == "published" else resource["editions"][name]
            yield from (self.by_id[aid] for aid in edition["asset_ids"])

    @staticmethod
    def tier_bytes(assets):
        totals = Counter()
        for asset in assets:
            if is_knowledge(asset):
                totals[asset["utility_tier"]] += asset["size_bytes"]
        return totals

    def test_continuous_fill_tier_priority_critical_and_core_nesting(self):
        full_core, full_fillers = ladder_choices(DEFAULT_LIMIT, self.ladder)
        full = self.tier_bytes(self.files({**full_core, **full_fillers}))
        critical = {a["id"] for a in self.assets if a["utility_tier"] == "CRITICAL"}
        previous = {}
        bounds = sorted({DEFAULT_LIMIT, *range(MIN_CAPACITY, DEFAULT_LIMIT, STEP),
                         *(row[0] for row in self.ladder["transitions"]),
                         *(row[0] for row in self.ladder["fillers"])})
        for start, stop in zip(bounds, [*bounds[1:], DEFAULT_LIMIT + 1], strict=True):
            with self.subTest(label_bytes=start):
                core, fillers = ladder_choices(start, self.ladder)
                self.assertFalse(core.keys() & fillers.keys())
                self.assertTrue(previous.keys() <= core.keys())
                for rid, edition in previous.items():
                    if edition != core[rid]:
                        old = list(self.files({rid: edition}))
                        current = list(self.files({rid: core[rid]}))
                        self.assertEqual({a["selection"]["edition_group"] for a in old + current}, {rid})
                        self.assertGreater(sum(a["size_bytes"] for a in current), sum(a["size_bytes"] for a in old))
                previous = core
                assets = list(self.files({**core, **fillers}))
                self.assertTrue(critical <= {a["id"] for a in assets})
                self.assertTrue(all(not self.resources[rid].get("opt_in") for rid in core.keys() | fillers.keys()))
                tiers = self.tier_bytes(assets)
                self.assertLessEqual(sum(a["size_bytes"] for a in assets),
                                     min(usable_capacity(start), usable_capacity(min(start + 1, stop - 1))))
                self.assertGreaterEqual(10 * tiers.total(), 9 * (stop - 1))
                self.assertGreater(tiers["NONESSENTIAL"], 0)
                self.assertGreaterEqual(tiers["USEFUL"] * full["NONESSENTIAL"],
                                        tiers["NONESSENTIAL"] * full["USEFUL"])

    def test_grid_utilization_domain_balance_and_cap(self):
        full_profile, full = self.suggested(1000)
        _, larger = self.suggested(2000)
        self.assertEqual(larger["effective_editions"], full["effective_editions"])
        self.assertEqual(larger["selected_ids"], full["selected_ids"])
        retention = DomainRetention(full["assets"])
        for gb in CAPACITY_GRID_GB:
            with self.subTest(gb=gb):
                profile, selection = self.suggested(gb)
                plan = capacity_plan(selection["assets"], profile, selection)
                self.assertTrue(plan["in_place_target_budget_fits"])
                used = self.tier_bytes(selection["assets"]).total()
                self.assertGreaterEqual(100 * used, 97 * usable_capacity(gb * GB))
                selected = {asset["id"] for asset in selection["assets"]}
                for domain, missing, next_asset, allowed in retention.gaps(selection["assets"], gb * GB):
                    self.assertTrue(allowed, (domain, missing, next_asset["id"]))
                    self.assertNotIn(next_asset["id"], selected)
                    self.assertGreater(10 * next_asset["size_bytes"], gb * GB)
        self.assertEqual(full_profile["nominal_capacity_bytes"], 1000 * GB)

    def test_illustrated_edition_and_weighted_archives(self):
        asset = self.by_id["wikipedia_en"]
        self.assertIn("_maxi_", asset["source_url"])
        threshold = next(c for c, rid, name in self.ladder["transitions"]
                         if rid == "wikipedia-en" and name == "published")
        self.assertLess(threshold, DEFAULT_LIMIT)
        full_core, full_fillers = ladder_choices(DEFAULT_LIMIT, self.ladder)
        retention = DomainRetention(self.files({**full_core, **full_fillers}))
        core, fillers = ladder_choices(threshold, self.ladder)
        for gap in retention.gaps(self.files({**core, **fillers}), threshold):
            self.assertTrue(gap[3], gap)
        for size, expected in ((threshold - 1, False), (threshold, True), (DEFAULT_LIMIT, True)):
            core, fillers = ladder_choices(size, self.ladder)
            chosen = {a["id"] for a in self.files({**core, **fillers})}
            self.assertEqual(asset["id"] in chosen, expected)
            self.assertEqual(len(chosen & {"wikipedia_en", "wikipedia_en_top",
                                           "wikipedia_en_mini", "wikipedia_en_nopic"}), 1)
        for identity in ("wikipedia_en", "survivorlibrary_com_en_all_2026_09", "gutenberg_en_lcc_t"):
            with self.subTest(identity=identity):
                row = self.by_id[identity]
                shares = attributed_bytes(row)
                self.assertEqual(sum(shares.values()), row["size_bytes"])
                self.assertGreater(len(shares), 1)
                self.assertTrue(shares.keys() <= set(row["knowledge_domains"]))
                self.assertTrue(row["selection"]["weight_basis"])

    def test_overrides_use_the_normal_resource_resolution(self):
        result = fill(24 * GB, {"exclude": ["wikipedia-en"]})
        self.assertNotIn("wikipedia-en", result["selected_ids"])
        self.assertIn("wikimed_en", {asset["id"] for asset in result["assets"]})
        self.assertTrue(result["customized"])

    @unittest.skipUnless(shutil.which("node"), "Node required for planner parity")
    def test_shared_vectors_match_browser_at_exact_and_intermediate_sizes(self):
        model = make_model(CATALOG, ROOT / "profiles", REGISTRY)
        capacities = [gb * GB for gb in (*CAPACITY_GRID_GB, 2000)]
        capacities += [23_999_999_999, 78_550_000_000, 319_999_999_999, 921_000_000_001]
        capacities += [c - 1 for c, rid, _ in self.ladder["transitions"] if rid == "wikipedia-en" and c > MIN_CAPACITY]
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
