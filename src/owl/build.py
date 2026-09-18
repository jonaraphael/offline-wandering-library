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
from .catalog import (CatalogError, capacity_plan, fingerprint, load_catalog,
                      load_profiles, read_yaml, resolve_content, resolve_locked_content, validate_catalog)
from .download import download, verified
from .runtime import file_lock as _lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file
from .transfer import resume_copy
from .verify import verify_drive

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUT = [f"CRITICAL/{name}" for name in ("FIRST_AID", "MEDICAL", "WATER_SANITATION", "FOOD", "AGRICULTURE", "ELECTRICAL", "MECHANICAL", "SHELTER")]
LAYOUT += ["REFERENCE", "BOOKS/TEXTBOOKS", "MAPS", "ZIM/WIKIPEDIA", "ZIM/WIKIMED", "ZIM/WIKTIONARY", "ZIM/OTHER",
           "SOFTWARE/ANDROID", "SOFTWARE/WINDOWS", "SOFTWARE/MACOS", "SOFTWARE/LINUX", "SEARCH", "INDEX"]
CORE_OUTPUTS = ["INVENTORY.json", "BUILD_INFO.json", "SHA256SUMS.txt", "LOCKED_CATALOG.yaml", "CONTENT_SELECTION.json", "VERIFY.py", "SOURCE_NOTES.txt",
                "SEARCH.html", "SEARCH/library.owl", "SEARCH/coverage.json"]


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


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
        safe_path(path.parent.parent, relative)
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
        check_space(group["path"], group["required_bytes"])
    return [{**g, "path": str(g["path"])} for g in groups.values()]


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


def build(target: Path, *, catalog: Path, profiles_dir: Path, profile_name: str,
          cache_dir: Path | None = None, work_dir: Path | None = None,
          allow_local: bool = False, plan_only: bool = False,
          resources_catalog: Path | None = None, include=(), exclude=(), editions=(),
          extra_catalogs=(),
          allow_incomplete: bool = False, navigation_dir: Path | None = None,
          strict_coverage: bool = False, progress=print) -> dict:
    from .navigation import GENERATED_PATHS, generate_navigation
    from .search import build_search, check_extractors, checkpoint_usage

    profiles = load_profiles(profiles_dir)
    if profile_name not in profiles:
        raise CatalogError(f"Unknown profile {profile_name!r}; choose {', '.join(profiles)}")
    all_assets = load_catalog(catalog, profiles, allow_local)
    extra_assets = []
    for extra_catalog in extra_catalogs:
        extra = load_catalog(Path(extra_catalog), profiles, allow_local)
        if any(a["status"] != "resolved" or not a["sha256"] for a in extra):
            raise CatalogError("Additional catalogs must contain resolved assets with pinned SHA-256 values")
        extra_assets.extend(extra)
    # Validate the entire namespace before selecting or writing any output.
    combined = validate_catalog({"schema_version": 1, "assets": all_assets + extra_assets}, profiles, allow_local)
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
    if not assets and not plan_only:
        raise CatalogError(f"Profile {profile_name} has no resolved content")
    plan = capacity_plan(assets, profile, selection)
    plan["in_place_peak_budget_bytes"] = (plan.get("planned_final_bytes", plan["estimated_final_bytes"])
                                          + plan["index_scratch_budget_bytes"] + plan["reserve_bytes"])
    plan["in_place_target_budget_fits"] = plan["in_place_peak_budget_bytes"] <= profile["capacity_bytes"]
    content_complete = not selection or not selection["incomplete_resources"]
    target = _root(target)
    cache = _root(cache_dir) / "owl-v1" if cache_dir else None
    work = _root(work_dir) if work_dir else target / ".owl/work"
    # Hashing during preflight can take hours. Capture the mounted filesystem
    # before it starts, not after a disappeared mount could have been recreated.
    anchors = [_directory_anchor(path) for path in (target, work, cache) if path is not None]
    progress(f"OWL {__version__} | {profile_name} | {target}")
    progress(f"Content/download total: {plan['content_bytes']:,} bytes ({plan['content_bytes'] / 1e9:.2f} GB)")
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
             "(content, index, scratch and reserve; excludes pre-existing old versions)")
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
        path = safe_path(target, relative)
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
    checkpoint = checkpoint_usage(target, work_dir=work)
    # Credit retained staging files: their allocation already reduced disk free
    # space. Their bytes are independently checked before any later promotion.
    search_bytes = max(0, plan["search_budget_bytes"] - checkpoint["output_bytes"])
    scratch_bytes = max(0, plan["index_scratch_budget_bytes"] - checkpoint["scratch_bytes"])
    required = transfer_bytes + search_bytes + plan["reserve_bytes"] + 16 * 1024 * 1024
    plan["remaining_transfer_allocation_bytes"] = transfer_bytes
    plan["remaining_cache_allocation_bytes"] = cache_bytes
    plan["retained_search_checkpoint_bytes"] = checkpoint
    allocations = [(target, required), (work, scratch_bytes)]
    if cache:
        allocations.append((cache, cache_bytes))
    plan["filesystem_allocations"] = check_space_groups(allocations)
    plan["required_free_bytes"] = sum(item["required_bytes"] for item in plan["filesystem_allocations"] if str(target) in item["uses"])
    if plan_only:
        progress("Plan only: no files created or downloaded. Index budget is a planning allowance, not a measured bound.")
        return plan
    check_extractors(assets)
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
        for relative in LAYOUT:
            safe_path(target, relative).mkdir(parents=True, exist_ok=True)
        safe_path(target, ".owl/downloads").mkdir(exist_ok=True)
        reject_symlinks(work)
        work.mkdir(parents=True, exist_ok=True)
        guards.enter_context(guard_directory(work))
        state["complete"] = False
        state["phase"] = "content"
        state["managed"] = sorted(owned | set(generated) | {a["destination"] for a in assets})
        atomic_write(state_path, _json(state))
        inventory_assets = []
        for asset in assets:
            state["active_asset"] = asset["id"]
            atomic_write(state_path, _json(state))
            destination = safe_path(target, asset["destination"])
            expected = _expected(asset, state, spool)
            if reusable[asset["id"]]:
                digest = expected
                progress(f"REUSE {asset['destination']}")
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
        state["phase"] = "search"
        atomic_write(state_path, _json(state))
        progress("Building full-text search and static navigation; large archives may take many hours.")
        search_report = build_search(target, inventory_assets, work_dir=work, progress=progress)
        state["phase"] = "navigation"
        atomic_write(state_path, _json(state))
        for warning in search_report.get("warnings", []):
            progress(f"SEARCH COVERAGE: {warning}")
        inventory = {"schema_version": 1, "assets": inventory_assets, "search": search_report,
                     "content_selection": selection, "content_complete": content_complete,
                     "learning_coverage": plan["learning_coverage"],
                     "unresolved": unresolved}
        from .atlas_build import plan_atlas, register_outputs, validate_links, write_outputs
        atlas_pages, atlas_report = plan_atlas(target, inventory_assets, navigation, state,
                                              strict_coverage=strict_coverage)
        inventory["navigation"] = atlas_report
        navigation_pages = generate_navigation(target, inventory_assets, inventory, search_report, write=False)
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
                "content_selection": selection, "content_complete": content_complete,
                "python_version": sys.version.split()[0], "dependencies": versions,
                "profile": profile, "catalog_sha256": sha256_file(catalog.resolve()), "plan": plan,
                "extra_catalogs": [{"path": str(Path(path)), "sha256": sha256_file(Path(path))}
                                   for path in extra_catalogs],
                "asset_count": len(assets), "unresolved_asset_ids": [a["id"] for a in unresolved],
                "search": search_report, "navigation": atlas_report, "complete": True,
                "integrity_note": "SHA-256 detects damage, not publisher identity. Save SHA256SUMS.txt separately."}
        atomic_write(safe_path(target, "BUILD_INFO.json"), _json(info))
        managed = sorted(set(nav_files) | set(search_report["generated_files"]) | set(CORE_OUTPUTS) |
                         {a["destination"] for a in assets})
        state["phase"] = "checksums"
        atomic_write(state_path, _json(state))
        progress("Generating checksums (streaming each managed file).")
        # Stream hashes; never load content files into memory.
        expected_files = {a["destination"]: (a["sha256"], a["size_bytes"]) for a in inventory_assets}
        expected_files["SEARCH/library.owl"] = (search_report["index_sha256"], search_report["index_bytes"])
        checksum_lines = []
        for relative in managed:
            if relative == "SHA256SUMS.txt":
                continue
            path = safe_path(target, relative)
            digest = sha256_file(path)
            if relative in expected_files and (digest, path.stat().st_size) != expected_files[relative]:
                raise SafetyError(f"File changed after verification: {relative}; rerun to repair before completion")
            checksum_lines.append(f"{digest}  {relative}\n")
        checksums = "".join(checksum_lines)
        atomic_write(safe_path(target, "SHA256SUMS.txt"), checksums.encode())
        final_size = sum(safe_path(target, name).stat().st_size for name in managed)
        if final_size + profile["reserve_bytes"] > profile["capacity_bytes"]:
            raise SafetyError("Actual generated output exceeds profile capacity; files retained, build incomplete")
        check_space(target, profile["reserve_bytes"])
        state["phase"] = "verification"
        atomic_write(state_path, _json(state))
        progress("Verifying completed library (reads every managed file).")
        results = verify_drive(target, emit=progress, allow_incomplete=True)
        if results["FAILED"] or results["MISSING"]:
            raise SafetyError("Completed-drive verification failed")
        state["complete"] = True
        state["phase"] = "complete"
        atomic_write(state_path, _json(state))
        progress(f"BUILD COMPLETE{' (PARTIAL CONTENT)' if not content_complete else ''}: {target / 'START_HERE.html'}")
        return info


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, nargs="?")
    parser.add_argument("--profile", default="critical-64gb")
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/library.yaml")
    parser.add_argument("--extra-catalog", type=Path, action="append", default=[],
                        help="add a pinned local export manifest; repeat for multiple exports; file URLs need --allow-local")
    parser.add_argument("--profiles-dir", type=Path, default=REPO_ROOT / "profiles")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--work-dir", type=Path, help="persistent directory for resumable search checkpoints; reuse on restart")
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
                  resources_catalog=args.resources_catalog, include=args.include, exclude=args.exclude,
                  editions=args.edition,
                  extra_catalogs=args.extra_catalog,
                  allow_incomplete=args.allow_incomplete, navigation_dir=args.navigation_dir,
                  strict_coverage=args.strict_coverage)
        return 0
    except KeyboardInterrupt:
        print("Paused safely. Verified files, partial transfers and search checkpoints are retained. "
              "Rerun the same command to continue. Wait for the prompt before safely ejecting the drive.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
