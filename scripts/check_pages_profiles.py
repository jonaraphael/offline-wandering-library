#!/usr/bin/env python3
"""Require production Pages recommendations to retain the Python essentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from owl.catalog import load_catalog, load_profiles, resolve_content

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"flash-16gb": 16_000_000_000, "critical-64gb": 64_000_000_000}

BROWSER_PLANS = """
import {readFileSync, statSync} from "node:fs";
import {join} from "node:path";
import {pathToFileURL} from "node:url";

const site = process.argv[1];
await import(pathToFileURL(join(site, "selector.js")));
const {recommendBrowser, selectBrowser} = await import(pathToFileURL(join(site, "builder-ui.mjs")));
const {planner, routes, navigation} = JSON.parse(readFileSync(join(site, "catalog.json")));
const published = JSON.parse(readFileSync(join(site, "chunk-manifests.json")));
const files = new Map(planner.assets.map(asset => [asset.id, asset]));
for (const [id, parts] of Object.entries(published.files)) {
  if (!parts.length || parts.some(part =>
    !/^\\.\\/mirrors\\/[a-z0-9_-]+-\\d+\\.bin$/.test(part.url) ||
    statSync(join(site, part.url)).size !== part.bytes)) throw Error("Missing or invalid published mirror: " + id);
}
const plans = {};
for (const [id, capacity] of Object.entries(JSON.parse(readFileSync(0)))) {
  const preset = OWLPlanner.preset(planner, id, capacity, {browser: true});
  const state = recommendBrowser(planner, preset, routes, published, undefined, {phone: navigation.phone});
  const resolved = OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true});
  const profile = OWLPlanner.profileFor(planner, id, capacity, state);
  const result = selectBrowser(profile, resolved, {files, routes, published, kept: () => false,
    phone: navigation.phone, minimum: planner.capacity_policy.min});
  if (result.errors.length || result.over) throw Error(id + " failed to fit: " + result.errors.join(", "));
  plans[id] = result.assets.map(asset => asset.id);
}
console.log(JSON.stringify(plans));
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)
    result = subprocess.run(["node", "--input-type=module", "--eval", BROWSER_PLANS,
                             str(args.artifact.resolve())],
                            input=json.dumps(PROFILES), text=True, stdout=subprocess.PIPE)
    if result.returncode:
        return result.returncode
    browser = json.loads(result.stdout)
    profiles = load_profiles(ROOT / "profiles")
    assets = load_catalog(ROOT / "catalog/library.yaml", profiles)
    failed = False
    for name in PROFILES:
        selected, unresolved, _ = resolve_content(assets, profiles[name], resources_path=ROOT / "catalog/resources.yaml")
        critical = {asset["id"] for asset in [*selected, *unresolved] if asset["utility_tier"] == "CRITICAL"}
        missing = sorted(critical - set(browser[name]))
        print(f"{name}: {len(critical) - len(missing)}/{len(critical)} Python CRITICAL files in the Pages recommendation")
        if missing:
            failed = True
            print("Missing: " + ", ".join(missing))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
