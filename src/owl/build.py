"""Build an OWL SSD without formatting, deleting unrelated data, or running binaries."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

import yaml

from . import __version__
from .archive import ZipSource, document_assets, order_archive_assets
from .catalog import (CatalogError, capacity_plan, fingerprint, load_catalog,
                      load_profiles, read_yaml, resolve_content, resolve_locked_content, validate_catalog)
from .download import download, verified
from .layout import checksum_name, content_root, managed_path
from .runtime import file_lock as _lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file
from .transfer import resume_copy
from .verify import verify_drive

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUT = [f"CRITICAL/{name}" for name in ("FIRST_AID", "MEDICAL", "WATER_SANITATION", "FOOD", "AGRICULTURE", "ELECTRICAL", "MECHANICAL", "SHELTER")]
LAYOUT += ["REFERENCE", "BOOKS/TEXTBOOKS", "MAPS", "ZIM/WIKIPEDIA", "ZIM/WIKIMED", "ZIM/WIKTIONARY", "ZIM/OTHER",
           "SOFTWARE/ANDROID", "SOFTWARE/WINDOWS", "SOFTWARE/MACOS", "SOFTWARE/LINUX", "SEARCH", "INDEX"]
CORE_OUTPUTS = ["INVENTORY.json", "BUILD_INFO.json", "SHA256SUMS.txt", "LOCKED_CATALOG.yaml", "CONTENT_SELECTION.json", "VERIFY.py", "SOURCE_NOTES.txt",
                "SEARCH.html", "SEARCH/manifest.js", "SEARCH/search.js", "SEARCH/coverage.json"]


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _event(progress, **fields) -> None:
    """Structured job status is separate from the full, human-readable log."""
    callback = getattr(progress, "event", None)
    if callable(callback):
        callback(**fields)


def _root(path: Path) -> Path:
    # Canonicalize the parent (e.g. macOS /tmp -> /private/tmp), but never a
    # symlink supplied as the target/cache directory itself.
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise SafetyError(f"Refusing symlink directory: {path}")
    result = path.parent.resolve() / path.name
    reject_symlinks(result)
    return result


def _owned_directory(path: Path) -> None:
    reject_symlinks(path)
    marker = path / "owner.json"
    if path.exists() and not marker.exists() and any(path.iterdir()):
        raise SafetyError(f"Reserved OWL directory already contains unrelated files: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        reject_symlinks(marker)
        if json.loads(marker.read_text()) != {"owner": "offline-wandering-library", "schema_version": 1}:
            raise SafetyError(f"Unrecognized OWL state directory: {path}")
    else:
        atomic_write(marker, _json({"owner": "offline-wandering-library", "schema_version": 1}))


def _state(path: Path) -> dict:
    reject_symlinks(path)
    if not path.exists():
        return {"schema_version": 1, "managed": [], "assets": {}, "complete": False}
    result = json.loads(path.read_text())
    if result.get("schema_version") != 1 or not isinstance(result.get("managed"), list) or not isinstance(result.get("assets"), dict):
        raise SafetyError("Invalid build state")
    for relative in result["managed"]:
        managed_path(path.parent.parent, relative)
    return result


def check_space(path: Path, required: int) -> None:
    existing = path
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    if free < required:
        raise SafetyError(f"Insufficient disk space at {path}: need {required:,} bytes, available {free:,}")


def check_space_groups(allocations: list[tuple[Path, int]]) -> list[dict]:
    """Add simultaneous allocations sharing a filesystem, including off-drive scratch/cache."""
    groups = {}
    for path, amount in allocations:
        existing = path
        while not existing.exists():
            existing = existing.parent
        group = groups.setdefault(existing.stat().st_dev, {"path": path, "required_bytes": 0, "uses": []})
        group["required_bytes"] += amount
        group["uses"].append(str(path))
    for group in groups.values():
        group["required_bytes"] = max(0, group["required_bytes"])
        check_space(group["path"], group["required_bytes"])
    return [{**g, "path": str(g["path"])} for g in groups.values()]


def check_space_phases(phases: dict[str, list[tuple[Path, int]]]) -> list[dict]:
    """Check each sequential phase, taking its peak separately per filesystem.

    A negative allocation is an owned checkpoint released before that phase;
    it can offset requirements only on the same filesystem.
    """
    combined = {}
    for phase, allocations in phases.items():
        for group in check_space_groups(allocations):
            path, _ = _directory_anchor(Path(group["path"]))
            item = combined.setdefault(path.stat().st_dev, {
                "path": group["path"], "required_bytes": 0, "uses": [], "phases": {}})
            item["required_bytes"] = max(item["required_bytes"], group["required_bytes"])
            item["phases"][phase] = group["required_bytes"]
            item["uses"] = sorted(set(item["uses"]) | set(group["uses"]))
    return list(combined.values())


def _expected(asset: dict, state: dict, spool: Path | None = None) -> str | None:
    previous = state["assets"].get(asset["id"], {})
    expected = asset["sha256"] or (previous.get("sha256") if previous.get("fingerprint") == fingerprint(asset) else None)
    if not expected and spool is not None:
        # A process can stop between promotion and its state write. The observed
        # staging digest was saved before promotion, so recover that baseline.
        metadata = safe_path(spool, fingerprint(asset) + ".json")
        if metadata.exists():
            saved = json.loads(metadata.read_text())
            if saved.get("fingerprint") == fingerprint(asset):
                expected = saved.get("sha256")
    return expected


def _partial_bytes(path: Path, maximum: int) -> int:
    """Credit owned staging storage already allocated, without trusting its bytes."""
    reject_symlinks(path)
    if path.exists() and not path.is_file():
        raise SafetyError(f"Staging path is not a file: {path}")
    return min(path.stat().st_size, maximum) if path.exists() else 0


def _directory_anchor(path: Path) -> tuple[Path, tuple[int, int]]:
    existing = path
    while not existing.exists():
        existing = existing.parent
    reject_symlinks(existing)
    info = existing.stat()
    return existing, (info.st_dev, info.st_ino)


def _transfer_space(target, cache, assets, reusable, state):
    target_bytes = cache_bytes = 0
    for asset in assets:
        if reusable[asset["id"]]:
            continue
        size = asset["size_bytes"]
        if "archive_member" in asset or "generation" in asset:
            # Members stream into target-owned partials, never the download
            # cache. They restart safely; reserve their full output size.
            target_bytes += size
            continue
        key = asset["sha256"] or fingerprint(asset)
        spool = cache or safe_path(target, ".owl/downloads")
        staged = safe_path(spool, key)
        expected = _expected(asset, state, spool)
        pending = 0 if verified(staged, size, expected) else size - _partial_bytes(
            safe_path(spool, key + ".part"), size)
        if cache:
            cache_bytes += pending
            target_bytes += size - _partial_bytes(safe_path(target, ".owl/downloads/" + key + ".copy"), size)
        else:
            target_bytes += pending
    return target_bytes, cache_bytes


def _build_extraction_directory(work, extraction, source):
    identity = {'source_sha256':source['sha256'], 'selection':extraction}
    digest = hashlib.sha256(_json(identity)).hexdigest()
    return safe_path(work, 'acquisition-inputs/extract-' + digest)


def build(target: Path, *, catalog: Path, profiles_dir: Path, profile_name: str,
          cache_dir: Path | None = None, work_dir: Path | None = None,
          index_cache_dir: Path | None = None, index_cache_budget_bytes: int | None = None,
          allow_local: bool = False, plan_only: bool = False,
          resources_catalog: Path | None = None, include=(), exclude=(), editions=(),
          extra_catalogs=(),
          allow_incomplete: bool = False, navigation_dir: Path | None = None,
          strict_coverage: bool = False, progress=print) -> dict:
    from .navigation import GENERATED_PATHS, generate_navigation
    from .search import (build_search, check_extractors, checkpoint_usage,
                         probe_completed_search, probe_raw_checkpoint)

    if index_cache_budget_bytes is not None and (
            type(index_cache_budget_bytes) is not int or index_cache_budget_bytes <= 0):
        raise CatalogError("Index cache budget must be a positive number of bytes")
    if index_cache_budget_bytes is not None and index_cache_dir is None:
        raise CatalogError("--index-cache-budget-bytes requires --index-cache-dir")
    _event(progress, phase="preflight")
    profiles = load_profiles(profiles_dir)
    if profile_name not in profiles:
        raise CatalogError(f"Unknown profile {profile_name!r}; choose {', '.join(profiles)}")
    all_assets = load_catalog(catalog, profiles, allow_local)
    from .acquisition.model import validate_recipes, build_inputs, build_input_extractions
    from .acquisition.runtime import (Generator, selected_recipes, order_assets,
                                      allocation as generation_allocation, directory_bytes,
                                      preflight_recipes)
    recipe_records = list(read_yaml(catalog).get("acquisition_recipes", []))
    extra_assets = []
    for extra_catalog in extra_catalogs:
        extra = read_yaml(Path(extra_catalog)).get('assets')
        if not isinstance(extra, list) or any(not isinstance(a, dict) or a.get("status", "resolved") != "resolved" or not a.get("sha256") for a in extra):
            raise CatalogError("Additional catalogs must contain resolved assets with pinned SHA-256 values")
        extra_assets.extend(extra)
        recipe_records.extend(read_yaml(Path(extra_catalog)).get("acquisition_recipes", []))
    # Validate the entire namespace before selecting or writing any output.
    combined = validate_catalog({"schema_version": 1, "assets": all_assets + extra_assets,
                                 "acquisition_recipes": recipe_records}, profiles, allow_local)
    extra_ids = {a['id'] for a in extra_assets}
    extra_assets = [a for a in combined if a['id'] in extra_ids]
    recipes = validate_recipes(recipe_records, assets=combined, allow_local=allow_local)
    navigation = None
    if navigation_dir is not None:
        from .atlas_model import load_navigation
        navigation = load_navigation(navigation_dir, combined)
    elif strict_coverage:
        raise CatalogError("--strict-coverage requires --navigation-dir")
    profile = profiles[profile_name]
    lock = read_yaml(catalog).get("selection_lock")
    if lock is not None:
        if include or exclude or editions or extra_catalogs:
            raise CatalogError("Customize the source catalog, not a locked selection")
        assets, unresolved, selection = resolve_locked_content(all_assets, profile, lock)
    else:
        assets, unresolved, selection = resolve_content(
            all_assets, profile, resources_path=resources_catalog or catalog.with_name("resources.yaml"),
            include=include, exclude=exclude, editions=editions)
    if extra_assets:
        source_ids = {a["id"] for a in assets}
        known_sources = {a["id"]: a for a in all_assets}
        for extra in extra_assets:
            parent = extra.get("derived_from_asset_id")
            if parent and parent not in known_sources:
                raise CatalogError(f"{extra['id']}: unknown derivation source {parent}")
            if parent and (not known_sources[parent].get("sha256") or
                           extra.get("source_archive_sha256") != known_sources[parent]["sha256"]):
                raise CatalogError(f"{extra['id']}: derivative source checksum differs from the selected catalog; export the selected edition")
        additions = [a for a in extra_assets if not a.get("derived_from_asset_id") or
                     a["derived_from_asset_id"] in source_ids]
        assets.extend({**a, "profiles": [profile_name]} for a in additions)
        if (any(a["format"].lower() == "zim" for a in assets) and
                not any(a["destination"].startswith("SOFTWARE/") for a in assets)):
            raise CatalogError("Additional ZIM content must include a pinned bundled reader")
        if selection is not None:
            selection["additional_asset_ids"] = [a["id"] for a in additions]
            # Explicit imports need their own space. Do not let a derivative
            # silently consume another still-unresolved collection's allowance.
            extra_bytes = sum(a["size_bytes"] for a in additions)
            selection["planned_total_bytes"] += extra_bytes
            selection["content_target_bytes"] += extra_bytes
            selection["resolved_asset_bytes"] += extra_bytes
    recipes = selected_recipes(assets, recipes)
    assets = order_assets(order_archive_assets(assets), recipes)
    if not assets and not plan_only:
        raise CatalogError(f"Profile {profile_name} has no resolved content")
    plan = capacity_plan(assets, profile, selection)
    generation_budget = plan["acquisition_workspace_budget_bytes"]
    if generation_budget != generation_allocation(recipes, assets):
        raise CatalogError("Generated workspace accounting differs from its pinned recipes")
    content_complete = plan["content_complete"]
    drive_root = _root(target)
    target = content_root(drive_root)
    for asset in assets:
        checksum_name(asset["destination"])  # Include LIBRARY/ in portable path limits before any writes.
    cache = _root(cache_dir) / "owl-v1" if cache_dir else None
    work = _root(work_dir) if work_dir else target / ".owl/work"
    temporary_sources = build_inputs(recipes)
    input_extractions = build_input_extractions(recipes)
    input_spool = cache or safe_path(work, 'acquisition-inputs')
    plan['build_input_work_bytes'] = plan['build_input_expanded_bytes'] + (0 if cache else plan['build_input_download_bytes'])
    plan['build_input_cache_bytes'] = plan['build_input_download_bytes'] if cache else 0
    input_cache_on_drive = bool(cache and cache.is_relative_to(drive_root))
    plan['build_input_cache_on_drive'] = input_cache_on_drive
    # Unlike default work inputs, a requested cache survives the indexing phase.
    if input_cache_on_drive:
        base_peak = plan.get('planned_final_bytes', plan['estimated_final_bytes']) - plan['search_budget_bytes'] + plan['reserve_bytes']
        plan['in_place_peak_budget_bytes'] = base_peak + max(plan['index_working_peak_bytes'],plan['build_input_expanded_bytes']) + plan['build_input_cache_bytes']
        plan['in_place_target_budget_fits'] = plan['in_place_peak_budget_bytes'] <= profile['capacity_bytes']
    index_cache = _root(index_cache_dir) if index_cache_dir else None
    cache_used = cache_allowance = 0
    if index_cache is not None:
        from .search_cache import cache_usage
        cache_used = cache_usage(index_cache)
        cache_allowance = index_cache_budget_bytes or plan["search_budget_bytes"]
        if cache_used > cache_allowance:
            raise SafetyError("Retained index cache exceeds --index-cache-budget-bytes; "
                              "increase its allowance or choose another cache directory")
        if index_cache.is_relative_to(drive_root) and not index_cache.is_relative_to(target / ".owl"):
            raise SafetyError("An index cache inside the library must be under LIBRARY/.owl/; "
                              "choose a separate directory for a shared cache")
    plan["index_cache_budget_bytes"] = cache_allowance
    plan["retained_index_cache_bytes"] = cache_used
    plan["remaining_index_cache_allocation_bytes"] = cache_allowance - cache_used
    cache_on_drive = index_cache is not None and index_cache.is_relative_to(drive_root)
    plan["index_cache_on_drive"] = cache_on_drive
    if cache_on_drive:
        plan["in_place_peak_budget_bytes"] += cache_allowance
        plan["in_place_target_budget_fits"] = plan["in_place_peak_budget_bytes"] <= profile["capacity_bytes"]
        if not plan["in_place_target_budget_fits"]:
            raise SafetyError("Retained index cache plus the in-place build exceeds this profile's capacity; "
                              "put --index-cache-dir on a separate disk or use a larger profile")
    for workspace in (cache, work):
        if workspace is not None and workspace.is_relative_to(drive_root) and not workspace.is_relative_to(target):
            raise SafetyError("Cache/work directories inside an OWL must be under LIBRARY/; "
                              "choose LIBRARY/.owl/ or a separate external directory")
    # Hashing during preflight can take hours. Capture the mounted filesystem
    # before it starts, not after a disappeared mount could have been recreated.
    anchors = [_directory_anchor(path) for path in (target, work, cache, index_cache) if path is not None]
    _event(progress, total_assets=len(assets), completed_assets=0)
    progress(f"OWL {__version__} | {profile_name} | {drive_root}")
    progress(f"Content on disk: {plan['content_bytes']:,} bytes ({plan['content_bytes'] / 1e9:.2f} GB); "
             f"download: {plan['download_bytes']:,}; extracted ZIP outputs: {plan['archive_output_bytes']:,}")
    progress(f"Pinned knowledge: {plan['pinned_knowledge_bytes']:,} bytes; readers: {plan['pinned_reader_bytes']:,}; "
             f"directly readable: {plan['direct_readable_bytes']:,}")
    if not plan["content_floor_met"]:
        progress(f"CONTENT BELOW MINIMUM: {plan['target_shortfall_bytes']:,} knowledge bytes remain below this profile's "
                 "minimum; unresolved plans do not count as installed content.")
        if not plan_only and not allow_incomplete:
            raise CatalogError("Pinned knowledge does not meet the default profile content minimum. "
                               "Resolve more sources or explicitly use --allow-incomplete. No files were written.")
    if not plan["content_ceiling_met"]:
        progress(f"CONTENT ABOVE MAXIMUM: {plan['target_overflow_bytes']:,} knowledge bytes exceed this profile's "
                 "maximum; revise the default selection to fit its declared content window.")
        if not plan_only and not allow_incomplete:
            raise CatalogError("Pinned knowledge exceeds the default profile content maximum. "
                               "Revise the selection or explicitly use --allow-incomplete. No files were written.")
    if selection:
        progress(f"Selected resource content target: {selection['content_target_bytes']:,} bytes; "
                 f"reader allowance: {selection['readers_budget_bytes']:,}; "
                 f"planned final with search: {plan['planned_final_bytes']:,}")
        if profile.get("content_target_max_bytes"):
            progress(f"Default content target window: {profile['content_target_min_bytes']:,}–"
                     f"{profile['content_target_max_bytes']:,} bytes (not an automatic fill quota)")
            progress(f"Content allocation: {plan['target_window_status']}. Unallocated space is not filled automatically.")
        progress("Selected resources: " + ", ".join(selection["selected_ids"]))
        for row in selection["incomplete_resources"]:
            progress(f"RESOURCE {row['status'].upper()}: {row['id']}: {row['reason']}")
        if not content_complete and not plan_only and not allow_incomplete:
            raise CatalogError("Selected resource collections are incomplete. Review --list-resources/--plan; "
                               "resolve or --exclude them, or explicitly use --allow-incomplete to build only "
                               "verified available files. No files were written.")
        if not content_complete:
            progress("CONTENT INCOMPLETE: available files do not fulfill the selected resource collection targets.")
    progress(f"Estimated final ceiling: {plan['estimated_final_bytes']:,} bytes; reserve: {plan['reserve_bytes']:,}; indexing scratch budget: {plan['index_scratch_budget_bytes']:,}")
    progress(f"In-place peak planning allowance for selected content: {plan['in_place_peak_budget_bytes']:,} bytes "
             "(content, peak indexing phase and reserve; excludes pre-existing old versions)")
    if not plan["in_place_target_budget_fits"]:
        progress("SPACE WARNING: the complete selected content targets plus current scratch allowances exceed "
                 "this profile's nominal drive size. The include list/index budget needs tuning before those "
                 "targets can be fulfilled in place. Actual available-file allocations are checked below.")
    for shelf, coverage in plan["learning_coverage"].items():
        floor = profile.get("minimum_coverage", {}).get(shelf, 0)
        progress(f"{shelf}: {coverage['count']} directly readable; {coverage['required_critical_count']} required critical (minimum {floor})")
    for asset in unresolved:
        progress(f"UNRESOLVED (excluded): {asset['id']}: {asset['unresolved_reason']}")
    generated = [*GENERATED_PATHS, *CORE_OUTPUTS]
    state_path = safe_path(target, ".owl/state.json")
    state = _state(state_path)
    if safe_path(target, ".owl/atlas-job.json").exists():
        raise SafetyError("An interrupted human-index publication is pending. Rerun its build_atlas.py command before rebuilding the drive.")
    owned = set(state["managed"])
    spool = cache or safe_path(target, ".owl/downloads")
    for relative in generated:
        path = managed_path(target, relative)
        if path.exists() and (relative not in owned or not path.is_file()):
            raise SafetyError(f"Generated output would overwrite an unowned file/directory: {path}")
    reusable = {}
    for asset in assets:
        path = safe_path(target, asset["destination"])
        checksum = _expected(asset, state, spool)
        if path.is_file():
            progress(f"CHECK {asset['destination']} (streaming SHA-256; safe to interrupt)")
        reusable[asset["id"]] = verified(path, asset["size_bytes"], checksum)
        if path.exists() and not reusable[asset["id"]] and asset["destination"] not in owned:
            raise SafetyError(f"Content destination contains an unverified, unowned file: {path}")
        if path.exists() and not path.is_file():
            raise SafetyError(f"Content destination is a directory: {path}")
    missing_bytes = sum(a["size_bytes"] for a in assets if not reusable[a["id"]])
    plan["remaining_content_bytes"] = missing_bytes
    progress(f"Verified reusable files: {sum(reusable.values())}/{len(assets)}; remaining content: {missing_bytes:,} bytes")
    transfer_bytes, cache_bytes = _transfer_space(target, cache, assets, reusable, state)
    active_input_recipes = {identity: recipe for identity, recipe in recipes.items()
                           if any(not reusable[oid] for oid in recipe['output_asset_ids'])}
    needed_inputs = build_inputs(active_input_recipes)
    # Keep the full selected allowlist and its owned directory stable when an
    # interrupted build has already finished one recipe sharing this archive.
    needed_extractions = {identity: input_extractions[identity]
                          for identity in build_input_extractions(active_input_recipes)}
    input_pending = 0
    input_paths = {}
    pending_hashes = set()
    for identity, source in needed_inputs.items():
        staged = safe_path(input_spool, source['sha256'])
        if staged.exists() and not verified(staged, source['size_bytes'], source['sha256']):
            raise SafetyError(f'Build-only input changed or cache is corrupt: {identity}; preserve evidence and use a new work/cache directory')
        input_paths[identity] = staged
        if not staged.exists() and source['sha256'] not in pending_hashes:
            pending_hashes.add(source['sha256'])
            input_pending += source['size_bytes'] - _partial_bytes(
                safe_path(input_spool, source['sha256'] + '.part'), source['size_bytes'])
    # Report selected retained cache bodies even on complete-output reuse, and
    # reclaim default work originals if interruption followed the last output.
    for identity, source in temporary_sources.items():
        path = safe_path(input_spool,source['sha256'])
        if path.exists():
            if not verified(path,source['size_bytes'],source['sha256']):
                raise SafetyError(f'Build-only input changed or cache is corrupt: {identity}')
            input_paths[identity]=path
    expanded_pending = 0
    extracted_paths = {}
    for source_id, extraction in input_extractions.items():
        folder = _build_extraction_directory(work,extraction,temporary_sources[source_id])
        for member in extraction['members']:
            path = safe_path(folder,'files/'+member['path'])
            if path.exists():
                if not verified(path,member['size_bytes'],member['sha256']):
                    raise SafetyError('Build-only extracted member changed: '+member['id'])
                extracted_paths[member['id']]=(path,member)
            elif source_id in needed_extractions:
                expanded_pending += member['size_bytes']
    plan['remaining_build_input_allocation_bytes'] = input_pending
    plan['remaining_build_input_expanded_allocation_bytes'] = expanded_pending
    plan['retained_build_input_bytes'] = directory_bytes(input_spool) if not cache else sum(
        path.stat().st_size for path in set(input_paths.values()) if path.exists())
    checkpoint = checkpoint_usage(target, work_dir=work)
    # Credit retained staging files: their allocation already reduced disk free
    # space. Their bytes are independently checked before any later promotion.
    # Finished script chunks include base64 overhead. Their raw intermediate
    # remains on the target even when the extraction workspace is elsewhere.
    # Divide the existing scratch allowance between these two filesystems.
    raw_budget = plan["index_serialization_budget_bytes"]
    raw_bytes = max(0, raw_budget - checkpoint["output_bytes"])
    search_bytes = plan["search_budget_bytes"]
    scratch_bytes = max(0, plan["index_extraction_budget_bytes"] - checkpoint["scratch_bytes"])
    search_reuse = raw_reuse = None
    if assets and all(reusable.values()):
        inputs = [{**asset, "sha256": _expected(asset, state, spool),
                   "verification": "pinned" if asset["sha256"] else "observed"} for asset in document_assets(assets)]
        search_reuse = probe_completed_search(target, inputs, progress=progress)
        if search_reuse is None:
            raw_reuse = probe_raw_checkpoint(target, inputs, work_dir=work, progress=progress)
    if search_reuse is not None:
        if search_reuse["generated_bytes"] > plan["search_budget_bytes"]:
            raise SafetyError("Verified existing search exceeds search_budget_bytes; increase the allowance "
                              "or change the selected content before rebuilding")
        # Existing source/index bytes already reduce filesystem free space. Only
        # freshly generated UI/coverage need replacement space for proven reuse.
        # build_search independently verifies this proof again after locking.
        search_bytes = search_reuse["rewrite_bytes"]
        raw_bytes = scratch_bytes = 0
        progress(f"Verified complete search reuse: {search_reuse['index_bytes']:,} logical bytes; "
                 f"reserving {search_bytes:,} bytes for UI/coverage rewrites, without new index scratch.")
    elif raw_reuse is not None:
        if raw_reuse['generated_bytes'] > plan['search_budget_bytes']:
            raise SafetyError("Serialized search exceeds search_budget_bytes; increase the allowance "
                              "or change the selected content before rebuilding")
        search_bytes = raw_reuse['remaining_pack_allocation_bytes']
        raw_bytes = scratch_bytes = 0
        progress(f"Verified serialized search checkpoint: {raw_reuse['index_bytes']:,} bytes; "
                 "only browser packaging remains.")
    generation_used = directory_bytes(safe_path(target, '.owl/acquisition'))
    generation_outputs = sum(a['size_bytes'] for a in assets if 'generation' in a)
    if generation_used > generation_budget + generation_outputs and recipes:
        raise SafetyError('Retained acquisition workspace exceeds its selected allowance')
    plan['retained_acquisition_bytes'] = generation_used
    input_metadata = plan['build_input_metadata_bytes']
    raw_input_metadata = 65536 * sum(bool(recipe.get('build_inputs')) for recipe in recipes.values())
    common = [(target, transfer_bytes + plan["reserve_bytes"] + 16 * 1024 * 1024 +
               generation_budget - input_metadata)]
    if input_metadata:
        common.extend([(input_spool,raw_input_metadata),(work,input_metadata-raw_input_metadata)])
    if cache:
        common.append((cache, cache_bytes))
    if index_cache is not None:
        common.append((index_cache, cache_allowance - cache_used))
        progress(f"Index cache: {index_cache}; retained {cache_used:,} bytes, "
                 f"allowance {cache_allowance:,} bytes (separate from extraction scratch)")
    plan["index_serialization_budget_bytes"] = raw_budget
    plan["remaining_transfer_allocation_bytes"] = transfer_bytes
    plan["remaining_cache_allocation_bytes"] = cache_bytes
    plan["retained_search_checkpoint_bytes"] = checkpoint
    plan["search_reuse_verified"] = search_reuse is not None
    plan["raw_search_reuse_verified"] = raw_reuse is not None
    plan["remaining_search_output_allocation_bytes"] = search_bytes
    plan["remaining_index_serialization_allocation_bytes"] = raw_bytes
    plan["remaining_index_scratch_allocation_bytes"] = scratch_bytes
    phases = {"packaging": [*common, (target, raw_bytes + search_bytes)]}
    if temporary_sources:
        phases['generation'] = [*common, (input_spool, input_pending), (work,expanded_pending)]
        if cache:
            # The cached source remains allocated through later phases too.
            for phase in phases.values():
                if phase is not phases['generation']:
                    phase.append((cache, input_pending))
    if search_reuse is None:
        # These files are deleted only after a durable raw-index checkpoint.
        # Do not transfer their space credit onto another filesystem.
        phases["packaging"].append((work, -min(checkpoint["scratch_bytes"], plan["index_extraction_budget_bytes"])))
        if raw_reuse is None:
            phases["extraction"] = [*common, (target, raw_bytes), (work, scratch_bytes)]
            if cache and temporary_sources:
                phases['extraction'].append((cache, input_pending))
    plan["filesystem_allocations"] = check_space_phases(phases)
    plan["required_free_bytes"] = sum(item["required_bytes"] for item in plan["filesystem_allocations"] if str(target) in item["uses"])
    if plan_only:
        progress("Plan only: no files created or downloaded. Index and scratch allowances are checked during building; "
                 "compressed archive size does not predict the required index space.")
        return plan
    if temporary_sources:
        local_inputs = input_spool.is_relative_to(drive_root)
        local_expanded = work.is_relative_to(drive_root)
        if local_inputs or local_expanded:
            needed_bytes=sum({s['sha256']:s['size_bytes'] for s in needed_inputs.values()}.values()) if local_inputs else 0
            expanded_bytes=sum(member['size_bytes'] for extraction in needed_extractions.values()
                               for member in extraction['members']) if local_expanded else 0
            phases_peak = (max(plan['index_working_peak_bytes'],expanded_bytes) + plan['build_input_download_bytes']
                           if input_cache_on_drive else max(plan['index_working_peak_bytes'],needed_bytes+expanded_bytes))
            actual_peak = (plan['content_bytes'] + 16 * 1024 * 1024 + generation_budget +
                           phases_peak + plan['reserve_bytes'])
            if actual_peak > profile['capacity_bytes']:
                raise SafetyError('Build-only sources and generated content exceed the profile peak capacity; use a separate work/cache disk')
    preflight_recipes(recipes)
    check_extractors(document_assets(assets))
    private = target / ".owl"
    with ExitStack() as guards:
        for anchor, identity in anchors:
            try:
                info = anchor.stat(follow_symlinks=False)
                unchanged = (info.st_dev, info.st_ino) == identity
            except OSError:
                unchanged = False
            if not unchanged:
                raise SafetyError(f"Build directory changed during preflight; reconnect the original drive and rerun: {anchor}")
            guards.enter_context(guard_directory(anchor))
        reject_symlinks(target)
        target.mkdir(parents=True, exist_ok=True)
        guards.enter_context(guard_directory(drive_root))
        guards.enter_context(guard_directory(target))
        _owned_directory(private)
        guards.enter_context(_lock(safe_path(target, ".owl/build.lock")))
        # Re-read after acquiring lock; detect another completed builder between
        # read-only preflight and lock acquisition rather than use stale state.
        current = _state(state_path)
        if current != state:
            raise SafetyError("Build state changed during preflight; rerun")
        if cache:
            _owned_directory(cache)
            guards.enter_context(guard_directory(cache))
        if index_cache is not None:
            reject_symlinks(index_cache)
            index_cache.mkdir(parents=True, exist_ok=True)
            guards.enter_context(guard_directory(index_cache))
        for relative in LAYOUT:
            safe_path(target, relative).mkdir(parents=True, exist_ok=True)
        safe_path(target, ".owl/downloads").mkdir(exist_ok=True)
        reject_symlinks(work)
        work.mkdir(parents=True, exist_ok=True)
        guards.enter_context(guard_directory(work))
        if (needed_inputs and not cache) or needed_extractions:
            input_work=safe_path(work,'acquisition-inputs')
            _owned_directory(input_work)
            guards.enter_context(guard_directory(input_work))
        state["complete"] = False
        state["phase"] = "content"
        _event(progress, phase="content")
        state["managed"] = sorted(owned | set(generated) | {a["destination"] for a in assets})
        atomic_write(state_path, _json(state))
        input_receipts = []
        for identity, source in needed_inputs.items():
            staged = input_paths[identity]
            with _lock(safe_path(input_spool, source['sha256'] + '.lock')):
                if staged.exists() and not verified(staged, source['size_bytes'], source['sha256']):
                    raise SafetyError(f'Build-only input changed during acquisition: {identity}')
                if not staged.exists():
                    download(source, staged, repo_root=REPO_ROOT, progress=progress)
                if not verified(staged, source['size_bytes'], source['sha256']):
                    raise SafetyError(f'Build-only input failed verification: {identity}')
                input_receipts.append({'id':identity,'sha256':source['sha256'],'size_bytes':source['size_bytes'],
                                       'verification':'pinned'})
        for source_id, extraction in needed_extractions.items():
            from .acquisition.sevenzip import extract
            folder=_build_extraction_directory(work,extraction,temporary_sources[source_id])
            members=[{key:member[key] for key in ('path','size_bytes','sha256')} for member in extraction['members']]
            paths=extract(input_paths[source_id],temporary_sources[source_id],members,folder,
                          max_bytes=extraction['max_bytes'],max_files=extraction['max_files'],progress=progress,
                          timeout=extraction.get('timeout_seconds',3600),
                          before_write=lambda size:check_space(work,size+(profile['reserve_bytes'] if work.is_relative_to(drive_root) else 0)))
            for member in extraction['members']:
                input_paths[member['id']]=paths[member['path']]
                extracted_paths[member['id']]=(paths[member['path']],member)
        inventory_assets = []
        selected_by_id = {asset["id"]: asset for asset in assets}
        zip_sources = {}
        generator = Generator(target, assets, recipes, progress, source_paths=input_paths)
        for asset_number, asset in enumerate(assets):
            state["active_asset"] = asset["id"]
            _event(progress, active_asset=asset["id"], completed_assets=asset_number)
            atomic_write(state_path, _json(state))
            destination = safe_path(target, asset["destination"])
            expected = _expected(asset, state, spool)
            if reusable[asset["id"]]:
                digest = expected
                progress(f"REUSE {asset['destination']}")
            elif "generation" in asset:
                digest = generator.materialize(asset, destination)
            elif "archive_member" in asset:
                source_id = asset["archive_member"]["source_asset_id"]
                if source_id not in zip_sources:
                    source = selected_by_id[source_id]
                    zip_sources[source_id] = guards.enter_context(ZipSource(
                        safe_path(target, source["destination"]), source))
                digest = zip_sources[source_id].extract(asset, destination,
                    part=safe_path(target, ".owl/downloads/" + fingerprint(asset) + ".extract.part"),
                    progress=progress)
            else:
                key = asset["sha256"] or fingerprint(asset)
                spool = cache or safe_path(target, ".owl/downloads")
                staged = safe_path(spool, key)
                metadata_path = safe_path(spool, key + ".json")
                with _lock(safe_path(spool, key + ".lock")):
                    cached_digest = expected
                    if not cached_digest and metadata_path.exists():
                        saved = json.loads(metadata_path.read_text())
                        if saved.get("fingerprint") == fingerprint(asset):
                            cached_digest = saved.get("sha256")
                    if verified(staged, asset["size_bytes"], cached_digest):
                        digest = cached_digest
                        progress(f"CACHE {asset['id']}")
                    else:
                        pinned = {**asset, "sha256": expected}
                        digest = download(pinned, staged, repo_root=REPO_ROOT, progress=progress)
                        atomic_write(metadata_path, _json({"sha256": digest, "fingerprint": fingerprint(asset)}))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    reject_symlinks(destination)
                    if cache:
                        copy = safe_path(target, ".owl/downloads/" + key + ".copy")
                        resume_copy(staged, destination, size=asset["size_bytes"],
                                    checksum=digest, part=copy, progress=progress)
                    else:
                        os.replace(staged, destination)
            state["assets"][asset["id"]] = {"sha256": digest, "fingerprint": fingerprint(asset)}
            atomic_write(state_path, _json(state))
            inventory_assets.append({**asset, "sha256": digest,
                                     "verification": "pinned" if asset["sha256"] else "observed"})
        state.pop("active_asset", None)
        # Outputs and state are durable. These sources are deliberately absent
        # from inventory/checksums/navigation; retain only a requested cache.
        if not cache:
            cleaned = set()
            for identity, path in input_paths.items():
                if identity not in temporary_sources:
                    continue
                if path in cleaned:
                    continue
                source = temporary_sources[identity]
                if not verified(path, source['size_bytes'], source['sha256']):
                    raise SafetyError(f'Build-only input changed before cleanup: {identity}')
                path.unlink()
                cleaned.add(path)
        for identity, (path, member) in extracted_paths.items():
            if not verified(path,member['size_bytes'],member['sha256']):
                raise SafetyError('Extracted build-only input changed before cleanup: '+identity)
            path.unlink()
        state["phase"] = "search"
        _event(progress, phase="search", active_asset=None, completed_assets=0)
        atomic_write(state_path, _json(state))
        progress("Building full-text search and static navigation; large archives may take many hours.")
        readable_assets = document_assets(inventory_assets)
        search_report = build_search(target, readable_assets, work_dir=work, progress=progress,
                                     search_budget_bytes=plan["search_budget_bytes"],
                                     index_scratch_budget_bytes=plan["index_scratch_budget_bytes"],
                                     reserve_bytes=plan["reserve_bytes"], reuse_only=search_reuse is not None,
                                     raw_reuse_only=raw_reuse is not None,
                                     index_cache_dir=index_cache,
                                     index_cache_budget_bytes=cache_allowance if index_cache else None)
        state["managed"] = sorted(set(state["managed"]) | set(search_report["generated_files"]))
        state["phase"] = "navigation"
        _event(progress, phase="navigation", active_asset=None)
        atomic_write(state_path, _json(state))
        for warning in search_report.get("warnings", []):
            progress(f"SEARCH COVERAGE: {warning}")
        inventory = {"schema_version": 1, "assets": inventory_assets, "search": search_report,
                     "build_inputs": [{'id':i,'size_bytes':s['size_bytes'],'sha256':s['sha256']} for i,s in temporary_sources.items()],
                     "build_input_verification": input_receipts,
                     "content_selection": selection, "content_complete": content_complete,
                     "learning_coverage": plan["learning_coverage"],
                     "unresolved": unresolved}
        from .atlas_build import plan_atlas, register_outputs, validate_links, write_outputs
        atlas_pages, atlas_report = plan_atlas(target, readable_assets, navigation, state,
                                              strict_coverage=strict_coverage)
        inventory["navigation"] = atlas_report
        navigation_pages = generate_navigation(target, readable_assets, inventory, search_report, write=False)
        navigation_pages.update(atlas_pages)
        validate_links(target, {**dict.fromkeys(CORE_OUTPUTS, ""), **navigation_pages}, inventory_assets)
        check_space(target, sum(len(text.encode("utf-8")) for text in navigation_pages.values()) + profile["reserve_bytes"])
        register_outputs(target, navigation_pages, state)
        write_outputs(target, navigation_pages)
        nav_files = list(navigation_pages)
        atomic_write(safe_path(target, "INVENTORY.json"), _json(inventory))
        atomic_write(safe_path(target, "CONTENT_SELECTION.json"), _json({
            "schema_version": 1, "profile": profile_name, "content_complete": content_complete,
            "selection": selection}))
        atomic_write(safe_path(target, "LOCKED_CATALOG.yaml"), _json({
            "schema_version": 1, "assets": inventory_assets,
            "acquisition_recipes": list(recipes.values()),
            "selection_lock": {"profile_id": profile_name, "content_selection": selection}}))
        atomic_write(safe_path(target, "VERIFY.py"), Path(__file__).with_name("verify.py").read_bytes())
        source_notes = REPO_ROOT / "docs/sources.md"
        atomic_write(safe_path(target, "SOURCE_NOTES.txt"), source_notes.read_bytes() if source_notes.exists() else
                     b"See INVENTORY.html and LOCKED_CATALOG.yaml for source provenance, licenses and attribution.\n")
        versions = {}
        for package in ("PyYAML", "pypdf", "cryptography", "fonttools", "libzim"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                pass
        info = {"schema_version": 1, "owl_version": __version__, "built_at": datetime.now(timezone.utc).isoformat(),
                "layout": {"entry_page": "START_HERE.html", "content_directory": "LIBRARY",
                           "catalog_paths_relative_to": "LIBRARY", "checksum_paths_relative_to": "drive"},
                "content_selection": selection, "content_complete": content_complete,
                "python_version": sys.version.split()[0], "dependencies": versions,
                "profile": profile, "catalog_sha256": sha256_file(catalog.resolve()), "plan": plan,
                "extra_catalogs": [{"path": str(Path(path)), "sha256": sha256_file(Path(path))}
                                   for path in extra_catalogs],
                "asset_count": len(assets), "unresolved_asset_ids": [a["id"] for a in unresolved],
                "search": search_report, "navigation": atlas_report, "complete": True,
                "integrity_note": "SHA-256 detects damage, not publisher identity. Save SHA256SUMS.txt separately."}
        atomic_write(safe_path(target, "BUILD_INFO.json"), _json(info))
        # Preserve checksum coverage of previous owned search generations. A
        # changed selection never silently prunes files from an existing drive.
        retained_search = {name for name in owned
                           if (name.startswith("SEARCH/chunks/") or name == "SEARCH/library.owl")
                           and safe_path(target, name).is_file()}
        managed = sorted(set(nav_files) | set(search_report["generated_files"]) | retained_search | set(CORE_OUTPUTS) |
                         {a["destination"] for a in assets})
        state["phase"] = "checksums"
        _event(progress, phase="checksums")
        atomic_write(state_path, _json(state))
        progress("Generating checksums (streaming each managed file).")
        # Stream hashes; never load content files into memory.
        expected_files = {a["destination"]: (a["sha256"], a["size_bytes"]) for a in inventory_assets}
        expected_files.update({name: (item["sha256"], item["size_bytes"])
                               for name, item in search_report["file_integrity"].items()})
        checksum_lines = []
        for relative in managed:
            if relative == "SHA256SUMS.txt":
                continue
            path = managed_path(target, relative)
            digest = sha256_file(path)
            if relative in expected_files and (digest, path.stat().st_size) != expected_files[relative]:
                raise SafetyError(f"File changed after verification: {relative}; rerun to repair before completion")
            checksum_lines.append(f"{digest}  {checksum_name(relative)}\n")
        checksums = "".join(checksum_lines)
        atomic_write(safe_path(target, "SHA256SUMS.txt"), checksums.encode())
        final_size = sum(managed_path(target, name).stat().st_size for name in managed)
        if final_size + profile["reserve_bytes"] + generation_budget + (cache_allowance if cache_on_drive else 0) + (plan['build_input_cache_bytes'] if input_cache_on_drive else 0) > profile["capacity_bytes"]:
            raise SafetyError("Actual generated output exceeds profile capacity; files retained, build incomplete")
        check_space(target, profile["reserve_bytes"])
        state["phase"] = "verification"
        _event(progress, phase="verification")
        atomic_write(state_path, _json(state))
        progress("Verifying completed library (reads every managed file).")
        results = verify_drive(drive_root, emit=progress, allow_incomplete=True)
        if results["FAILED"] or results["MISSING"]:
            raise SafetyError("Completed-drive verification failed")
        state["phase"] = "postflight"
        atomic_write(state_path, _json(state))
        _event(progress, phase="postflight")
        from .postflight import audit_build
        postflight = audit_build(drive_root, info={**info, "verification": results})
        state["result"] = postflight
        state["complete"] = True
        state["phase"] = "complete"
        atomic_write(state_path, _json(state))
        _event(progress, phase="complete", active_asset=None, completed_assets=len(assets), total_assets=len(assets))
        progress(f"BUILD COMPLETE{' (PARTIAL CONTENT)' if not content_complete else ''}: {drive_root / 'START_HERE.html'}")
        info["result"] = postflight
        return info


def main(argv=None, *, raise_errors=False, progress=print) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, nargs="?")
    parser.add_argument("--profile", default="critical-64gb")
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/library.yaml")
    parser.add_argument("--extra-catalog", type=Path, action="append", default=[],
                        help="add a pinned local export manifest; repeat for multiple exports; file URLs need --allow-local")
    parser.add_argument("--profiles-dir", type=Path, default=REPO_ROOT / "profiles")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--work-dir", type=Path, help="persistent directory for resumable search checkpoints; reuse on restart")
    parser.add_argument("--index-cache-dir", type=Path,
                        help="persistent shared per-asset search cache; only selected assets are compiled")
    parser.add_argument("--index-cache-budget-bytes", type=int,
                        help="total retained index cache allowance (default: profile search budget)")
    parser.add_argument("--detach", action="store_true", help="start a saved background job and return immediately")
    parser.add_argument("--job-dir", type=Path, help="saved job directory for --detach (default: .owl/jobs/<unique ID>)")
    parser.add_argument("--plan", action="store_true", help="validate and estimate without writing/downloading")
    parser.add_argument("--allow-local", action="store_true", help="allow trusted local fixtures and plain HTTP test sources")
    parser.add_argument("--resources-catalog", type=Path, help="resource registry (default: resources.yaml beside catalog)")
    parser.add_argument("--include", action="append", default=[], metavar="RESOURCE", help="add resource ID or list number; repeat or separate by commas")
    parser.add_argument("--exclude", action="append", default=[], metavar="RESOURCE", help="omit resource ID or list number; repeat or separate by commas; does not delete existing files")
    parser.add_argument("--edition", action="append", default=[], metavar="RESOURCE=EDITION", help="choose a registered direct, compact, or published edition of a selected resource; repeat as needed")
    parser.add_argument("--list-resources", action="store_true", help="list every selectable collection without a target or downloads")
    parser.add_argument("--allow-incomplete", action="store_true", help="explicitly build available verified files from incomplete collections")
    parser.add_argument("--navigation-dir", type=Path, help="generate the static topic atlas using this reviewed YAML directory")
    parser.add_argument("--strict-coverage", action="store_true", help="require critical and textbook subject/learning atlas routes")
    args = parser.parse_args(argv)
    try:
        if args.job_dir and not args.detach:
            raise CatalogError("--job-dir requires --detach")
        if args.detach:
            if args.plan or args.list_resources or args.target is None:
                raise CatalogError("--detach requires a build target and cannot be combined with --plan or --list-resources")
            from .jobs import start_job
            from uuid import uuid4
            job_dir = args.job_dir or Path.cwd() / ".owl/jobs" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
            build_argv = []
            skip = False
            for value in argv:
                if skip:
                    skip = False
                elif value == "--job-dir":
                    skip = True
                elif value != "--detach" and not value.startswith("--job-dir="):
                    build_argv.append(value)
            print(json.dumps(start_job(build_argv, job_dir=job_dir), sort_keys=True))
            return 0
        if args.list_resources:
            if args.extra_catalog:
                raise CatalogError("Use --plan with --extra-catalog; --list-resources lists the source registry")
            from .resources import load_resources, resolve_resources
            if args.edition and read_yaml(args.catalog).get("selection_lock") is not None:
                raise CatalogError("Customize the source catalog, not a locked selection")
            profiles = load_profiles(args.profiles_dir)
            if args.profile not in profiles:
                raise CatalogError(f"Unknown profile: {args.profile}")
            assets = load_catalog(args.catalog, profiles, args.allow_local)
            resources = load_resources(args.resources_catalog or args.catalog.with_name("resources.yaml"), assets)
            report = resolve_resources(assets, profiles[args.profile], resources,
                                       include=args.include, exclude=args.exclude, editions=args.edition)
            rows = {row["id"]: row for row in report["resource_rows"]}
            print("* = selected; GB = effective selected target, or base estimate when unselected. All units decimal.")
            for identity, resource in resources.items():
                selected = "*" if identity in report["selected_ids"] else " "
                number = str(resource.get("number") or "-")
                target_bytes = rows.get(identity, {}).get("effective_target_bytes", resource["target_bytes"])
                row = rows.get(identity, resource)
                print(f"{selected} {number:>2} {identity:28} {row['status']:10} "
                      f"{target_bytes/1e9:7.2f} GB  {resource['title']} [{row.get('edition', 'published')}]")
            print(f"Selected content target: {report['content_target_bytes']:,} bytes; "
                  f"known resolved files: {report['resolved_asset_bytes']:,}; "
                  f"incomplete collections: {len(report['incomplete_resources'])}. "
                  "Targets are planning estimates, not verified download sizes.")
            if "default_resources" not in profiles[args.profile]:
                fixed, _, _ = resolve_content(assets, profiles[args.profile],
                    resources_path=args.resources_catalog or args.catalog.with_name("resources.yaml"),
                    include=args.include, exclude=args.exclude, editions=args.edition)
                print(f"Fixed-profile baseline/selection: {len(fixed)} verified asset definitions, "
                      f"{sum(a['size_bytes'] for a in fixed):,} bytes. "
                      "The stars above describe named additions, not baseline membership.")
            return 0
        if args.target is None:
            parser.error("target is required unless --list-resources is used")
        with interrupt_signals():
            build(args.target, catalog=args.catalog, profiles_dir=args.profiles_dir, profile_name=args.profile,
                  cache_dir=args.cache_dir, work_dir=args.work_dir, allow_local=args.allow_local, plan_only=args.plan,
                  index_cache_dir=args.index_cache_dir, index_cache_budget_bytes=args.index_cache_budget_bytes,
                  resources_catalog=args.resources_catalog, include=args.include, exclude=args.exclude,
                  editions=args.edition,
                  extra_catalogs=args.extra_catalog,
                  allow_incomplete=args.allow_incomplete, navigation_dir=args.navigation_dir,
                  strict_coverage=args.strict_coverage, progress=progress)
        return 0
    except KeyboardInterrupt:
        if raise_errors:
            raise
        print("Paused safely. Verified files, partial transfers and search checkpoints are retained. "
              "Rerun the same command to continue. Wait for the prompt before safely ejecting the drive.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, yaml.YAMLError) as error:
        if raise_errors:
            raise
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
