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


def is_document(asset: dict) -> bool:
    """A package's input/dependencies remain inventoried, not reading material."""
    return not asset.get("supporting_file", False) and asset.get("archive_member", {}).get("document", True)


def learning_shelves(asset: dict) -> set[str]:
    """Directly readable learning collections; illustrated textbooks belong to both."""
    if (not is_document(asset) or str(asset.get("format", "")).lower() not in DIRECT or asset.get("reader_required") or
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
        for field in ("content_target_min_bytes", "content_target_max_bytes", "readers_budget_bytes",
                      "index_scratch_budget_bytes"):
            if field in profile and (type(profile[field]) is not int or profile[field] < 0):
                raise CatalogError(f"{name}: {field} must be a nonnegative integer")
        if ("index_scratch_budget_bytes" in profile and
                profile["index_scratch_budget_bytes"] < (profile["search_budget_bytes"] * 3 + 3) // 4):
            raise CatalogError(f"{name}: index_scratch_budget_bytes must cover the raw-index serialization allowance")
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
        for field in ("required", "redistributable", "critical", "reader_required", "illustrated", "supporting_file", "legacy"):
            if field in asset and type(asset[field]) is not bool:
                raise CatalogError(f"{identity}: {field} must be boolean")
        asset.setdefault("illustrated", False)
        if not isinstance(asset.setdefault("resource_type", "reference"), str) or asset["resource_type"] not in RESOURCE_TYPES:
            raise CatalogError(f"{identity}: resource_type must be one of {', '.join(sorted(RESOURCE_TYPES))}")
        if asset.get("supporting_file") and (asset.get("critical") or asset.get("illustrated") or
                                             asset["resource_type"] not in {"reference", "archive"}):
            raise CatalogError(f"{identity}: supporting files cannot claim document/learning coverage")
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
        minimum_size = 0 if "archive_member" in asset or ("generation" in asset and asset.get('supporting_file')) else 1
        if not (type(size) is int and size >= minimum_size) and not (status == "unresolved" and size is None):
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
    # ZIP inputs and ordinary outputs are separate pinned assets. Resolving the
    # reference after the loop permits source records in any catalog order.
    asset_map = {asset["id"]: asset for asset in assets}
    for asset in assets:
        if "archive_member" not in asset:
            continue
        member = asset["archive_member"]
        if (not isinstance(member, dict) or
                set(member) != {"source_asset_id", "path", "document"} or
                not isinstance(member["source_asset_id"], str) or
                not isinstance(member["path"], str) or
                type(member["document"]) is not bool):
            raise CatalogError(f"{asset['id']}: archive_member requires source_asset_id, path and document")
        validate_relative(member["path"])
        source = asset_map.get(member["source_asset_id"])
        if (not source or source["id"] == asset["id"] or "archive_member" in source or
                source["format"].lower() != "zip" or source["status"] != "resolved" or
                not source["sha256"] or not source.get("supporting_file") or
                asset["status"] != "resolved" or not asset["sha256"]):
            raise CatalogError(f"{asset['id']}: archive member requires a resolved, SHA-256-pinned ZIP source and output")
        if asset["source_url"] != source["source_url"] or asset.get("mirrors", []) != source.get("mirrors", []):
            raise CatalogError(f"{asset['id']}: archive member URLs must match its ZIP input")
        if not member["document"] and (asset.get("critical") or asset.get("illustrated") or
                                        asset["resource_type"] != "reference"):
            raise CatalogError(f"{asset['id']}: supporting archive files cannot claim document/learning coverage")
    if document.get("acquisition_recipes") or any("generation" in a for a in assets):
        from .acquisition.model import validate_recipes, validate_generation, retained_input_asset_ids, build_input_metadata_allowance
        recipes = validate_recipes(document.get("acquisition_recipes", []), assets=assets, allow_local=allow_local)
        validate_generation(assets, recipes, allow_local=allow_local)
        # Derive these from validated recipes; caller-provided dependency or
        # provenance fields cannot override the authoritative recipe.
        for asset in assets:
            if 'generation' in asset:
                recipe = recipes[asset['generation']['recipe_id']]
                asset['generation_source_asset_ids'] = retained_input_asset_ids(recipe)
                asset['generation_build_inputs'] = [{key: source[key] for key in ('id','size_bytes','sha256')}
                                                    for source in recipe.get('build_inputs',[])]
                asset['generation_build_input_members'] = [{key:member[key] for key in ('id','size_bytes','sha256')}
                    for extraction in recipe.get('build_input_extractions',[]) for member in extraction['members']]
                asset['generation_source_resource_ids'] = sorted({identity for source in recipe.get('build_inputs',[])
                                                                 for identity in source.get('source_resource_ids',[])})
                asset['generation_workspace_bytes'] = recipe.get('workspace_bytes', 0)
                asset['generation_build_input_metadata_bytes'] = build_input_metadata_allowance(recipe)
                from .acquisition.runtime import recipe_digest
                asset['generation_recipe_sha256'] = recipe_digest(recipe, assets)
    return assets


def select_profile(assets: list[dict], profile: dict) -> tuple[list[dict], list[dict]]:
    name = profile["id"]
    selected = [a for a in assets if name in a["profiles"]]
    unresolved = [a for a in selected if a["status"] == "unresolved"]
    required = [a["id"] for a in unresolved if a["required"]]
    if required:
        raise CatalogError(f"Required sources unresolved: {', '.join(required)}")
    resolved = [a for a in selected if a["status"] == "resolved"]
    selected_ids = {asset["id"] for asset in resolved}
    for asset in resolved:
        member = asset.get("archive_member")
        if member and member["source_asset_id"] not in selected_ids:
            raise CatalogError(f"{asset['id']}: select its ZIP source asset {member['source_asset_id']} as well")
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
    if "archive_member" in asset:
        fields["archive_member"] = asset["archive_member"]
    if "supporting_file" in asset:
        fields["supporting_file"] = asset["supporting_file"]
    if "generation" in asset:
        fields["generation"] = asset["generation"]
        fields["generation_recipe_sha256"] = asset.get("generation_recipe_sha256")
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
        defaults = selection.get("default_editions", {})
        effective_editions = selection.get("effective_editions", editions)
        if (any(not isinstance(mapping, dict) or set(mapping) - set(ids) or
                any(not isinstance(value, str) or value not in {"published", "direct", "compact"}
                    for value in mapping.values()) for mapping in (editions, defaults, effective_editions)) or
                effective_editions != {**defaults, **editions} or
                any(row.get("edition", "published") != effective_editions.get(row["id"], "published") for row in rows)):
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
    readers = sum(a["size_bytes"] for a in assets if a["destination"].startswith("SOFTWARE/"))
    supporting = sum(a["size_bytes"] for a in assets if not is_document(a) and not a["destination"].startswith("SOFTWARE/"))
    knowledge = content - readers - supporting
    direct = sum(a["size_bytes"] for a in assets if is_document(a) and a["format"].lower() in DIRECT
                 and not a.get("reader_required") and not a["destination"].startswith(("SOFTWARE/", "ZIM/")))
    overhead = 16 * 1024 * 1024
    generated = [a for a in assets if 'generation' in a]
    generation_work = {a['generation']['recipe_id']: a.get('generation_workspace_bytes', 0)
                       for a in generated}
    input_metadata = {a['generation']['recipe_id']: a.get('generation_build_input_metadata_bytes',0) for a in generated}
    temporary = {source['id']: source for asset in generated for source in asset.get('generation_build_inputs', [])}
    temporary_bytes = sum({source['sha256']: source['size_bytes'] for source in temporary.values()}.values())
    expanded_inputs = {member['id']:member['size_bytes'] for asset in generated
                       for member in asset.get('generation_build_input_members',[])}
    expanded_bytes = sum(expanded_inputs.values())
    # Allow complete regeneration while verified sibling outputs remain in place.
    acquisition = sum(generation_work.values()) + sum(input_metadata.values()) + 65536 * len(generation_work) + sum(a['size_bytes'] for a in generated)
    final = content + profile["search_budget_bytes"] + overhead + acquisition
    if final + profile["reserve_bytes"] > profile["capacity_bytes"]:
        if acquisition:
            raise CatalogError('Generated content plus retained acquisition workspace exceeds profile capacity')
        raise CatalogError(f"Profile exceeds capacity: {final:,} bytes plus {profile['reserve_bytes']:,} reserve")
    scratch = profile.get("index_scratch_budget_bytes", profile["search_budget_bytes"] * 2)
    raw = (profile["search_budget_bytes"] * 3 + 3) // 4
    if type(scratch) is not int or scratch < raw:
        raise CatalogError("index_scratch_budget_bytes must be an integer covering the raw-index serialization allowance")
    result = {"download_bytes": sum(a["size_bytes"] for a in assets if "archive_member" not in a and "generation" not in a) + temporary_bytes,
            "build_input_download_bytes": temporary_bytes,
            "build_input_expanded_bytes": expanded_bytes,
            "build_input_metadata_bytes": sum(input_metadata.values()),
            "build_input_work_bytes": temporary_bytes + expanded_bytes,
            "build_input_cache_bytes": 0,
            "archive_output_bytes": sum(a["size_bytes"] for a in assets if "archive_member" in a),
            "generated_output_bytes": sum(a["size_bytes"] for a in assets if "generation" in a),
            "acquisition_workspace_budget_bytes": acquisition,
            "supporting_file_bytes": supporting,
            "content_bytes": content, "estimated_final_bytes": final,
            "search_budget_bytes": profile["search_budget_bytes"], "reserve_bytes": profile["reserve_bytes"],
            "capacity_bytes": profile["capacity_bytes"], "index_scratch_budget_bytes": scratch,
            "index_serialization_budget_bytes": raw, "index_extraction_budget_bytes": scratch - raw,
            "pinned_knowledge_bytes": knowledge, "pinned_reader_bytes": readers,
            "direct_readable_bytes": direct,
            "actual_content_utilization_percent": knowledge * 100 // profile["capacity_bytes"],
            "target_shortfall_bytes": max(0, profile.get("content_target_min_bytes", 0) - knowledge),
            "target_overflow_bytes": max(0, knowledge - profile.get("content_target_max_bytes", knowledge)),
            "learning_coverage": learning_coverage(assets)}
    actual_status = ("not-specified" if "content_target_min_bytes" not in profile else
                     "below-target" if knowledge < profile["content_target_min_bytes"] else
                     "above-target" if knowledge > profile["content_target_max_bytes"] else "in-range")
    result["actual_target_window_status"] = actual_status
    result["target_window_status"] = actual_status
    result["content_floor_applies"] = "content_target_min_bytes" in profile and not (selection and selection.get("customized") is True)
    result["content_floor_met"] = not result["content_floor_applies"] or result["target_shortfall_bytes"] == 0
    result["content_ceiling_applies"] = "content_target_max_bytes" in profile and not (selection and selection.get("customized") is True)
    result["content_ceiling_met"] = not result["content_ceiling_applies"] or result["target_overflow_bytes"] == 0
    result["content_complete"] = result["content_floor_met"] and result["content_ceiling_met"] and (not selection or not selection["incomplete_resources"])
    if selection is not None:
        target = max(content, selection["planned_total_bytes"])
        planned_final = target + profile["search_budget_bytes"] + overhead + acquisition
        if planned_final + profile["reserve_bytes"] > profile["capacity_bytes"]:
            raise CatalogError(f"Selected resource targets exceed capacity: {planned_final:,} bytes "
                               f"plus {profile['reserve_bytes']:,} reserve. Exclude resources or choose a larger profile.")
        result.update(content_selection=selection, planned_final_bytes=planned_final,
                      content_target_min_bytes=profile.get("content_target_min_bytes"),
                      content_target_max_bytes=profile.get("content_target_max_bytes"))
        if "content_target_min_bytes" in profile:
            actual = selection["content_target_bytes"]
            result["target_window_status"] = ("below-target" if actual < profile["content_target_min_bytes"]
                else "above-target" if actual > profile["content_target_max_bytes"] else "in-range")
    # Extraction files are released after a durable, verified raw-index
    # checkpoint, before the browser transport is packaged. They never need
    # to coexist with the finished transport on a fresh build.
    working_peak = raw + max(scratch - raw, profile["search_budget_bytes"])
    result["index_working_peak_bytes"] = working_peak
    result["in_place_peak_budget_bytes"] = (result.get("planned_final_bytes", final)
        - profile["search_budget_bytes"] + max(working_peak, temporary_bytes + expanded_bytes) + profile["reserve_bytes"])
    result["in_place_target_budget_fits"] = result["in_place_peak_budget_bytes"] <= profile["capacity_bytes"]
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
