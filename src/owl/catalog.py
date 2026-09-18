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
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("assets"), list):
        raise CatalogError("Catalog requires schema_version: 1 and assets list")
    ids, paths = set(), set()
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
        if any(lowered == p or lowered.startswith(p + "/") or p.startswith(lowered + "/") for p in paths):
            raise CatalogError(f"Duplicate or conflicting destination: {dest}")
        paths.add(lowered)
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
        for field in ("description", "publisher", "source_page", "language", "snapshot_date", "attribution", "text_encoding", "unresolved_reason"):
            if field in asset and not isinstance(asset[field], str):
                raise CatalogError(f"{identity}: {field} must be text")
        memberships = asset["profiles"]
        if not isinstance(memberships, list) or not memberships or any(not isinstance(p, str) for p in memberships):
            raise CatalogError(f"{identity}: profiles must be a nonempty list")
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


def capacity_plan(assets: list[dict], profile: dict) -> dict:
    content = sum(a["size_bytes"] for a in assets)
    overhead = 16 * 1024 * 1024
    final = content + profile["search_budget_bytes"] + overhead
    if final + profile["reserve_bytes"] > profile["capacity_bytes"]:
        raise CatalogError(f"Profile exceeds capacity: {final:,} bytes plus {profile['reserve_bytes']:,} reserve")
    return {"download_bytes": content, "content_bytes": content, "estimated_final_bytes": final,
            "search_budget_bytes": profile["search_budget_bytes"], "reserve_bytes": profile["reserve_bytes"],
            "capacity_bytes": profile["capacity_bytes"], "index_scratch_budget_bytes": profile["search_budget_bytes"] * 2,
            "learning_coverage": learning_coverage(assets)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", type=Path, default=Path("catalog/library.yaml"))
    parser.add_argument("--profiles-dir", type=Path, default=Path("profiles"))
    parser.add_argument("--allow-local", action="store_true")
    args = parser.parse_args(argv)
    try:
        profiles = load_profiles(args.profiles_dir)
        assets = load_catalog(args.catalog, profiles, args.allow_local)
        for name, profile in profiles.items():
            if not any(name in a["profiles"] for a in assets):
                continue
            selected, unresolved = select_profile(assets, profile)
            plan = capacity_plan(selected, profile)
            print(f"{name}: {len(selected)} assets, {plan['content_bytes']:,} bytes; {len(unresolved)} unresolved")
            for shelf, coverage in plan["learning_coverage"].items():
                print(f"  {shelf}: {coverage['count']} directly readable, {coverage['required_critical_count']} required critical")
        print("Catalog OK")
        return 0
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f"ERROR: {error}")
        return 1
