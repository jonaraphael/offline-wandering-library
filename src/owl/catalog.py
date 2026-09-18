"""Small YAML schema with strict safety and profile validation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

from .safety import validate_relative


class CatalogError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise CatalogError(f"Duplicate or invalid YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
DIRECT = {"html", "htm", "pdf", "txt", "md", "png", "jpg", "jpeg"}
SOFTWARE = {"apk", "exe", "msi", "dmg", "appimage", "deb", "rpm"}
ROOTS = {"CRITICAL", "REFERENCE", "BOOKS", "MAPS", "ZIM", "SOFTWARE"}
RESOURCE_TYPES = {"textbook", "guide", "reference", "archive", "software"}
LEARNING_SHELVES = ("textbooks", "illustrated-guides")
REQUIRED = {"id", "title", "category", "format", "source_url", "destination", "version",
            "size_bytes", "sha256", "license", "redistributable", "required", "profiles"}


def learning_shelves(asset: dict) -> set[str]:
    """Directly readable learning collections; illustrated textbooks belong to both."""
    if (str(asset.get("format", "")).lower() not in DIRECT or asset.get("reader_required") or
            str(asset.get("destination", "")).split("/")[0].upper() in {"ZIM", "SOFTWARE"}):
        return set()
    shelves = set()
    resource_type = asset.get("resource_type", "reference")
    if resource_type == "textbook":
        shelves.add("textbooks")
    if asset.get("illustrated") is True and resource_type in {"textbook", "guide"}:
        shelves.add("illustrated-guides")
    return shelves


def learning_coverage(assets: list[dict]) -> dict:
    result = {shelf: {"count": 0, "required_critical_count": 0, "size_bytes": 0}
              for shelf in LEARNING_SHELVES}
    for asset in assets:
        for shelf in learning_shelves(asset):
            result[shelf]["count"] += 1
            result[shelf]["required_critical_count"] += int(bool(asset.get("required") and asset.get("critical")))
            result[shelf]["size_bytes"] += asset["size_bytes"]
    return result


def read_yaml(path: Path):
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=UniqueLoader)


def load_profiles(directory: Path) -> dict:
    result = {}
    for path in sorted(directory.glob("*.yaml")):
        profile = read_yaml(path)
        if not isinstance(profile, dict):
            raise CatalogError(f"Invalid profile: {path}")
        name = profile.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name) or name in result:
            raise CatalogError(f"Invalid/duplicate profile id: {name}")
        for field in ("capacity_bytes", "reserve_bytes", "search_budget_bytes"):
            if type(profile.get(field)) is not int or profile[field] < 0:
                raise CatalogError(f"{name}: {field} must be a nonnegative integer")
        if profile["capacity_bytes"] <= profile["reserve_bytes"]:
            raise CatalogError(f"{name}: no usable capacity")
        for field in ("content_target_min_bytes", "content_target_max_bytes", "readers_budget_bytes"):
            if field in profile and (type(profile[field]) is not int or profile[field] < 0):
                raise CatalogError(f"{name}: {field} must be a nonnegative integer")
        if ("content_target_min_bytes" in profile) != ("content_target_max_bytes" in profile):
            raise CatalogError(f"{name}: content target requires both minimum and maximum")
        if profile.get("content_target_min_bytes", 0) > profile.get("content_target_max_bytes", 0):
            raise CatalogError(f"{name}: content target minimum exceeds maximum")
        minimum = profile.get("minimum_coverage", {})
        if (not isinstance(minimum, dict) or set(minimum) - set(LEARNING_SHELVES) or
                any(type(count) is not int or count < 0 for count in minimum.values())):
            raise CatalogError(f"{name}: minimum_coverage must map learning shelves to nonnegative integer counts")
        result[name] = profile
    if not result:
        raise CatalogError(f"No profiles in {directory}")
    return result


def load_catalog(path: Path, profiles: dict | None = None, allow_local: bool = False) -> list[dict]:
    document = read_yaml(path)
    return validate_catalog(document, profiles, allow_local)


def validate_catalog(document: dict, profiles: dict | None = None, allow_local: bool = False) -> list[dict]:
    """Validate a parsed catalog, including collisions across combined manifests."""
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("assets"), list):
        raise CatalogError("Catalog requires schema_version: 1 and assets list")
    ids, paths, directories = set(), set(), set()
    assets = []
    for raw in document["assets"]:
        if not isinstance(raw, dict) or REQUIRED - raw.keys():
            raise CatalogError(f"Asset missing fields: {REQUIRED - raw.keys() if isinstance(raw, dict) else raw}")
        asset = dict(raw)
        identity = asset["id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9_-]+", identity) or identity in ids:
            raise CatalogError(f"Invalid or duplicate id: {identity!r}")
        ids.add(identity)
        dest = validate_relative(asset["destination"])
        if dest.split("/")[0] not in ROOTS or len(dest.split("/")) < 2:
            raise CatalogError(f"{identity}: destination must be inside a content directory")
        lowered = dest.casefold()
        parts = lowered.split("/")
        parents = {"/".join(parts[:n]) for n in range(1, len(parts))}
        if lowered in paths or lowered in directories or parents & paths:
            raise CatalogError(f"Duplicate or conflicting destination: {dest}")
        paths.add(lowered)
        directories.update(parents)
        for field in ("title", "category", "format", "version", "license"):
            if not isinstance(asset[field], str) or not asset[field].strip():
                raise CatalogError(f"{identity}: {field} must be nonempty text (quote versions)")
        for field in ("required", "redistributable", "critical", "reader_required", "illustrated"):
            if field in asset and type(asset[field]) is not bool:
                raise CatalogError(f"{identity}: {field} must be boolean")
        asset.setdefault("illustrated", False)
        if not isinstance(asset.setdefault("resource_type", "reference"), str) or asset["resource_type"] not in RESOURCE_TYPES:
            raise CatalogError(f"{identity}: resource_type must be one of {', '.join(sorted(RESOURCE_TYPES))}")
        for field in ("mirrors", "tags"):
            if field in asset and (not isinstance(asset[field], list) or any(not isinstance(v, str) for v in asset[field])):
                raise CatalogError(f"{identity}: {field} must be a list of strings")
        for field in ("description", "publisher", "source_page", "language", "snapshot_date", "attribution", "text_encoding", "unresolved_reason", "derived_from_asset_id"):
            if field in asset and not isinstance(asset[field], str):
                raise CatalogError(f"{identity}: {field} must be text")
        memberships = asset["profiles"]
        if not isinstance(memberships, list) or any(not isinstance(p, str) for p in memberships):
            raise CatalogError(f"{identity}: profiles must be a list (empty for resource-selected files)")
        if profiles and set(memberships) - profiles.keys():
            raise CatalogError(f"{identity}: unknown profile")
        status = asset.setdefault("status", "resolved")
        if status not in {"resolved", "unresolved"}:
            raise CatalogError(f"{identity}: invalid status")
        if status == "unresolved" and not asset.get("unresolved_reason"):
            raise CatalogError(f"{identity}: explain unresolved source")
        size = asset["size_bytes"]
        if not (type(size) is int and size > 0) and not (status == "unresolved" and size is None):
            raise CatalogError(f"{identity}: exact positive size_bytes required")
        checksum = asset["sha256"]
        if checksum is not None and (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)):
            raise CatalogError(f"{identity}: invalid SHA-256")
        if (asset["format"].lower() in SOFTWARE or dest.startswith("SOFTWARE/")) and status == "resolved" and not checksum:
            raise CatalogError(f"{identity}: executable distributions require pinned SHA-256")
        if asset.get("critical") and (asset["format"].lower() not in DIRECT or asset.get("reader_required")):
            raise CatalogError(f"{identity}: critical content must be directly readable")
        if asset["format"].lower() == "zim" and not asset.get("reader_required"):
            raise CatalogError(f"{identity}: ZIM requires reader_required: true")
        urls = [asset["source_url"], *asset.get("mirrors", [])]
        for url in urls:
            if status == "unresolved" and url is None:
                continue
            if not isinstance(url, str):
                raise CatalogError(f"{identity}: invalid source URL")
            parsed = urlsplit(url)
            allowed = {"https", "repo", "file", "http"} if allow_local else {"https"}
            if parsed.scheme not in allowed or parsed.username or parsed.password or parsed.fragment:
                raise CatalogError(f"{identity}: HTTPS source required (local/test sources need --allow-local)")
            if parsed.scheme in {"http", "https"} and not parsed.hostname:
                raise CatalogError(f"{identity}: source URL needs host")
        assets.append(asset)
    return assets


def select_profile(assets: list[dict], profile: dict) -> tuple[list[dict], list[dict]]:
    name = profile["id"]
    selected = [a for a in assets if name in a["profiles"]]
    unresolved = [a for a in selected if a["status"] == "unresolved"]
    required = [a["id"] for a in unresolved if a["required"]]
    if required:
        raise CatalogError(f"Required sources unresolved: {', '.join(required)}")
    resolved = [a for a in selected if a["status"] == "resolved"]
    if any(a["format"].lower() == "zim" for a in resolved) and not any(a["destination"].startswith("SOFTWARE/") for a in resolved):
        raise CatalogError(f"{name}: ZIM content must include a pinned bundled reader")
    coverage = learning_coverage(resolved)
    for shelf, minimum in profile.get("minimum_coverage", {}).items():
        actual = coverage[shelf]["required_critical_count"]
        if actual < minimum:
            raise CatalogError(f"{name}: requires at least {minimum} required critical {shelf}; found {actual}. "
                               "Only directly readable, resolved assets count; archive-only material cannot satisfy this floor.")

    def priority(asset):
        shelves = learning_shelves(asset)
        if asset.get("required") and asset.get("critical") and shelves:
            tier = 0
        elif asset.get("critical"):
            tier = 1
        elif shelves:
            tier = 2
        elif asset["destination"].startswith("SOFTWARE/"):
            tier = 4
        elif asset["format"].lower() in DIRECT and not asset.get("reader_required"):
            tier = 3
        else:
            tier = 5
        return tier, asset["size_bytes"], asset["destination"].casefold()

    return sorted(resolved, key=priority), unresolved


def fingerprint(asset: dict) -> str:
    fields = {key: asset.get(key) for key in ("source_url", "version", "size_bytes", "sha256")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def resolve_content(assets: list[dict], profile: dict, *, resources_path: Path | None = None,
                    include=(), exclude=(), editions=()) -> tuple[list[dict], list[dict], dict | None]:
    """Resolve named collections, or the fixed directly-readable baseline."""
    if "default_resources" not in profile and not include and not exclude and not editions:
        selected, unresolved = select_profile(assets, profile)
        return selected, unresolved, None
    from .resources import load_resources, resolve_resources, resource_asset_ids
    if resources_path is None:
        raise CatalogError("This selection requires a resource registry (--resources-catalog)")
    resources = load_resources(resources_path, assets)
    result = resolve_resources(assets, profile, resources, include=include, exclude=exclude, editions=editions)
    candidates = result.pop("assets")
    if "default_resources" not in profile:
        # Fixed small/custom profiles can also add or subtract named collections.
        removed = {identity for rid in result["excluded_ids"] for identity in resource_asset_ids(resources[rid])}
        removed.update(identity for rid in result["selected_ids"]
                       for identity in resources[rid].get("replaces_asset_ids", []))
        removed.update(identity for rid, edition in result["explicit_editions"].items()
                       if edition != "published" for identity in resource_asset_ids(resources[rid]))
        added = {a["id"] for a in candidates}
        baseline = [a for a in assets if profile["id"] in a["profiles"] and a["id"] not in removed | added]
        candidates.extend(baseline)
        baseline_bytes = sum(a["size_bytes"] for a in baseline if a["status"] == "resolved")
        result["baseline_asset_ids"] = [a["id"] for a in baseline]
        result["content_target_bytes"] += baseline_bytes
        result["declared_content_target_bytes"] += baseline_bytes
        result["planned_total_bytes"] += baseline_bytes
        result["resolved_asset_bytes"] += baseline_bytes
    effective_profile = dict(profile)
    if result["customized"]:
        effective_profile.pop("minimum_coverage", None)
    selected, unresolved = select_profile(candidates, effective_profile)
    result["registry_sha256"] = hashlib.sha256(resources_path.read_bytes()).hexdigest()
    return selected, unresolved, result


def resolve_locked_content(assets: list[dict], profile: dict, lock: dict):
    """A locked catalog is an exact selection, independent of current defaults."""
    if not isinstance(lock, dict) or lock.get("profile_id") != profile["id"]:
        raise CatalogError("Locked catalog must use its original profile")
    if any(profile["id"] not in a["profiles"] for a in assets):
        raise CatalogError("Locked asset does not belong to its recorded profile")
    if "content_selection" not in lock:
        raise CatalogError("Locked catalog is missing its content selection")
    selection = lock.get("content_selection")
    if selection is None and "default_resources" in profile:
        raise CatalogError("Resource profile requires locked collection coverage")
    if selection is not None:
        if not isinstance(selection, dict):
            raise CatalogError("Invalid locked content selection")
        for field in ("content_target_bytes", "readers_budget_bytes", "planned_total_bytes"):
            if type(selection.get(field)) is not int or selection[field] < 0:
                raise CatalogError(f"Invalid locked selection {field}")
        if selection["planned_total_bytes"] != selection["content_target_bytes"] + selection["readers_budget_bytes"]:
            raise CatalogError("Invalid locked selection budget total")
        ids = selection.get("selected_ids")
        rows = selection.get("resource_rows")
        incomplete = selection.get("incomplete_resources")
        if (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                or not isinstance(rows, list) or not isinstance(incomplete, list)
                or any(not isinstance(r, dict) or r.get("id") not in ids
                       or not isinstance(r.get("status"), str)
                       or r.get("status") not in {"ready", "partial", "unresolved"}
                       or not isinstance(r.get("reason"), str) for r in rows)
                or incomplete != [r for r in rows if r["status"] != "ready"]):
            raise CatalogError("Invalid locked resource coverage")
        if len(set(ids)) != len(ids) or sorted(r['id'] for r in rows) != sorted(ids):
            raise CatalogError("Locked resource coverage must describe every selected resource exactly once")
        editions = selection.get("explicit_editions", {})
        if (not isinstance(editions, dict) or set(editions) - set(ids) or
                any(not isinstance(value, str) or value not in {"published", "direct", "compact"}
                    for value in editions.values()) or
                any(row.get("edition", "published") != editions.get(row["id"], "published") for row in rows)):
            raise CatalogError("Invalid locked resource editions")
        resolved_ids = set()
        for row in rows:
            values = row.get("resolved_asset_ids")
            if not isinstance(values, list) or any(not isinstance(i, str) for i in values):
                raise CatalogError("Invalid locked resource asset references")
            resolved_ids.update(values)
        baseline = selection.get("baseline_asset_ids", [])
        if not isinstance(baseline, list) or any(not isinstance(i, str) for i in baseline):
            raise CatalogError("Invalid locked baseline")
        actual_ids = {a['id'] for a in assets}
        additional = selection.get("additional_asset_ids", [])
        if not isinstance(additional, list) or any(not isinstance(i, str) for i in additional):
            raise CatalogError("Invalid locked additional assets")
        if not resolved_ids <= actual_ids or not actual_ids <= resolved_ids | set(baseline) | set(additional):
            raise CatalogError("Locked collection coverage differs from its asset files")
    effective = {key: value for key, value in profile.items() if key != "minimum_coverage"}
    selected, unresolved = select_profile(assets, effective)
    return selected, unresolved, selection


def capacity_plan(assets: list[dict], profile: dict, selection: dict | None = None) -> dict:
    content = sum(a["size_bytes"] for a in assets)
    overhead = 16 * 1024 * 1024
    final = content + profile["search_budget_bytes"] + overhead
    if final + profile["reserve_bytes"] > profile["capacity_bytes"]:
        raise CatalogError(f"Profile exceeds capacity: {final:,} bytes plus {profile['reserve_bytes']:,} reserve")
    result = {"download_bytes": content, "content_bytes": content, "estimated_final_bytes": final,
            "search_budget_bytes": profile["search_budget_bytes"], "reserve_bytes": profile["reserve_bytes"],
            "capacity_bytes": profile["capacity_bytes"], "index_scratch_budget_bytes": profile["search_budget_bytes"] * 2,
            "learning_coverage": learning_coverage(assets)}
    if selection is not None:
        target = max(content, selection["planned_total_bytes"])
        planned_final = target + profile["search_budget_bytes"] + overhead
        if planned_final + profile["reserve_bytes"] > profile["capacity_bytes"]:
            raise CatalogError(f"Selected resource targets exceed capacity: {planned_final:,} bytes "
                               f"plus {profile['reserve_bytes']:,} reserve. Exclude resources or choose a larger profile.")
        result.update(content_selection=selection, planned_final_bytes=planned_final,
                      content_target_min_bytes=profile.get("content_target_min_bytes"),
                      content_target_max_bytes=profile.get("content_target_max_bytes"),
                      content_complete=not selection["incomplete_resources"])
        if "content_target_min_bytes" in profile:
            actual = selection["content_target_bytes"]
            result["target_window_status"] = ("below-target" if actual < profile["content_target_min_bytes"]
                else "above-target" if actual > profile["content_target_max_bytes"] else "in-range")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", type=Path, default=Path("catalog/library.yaml"))
    parser.add_argument("--profiles-dir", type=Path, default=Path("profiles"))
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument("--resources-catalog", type=Path)
    args = parser.parse_args(argv)
    try:
        profiles = load_profiles(args.profiles_dir)
        assets = load_catalog(args.catalog, profiles, args.allow_local)
        lock = read_yaml(args.catalog).get("selection_lock")
        if lock is not None:
            if not isinstance(lock, dict) or lock.get("profile_id") not in profiles:
                raise CatalogError("Locked catalog names an unknown profile")
            profile = profiles[lock["profile_id"]]
            selected, _, selection = resolve_locked_content(assets, profile, lock)
            capacity_plan(selected, profile, selection)
            print(f"Locked catalog OK: {profile['id']}, {len(selected)} assets")
            return 0
        for name, profile in profiles.items():
            if "default_resources" not in profile and not any(name in a["profiles"] for a in assets):
                continue
            # A demo catalog does not purport to provide the production registry.
            registry = args.resources_catalog or args.catalog.with_name("resources.yaml")
            if ("default_resources" in profile and not args.resources_catalog
                    and not read_yaml(args.catalog).get("resource_catalog")):
                continue
            selected, unresolved, selection = resolve_content(assets, profile, resources_path=registry)
            plan = capacity_plan(selected, profile, selection)
            print(f"{name}: {len(selected)} assets, {plan['content_bytes']:,} bytes; {len(unresolved)} unresolved")
            if selection:
                print(f"  Resource content target: {selection['content_target_bytes']:,} bytes; "
                      f"{len(selection['incomplete_resources'])} collections incomplete")
            for shelf, coverage in plan["learning_coverage"].items():
                print(f"  {shelf}: {coverage['count']} directly readable, {coverage['required_critical_count']} required critical")
        print("Catalog OK")
        return 0
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f"ERROR: {error}")
        return 1
