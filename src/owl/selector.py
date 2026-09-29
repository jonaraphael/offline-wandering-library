"""Generate a small, self-contained offline selection tool from the OWL recipe."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .atlas_model import load_navigation
from .catalog import load_catalog, load_profiles, read_yaml
from .resources import load_resources, resource_asset_ids
from .content_policy import require_content_policy, load_policy
from .utility_policy import require_utility_policy
from .safety import atomic_write, reject_symlinks

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Path(__file__).with_name("templates")


def make_model(catalog: Path, profiles_dir: Path, resources_path: Path, *, allow_local=False) -> dict:
    profiles = load_profiles(profiles_dir)
    assets = load_catalog(catalog, profiles, allow_local)
    require_content_policy(assets)
    resources = load_resources(resources_path, assets)
    if catalog.resolve() == (ROOT / "catalog/library.yaml").resolve():
        require_utility_policy(assets, resources, profiles, resources_path)
    visible = []
    for profile in sorted(profiles.values(), key=lambda row: (row["capacity_bytes"], row["id"])):
        baseline = [a for a in assets if profile["id"] in a["profiles"]]
        if not baseline and "default_resources" not in profile:
            continue
        row = dict(profile)
        row["baseline_asset_ids"] = [a["id"] for a in baseline] if "default_resources" not in profile else []
        pinned = {a["id"] for a in baseline if a["status"] == "resolved"}
        row["preset_resource_ids"] = profile.get("default_resources", [identity for identity, resource in resources.items()
            if pinned & resource_asset_ids(resource)])
        visible.append(row)
    fields = ("id", "title", "category", "utility_tier", "utility_reason", "knowledge_domains", "status", "size_bytes", "sha256", "format", "destination", "critical", "required",
              "reader_required", "resource_type", "illustrated", "profiles", "supporting_file", "archive_member", "generation", "generation_source_asset_ids",
              "generation_source_resource_ids", "generation_build_inputs", "generation_build_input_members", "generation_build_input_metadata_bytes")
    # Reuse validated pseudoindex metadata; no source document is opened.
    discovery = {}
    if catalog.resolve() == (ROOT / "catalog/library.yaml").resolve():
        navigation = load_navigation(ROOT / "catalog/navigation", assets)
        for assignment in navigation["assignments"]:
            topic = navigation["topics"][assignment["topic_id"]]
            entry = discovery.setdefault(assignment["asset_id"], {"topics": [], "terms": []})
            route = {"id": topic["id"], "title": topic["title"]}
            if route not in entry["topics"]:
                entry["topics"].append(route)
            entry["terms"] = sorted(set(entry["terms"] + [topic["title"], assignment.get("description", "")] +
                                        topic["aliases"] + assignment.get("aliases", [])) - {""})
    cli = {}
    for flag, path, default in (("--catalog", catalog, ROOT / "catalog/library.yaml"),
                                ("--profiles-dir", profiles_dir, ROOT / "profiles"),
                                ("--resources-catalog", resources_path, ROOT / "catalog/resources.yaml")):
        if path.resolve() != default.resolve():
            cli[flag] = str(path.resolve())
    if allow_local:
        cli["--allow-local"] = None
    return {"schema_version": 1, "direct_reading_formats": load_policy()["direct_reading_formats"], "cli": cli, "atlas_available": catalog.resolve() == (ROOT / "catalog/library.yaml").resolve(),
            "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            "resources_sha256": hashlib.sha256(resources_path.read_bytes()).hexdigest(),
            "profiles": visible, "resources": sorted(resources.values(), key=lambda r: ({"CRITICAL": 0, "USEFUL": 1, "NONESSENTIAL": 2}.get(r.get("utility_tier"), 3), r.get("number") or 1000, r["id"])),
            "topic_verticals": json.loads(Path(__file__).with_name("topic_verticals.json").read_text())["verticals"],
            "acquisition_recipes": read_yaml(catalog).get("acquisition_recipes", []),
            "assets": [{**{key: a[key] for key in fields if key in a}, **({"discovery": discovery[a["id"]]} if a["id"] in discovery else {})} for a in assets]}


def render_selector(model: dict) -> str:
    # JSON lives in an inert script element; an imported title cannot close it.
    data = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (TEMPLATES / "selector.html").read_text(encoding="utf-8")
    engine = (TEMPLATES / "selector.js").read_text(encoding="utf-8") + "\n" + (TEMPLATES / "selector-map.js").read_text(encoding="utf-8")
    if template.count("__OWL_MODEL__") != 1 or template.count("__OWL_ENGINE__") != 1:
        raise ValueError("Selector template requires exactly one model and engine placeholder")
    return template.replace("__OWL_ENGINE__", engine).replace("__OWL_MODEL__", data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "SELECT.html")
    parser.add_argument("--catalog", type=Path, default=ROOT / "catalog/library.yaml")
    parser.add_argument("--profiles-dir", type=Path, default=ROOT / "profiles")
    parser.add_argument("--resources-catalog", type=Path, default=ROOT / "catalog/resources.yaml")
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument("--check", action="store_true", help="fail if the existing HTML differs from the current recipe")
    args = parser.parse_args(argv)
    try:
        output = render_selector(make_model(args.catalog, args.profiles_dir, args.resources_catalog,
                                            allow_local=args.allow_local)).encode("utf-8")
        reject_symlinks(args.output)
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != output:
                raise ValueError("SELECT.html is stale; regenerate it with scripts/build_selector.py")
            print("Selector matches the current catalog, profiles, and templates")
        else:
            atomic_write(args.output, output)
            print(f"Open {args.output.resolve()} in a browser; no server or internet is needed")
        return 0
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
