"""Bounded, read-only checks after the builder's full integrity verification.

The returned summary belongs in private build state, outside the checksum
manifest. This audit does not rehash source files or certify a browser/device.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .archive import document_assets
from .atlas_build import validate_links
from .catalog import learning_coverage, learning_shelves
from .layout import content_root, logical_name, managed_path
from .safety import SafetyError, reject_symlinks, safe_path
from .search_pack import _validate as validate_transport, chunk_path

METADATA_LIMIT = 64 * 1024 * 1024
SMOKE_TIMEOUT = 60
TEMPLATES = Path(__file__).with_name("templates")


def _read(path: Path, limit: int = METADATA_LIMIT) -> bytes:
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise SafetyError(f"Postflight file is missing or exceeds its read limit: {path.name}")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SafetyError(f"Postflight file exceeds its read limit: {path.name}")
    return data


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise SafetyError(f"Postflight expected an object: {path.name}")
    return value


def _require(condition, message: str) -> None:
    if not condition:
        raise SafetyError("Postflight: " + message)


def _smoke(library: Path, assets: list[dict], coverage: dict, required: bool) -> dict:
    node = shutil.which("node")
    if node is None:
        _require(not required, "Node is required for search runtime smoke testing")
        return {"status": "skipped", "reason": "Node is unavailable"}
    runtime = _read(safe_path(library, "SEARCH/search.js"), 1024 * 1024)
    _require(runtime == _read(TEMPLATES / "search.js", 1024 * 1024),
             "published search runtime differs from this OWL installation")
    by_path = {a["destination"]: a for a in assets}
    starts, cursor = [], 0
    for row in coverage["assets"]:
        starts.append({"id": cursor, "destination": row["destination"]})
        cursor += row["passages"]
    samples = []
    if starts:
        samples = [starts[0], starts[len(starts) // 2], starts[-1]]
        for category in ("critical", "textbooks", "illustrated-guides"):
            for item in starts:
                asset = by_path[item["destination"]]
                if (asset.get("critical") if category == "critical" else category in learning_shelves(asset)):
                    samples.append(item)
                    break
    samples = list({row["id"]: row for row in samples}.values())
    payload = {"library": str(library), "runtime": str(TEMPLATES / "search.js"),
               "documents": coverage["documents"], "samples": samples,
               "assets": [{"destination": a["destination"], "shelves": (["legacy"] if a.get("legacy") else sorted(learning_shelves(a))),
                           "legacy": bool(a.get("legacy"))}
                          for a in assets]}
    # The helper writes exactly one bounded JSON result. Redirect diagnostics to
    # a file so an unexpected child failure cannot fill parent memory/context.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run([node, "--max-old-space-size=128", str(TEMPLATES / "search_smoke.cjs")],
                                    input=json.dumps(payload).encode(), stdout=output,
                                    stderr=output, timeout=SMOKE_TIMEOUT, check=False)
        except subprocess.TimeoutExpired as error:
            raise SafetyError(f"Postflight search smoke exceeded {SMOKE_TIMEOUT} seconds") from error
        output.seek(0)
        raw = output.read(8193)
    _require(len(raw) <= 8192, "search smoke output exceeded its limit")
    _require(result.returncode == 0, "search runtime smoke failed: " + raw.decode("utf-8", "replace")[:1500])
    report = json.loads(raw)
    _require(isinstance(report, dict) and report.get("status") in {"passed", "skipped"},
             "invalid search smoke result")
    if required:
        _require(report["status"] == "passed", "required search runtime smoke was skipped")
    return report


def audit_build(drive_root: Path, *, info=None, run_smoke=True) -> dict:
    """Check generated output and return small actual-size/coverage summaries.

    Call after ``verify_drive`` and before marking private state complete. Supply
    its counts as ``info['verification']`` to include them without hashing again.
    ``run_smoke='required'`` also fails if Node or a bounded positive query is
    unavailable. ``False`` records an explicit skip. No files are changed.
    """
    try:
        return _audit(drive_root, info=info, run_smoke=run_smoke)
    except (OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, SafetyError):
            raise
        raise SafetyError(f"Postflight: invalid build output ({str(error)[:500]})") from error


def _audit(drive_root: Path, *, info, run_smoke) -> dict:
    _require(run_smoke in (True, False, "required"), "invalid search smoke policy")
    root = Path(drive_root).resolve()
    library = content_root(root)
    stored = _json(safe_path(library, "BUILD_INFO.json"))
    info = stored if info is None else info
    inventory = _json(safe_path(library, "INVENTORY.json"))
    locked = _json(safe_path(library, "LOCKED_CATALOG.yaml"))
    selection = _json(safe_path(library, "CONTENT_SELECTION.json"))
    coverage = _json(safe_path(library, "SEARCH/coverage.json"))
    for name in ("profile", "content_selection", "content_complete", "asset_count", "search"):
        _require(info.get(name) == stored.get(name), f"BUILD_INFO differs from the supplied {name}")
    assets = inventory["assets"]
    _require(isinstance(assets, list) and locked.get("assets") == assets, "locked catalog and inventory assets differ")
    profile = info["profile"]
    _require(len(assets) == info["asset_count"], "asset count differs from build information")
    chosen = inventory.get("content_selection")
    _require(chosen == info.get("content_selection") == selection.get("selection") ==
             locked["selection_lock"].get("content_selection"), "selection manifests differ")
    _require(profile["id"] == selection.get("profile") == locked["selection_lock"].get("profile_id"),
             "selection profile differs")
    _require(inventory.get("content_complete") == info.get("content_complete") == selection.get("content_complete"),
             "content completeness differs")
    _require(coverage == inventory.get("search") == info.get("search"), "search coverage manifests differ")
    ids = [a["id"] for a in assets]
    destinations = [a["destination"] for a in assets]
    _require(len(set(ids)) == len(ids) and len({s.casefold() for s in destinations}) == len(destinations),
             "duplicate selected asset or destination")
    manifest, seen = {}, set()
    for line in _read(safe_path(library, "SHA256SUMS.txt")).decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        _require(match is not None, "invalid checksum manifest entry")
        name = logical_name(match[2])
        _require(name.casefold() not in seen, "duplicate checksum manifest entry")
        seen.add(name.casefold())
        manifest[name] = match[1]
    _require("START_HERE.html" in manifest and "SHA256SUMS.txt" not in manifest and
             not any(name.casefold().startswith(".owl/") for name in manifest), "invalid checksum manifest scope")
    sizes = {}
    for name in [*manifest, "SHA256SUMS.txt"]:
        path = managed_path(library, name)
        _require(path.is_file(), f"managed file is missing: {name}")
        sizes[name] = path.stat().st_size
    for asset in assets:
        name = asset["destination"]
        _require(name in manifest and manifest[name] == asset["sha256"] and sizes[name] == asset["size_bytes"],
                 f"selected source differs from manifest: {name}")
    readable = document_assets(assets)
    rows = coverage["assets"]
    _require(isinstance(rows, list) and [(r["id"], r["destination"]) for r in rows] ==
             [(a["id"], a["destination"]) for a in sorted(readable, key=lambda a: a["destination"])],
             "search coverage does not match selected documents")
    _require(all(type(row["passages"]) is int and row["passages"] > 0 for row in rows) and
             sum(row["passages"] for row in rows) == coverage["documents"], "search passage counts differ")
    _require(all(row["status"] in {"full_text", "partial", "metadata_only"} for row in rows),
             "invalid search coverage status")
    transport = coverage["transport"]
    validate_transport(transport)
    _require(transport["size"] == coverage["index_bytes"] and transport["index_sha256"] == coverage["index_sha256"],
             "search index identity differs from coverage")
    encoded = _read(safe_path(library, "SEARCH/manifest.js"), 4096)
    prefix, suffix = b"globalThis.OWLSearchManifest(", b");\n"
    _require(encoded.startswith(prefix) and encoded.endswith(suffix) and
             json.loads(encoded[len(prefix):-len(suffix)]) == transport, "published search manifest differs")
    generated = set(coverage["generated_files"])
    expected = {"SEARCH/manifest.js", "SEARCH/search.js", "SEARCH/coverage.json", "SEARCH.html",
                f"SEARCH/chunks/{transport['index_sha256']}/owner.json",
                *(chunk_path(transport, n) for n in range(transport["chunk_count"]))}
    _require(generated == expected and generated <= manifest.keys(), "search output selection differs")
    for name, integrity in coverage["file_integrity"].items():
        _require(name in generated and sizes[name] == integrity["size_bytes"] and manifest[name] == integrity["sha256"],
                 f"search file differs from integrity metadata: {name}")
    _require(set(coverage["file_integrity"]) == generated - {"SEARCH/coverage.json"},
             "search integrity metadata is incomplete")
    # Only generated navigation is parsed. Publisher content remains untouched;
    # the existing link validator streams any referenced source HTML anchors.
    pages, page_bytes = {}, 0
    for name in manifest:
        if name not in destinations and name.endswith(".html") and name != "SEARCH.html":
            data = _read(managed_path(library, name))
            page_bytes += len(data)
            _require(page_bytes <= METADATA_LIMIT, "generated navigation exceeds its read limit")
            pages[name] = data.decode("utf-8")
    validate_links(library, pages, assets)
    _require(inventory.get("learning_coverage") == learning_coverage(assets), "learning coverage differs")
    source_bytes = sum(sizes[name] for name in destinations)
    search_bytes = sum(sizes[name] for name in generated)
    managed_bytes = sum(sizes.values())
    reserve = profile["reserve_bytes"]
    plan = info.get("plan", {})
    cache_allowance = plan.get("index_cache_budget_bytes", 0) if plan.get("index_cache_on_drive") else 0
    cache_allowance += plan.get("build_input_cache_bytes", 0) if plan.get("build_input_cache_on_drive") else 0
    acquisition_allowance = plan.get("acquisition_workspace_budget_bytes", 0)
    free = shutil.disk_usage(library).free
    _require(managed_bytes + reserve + cache_allowance + acquisition_allowance <= profile["capacity_bytes"],
             "actual managed output and retained cache allowance exceed profile capacity")
    _require(search_bytes <= profile["search_budget_bytes"], "actual search output exceeds profile budget")
    _require(free >= reserve, "filesystem free space is below the profile reserve")
    verification = info.get("verification")
    if verification is not None:
        _require(isinstance(verification, dict) and not verification.get("FAILED") and not verification.get("MISSING"),
                 "preceding integrity verification failed")
        verification = {key: verification.get(key, 0) for key in ("OK", "FAILED", "MISSING", "UNKNOWN")}
    smoke = (_smoke(library, readable, coverage, run_smoke == "required") if run_smoke else
             {"status": "skipped", "reason": "disabled by caller"})
    summary = {"schema_version": 1, "status": "passed", "profile": profile["id"],
            "selection": {"assets": len(assets), "documents": len(readable),
                          "content_complete": inventory["content_complete"],
                          "sha256": hashlib.sha256(json.dumps(locked, sort_keys=True, separators=(",", ":")).encode()).hexdigest()},
            "bytes": {"managed": managed_bytes, "sources": source_bytes, "search": search_bytes,
                      "raw_index": coverage["index_bytes"], "capacity": profile["capacity_bytes"],
                      "reserve": reserve, "filesystem_free": free, "on_drive_cache_allowance": cache_allowance,
                      "acquisition_workspace_allowance": acquisition_allowance,
                      "capacity_remaining_after_reserve": profile["capacity_bytes"] - managed_bytes - reserve - cache_allowance - acquisition_allowance},
            "coverage": {"passages": coverage["documents"], "assets_by_status": dict(Counter(r["status"] for r in rows)),
                         "warnings": sum(r.get("warning_count", 0) for r in rows),
                         "learning": inventory["learning_coverage"]},
            "navigation": {"status": "passed", "pages_checked": len(pages)},
            "verification": {"source_hashes_repeated": False, "preceding_counts": verification,
                             "manifest_entries": len(manifest)}, "search_smoke": smoke}
    cache = coverage.get("cache")
    if cache is not None:
        _require(isinstance(cache, dict) and cache.get("mode") in {"shards", "completed-index", "raw-index"} and
                 all(type(cache.get(key)) is int and cache[key] >= 0 for key in ("hits", "misses", "metadata_reuses")),
                 "invalid search cache statistics")
        summary["cache"] = {key: cache[key] for key in ("mode", "hits", "misses", "metadata_reuses")}
    return summary
