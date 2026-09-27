"""Prepare source-review inputs from frozen map selection and cached metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..safety import atomic_write, reject_symlinks
from .capture import normalize_manifest
from .map_manifest import _load, freeze_selection
from .maps import MapError
from .metadata import Fetcher
from .providers import _Links, _map_row


def probe_requests(discovery, profile):
    selection = freeze_selection(discovery, profile)
    requests = [{"id": "usgs_" + row["publisher_id"], "url": row["source_url"],
                 "expected_size_bytes": row["api_size_bytes"]} for row in selection["sheets"]]
    if len({row["id"] for row in requests}) != len(requests):
        raise MapError("Duplicate selected USGS publisher identity")
    return {"schema_version": 1,
            "description": "HEAD-only exact lengths and publisher checksums for all selected detailed New England topo sheets; no resource bodies.",
            "requests": requests}


def asset_template(source):
    """Ordinary PDF identity for capture receipts; content review stays pending."""
    info = source["map_metadata"]
    overview = info["role"] == "national-overview"
    scale = f"1:{info['scale']:,}"
    location = "USA_OVERVIEW" if overview else "NEW_ENGLAND"
    return {"id": source["id"], "title": f"{info['title']} — {scale}, {source['version']}",
        "category": "maps", "format": "pdf", "source_url": source["source_url"],
        "destination": f"MAPS/TOPOGRAPHIC/{location}/{source['id']}.pdf", "version": source["version"],
        "size_bytes": source["size_bytes"], "sha256": source["sha256"],
        "license": "USGS U.S. Government map; preserve original map and third-party notices; notice review pending",
        "redistributable": False, "required": True, "profiles": [], "critical": False, "reader_required": False,
        "publisher": "U.S. Geological Survey", "source_page": source["metadata_evidence"][0]["url"],
        "language": "en", "resource_type": "reference", "illustrated": True,
        "attribution": "U.S. Geological Survey and credited map-data contributors. Preserve the original sheet, publication date, legend and all notices.",
        "description": f"Original complete publisher PDF at {scale}, edition {source['version']}. " +
            ("Historical national overview; all-50-state extent and original notices await PDF review. " if overview else
             "New England " + ("coastal supplement" if info["role"] == "coastal-supplement" else "required-scale sheet") +
             "; footprint is based on publisher bounds and actual map-frame coverage awaits review. ") +
            "Mixed-scale footprint coverage does not establish complete 1:24,000 land coverage. Roads, structures, shorelines and routes may have changed; evacuation-route suitability is not verified.",
        "tags": ["maps", "usgs", "topographic", info["role"]], "review_status": "pending"}


def capture_candidates(selection, fetcher, *, overviews=(), overview_fetcher=None):
    """Bind each candidate to a verified publisher metadata page, never a PDF."""
    if (selection.get("content_ready") is not False or not selection.get("geographic_complete")
            or selection.get("sheet_count") != len(selection.get("sheets", []))):
        raise MapError("Capture requires a pending frozen map selection")
    indexed = {}
    for evidence in selection.get("metadata_evidence", []):
        if urlsplit(evidence.get("url", "")).hostname != "tnmaccess.nationalmap.gov":
            continue
        body = fetcher.fetch(evidence["url"])
        if hashlib.sha256(body).hexdigest() != evidence.get("sha256"):
            raise MapError("USGS metadata changed from the frozen selection")
        for item in json.loads(body).get("items", []):
            key = (item.get("sourceId"), item.get("downloadURL"))
            if key in indexed:
                raise MapError("Duplicate publisher map identity across metadata pages")
            indexed[key] = (item, {key: value for key, value in evidence.items() if key != "cached"})
    sources = []
    for row in selection["sheets"]:
        if row.get("size_status") != "verified-by-head":
            raise MapError("Every map capture candidate requires an exact HEAD size")
        match = indexed.get((row.get("publisher_id"), row.get("source_url")))
        if match is None:
            raise MapError("Selected map identity is absent from its frozen publisher metadata")
        item, evidence = match
        normalized = _map_row(item, {"url": row["discovered_on"], "scale": row["scale"]})
        for key in ("sheet_id", "source_url", "edition", "bbox", "title", "scale"):
            if normalized[key] != row[key]:
                raise MapError(f"Selected map {key} differs from its frozen publisher metadata")
        sources.append({"id": "usgs_" + row["publisher_id"], "resource_ids": ["regional-maps"],
            "source_url": row["source_url"], "version": str(row["edition"]), "size_bytes": row["size_bytes"],
            "sha256": row["sha256"], "publisher_checksums": {}, "metadata_evidence": [evidence],
            "map_metadata": {"title": row["title"], "sheet_id": row["sheet_id"], "scale": row["scale"],
                "bbox": row["bbox"], "role": "required-scale" if row["scale"] == selection["base_scale"] else "coastal-supplement",
                "review_status": "pending", "source_probe_id": row["source_probe_id"]}})
    expected = {row["source_url"]: row for row in selection.get("overview_candidates", [])}
    supplied = {}
    for row in overviews:
        url = row.get("source_url")
        if url not in expected or url in supplied:
            raise MapError("Unexpected or duplicate national overview candidate")
        frozen = expected[url]
        if any(row.get(key) != frozen.get(key) for key in ("id", "size_bytes", "version_date", "scale", "sha256")):
            raise MapError("National overview identity changed from the frozen selection")
        if row.get("size_status") != "verified-by-head" or row.get("content_ready") is not False:
            raise MapError("National overview requires an exact pending source candidate")
        evidence = row["metadata_evidence"]
        body = (overview_fetcher or fetcher).fetch(evidence["url"])
        links = {urljoin(evidence["url"], href) for href, _ in _Links(body).links}
        if hashlib.sha256(body).hexdigest() != evidence.get("sha256") or url not in links:
            raise MapError("National overview is not bound to unchanged publisher metadata")
        supplied[url] = row
        sources.append({"id": row["id"], "resource_ids": ["regional-maps"], "source_url": url,
            "version": row["version_date"], "size_bytes": row["size_bytes"], "sha256": row["sha256"],
            "publisher_checksums": {}, "metadata_evidence": [evidence],
            "map_metadata": {"title": row["title"], "scale": row["scale"], "role": "national-overview",
                "review_status": "pending", "source_probe_id": row["source_probe_id"]}})
    if expected.keys() != supplied.keys():
        raise MapError("Missing frozen national overview candidate")
    total = sum(row["size_bytes"] for row in sources)
    if total != selection["combined_candidate_bytes"]:
        raise MapError("Map capture bytes differ from frozen selection")
    for source in sources:
        source["fullasset_metadata"] = asset_template(source)
    return normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": "regional-maps-detailed-1tb",
        "profile": selection["profile"], "content_ready": False, "sources": sources,
        "selection_recipe": {"id": selection["recipe_id"], "sha256": selection["recipe_sha256"]},
        "coverage": selection["coverage"], "blockers": selection["blockers"],
        "review_requirements": ["Check every PDF's map frame, scale, edition date and geographic extent.",
            "Review labels, contours, legends and notices at ordinary offline reading sizes.",
            "Resolve required-scale coastal gaps using inspected map frames or authoritative valid water geometry; do not relax area tolerance.",
            "Keep historical publication dates and the mixed-scale warning visible in navigation."],
        "budget": {"download_bytes": total, "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0}})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--source-probes", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--overview", type=Path, action="append", default=[])
    parser.add_argument("--profile", default="full-1tb")
    parser.add_argument("--metadata-cache", type=Path, default=Path(".owl/acquisition/metadata"))
    parser.add_argument("--overview-metadata-cache", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.output and not args.request_output:
        parser.error("Choose --request-output for HEAD requests and/or --output for capture candidates")
    if args.output and not args.source_probes:
        parser.error("Capture candidates require --source-probes")
    discovery = _load(args.discovery)
    if args.request_output:
        requests = probe_requests(discovery, args.profile)
        reject_symlinks(args.request_output)
        args.request_output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.request_output, (json.dumps(requests, indent=2, sort_keys=True) + "\n").encode())
        if not args.output:
            print(json.dumps({"head_requests": len(requests["requests"]), "body_downloads": 0,
                              "output": str(args.request_output)}, indent=2))
            return 0
    selection = freeze_selection(discovery, args.profile, _load(args.source_probes))
    result = capture_candidates(selection, Fetcher(args.metadata_cache, offline=True),
                                overviews=[_load(path) for path in args.overview],
                                overview_fetcher=Fetcher(args.overview_metadata_cache, offline=True) if args.overview_metadata_cache else None)
    reject_symlinks(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(args.output, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"sources": len(result["sources"]), "download_bytes": result["budget"]["download_bytes"],
                      "storage_peak_bytes": result["storage_peak_bytes"], "body_downloads": 0,
                      "content_ready": False, "output": str(args.output)}, indent=2))
    return 0
