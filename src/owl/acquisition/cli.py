"""Small acquisition commands: full evidence on disk, concise exceptions on stdout."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
import warnings

import yaml

from ..catalog import (CatalogError, capacity_plan, load_catalog, load_profiles,
                       read_yaml, resolve_content, validate_catalog)
from ..resources import load_resources, resource_asset_ids
from ..safety import atomic_write, reject_symlinks, sha256_file
from .metadata import Fetcher
from .model import AcquisitionError, input_asset_ids, load_recipes, validate_generation, validate_recipes

ROOT = Path(__file__).resolve().parents[3]
SUMMARY_BYTES = 2048


def _json(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()


def _ids(values):
    return {item for value in values for item in value.split(",") if item}


def _update_asset_ids(update):
    editions = update.get("editions", {})
    if not isinstance(editions, dict) or any(not isinstance(row, dict) for row in editions.values()):
        raise AcquisitionError("Staged editions must be mappings")
    groups = [update.get("asset_ids", []), update.get("add_asset_ids", [])]
    groups.extend(row.get("asset_ids", []) for row in editions.values())
    if any(not isinstance(group, list) or any(not isinstance(item, str) for item in group) for group in groups):
        raise AcquisitionError("Staged resource and edition asset IDs must be lists of strings")
    return {identity for group in groups for identity in group}


def _context(args):
    assets = load_catalog(args.catalog, allow_local=args.allow_local)
    resources_path = args.resources or args.catalog.with_name("resources.yaml")
    resources = load_resources(resources_path, assets)
    profiles = load_profiles(args.profiles_dir)
    requested = _ids(args.resource)
    numbers = {str(row["number"]): key for key, row in resources.items() if row.get("number") is not None}
    requested = {numbers.get(key, key) for key in requested}
    if requested - resources.keys():
        raise AcquisitionError("Unknown resources: " + ", ".join(sorted(requested - resources.keys())))
    selected_profiles = _ids(args.profile) or {name for name in profiles if name != "demo"}
    if selected_profiles - profiles.keys():
        raise AcquisitionError("Unknown profiles: " + ", ".join(sorted(selected_profiles - profiles.keys())))
    resolutions = {}
    profile_resources = set()
    for name in sorted(selected_profiles):
        selected, unresolved, selection = resolve_content(assets, profiles[name], resources_path=resources_path)
        resolutions[name] = (selected, unresolved, selection)
        if selection:
            profile_resources.update(selection["selected_ids"])
        else:
            selected_ids = {a["id"] for a in selected + unresolved}
            profile_resources.update(key for key, row in resources.items() if resource_asset_ids(row) & selected_ids)
    selected_resources = requested or profile_resources
    if requested and args.profile:
        selected_resources &= profile_resources
    recipes = load_recipes(args.recipes) if args.recipes.exists() else {}
    recipes = {key: row for key, row in recipes.items() if row["resource_id"] in selected_resources
               and (row["adapter"] != "usgs_maps" or
                    not isinstance(row["selection"].get("allowances"), dict) or
                    selected_profiles.intersection(row["selection"]["allowances"]))}
    return assets, resources, profiles, resolutions, selected_resources, recipes


def audit(args, context=None):
    assets, resources, profiles, resolutions, selected_resources, recipes = context or _context(args)
    rows, effective_gaps = [], {}
    for name, (selected, unresolved, selection) in resolutions.items():
        plan = _capacity(selected, profiles[name], selection, read_yaml(args.catalog).get("acquisition_recipes", []))
        selected_rows = []
        if selection:
            selected_rows = [row for row in selection["resource_rows"] if row["id"] in selected_resources]
            for row in selected_rows:
                if row["status"] != "ready":
                    effective_gaps.setdefault(row["id"], []).append({"profile": name, **row})
        rows.append({"profile": name, "pinned_bytes": plan["content_bytes"],
                     "pinned_knowledge_bytes": plan["pinned_knowledge_bytes"],
                     "target_shortfall_bytes": plan["target_shortfall_bytes"],
                     "complete": plan["content_complete"], "peak_fits": plan["in_place_target_budget_fits"],
                     "acquisition_workspace_bytes": plan["acquisition_workspace_bytes"],
                     "effective_editions": selection.get("effective_editions", {}) if selection else {},
                     "incomplete_resources": [row for row in selected_rows if row["status"] != "ready"],
                     "device_validation_pending": [row["id"] for row in selected_rows
                         if row["device_validation"]["status"] == "pending"],
                     "unresolved_assets": [a["id"] for a in unresolved]})
    explicit_scope = bool(args.resource) and not args.profile
    gap_ids = ({key for key in selected_resources if resources[key]["status"] != "ready"}
               if explicit_scope else set(effective_gaps))
    gaps = []
    for key in sorted(gap_ids):
        selected = effective_gaps.get(key, [])
        status = resources[key]["status"] if explicit_scope else (
            "partial" if any(row["status"] == "partial" for row in selected) else "unresolved")
        reason = resources[key]["reason"] if explicit_scope else "; ".join(dict.fromkeys(row["reason"] for row in selected))
        gaps.append({"resource_id": key, "status": status, "reason": reason,
                     "selected_editions": sorted({row["edition"] for row in selected}),
                     "profiles": sorted({row["profile"] for row in selected}),
                     "recipes": [{"id": r["id"], "review": r["review"], "blockers": r["blockers"]}
                                 for r in recipes.values() if r["resource_id"] == key]})
    return {"operation": "audit", "profiles": rows, "gaps": gaps, "recipe_count": len(recipes)}


def discover(args, context):
    recipes = context[-1]
    fetcher = Fetcher(args.cache_dir / "metadata", offline=args.offline, refresh=args.refresh)
    try:
        provider = importlib.import_module("owl.acquisition.providers")
    except ModuleNotFoundError as error:
        if error.name != "owl.acquisition.providers":
            raise
        provider = None
    results = []
    for recipe in sorted(recipes.values(), key=lambda row: row["id"]):
        first = len(fetcher.evidence)
        try:
            if provider is not None:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("once")
                    result = provider.discover(recipe, fetcher)
                if caught:
                    result["diagnostics"] = list(dict.fromkeys(str(item.message) for item in caught))[:20]
                if not isinstance(result, dict):
                    raise AcquisitionError("Discovery adapter must return a mapping")
            else:
                for source in recipe["metadata_sources"]:
                    fetcher.fetch(source["url"], kind=source["kind"])
                result = {"recipe_id": recipe["id"], "candidates": [],
                          "blockers": recipe["blockers"] + ["No discovery adapter installed"]}
        except (OSError, ValueError) as error:
            result = {"recipe_id": recipe["id"], "candidates": [], "blockers": [str(error)]}
        result = {**result, "recipe_id": recipe["id"], "resource_id": recipe["resource_id"],
                  "recipe_sha256": hashlib.sha256(_json(recipe)).hexdigest(),
                  "metadata_evidence": fetcher.evidence[first:]}
        results.append(result)
        _persist(args, {"operation": "discover", "results": [result]})
    return {"operation": "discover", "results": results}


class _Dependencies(HTMLParser):
    def __init__(self):
        super().__init__()
        self.remote, self.local = set(), set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "poster", "data"):
            if attrs.get(key):
                self.add(attrs[key])
        if tag == "link" and attrs.get("href"):
            self.add(attrs["href"])

    def add(self, url):
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} or url.startswith("//"):
            self.remote.add(url)
        elif url and not parsed.scheme and not url.startswith("#"):
            self.local.add(url)


def inspect_local(args, context):
    assets, resources, _, _, selected_resources, recipes = context
    selected_ids = set().union(*(resource_asset_ids(resources[key]) for key in selected_resources))
    for recipe in recipes.values():
        selected_ids.update(input_asset_ids(recipe))
    manifest = read_yaml(args.local_manifest) if args.local_manifest else {}
    if not isinstance(manifest, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in manifest.items()):
        raise AcquisitionError("Local manifest must map asset IDs to local file paths")
    results = []
    for asset in assets:
        if asset["id"] not in selected_ids:
            continue
        path = Path(manifest[asset["id"]]) if asset["id"] in manifest else args.local_root / asset["destination"]
        reject_symlinks(path)
        row = {"asset_id": asset["id"], "path": str(path), "status": "missing",
               "expected_sha256": asset["sha256"], "expected_size_bytes": asset["size_bytes"]}
        if path.is_file():
            size, digest = path.stat().st_size, sha256_file(path)
            row.update(size_bytes=size, sha256=digest, status="verified" if size == asset["size_bytes"] and digest == asset["sha256"] else "mismatch")
            if row["status"] == "verified":
                try:
                    if asset["format"].lower() == "pdf":
                        from pypdf import PdfReader
                        pdf = PdfReader(path)
                        count = len(pdf.pages)
                        pages = sorted({0, count // 2, count - 1}) if count else []
                        row["pdf"] = {"page_count": count, "sampled_text_lengths": {
                            str(index + 1): len((pdf.pages[index].extract_text() or "")[:100000]) for index in pages}}
                    elif asset["format"].lower() in {"html", "htm"}:
                        if size > 8 * 1024 * 1024:
                            row["inspection_warning"] = "HTML dependency inspection skipped above 8 MiB"
                        else:
                            parser = _Dependencies()
                            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
                            row["html"] = {"remote_dependencies": sorted(parser.remote), "local_dependencies": sorted(parser.local)}
                except Exception as error:
                    row["inspection_warning"] = str(error)
        results.append(row)
    return {"operation": "inspect-local", "results": results,
            "review_required": "Structural checks and sampled text do not certify visual quality or coverage."}


def report(args, context):
    result = audit(args, context)
    result["operation"] = "report"
    assets, resources, _, _, selected_resources, recipes = context
    selected_ids = set().union(*(resource_asset_ids(resources[key]) for key in selected_resources))
    by_id = {asset["id"]: asset for asset in assets}
    discoveries, inspections = {}, {}
    directory = args.cache_dir / "reports"
    reject_symlinks(directory)
    paths = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:500]
    for path in paths:
        if not path.name.startswith(("discover-", "inspect-local-")):
            continue
        reject_symlinks(path)
        if path.stat().st_size > 64 * 1024 * 1024:
            continue
        saved = json.loads(path.read_text())
        for row in saved.get("results", []):
            if saved.get("operation") == "discover":
                identity = row.get("recipe_id")
                if identity in recipes and identity not in discoveries and row.get("recipe_sha256") == hashlib.sha256(_json(recipes[identity])).hexdigest():
                    discoveries[identity] = row
            elif saved.get("operation") == "inspect-local":
                identity = row.get("asset_id")
                if (identity in selected_ids and identity not in inspections
                        and row.get("expected_sha256") == by_id[identity]["sha256"]
                        and row.get("expected_size_bytes") == by_id[identity]["size_bytes"]):
                    inspections[identity] = row
    result["results"] = [*sorted(discoveries.values(), key=lambda row: row["recipe_id"]),
                         *sorted(inspections.values(), key=lambda row: row["asset_id"])]
    result["history_scope"] = "Latest matching recipe/source pins; reports for changed pins are excluded."
    return result


def prepare_local(args, context):
    """Pin already reviewed local originals into a portable staging fragment."""
    document = read_yaml(args.fragment)
    manifest = read_yaml(args.local_manifest)
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("assets"), list):
        raise AcquisitionError("Preparation template requires schema_version and assets")
    if not isinstance(manifest, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in manifest.items()):
        raise AcquisitionError("Local manifest must map asset IDs to original file paths")
    resources = context[4]
    updates = [row for row in document.get("resource_updates", []) if row.get("id") in resources]
    selected = {identity for row in updates for identity in _update_asset_ids(row)}
    assets = document["assets"]
    if args.resource or args.profile:
        assets = [row for row in assets if row.get("id") in selected]
        document["resource_updates"] = updates
    evidence = []
    for row in assets:
        if row.get("generation") or row.get("archive_member"):
            raise AcquisitionError("prepare-local accepts publisher originals, not generated/archive-member outputs")
        if row.get("id") not in manifest:
            raise AcquisitionError(f"{row.get('id')}: no local original supplied")
        path = Path(manifest[row["id"]])
        if not path.is_absolute():
            path = args.local_manifest.parent / path
        reject_symlinks(path)
        size, digest = path.stat().st_size, sha256_file(path)
        if (row.get("sha256") is not None and row["sha256"] != digest) or (row.get("size_bytes") is not None and row["size_bytes"] != size):
            raise AcquisitionError(f"{row['id']}: preserved source disagrees with recorded pin")
        row.update(size_bytes=size, sha256=digest)
        evidence.append({"asset_id": row["id"], "size_bytes": size, "sha256": digest,
                         "method": "Streaming hash of preserved local original; no network request or source conversion"})
    validate_catalog({"schema_version": 1, "assets": assets}, context[2], args.allow_local)
    document["assets"] = assets
    document["local_verification"] = evidence
    reject_symlinks(args.output)
    if args.output.exists():
        raise AcquisitionError("Prepared fragment already exists; choose a new output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, yaml.safe_dump(document, sort_keys=False).encode())
    return {"operation": "prepare-local", "candidate": str(args.output), "added_assets": len(assets),
            "source_template_sha256": sha256_file(args.fragment)}


def _capacity(assets, profile, selection, recipes):
    from .runtime import allocation, order_assets, selected_recipes
    registry = validate_recipes(recipes)
    active = selected_recipes(assets, registry)
    order_assets(assets, active)
    plan = capacity_plan(assets, profile, selection)
    workspace = allocation(active, assets)
    plan["acquisition_workspace_bytes"] = workspace
    if workspace != plan["acquisition_workspace_budget_bytes"]:
        raise AcquisitionError("Generated workspace accounting differs from its pinned recipes")
    return plan


def _ready_review(update, recipes):
    review = update.get("review", {})
    return (review.get("status") == "approved" and review.get("full_scope") is True
            and isinstance(review.get("evidence"), list) and bool(review["evidence"])
            and all(isinstance(item, str) and item.strip() for item in review["evidence"]))


def stage(args, context):
    assets, resources, profiles, _, selected_resources, _ = context
    fragment = read_yaml(args.fragment)
    if not isinstance(fragment, dict) or fragment.get("schema_version") != 1:
        raise AcquisitionError("Stage fragment needs schema_version: 1")
    captured = fragment.get("acquisition_capture") or any(
        isinstance(asset, dict) and asset.get("acquisition_provenance") for asset in fragment.get("assets", []))
    if captured and not args.review_receipt:
        raise AcquisitionError("Captured candidates require --review-receipt before admission")
    if args.review_receipt:
        from .capture import validate_review_binding
        validate_review_binding(fragment, args.review_receipt)
    catalog_doc = deepcopy(read_yaml(args.catalog))
    recipes = validate_recipes(catalog_doc.get("acquisition_recipes", []))
    additions = validate_recipes(fragment.get("acquisition_recipes", fragment.get("recipes", [])))
    additions = {key: row for key, row in additions.items() if row["resource_id"] in selected_resources}
    for key, row in additions.items():
        if row["review"]["status"] != "approved":
            raise AcquisitionError(f"{key}: pending recipes cannot register generated catalog outputs")
        if key in recipes and recipes[key] != row:
            raise AcquisitionError(f"{key}: stage refuses replacement of an existing recipe")
        recipes[key] = row
    updates = fragment.get("resource_updates", fragment.get("proposed_resource_updates", []))
    if not isinstance(updates, list):
        raise AcquisitionError("resource_updates must be a list")
    if any(not isinstance(row, dict) or row.get("id") not in resources for row in updates):
        raise AcquisitionError("Resource updates must reference known resource IDs")
    updates = [u for u in updates if isinstance(u, dict) and u.get("id") in selected_resources]
    admitted_ids = {aid for update in updates for aid in _update_asset_ids(update)}
    for recipe in additions.values():
        admitted_ids.update(input_asset_ids(recipe) + recipe["output_asset_ids"])
    new_assets = fragment.get("assets", [])
    if not isinstance(new_assets, list):
        raise AcquisitionError("Fragment assets must be a list")
    if args.resource or args.profile:
        new_assets = [a for a in new_assets if isinstance(a, dict) and a.get("id") in admitted_ids]
    by_id = {a["id"]: a for a in catalog_doc["assets"]}
    count = 0
    for asset in new_assets:
        if not isinstance(asset, dict) or "id" not in asset:
            raise AcquisitionError("Fragment asset requires id")
        if asset["id"] in by_id:
            if by_id[asset["id"]] != asset:
                raise AcquisitionError(f"{asset['id']}: stage refuses replacement of an existing pin")
        else:
            catalog_doc["assets"].append(asset)
            by_id[asset["id"]] = asset
            count += 1
    if recipes:
        catalog_doc["acquisition_recipes"] = list(recipes.values())
    combined = validate_catalog(catalog_doc, profiles, args.allow_local)
    from ..content_policy import require_content_policy
    require_content_policy(combined)
    validate_generation(combined, recipes)
    resource_doc = deepcopy(read_yaml(args.resources or args.catalog.with_name("resources.yaml")))
    rows = {row["id"]: row for row in resource_doc["resources"]}
    seen = set()
    for update in updates:
        key = update["id"]
        if key in seen:
            raise AcquisitionError(f"Duplicate resource update: {key}")
        seen.add(key)
        if update.get("status") == "ready" and rows[key]["status"] != "ready" and not _ready_review(update, recipes):
            raise AcquisitionError(f"{key}: readiness promotion requires explicit approved review evidence")
        for edition, details in update.get("editions", {}).items():
            if details.get("status") == "ready" and not _ready_review(update, recipes):
                raise AcquisitionError(f"{key}/{edition}: ready edition requires approved review evidence")
        additions = update.get("add_asset_ids", [])
        if not isinstance(additions, list) or any(not isinstance(item, str) or item not in by_id for item in additions):
            raise AcquisitionError(f"{key}: add_asset_ids must reference candidate assets")
        if additions and "asset_ids" in update:
            raise AcquisitionError(f"{key}: use either asset_ids or add_asset_ids")
        rows[key].update({k: v for k, v in update.items() if k not in {"review", "add_asset_ids"}})
        if additions:
            rows[key]["asset_ids"] = list(dict.fromkeys([*rows[key]["asset_ids"], *additions]))
    out = args.output
    reject_symlinks(out)
    if out.exists():
        raise AcquisitionError("Candidate output already exists; choose a new directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    navigation = args.navigation_dir
    if navigation is None and (args.catalog.parent / "navigation").is_dir():
        navigation = args.catalog.parent / "navigation"
    with tempfile.TemporaryDirectory(prefix=".owl-candidate-", dir=out.parent) as temporary:
        candidate = Path(temporary) / "bundle"
        candidate.mkdir()
        (candidate / "library.yaml").write_text(yaml.safe_dump(catalog_doc, sort_keys=False), encoding="utf-8")
        resource_path = candidate / "resources.yaml"
        resource_path.write_text(yaml.safe_dump(resource_doc, sort_keys=False), encoding="utf-8")
        load_resources(resource_path, combined)
        reject_symlinks(args.profiles_dir)
        for path in args.profiles_dir.rglob("*"):
            reject_symlinks(path)
        shutil.copytree(args.profiles_dir, candidate / "profiles")
        if navigation is not None:
            reject_symlinks(navigation)
            for path in navigation.rglob("*"):
                reject_symlinks(path)
            shutil.copytree(navigation, candidate / "navigation")
            new_assignments = fragment.get("navigation_assignments", [])
            if not isinstance(new_assignments, list):
                raise AcquisitionError("navigation_assignments must be a list")
            if new_assignments:
                from ..atlas_model import read_asset_assignments
                documents = {}
                for row in new_assignments:
                    if not isinstance(row, dict):
                        raise AcquisitionError("Navigation assignment must be a mapping")
                    aid = row.get('asset_id')
                    if not isinstance(aid, str):
                        raise AcquisitionError('Navigation assignment requires an asset_id string')
                    if (args.resource or args.profile) and aid not in admitted_ids:
                        continue
                    if aid not in documents:
                        documents[aid] = read_asset_assignments(candidate / 'navigation', aid)
                    document = documents[aid]
                    entry = {k: v for k, v in row.items() if k != 'asset_id'}
                    existing = next((r for r in document['assignments'] if
                        (r.get('topic_id'), r.get('section_id')) ==
                        (entry.get('topic_id'), entry.get('section_id'))), None)
                    if existing is not None:
                        if existing != entry:
                            raise AcquisitionError("Conflicting staged navigation assignment")
                    else:
                        document['assignments'].append(entry)
                for aid, document in documents.items():
                    path = candidate / 'navigation/assignments' / (aid + '.yaml')
                    path.parent.mkdir(exist_ok=True)
                    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
            from ..atlas_model import load_navigation
            load_navigation(candidate / "navigation", combined)
        elif fragment.get("navigation_assignments"):
            raise AcquisitionError("Navigation assignments require a navigation directory")
        checks = []
        for name, profile in sorted(profiles.items()):
            if "default_resources" not in profile and not any(name in asset["profiles"] for asset in combined):
                continue
            selected, _, selection = resolve_content(combined, profile, resources_path=resource_path)
            plan = _capacity(selected, profile, selection, list(recipes.values()))
            if not plan["in_place_target_budget_fits"]:
                raise AcquisitionError(f"{name}: staged selection exceeds peak storage budget")
            checks.append({"profile": name, "pinned_bytes": plan["content_bytes"],
                           "target_shortfall_bytes": plan["target_shortfall_bytes"], "complete": plan["content_complete"],
                           "acquisition_workspace_bytes": plan["acquisition_workspace_bytes"]})
        result = {"operation": "stage", "candidate": str(out), "added_assets": count,
                  "updated_resources": sorted(seen), "profiles": checks,
                  "source_fragment_sha256": sha256_file(args.fragment)}
        (candidate / "stage-report.json").write_bytes(_json(result))
        # A new bundle is the only publication. The working catalogs are untouched.
        os.rename(candidate, out)
    return result


def _persist(args, result):
    payload = _json(result)
    digest = hashlib.sha256(payload).hexdigest()
    directory = args.cache_dir / "reports"
    reject_symlinks(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (result["operation"] + "-" + digest[:16] + ".json")
    reject_symlinks(path)
    atomic_write(path, payload)
    return path, digest


def _semantic(value):
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items() if key not in {"cached", "checked_at"}}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _save_and_print(args, result):
    path, digest = _persist(args, result)
    pointer = args.cache_dir / "last-report.json"
    atomic_write(pointer, _json({"path": str(path.absolute()), "sha256": digest}))
    if args.only_changed:
        identity = hashlib.sha256(_json({"command": args.command, "catalog": str(args.catalog.absolute()),
            "resources": str(args.resources), "profiles": sorted(args.profile), "resource": sorted(args.resource)})).hexdigest()
        seen = args.cache_dir / ("seen-" + identity + ".json")
        reject_symlinks(seen)
        semantic = hashlib.sha256(_json(_semantic(result))).hexdigest()
        if seen.is_file() and seen.stat().st_size < 4096 and json.loads(seen.read_text()).get("sha256") == semantic:
            print(json.dumps({"operation": result["operation"], "status": "unchanged", "detail": str(path.absolute())}, sort_keys=True))
            return
        atomic_write(seen, _json({"sha256": semantic}))
    summary = {"operation": result["operation"], "detail": str(path.absolute())}
    if "profiles" in result:
        summary["profiles"] = [{k: row[k] for k in ("profile", "pinned_bytes", "target_shortfall_bytes", "complete") if k in row}
                               | ({"incomplete_count": len(row["incomplete_resources"])} if "incomplete_resources" in row else {})
                               for row in result["profiles"]]
    if "gaps" in result:
        summary["gap_count"] = len(result["gaps"])
    if "results" in result:
        summary["items"] = len(result["results"])
        counts = {}
        for row in result["results"]:
            status = row.get("status", "blocked" if row.get("blockers") else "discovered")
            counts[status] = counts.get(status, 0) + 1
        summary["counts"] = counts
        issues = [{"id": row.get("resource_id", row.get("asset_id", row.get("recipe_id"))),
                   "reason": str((row.get("blockers") or [row.get("inspection_warning", row.get("status"))])[-1])[:180]}
                  for row in result["results"] if row.get("blockers") or row.get("status") == "mismatch" or row.get("inspection_warning")]
        if issues:
            summary["issues"] = issues[:5]
            if len(issues) > 5:
                summary["additional_issues"] = len(issues) - 5
    for key in ("candidate", "added_assets", "updated_resources", "status", "staging_root", "source_count",
                "storage_peak_bytes", "free_bytes", "job_dir", "job_id", "content_ready", "receipt", "staging",
                "body_downloads", "reused_sources", "candidate_fragment"):
        if key in result:
            summary[key] = result[key]
    output = _json(summary)
    if len(output) > SUMMARY_BYTES:
        summary.pop("profiles", None)
        summary["summary_truncated"] = True
        output = _json(summary)
    if len(output) > SUMMARY_BYTES:
        summary = {"operation": result["operation"], "detail": str(path.absolute()), "summary_truncated": True}
        output = _json(summary)
    if args.format == "text":
        print(f"{summary['operation']}: " + ", ".join(f"{key}={value}" for key, value in summary.items() if key not in {"operation", "detail", "profiles"}))
        for row in summary.get("profiles", []):
            print(f"  {row['profile']}: {row['pinned_bytes']:,} bytes; shortfall {row['target_shortfall_bytes']:,}; complete={row['complete']}")
        print("Details: " + summary["detail"])
    else:
        print(output.decode(), end="")


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("audit", "discover", "inspect-local", "prepare-local", "stage", "report", "build", "preview", "review"):
        command = commands.add_parser(name)
        command.add_argument("--catalog", type=Path, default=ROOT / "catalog/library.yaml")
        command.add_argument("--resources", "--resources-catalog", type=Path)
        command.add_argument("--profiles-dir", type=Path, default=ROOT / "profiles")
        command.add_argument("--recipes", type=Path, default=ROOT / "catalog/acquisition/recipes.yaml")
        command.add_argument("--resource", action="append", default=[])
        command.add_argument("--profile", action="append", default=[])
        command.add_argument("--cache-dir", type=Path, default=ROOT / ".owl/acquisition")
        command.add_argument("--format", choices=("json", "text"), default="json")
        command.add_argument("--json", action="store_const", dest="format", const="json")
        command.add_argument("--only-changed", action="store_true")
        command.add_argument("--allow-local", action="store_true")
        if name == "discover":
            command.add_argument("--offline", action="store_true")
            command.add_argument("--refresh", action="store_true")
        elif name == "inspect-local":
            command.add_argument("--local-root", type=Path, default=Path.cwd())
            command.add_argument("--local-manifest", type=Path)
        elif name == "stage":
            command.add_argument("--fragment", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--navigation-dir", type=Path)
            command.add_argument("--review-receipt", type=Path)
        elif name == "prepare-local":
            command.add_argument("--fragment", type=Path, required=True)
            command.add_argument("--local-manifest", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
        elif name == "build":
            command.add_argument("--candidate-manifest", type=Path, required=True)
            command.add_argument("--local-manifest", type=Path, help="Reuse pinned existing originals without changing official source identities")
            command.add_argument("--staging-root", type=Path, required=True)
            command.add_argument("--budget-bytes", type=int)
            command.add_argument("--reserve-bytes", type=int, default=1024**3)
            command.add_argument("--production-root", type=Path)
            command.add_argument("--plan", action="store_true")
            command.add_argument("--detach", action="store_true")
            command.add_argument("--job-dir", type=Path)
            command.add_argument("--continue-missing-sources", action="store_true",
                                 help="Checkpoint HTTP 404/410 failures and attempt remaining sources; the batch still fails incomplete")
        elif name == "preview":
            command.add_argument("--staging-root", type=Path, required=True)
            command.add_argument("--recipe", type=Path, required=True)
            command.add_argument("--assets", type=Path, required=True)
            command.add_argument("--preview-bytes", type=int)
            command.add_argument("--expanded-bytes", type=int)
            command.add_argument("--scratch-bytes", type=int)
            command.add_argument("--reserve-bytes", type=int)
            command.add_argument("--budget-bytes", type=int)
            command.add_argument("--shared-expansion", type=Path,
                                 help="Reuse owned, fully pinned shared XML input evidence from this capture")
        elif name == "review":
            command.add_argument("--staging-root", type=Path, required=True)
            command.add_argument("--fragment", type=Path, required=True)
            command.add_argument("--evidence", action="append", required=True)
            command.add_argument("--reviewer", default="acquisition reviewer")
            command.add_argument("--output", type=Path)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        context = None if args.command in {"build", "preview", "review"} else _context(args)
        if args.command == "build":
            from .capture import capture
            if args.plan and args.detach:
                raise AcquisitionError("Use either --plan or --detach")
            if args.detach and not args.job_dir:
                raise AcquisitionError("Detached acquisition requires --job-dir")
            profiles = sorted(_ids(args.profile))
            if len(profiles) > 1:
                raise AcquisitionError("A frozen acquisition batch has one profile; select at most one")
            options = dict(budget_bytes=args.budget_bytes, reserve_bytes=args.reserve_bytes,
                local_manifest=args.local_manifest,
                continue_missing_sources=args.continue_missing_sources,
                allow_local=args.allow_local, production_root=args.production_root,
                resource_ids=sorted(_ids(args.resource)), profile=profiles[0] if profiles else None)
            if args.detach:
                from ..jobs import start_acquisition_job
                result = start_acquisition_job(args.candidate_manifest, args.staging_root,
                    job_dir=args.job_dir, **options)
                result = {"operation": "build", **result}
            else:
                result = capture(args.candidate_manifest, args.staging_root, plan_only=args.plan,
                    progress=lambda message: print(message, file=sys.stderr), **options)
                result["operation"] = "build"
        elif args.command == "preview":
            from .capture import preview
            if len(_ids(args.profile)) > 1:
                raise AcquisitionError("A frozen preview has one profile; select at most one")
            result = preview(args.staging_root, args.recipe, args.assets, preview_bytes=args.preview_bytes,
                expanded_bytes=args.expanded_bytes, scratch_bytes=args.scratch_bytes,
                reserve_bytes=args.reserve_bytes, budget_bytes=args.budget_bytes,
                shared_expansion=args.shared_expansion,
                resource_ids=sorted(_ids(args.resource)), profile=next(iter(_ids(args.profile)), None),
                progress=lambda message: print(message, file=sys.stderr))
        elif args.command == "review":
            from .capture import review
            if len(_ids(args.profile)) > 1:
                raise AcquisitionError("A frozen review has one profile; select at most one")
            result = review(args.staging_root, args.fragment, evidence=args.evidence, reviewer=args.reviewer, output=args.output,
                resource_ids=sorted(_ids(args.resource)), profile=next(iter(_ids(args.profile)), None))
        elif args.command == "audit":
            result = audit(args, context)
        elif args.command == "report":
            result = report(args, context)
        elif args.command == "discover":
            result = discover(args, context)
        elif args.command == "inspect-local":
            result = inspect_local(args, context)
        elif args.command == "prepare-local":
            result = prepare_local(args, context)
        else:
            result = stage(args, context)
        _save_and_print(args, result)
        return 0
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"error": str(error)[:1500]}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
