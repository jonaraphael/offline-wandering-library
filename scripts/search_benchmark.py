#!/usr/bin/env python3
"""Measure real offline ranking on the default 16 GB, 128 GB and 1 TB selections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from owl.atlas_model import load_navigation
from owl.catalog import load_catalog, load_profiles, resolve_content
from owl.discovery import plan_discovery
from owl.search_shards import ROOT, SEARCH_ROOT, SELECTION_FILE, load_manifest, payload
from owl.selection import load_ladder, recommended_profile
from owl.wikimed_phone import manifest as phone_manifest, volumes as phone_volumes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="enforce checked-in recall and empty-result bounds")
    parser.add_argument("--bounded", action="store_true", help="measure the bounded term-index route")
    parser.add_argument("--quick", action="store_true", help="measure recall over the first 28 MB of ranked chunks")
    parser.add_argument("--tasks", action="store_true", help="export the three results per graded task query")
    parser.add_argument("--extra-tasks", type=Path, help="JSON list of additional task IDs and queries")
    parser.add_argument("--task-depth", type=int, choices=range(3, 51), metavar="3-50", default=3,
                        help="export optional deeper candidate lists for relevance review")
    args = parser.parse_args()
    catalog = ROOT / "catalog/library.yaml"
    profiles = load_profiles(ROOT / "profiles")
    assets = load_catalog(catalog, profiles)
    navigation = load_navigation(ROOT / "catalog/navigation", assets)
    ladder = load_ladder(catalog)
    shards = load_manifest()["sources"]
    plans = []
    phone = phone_manifest()
    for capacity in (16, 128, 1000):
        profile = recommended_profile(profiles["flash-16gb"], capacity * 10**9, ladder)
        selected, _, _ = resolve_content(assets, profile, resources_path=catalog.with_name("resources.yaml"))
        phone_bytes = sum(volume["bytes"] for volume in phone_volumes(selected, phone))
        files, report = plan_discovery(selected, navigation, budget=profile["discovery_budget_bytes"] - phone_bytes)
        selection = payload(files[SELECTION_FILE].encode("utf-8"), "OWLShardSelection")
        name = report["manifest"]["path"]
        catalog_records = payload(files[name].encode("utf-8"), "OWLDiscoveryData")["records"]
        plans.append({"capacity_gb": capacity, "sources": selection["sources"], "metadata": catalog_records,
                      "search_bytes": sum(row["size_bytes"] for row in report["file_integrity"].values())
                                      + len(files["SEARCH/coverage.json"].encode("utf-8")),
                      "impact": selection.get("impact"),
                      "shard_bytes": sum(row["size_bytes"] for path, row in report["file_integrity"].items()
                                         if path.startswith(("SEARCH/sources/", "SEARCH/chunks/"))),
                      "indexed_zims": sum(source["format"] == "zim" for source in selection["sources"]),
                      "sampled_zims": sum(shards[source["sha256"]].get("source_evidence", {}).get("directory_coverage")
                                          in {"sampled", "entry-point"} for source in selection["sources"]
                                          if source["format"] == "zim"),
                      "selected_zims": sum(asset["format"] == "zim" for asset in selected),
                      "selected_assets": len(selected)})
        del files
    with tempfile.TemporaryDirectory(prefix="owl-search-benchmark-") as folder:
        plan = Path(folder) / "plans.json"
        plan.write_text(json.dumps(plans, ensure_ascii=True), encoding="utf-8")
        command = ["node", str(ROOT / "tests/search/benchmark.cjs"), str(plan), str(SEARCH_ROOT)]
        if args.check:
            command.append("--check")
        if args.tasks:
            command.append("--tasks")
        if args.bounded:
            command.append("--bounded")
        if args.quick:
            command.append("--quick")
        if args.extra_tasks:
            command.extend(("--extra-tasks", str(args.extra_tasks.resolve())))
        if args.task_depth != 3:
            command.extend(("--task-depth", str(args.task_depth)))
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
