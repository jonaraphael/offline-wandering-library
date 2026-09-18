"""Build an OWL SSD without formatting, deleting unrelated data, or running binaries."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
                      load_profiles, read_yaml, resolve_content, resolve_locked_content)
from .download import DownloadError, download, verified
from .safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file
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


@contextmanager
def _lock(path: Path):
    reject_symlinks(path)
    try:
        with path.open("x") as handle:
            handle.write(f"pid={os.getpid()}\n")
    except FileExistsError:
        raise SafetyError(f"Build/cache lock exists: {path}. If a previous process crashed, confirm it has stopped before removing this lock.") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


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


def _expected(asset: dict, state: dict) -> str | None:
    previous = state["assets"].get(asset["id"], {})
    return asset["sha256"] or (previous.get("sha256") if previous.get("fingerprint") == fingerprint(asset) else None)


def build(target: Path, *, catalog: Path, profiles_dir: Path, profile_name: str,
          cache_dir: Path | None = None, work_dir: Path | None = None,
          allow_local: bool = False, plan_only: bool = False,
          resources_catalog: Path | None = None, include=(), exclude=(),
          allow_incomplete: bool = False, progress=print) -> dict:
    from .navigation import GENERATED_PATHS, generate_navigation
    from .search import build_search, check_extractors

    profiles = load_profiles(profiles_dir)
    if profile_name not in profiles:
        raise CatalogError(f"Unknown profile {profile_name!r}; choose {', '.join(profiles)}")
    all_assets = load_catalog(catalog, profiles, allow_local)
    profile = profiles[profile_name]
    lock = read_yaml(catalog).get("selection_lock")
    if lock is not None:
        if include or exclude:
            raise CatalogError("Customize the source catalog, not a locked selection")
        assets, unresolved, selection = resolve_locked_content(all_assets, profile, lock)
    else:
        assets, unresolved, selection = resolve_content(
            all_assets, profile, resources_path=resources_catalog or catalog.with_name("resources.yaml"),
            include=include, exclude=exclude)
    if not assets and not plan_only:
        raise CatalogError(f"Profile {profile_name} has no resolved content")
    plan = capacity_plan(assets, profile, selection)
    content_complete = not selection or not selection["incomplete_resources"]
    target = _root(target)
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
    for shelf, coverage in plan["learning_coverage"].items():
        floor = profile.get("minimum_coverage", {}).get(shelf, 0)
        progress(f"{shelf}: {coverage['count']} directly readable; {coverage['required_critical_count']} required critical (minimum {floor})")
    for asset in unresolved:
        progress(f"UNRESOLVED (excluded): {asset['id']}: {asset['unresolved_reason']}")
    generated = [*GENERATED_PATHS, *CORE_OUTPUTS]
    state_path = safe_path(target, ".owl/state.json")
    state = _state(state_path)
    owned = set(state["managed"])
    for relative in generated:
        path = safe_path(target, relative)
        if path.exists() and (relative not in owned or not path.is_file()):
            raise SafetyError(f"Generated output would overwrite an unowned file/directory: {path}")
    reusable = {}
    for asset in assets:
        path = safe_path(target, asset["destination"])
        checksum = _expected(asset, state)
        reusable[asset["id"]] = verified(path, asset["size_bytes"], checksum)
        if path.exists() and not reusable[asset["id"]] and asset["destination"] not in owned:
            raise SafetyError(f"Content destination contains an unverified, unowned file: {path}")
        if path.exists() and not path.is_file():
            raise SafetyError(f"Content destination is a directory: {path}")
    missing_bytes = sum(a["size_bytes"] for a in assets if not reusable[a["id"]])
    plan["remaining_content_bytes"] = missing_bytes
    progress(f"Verified reusable files: {sum(reusable.values())}/{len(assets)}; remaining content: {missing_bytes:,} bytes")
    # Existing final index remains until replacement is ready; budget a complete
    # new output plus transient database even when rebuilding the same corpus.
    required = missing_bytes + plan["search_budget_bytes"] + plan["reserve_bytes"] + 16 * 1024 * 1024
    cache = _root(cache_dir) / "owl-v1" if cache_dir else None
    work = _root(work_dir) if work_dir else target / ".owl/work"
    allocations = [(target, required), (work, plan["index_scratch_budget_bytes"])]
    if cache:
        allocations.append((cache, missing_bytes))
    plan["filesystem_allocations"] = check_space_groups(allocations)
    plan["required_free_bytes"] = sum(item["required_bytes"] for item in plan["filesystem_allocations"] if str(target) in item["uses"])
    if plan_only:
        progress("Plan only: no files created or downloaded. Index budget is a planning allowance, not a measured bound.")
        return plan
    check_extractors(assets)
    target.mkdir(parents=True, exist_ok=True)
    private = target / ".owl"
    _owned_directory(private)
    with _lock(safe_path(target, ".owl/build.lock")):
        # Re-read after acquiring lock; detect another completed builder between
        # read-only preflight and lock acquisition rather than use stale state.
        current = _state(state_path)
        if current != state:
            raise SafetyError("Build state changed during preflight; rerun")
        if cache:
            _owned_directory(cache)
        for relative in LAYOUT:
            safe_path(target, relative).mkdir(parents=True, exist_ok=True)
        safe_path(target, ".owl/downloads").mkdir(exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        state["complete"] = False
        state["managed"] = sorted(owned | set(generated) | {a["destination"] for a in assets})
        atomic_write(state_path, _json(state))
        inventory_assets = []
        for asset in assets:
            destination = safe_path(target, asset["destination"])
            expected = _expected(asset, state)
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
                        with staged.open("rb") as source, copy.open("wb") as output:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                            output.flush()
                            os.fsync(output.fileno())
                        if sha256_file(copy) != digest:
                            raise DownloadError("Checksum changed while copying cached content")
                        os.replace(copy, destination)
                    else:
                        os.replace(staged, destination)
                state["assets"][asset["id"]] = {"sha256": digest, "fingerprint": fingerprint(asset)}
                atomic_write(state_path, _json(state))
            inventory_assets.append({**asset, "sha256": digest,
                                     "verification": "pinned" if asset["sha256"] else "observed"})
        progress("Building full-text search and static navigation; large archives may take many hours.")
        search_report = build_search(target, inventory_assets, work_dir=work, progress=progress)
        for warning in search_report.get("warnings", []):
            progress(f"SEARCH COVERAGE: {warning}")
        inventory = {"schema_version": 1, "assets": inventory_assets, "search": search_report,
                     "content_selection": selection, "content_complete": content_complete,
                     "learning_coverage": plan["learning_coverage"],
                     "unresolved": unresolved}
        nav_files = generate_navigation(target, inventory_assets, inventory, search_report)
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
        for package in ("PyYAML", "pypdf", "fonttools", "libzim"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                pass
        info = {"schema_version": 1, "owl_version": __version__, "built_at": datetime.now(timezone.utc).isoformat(),
                "content_selection": selection, "content_complete": content_complete,
                "python_version": sys.version.split()[0], "dependencies": versions,
                "profile": profile, "catalog_sha256": sha256_file(catalog.resolve()), "plan": plan,
                "asset_count": len(assets), "unresolved_asset_ids": [a["id"] for a in unresolved],
                "search": search_report, "complete": True,
                "integrity_note": "SHA-256 detects damage, not publisher identity. Save SHA256SUMS.txt separately."}
        atomic_write(safe_path(target, "BUILD_INFO.json"), _json(info))
        managed = sorted(set(nav_files) | set(search_report["generated_files"]) | set(CORE_OUTPUTS) |
                         {a["destination"] for a in assets})
        # Stream hashes; never load content files into memory.
        checksums = "".join(f"{sha256_file(safe_path(target, relative))}  {relative}\n"
                            for relative in managed if relative != "SHA256SUMS.txt")
        atomic_write(safe_path(target, "SHA256SUMS.txt"), checksums.encode())
        final_size = sum(safe_path(target, name).stat().st_size for name in managed)
        if final_size + profile["reserve_bytes"] > profile["capacity_bytes"]:
            raise SafetyError("Actual generated output exceeds profile capacity; files retained, build incomplete")
        check_space(target, profile["reserve_bytes"])
        progress("Verifying completed library (reads every managed file).")
        results = verify_drive(target, emit=progress, allow_incomplete=True)
        if results["FAILED"] or results["MISSING"]:
            raise SafetyError("Completed-drive verification failed")
        state["complete"] = True
        atomic_write(state_path, _json(state))
        progress(f"BUILD COMPLETE{' (PARTIAL CONTENT)' if not content_complete else ''}: {target / 'START_HERE.html'}")
        return info


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, nargs="?")
    parser.add_argument("--profile", default="critical-64gb")
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/library.yaml")
    parser.add_argument("--profiles-dir", type=Path, default=REPO_ROOT / "profiles")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--work-dir", type=Path, help="directory for temporary search database")
    parser.add_argument("--plan", action="store_true", help="validate and estimate without writing/downloading")
    parser.add_argument("--allow-local", action="store_true", help="allow trusted local fixtures and plain HTTP test sources")
    parser.add_argument("--resources-catalog", type=Path, help="resource registry (default: resources.yaml beside catalog)")
    parser.add_argument("--include", action="append", default=[], metavar="RESOURCE", help="add resource ID or list number; repeat or separate by commas")
    parser.add_argument("--exclude", action="append", default=[], metavar="RESOURCE", help="omit resource ID or list number; repeat or separate by commas; does not delete existing files")
    parser.add_argument("--list-resources", action="store_true", help="list every selectable collection without a target or downloads")
    parser.add_argument("--allow-incomplete", action="store_true", help="explicitly build available verified files from incomplete collections")
    args = parser.parse_args(argv)
    try:
        if args.list_resources:
            from .resources import load_resources, resolve_resources
            profiles = load_profiles(args.profiles_dir)
            if args.profile not in profiles:
                raise CatalogError(f"Unknown profile: {args.profile}")
            assets = load_catalog(args.catalog, profiles, args.allow_local)
            resources = load_resources(args.resources_catalog or args.catalog.with_name("resources.yaml"), assets)
            report = resolve_resources(assets, profiles[args.profile], resources,
                                       include=args.include, exclude=args.exclude)
            rows = {row["id"]: row for row in report["resource_rows"]}
            print("* = selected; GB = effective selected target, or base estimate when unselected. All units decimal.")
            for identity, resource in resources.items():
                selected = "*" if identity in report["selected_ids"] else " "
                number = str(resource.get("number") or "-")
                target_bytes = rows.get(identity, {}).get("effective_target_bytes", resource["target_bytes"])
                print(f"{selected} {number:>2} {identity:28} {resource['status']:10} "
                      f"{target_bytes/1e9:7.2f} GB  {resource['title']}")
            print(f"Selected content target: {report['content_target_bytes']:,} bytes; "
                  f"known resolved files: {report['resolved_asset_bytes']:,}; "
                  f"incomplete collections: {len(report['incomplete_resources'])}. "
                  "Targets are planning estimates, not verified download sizes.")
            if "default_resources" not in profiles[args.profile]:
                fixed, _, _ = resolve_content(assets, profiles[args.profile],
                    resources_path=args.resources_catalog or args.catalog.with_name("resources.yaml"),
                    include=args.include, exclude=args.exclude)
                print(f"Fixed-profile baseline/selection: {len(fixed)} verified asset definitions, "
                      f"{sum(a['size_bytes'] for a in fixed):,} bytes. "
                      "The stars above describe named additions, not baseline membership.")
            return 0
        if args.target is None:
            parser.error("target is required unless --list-resources is used")
        build(args.target, catalog=args.catalog, profiles_dir=args.profiles_dir, profile_name=args.profile,
              cache_dir=args.cache_dir, work_dir=args.work_dir, allow_local=args.allow_local, plan_only=args.plan,
              resources_catalog=args.resources_catalog, include=args.include, exclude=args.exclude,
              allow_incomplete=args.allow_incomplete)
        return 0
    except KeyboardInterrupt:
        print("Interrupted; verified files and resumable partial downloads retained.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
