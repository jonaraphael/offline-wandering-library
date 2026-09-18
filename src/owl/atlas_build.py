"""Publish a human topic index from verified files already on a library drive."""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import unquote, urlsplit

from .build import REPO_ROOT, _json, _owned_directory, _root, _state, check_space
from .catalog import ROOTS, fingerprint, load_catalog, load_profiles, resolve_content
from .navigation import GENERATED_PATHS, generate_navigation
from .runtime import file_lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, safe_path, sha256_file, validate_relative

REPORT = "INDEX/navigation-report.json"
JOB = ".owl/atlas-job.json"


def _atlas_path(relative: str) -> bool:
    validate_relative(relative)
    return (relative in {"INDEX/topics.html", "INDEX/books.html", REPORT} or
            any(relative.startswith(prefix) and relative.endswith(".html")
                for prefix in ("INDEX/topics/", "INDEX/topic-a-z/", "INDEX/books/", "INDEX/topic-entrances/")))


def _previous(state: dict) -> list[str]:
    previous = state.get("atlas_managed", [])
    if not isinstance(previous, list) or any(not isinstance(p, str) or not _atlas_path(p) for p in previous):
        raise SafetyError("Invalid managed atlas paths")
    if set(previous) - set(state["managed"]):
        raise SafetyError("Atlas paths are not registered as managed outputs")
    return previous


def _reported_paths(report: dict, managed) -> list[str]:
    """Recover atlas ownership only from a checksum-verified output report."""
    paths = report.get("generated_files") if isinstance(report, dict) else None
    if (not isinstance(paths, list) or any(not isinstance(p, str) or not _atlas_path(p) for p in paths)
            or len(paths) != len(set(paths)) or set(paths) - set(managed) or REPORT not in paths):
        raise SafetyError("Invalid checksum-covered atlas output report")
    return sorted(paths)


def _unavailable(relative: str) -> str:
    home = posixpath.relpath("START_HERE.html", posixpath.dirname(relative))
    categories = posixpath.relpath("INDEX/categories.html", posixpath.dirname(relative))
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Unavailable in this build · OWL</title><body><main>'
            '<h1>Unavailable in this build</h1><p>This previously managed navigation page '
            'is no longer part of the current topic selection.</p>'
            f'<p><a href="{html.escape(home)}">Start here</a> · '
            f'<a href="{html.escape(categories)}">Current category index</a></p></main></body></html>')


def plan_atlas(target: Path, assets: list[dict], navigation: dict | None, state: dict,
               *, strict_coverage: bool = False) -> tuple[dict[str, str], dict | None]:
    """Resolve sources and plan every dynamic path before allowing publication."""
    from .atlas import prepare_atlas
    from .atlas_model import validate_sources
    if navigation is None:
        pages, report = {}, None
    else:
        sections = validate_sources(target, assets, navigation)
        pages, report = prepare_atlas(target, assets, {**navigation, "sections": sections})
        if strict_coverage and any(report.get(key) for key in (
                "unmapped_critical", "missing_textbook_subject_routes", "missing_textbook_learning_routes")):
            raise SafetyError("Atlas coverage is incomplete for critical assets or required textbook routes; review navigation-report coverage")
    retired = []
    for relative in _previous(state):
        if relative not in pages and relative != REPORT:
            pages[relative] = _unavailable(relative)
            retired.append(relative)
    if report is not None:
        report["retired_pages"] = sorted(retired)
        report["generated_files"] = sorted([*pages, REPORT])
        report["html_bytes"] = sum(len(text.encode("utf-8")) for text in pages.values())
        report["generated_file_count"] = len(pages) + 1
        pages[REPORT] = _json(report).decode("utf-8")
    elif REPORT in _previous(state):
        pages[REPORT] = _json({"schema_version": 1, "enabled": False,
                               "retired_pages": sorted(retired), "generated_files": sorted([*pages, REPORT])}).decode()
    return pages, report


def preflight_outputs(target: Path, pages: dict, state: dict) -> None:
    from .copy import _check_names, _existing_names
    _check_names(list(pages))
    _existing_names(target, pages)
    owned = set(state["managed"])
    for relative in pages:
        path = safe_path(target, relative)
        if path.exists() and (relative not in owned or not path.is_file()):
            raise SafetyError(f"Atlas would overwrite an unowned file or directory: {relative}")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.ids = [], set()
        self.scripts = []
        self.inline_script = False
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") is not None:
            self.ids.add(values["id"])
        if tag == "a" and "href" in values:
            self.links.append(values["href"])
        if tag == "script":
            self.scripts.append(attrs)
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script and data.strip():
            self.inline_script = True


class _SourceAnchors(HTMLParser):
    """Retain only requested source IDs, never the source's links or other IDs."""
    def __init__(self, wanted):
        super().__init__(convert_charrefs=True)
        self.wanted = frozenset(wanted)
        self.found = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value in self.wanted:
                self.found.add(value)


def validate_links(target: Path, pages: dict[str, str], assets=()) -> None:
    """Check generated pages, including local HTML fragments, before writing."""
    parsed = {}
    encodings = {a["destination"]: a.get("text_encoding", "utf-8") for a in assets}
    for relative, text in pages.items():
        if relative.endswith(".html"):
            parsed[relative] = _Links()
            parsed[relative].feed(text)
            page = parsed[relative]
            if page.scripts:
                allowed = (relative == "START_HERE.html" and not page.inline_script and
                           len(page.scripts) == 1 and len(page.scripts[0]) == 2 and
                           dict(page.scripts[0]) == {"defer": None, "src": "SEARCH/search.js"})
                if not allowed:
                    raise SafetyError(f"Unexpected generated script: {relative}")
                for required in ("SEARCH/search.js", "SEARCH/manifest.js"):
                    if required not in pages and not safe_path(target, required).is_file():
                        raise SafetyError(f"Missing automatic search dependency: {required}")
    requested = {}
    for relative, page in list(parsed.items()):
        for href in page.links:
            link = urlsplit(href)
            if link.scheme or link.netloc or link.query:
                raise SafetyError(f"Nonlocal generated link in {relative}: {href}")
            destination = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(link.path))) if link.path else relative
            path = safe_path(target, destination)
            if destination not in pages and not path.is_file():
                raise SafetyError(f"Missing generated link in {relative}: {destination}")
            if link.fragment and destination.lower().endswith((".html", ".htm")):
                fragment = unquote(link.fragment)
                if destination not in parsed:
                    requested.setdefault(destination, {}).setdefault(fragment, (relative, href))
                elif fragment not in parsed[destination].ids:
                    raise SafetyError(f"Missing HTML fragment in {relative}: {href}")
    # Source HTML may be enormous. Scan each referenced file once while retaining
    # only the bounded set of anchors requested by generated navigation pages.
    for destination, anchors in requested.items():
        parser = _SourceAnchors(anchors)
        path = safe_path(target, destination)
        with path.open(encoding=encodings.get(destination, "utf-8"), errors="replace") as handle:
            for block in iter(lambda: handle.read(65536), ""):
                parser.feed(block)
                if len(parser.rawdata) > 1024 * 1024:
                    raise SafetyError(f"Source HTML has an unterminated token over 1 MiB: {destination}")
        parser.close()
        for fragment, (relative, href) in anchors.items():
            if fragment not in parser.found:
                raise SafetyError(f"Missing HTML fragment in {relative}: {href}")


def register_outputs(target: Path, pages: dict, state: dict) -> None:
    preflight_outputs(target, pages, state)
    state["managed"] = sorted(set(state["managed"]) | set(pages))
    state["atlas_managed"] = sorted(set(_previous(state)) | {p for p in pages if _atlas_path(p)})
    atomic_write(safe_path(target, ".owl/state.json"), _json(state))


def write_outputs(target: Path, pages: dict[str, str]) -> None:
    for relative, text in sorted(pages.items()):
        atomic_write(safe_path(target, relative), text.encode("utf-8"))


def _checksums(target: Path) -> dict[str, str]:
    from .copy import _check_names
    path = safe_path(target, "SHA256SUMS.txt")
    if not path.exists():
        return {}
    names, result = [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match or match[2].casefold() == "sha256sums.txt":
            raise SafetyError("Invalid existing checksum manifest")
        names.append(match[2])
        result[match[2]] = match[1]
    _check_names(names)
    if not result:
        raise SafetyError("Empty existing checksum manifest")
    return result


def _verify_entries(target: Path, entries: dict, excluded=(), *, progress=print) -> None:
    from .copy import _check_names
    _check_names(list(entries))
    for relative, digest in sorted(entries.items()):
        if relative in excluded:
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SafetyError("Invalid stored atlas baseline checksum")
        progress(f"ATLAS VERIFY {relative}")
        path = safe_path(target, relative)
        if not path.is_file() or sha256_file(path) != digest:
            raise SafetyError(f"Library file failed integrity verification: {relative}")


def _new_inventory(target, all_assets, profile, profiles_dir, catalog, state, progress):
    profiles = load_profiles(profiles_dir)
    if profile not in profiles:
        raise SafetyError(f"Unknown profile: {profile}")
    selected, unresolved, selection = resolve_content(all_assets, profiles[profile],
        resources_path=catalog.with_name("resources.yaml"))
    present, missing = [], []
    for asset in selected:
        path = safe_path(target, asset["destination"])
        if not path.exists():
            missing.append({**asset, "unresolved_reason": "Selected file has not been downloaded onto this drive"})
            continue
        progress(f"ATLAS VERIFY {asset['destination']}")
        if not path.is_file() or path.stat().st_size != asset["size_bytes"]:
            raise SafetyError(f"Selected source size differs: {asset['destination']}")
        digest = sha256_file(path)
        if asset["sha256"] and digest != asset["sha256"]:
            raise SafetyError(f"Selected source checksum differs: {asset['destination']}")
        present.append({**asset, "sha256": digest, "verification": "pinned" if asset["sha256"] else "observed"})
    if not present:
        raise SafetyError("No selected catalog files are present on this drive")
    complete = not missing and (not selection or not selection["incomplete_resources"])
    inventory = {"schema_version": 1, "assets": present, "search": {"status": "not-built", "assets": [], "warnings": []},
                 "content_selection": selection, "content_complete": complete, "unresolved": [*unresolved, *missing]}
    info = {"schema_version": 1, "complete": True, "build_kind": "human-index-only", "profile": profiles[profile],
            "asset_count": len(present), "content_complete": complete,
            "search": inventory["search"], "catalog_sha256": sha256_file(catalog)}
    return inventory, info


def _inventory_assets(inventory: dict) -> list[dict]:
    """Resume state must meet the same content-path and hash invariants as inputs."""
    from .copy import _check_names
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1 or not isinstance(inventory.get("assets"), list):
        raise SafetyError("Invalid atlas source inventory")
    identities, paths = set(), []
    for asset in inventory["assets"]:
        if not isinstance(asset, dict):
            raise SafetyError("Invalid atlas inventory asset")
        identity, destination, digest = asset.get("id"), asset.get("destination"), asset.get("sha256")
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9_-]+", identity) or identity in identities
                or not isinstance(destination, str) or destination.split("/")[0] not in ROOTS
                or "/" not in destination or type(asset.get("size_bytes")) is not int or asset["size_bytes"] <= 0
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise SafetyError("Invalid or duplicate atlas source ID, content path, size, or SHA-256")
        for key in ("title", "category", "format", "version", "license"):
            if not isinstance(asset.get(key), str) or not asset[key].strip():
                raise SafetyError(f"Invalid atlas source metadata: {key}")
        identities.add(identity)
        paths.append(destination)
    _check_names(paths)
    return inventory["assets"]


def build_atlas(target: Path, *, navigation_dir: Path, catalog: Path = REPO_ROOT / "catalog/library.yaml",
                profile: str | None = None, profiles_dir: Path = REPO_ROOT / "profiles",
                allow_local: bool = False, strict_coverage: bool = False, progress=print) -> dict:
    """No downloads or search extraction. An interrupted publication can be rerun."""
    from .atlas_model import load_navigation
    target = _root(target)
    if not target.is_dir():
        raise SafetyError("The library directory must already exist on the mounted drive")
    all_assets = load_catalog(catalog, allow_local=allow_local)
    navigation = load_navigation(navigation_dir, all_assets)
    with guard_directory(target):
        _owned_directory(safe_path(target, ".owl"))
        with file_lock(safe_path(target, ".owl/build.lock")):
            state_path = safe_path(target, ".owl/state.json")
            state = _state(state_path)
            job_path = safe_path(target, JOB)
            if job_path.exists():
                job = json.loads(job_path.read_text(encoding="utf-8"))
                if (not isinstance(job, dict) or type(job.get("schema_version")) is not int or job["schema_version"] != 1
                        or not all(isinstance(job.get(key), dict) for key in ("inventory", "build_info", "baseline", "support_files"))
                        or type(job.get("finish_complete")) is not bool
                        or not isinstance(job.get("atlas_managed"), list)
                        or not isinstance(job["inventory"].get("assets"), list)):
                    raise SafetyError("Invalid atlas publication checkpoint")
                inventory, info, baseline = job["inventory"], job["build_info"], job["baseline"]
                progress("ATLAS RESUME: regenerating small static pages from the saved source inventory")
            else:
                baseline = _checksums(target)
                _verify_entries(target, baseline, progress=progress)
                inventory_path = safe_path(target, "INVENTORY.json")
                if inventory_path.exists():
                    if profile is not None:
                        raise SafetyError("Use the drive's existing inventory; change its profile with the drive builder")
                    if "INVENTORY.json" not in baseline or "BUILD_INFO.json" not in baseline:
                        raise SafetyError("Existing inventory and build information require a verified checksum manifest")
                    assets = load_catalog(inventory_path, allow_local=allow_local)
                    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                    inventory["assets"] = assets
                    info = json.loads(safe_path(target, "BUILD_INFO.json").read_text(encoding="utf-8"))
                    if not isinstance(info, dict) or info.get("schema_version") != 1:
                        raise SafetyError("Invalid build information")
                else:
                    if not profile:
                        raise SafetyError("No INVENTORY.json: supply --profile to use downloaded files at catalog destinations")
                    inventory, info = _new_inventory(target, all_assets, profile, profiles_dir, catalog, state, progress)
                # A checksum-verified OWL drive without its private state can be
                # adopted; arbitrary unrelated destination files remain unowned.
                state["managed"] = sorted(set(state["managed"]) | set(baseline))
                if baseline:
                    state["managed"] = sorted(set(state["managed"]) | {"SHA256SUMS.txt"})
                job = {"schema_version": 1, "inventory": inventory, "build_info": info, "baseline": baseline,
                       "support_files": {}, "atlas_managed": [],
                       "finish_complete": state.get("complete", False) if state_path.exists() else True}
                if REPORT in baseline:
                    previous_report = json.loads(safe_path(target, REPORT).read_text(encoding="utf-8"))
                    job["atlas_managed"] = _reported_paths(previous_report, baseline)
            # This also recovers adoption if stopped after saving the job but
            # before saving state on a drive whose private state was absent.
            state["managed"] = sorted(set(state["managed"]) | set(baseline) | ({"SHA256SUMS.txt"} if baseline else set()))
            if job["atlas_managed"]:
                recovered = _reported_paths({"generated_files": job["atlas_managed"]}, baseline)
                state["atlas_managed"] = sorted(set(_previous(state)) | set(recovered))
            assets = _inventory_assets(inventory)
            atlas_pages, report = plan_atlas(target, assets, navigation, state, strict_coverage=strict_coverage)
            inventory = {**inventory, "navigation": report}
            info = {**info, "navigation": report}
            pages = generate_navigation(target, assets, inventory, inventory.get("search", {}), write=False)
            pages.update(atlas_pages)
            pages["INVENTORY.json"] = _json(inventory).decode("utf-8")
            pages["BUILD_INFO.json"] = _json(info).decode("utf-8")
            support = job["support_files"]
            if "SEARCH.html" not in baseline and "SEARCH.html" not in support:
                support["SEARCH.html"] = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Search not built</title>'
                    '<h1>Full-text search has not been built</h1><p>The human topic index is available offline.</p>'
                    '<a href="INDEX/topics.html">Browse topics</a></html>')
            if "SEARCH/coverage.json" not in baseline and "SEARCH/coverage.json" not in support:
                support["SEARCH/coverage.json"] = _json(inventory.get("search", {"status": "not-built"})).decode()
            if "SOURCE_NOTES.txt" not in baseline and "SOURCE_NOTES.txt" not in support:
                support["SOURCE_NOTES.txt"] = (REPO_ROOT / "docs/sources.md").read_text(encoding="utf-8")
            if "VERIFY.py" not in baseline and "VERIFY.py" not in support:
                support["VERIFY.py"] = Path(__file__).with_name("verify.py").read_text(encoding="utf-8")
            if set(support) - {"SEARCH.html", "SEARCH/coverage.json", "SOURCE_NOTES.txt", "VERIFY.py"} or any(not isinstance(v, str) for v in support.values()):
                raise SafetyError("Invalid atlas checkpoint support-file paths")
            pages.update(support)
            if set(pages) & {a["destination"] for a in assets}:
                raise SafetyError("Generated atlas output conflicts with a source document")
            # On retries, only this operation's previously registered outputs may
            # differ from its immutable baseline. Existing source data never may.
            mutable = set(pages) | set(_previous(state)) | {"SHA256SUMS.txt"}
            _verify_entries(target, baseline, excluded=mutable, progress=progress)
            source_hashes = {a["destination"]: a["sha256"] for a in assets}
            _verify_entries(target, source_hashes, progress=progress)
            preflight_outputs(target, pages, state)
            validate_links(target, {**pages, "SHA256SUMS.txt": ""}, assets)
            check_space(target, sum(len(text.encode("utf-8")) for text in pages.values()) +
                        info.get("profile", {}).get("reserve_bytes", 0) + 1024 * 1024)
            atomic_write(job_path, _json(job))
            state.update(complete=False, phase="atlas")
            state["managed"] = sorted(set(state["managed"]) | set(source_hashes) | {"SHA256SUMS.txt"})
            register_outputs(target, pages, state)
            write_outputs(target, pages)
            checksums = {**baseline, **source_hashes,
                         **{p: hashlib.sha256(text.encode("utf-8")).hexdigest() for p, text in pages.items()}}
            _verify_entries(target, {p: checksums[p] for p in pages}, progress=progress)
            profile_data = info.get("profile", {})
            final_bytes = sum(safe_path(target, p).stat().st_size for p in checksums)
            if profile_data.get("capacity_bytes") and final_bytes + profile_data.get("reserve_bytes", 0) > profile_data["capacity_bytes"]:
                raise SafetyError("Atlas output exceeds the profile's final capacity; publication remains incomplete")
            check_space(target, profile_data.get("reserve_bytes", 0))
            atomic_write(safe_path(target, "SHA256SUMS.txt"), "".join(f"{digest}  {p}\n" for p, digest in sorted(checksums.items())).encode())
            for asset in assets:
                original = {**asset, "sha256": None} if asset.get("verification") == "observed" else asset
                state["assets"][asset["id"]] = {"sha256": asset["sha256"], "fingerprint": fingerprint(original)}
            state.update(complete=job["finish_complete"], phase="complete" if job["finish_complete"] else "build-incomplete")
            atomic_write(state_path, _json(state))
            job_path.unlink()
            progress(f"HUMAN INDEX COMPLETE: {target / 'INDEX/topics.html'}")
            if not state["complete"]:
                progress("The human index is usable; the interrupted full drive build remains incomplete. Rerun its build command to finish it.")
            for key in ("unmapped_critical", "missing_textbook_subject_routes", "missing_textbook_learning_routes"):
                if report.get(key):
                    progress(f"ATLAS COVERAGE {key}: {report[key]}")
            return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--navigation-dir", type=Path, default=REPO_ROOT / "catalog/navigation")
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog/library.yaml")
    parser.add_argument("--profile", help="only when no drive inventory exists: select already downloaded catalog files")
    parser.add_argument("--profiles-dir", type=Path, default=REPO_ROOT / "profiles")
    parser.add_argument("--allow-local", action="store_true", help="permit local/test source metadata; no source is downloaded")
    parser.add_argument("--strict-coverage", action="store_true", help="fail if critical assets or required textbook subject/learning routes are missing")
    args = parser.parse_args(argv)
    try:
        with interrupt_signals():
            build_atlas(args.target, navigation_dir=args.navigation_dir, catalog=args.catalog,
                        profile=args.profile, profiles_dir=args.profiles_dir, allow_local=args.allow_local,
                        strict_coverage=args.strict_coverage)
        return 0
    except KeyboardInterrupt:
        print("Human-index generation paused. Rerun the same command; source files and the publication checkpoint are retained.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
