"""Freeze metadata-selected map identities without inventing content pins."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ..safety import atomic_write, reject_symlinks
from .maps import MapError


def freeze_selection(discovery: dict, profile: str, probes: dict | None = None) -> dict:
    matches = [row for row in discovery.get("results", []) if row.get("resource_id") == "regional-maps"
               and profile in row.get("plans", {})]
    if len(matches) != 1:
        raise MapError("Expected exactly one regional-maps discovery result for the requested profile")
    result = matches[0]
    if not result.get("inventory_complete"):
        raise MapError("Cannot freeze an incomplete map inventory")
    plan = result.get("plans", {}).get(profile, {})
    if not plan.get("geographic_complete") or plan.get("holes"):
        raise MapError("Cannot freeze a geographically incomplete map proposal")
    sheets = deepcopy(plan.get("proposed_sheets", []))
    if not sheets:
        raise MapError("Map proposal has no sheets")
    by_url = {}
    for row in (probes or {}).get("records", []):
        url = row.get("source_url")
        if url in by_url:
            raise MapError("Duplicate source probe URL")
        by_url[url] = row
    seen, seen_urls, discrepancies, missing_sizes, missing_hashes = set(), set(), [], [], []
    for row in sheets:
        url = row["source_url"]
        identity = (row["sheet_id"], row["scale"])
        if identity in seen:
            raise MapError("Duplicate selected map sheet")
        if url in seen_urls:
            raise MapError("Duplicate selected map source URL")
        seen.add(identity)
        seen_urls.add(url)
        row["api_size_bytes"] = row["size_bytes"]
        probe = by_url.get(url, {})
        success = [item for item in probe.get("evidence", [])
                   if item.get("method") == "HEAD" and item.get("status") == 200 and
                   item.get("url") == url and item.get("body_read") is False]
        size = probe.get("size_bytes")
        if success:
            measured_sizes = set()
            for response in success:
                headers = response.get("headers", {})
                if "content-range" in headers or headers.get("content-encoding", "identity").lower() != "identity":
                    raise MapError("Map HEAD does not describe a whole identity representation")
                length = headers.get("content-length")
                if not isinstance(length, str) or not length.isascii() or not length.isdigit() or int(length) < 1:
                    raise MapError("Successful map HEAD lacks an exact Content-Length")
                measured_sizes.add(int(length))
            if len(measured_sizes) != 1:
                raise MapError("Conflicting map HEAD Content-Length evidence")
            if type(size) is not int or size not in measured_sizes:
                raise MapError("Source probe size differs from its URL-bound HEAD Content-Length")
            row["size_bytes"] = size
            row["size_status"] = "verified-by-head"
            row["source_probe_id"] = probe["id"]
            if size != row["api_size_bytes"]:
                discrepancies.append({"sheet_id": row["sheet_id"], "source_url": url,
                                      "api_size_bytes": row["api_size_bytes"], "head_size_bytes": size})
        else:
            row["size_status"] = "publisher-inventory-only"
            missing_sizes.append(url)
        pin = probe.get("sha256")
        if pin is not None and (not isinstance(pin, str) or len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin)):
            raise MapError("Source probe has an invalid whole-file SHA256")
        if pin is not None and (probe.get("status") != "proposed" or not success):
            raise MapError("Whole-file SHA256 requires a proposed source probe and successful URL-bound HEAD")
        row["sha256"] = pin
        row["review_status"] = "pending"
        if pin is None:
            missing_hashes.append(url)
    total = sum(row["size_bytes"] for row in sheets)
    overviews = deepcopy(result.get("overview_candidates", []))
    overview_urls = set()
    sheet_urls = {row["source_url"] for row in sheets}
    for row in overviews:
        if (not row.get("source_url") or row["source_url"] in overview_urls or row["source_url"] in sheet_urls
                or type(row.get("size_bytes")) is not int or row["size_bytes"] < 1
                or row.get("sha256") is not None or row.get("pin_status") != "pending"):
            raise MapError("National overview candidates require unique identities, exact sizes and pending pins")
        overview_urls.add(row["source_url"])
    overview_bytes = sum(row["size_bytes"] for row in overviews)
    if total + overview_bytes > plan["budget_bytes"]:
        raise MapError("Verified map sizes exceed the original map allowance")
    evidence = [{k: v for k, v in row.items() if k != "cached"} for row in result.get("metadata_evidence", [])]
    blockers = ["Selected PDFs await build-time whole-file verification and visual/scale/attribution review.",
                ("USA overview source identity is selected; whole-file SHA256 and PDF coverage/scale/notices review remain pending."
                 if overviews else "USA overview source selection and whole-file pin remain pending.")]
    if missing_hashes:
        blockers.append(f"{len(missing_hashes)} map PDFs lack independently verified whole-file SHA256 pins.")
    if missing_sizes:
        blockers.append(f"{len(missing_sizes)} map PDF byte sizes have publisher-inventory evidence only.")
    if plan.get("required_scale_holes"):
        blockers.append("Required 1:24,000 coverage retains explicit gaps; coarser supplements establish mixed-scale footprint coverage only.")
    return {"schema_version": 1, "status": "proposed", "resource_id": "regional-maps", "profile": profile,
            "recipe_id": result["recipe_id"], "recipe_sha256": result["recipe_sha256"],
            "geographic_complete": True, "content_ready": False, "base_scale": plan["base_scale"],
            "scales": plan["scales"], "size_bytes": total, "budget_bytes": plan["budget_bytes"],
            "overview_candidates": overviews, "overview_candidate_bytes": overview_bytes,
            "combined_candidate_bytes": total + overview_bytes,
            "sheet_count": len(sheets), "sheets": sheets, "metadata_size_discrepancies": discrepancies,
            "coverage": {"states": result["boundary_states"], "area_tolerance_square_degrees": 0,
                         "holes": {}, "offshore_water_exclusions": result.get("offshore_water_exclusions", []),
                         **({"required_scale_complete": plan["required_scale_complete"],
                             "required_scale_holes": plan.get("required_scale_holes", {})} if "required_scale_complete" in plan else {}),
                         "basis": "Publisher sheet bounding boxes against exact Census state polygons, excluding only evidenced zero-land ocean geometry; no buffer or simplification."},
            "historical_warning": "Historical sheets retain their publication dates. Roads, routes, structures and shorelines may have changed; current evacuation-route suitability is not verified.",
            "blockers": blockers, "metadata_evidence": evidence}


def _load(path: Path):
    reject_symlinks(path)
    if path.stat().st_size > 50 * 1024 * 1024:
        raise MapError("Map evidence exceeds 50 MiB bound")
    return json.loads(path.read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--profile", default="full-1tb")
    parser.add_argument("--source-probes", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = freeze_selection(_load(args.discovery), args.profile,
                              _load(args.source_probes) if args.source_probes else None)
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    reject_symlinks(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, payload)
    print(json.dumps({"status": result["status"], "sheets": result["sheet_count"], "size_bytes": result["size_bytes"],
                      "geographic_complete": True, "content_ready": False, "sha256": hashlib.sha256(payload).hexdigest(),
                      "output": str(args.output)}, indent=2))
    return 0
