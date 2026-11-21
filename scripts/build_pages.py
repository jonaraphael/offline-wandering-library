#!/usr/bin/env python3
"""Build the GitHub Pages artifact and optionally publish pinned, licensed copies."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

from owl.atlas_model import load_navigation
from owl.catalog import is_document, learning_shelves, load_catalog, load_profiles
from owl.navigation import CSS, GROUPS, _group
from owl.discovery import compile_records
from owl.search_ui import render_search_page
from owl.search_shards import SEARCH_ROOT, load_manifest
from owl.selector import ROOT, make_model, render_selector


CATALOG = ROOT / "catalog/library.yaml"
PROFILES = ROOT / "profiles"
SOURCE = ROOT / "web"
SITE_LIMIT = 950_000_000
FILE_LIMIT = 100_000_000
PUBLISH_PART = 80_000_000
ZIM_PART = 2**30
BLOCK = 1024 * 1024
KIWIX = "mirror.download.kiwix.org"
KIWIX_REDIRECTORS = {"download.kiwix.org", "lb.download.kiwix.org", KIWIX}
READER_IDS = {"kiwix_windows", "kiwix_linux", "kiwix_macos", "kiwix_android"}
TIER = {"CRITICAL": 0, "USEFUL": 1, "NONESSENTIAL": 2}


def write_json(path: Path, content) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")


def browser_routes(asset: dict) -> list[str]:
    if asset.get("archive_member") or asset.get("generation"):
        return []
    url = urlsplit(asset["source_url"])
    observed = asset.get("browser_fetch") or {}
    candidates = []
    if ((url.hostname in KIWIX_REDIRECTORS and url.path.startswith("/zim/")) or
            (asset["id"] in READER_IDS and url.path.removeprefix("/kiwix").startswith("/release/"))):
        candidates.append(urlunsplit(("https", KIWIX, url.path.removeprefix("/kiwix"), url.query, "")))
    elif observed.get("cors") is True and (asset["format"] != "zim" or observed.get("range") is True):
        candidates.append(asset["source_url"])
    for alternate in asset.get("mirrors", []):
        evidence = asset.get("mirror_fetch", {}).get(alternate, {})
        if (evidence.get("sha256_verified") is True and evidence.get("cors") is True and
                (asset["format"] != "zim" or evidence.get("range") is True)):
            candidates.append(alternate)
    return list(dict.fromkeys(candidates))


def mirror_candidates(assets: list[dict], routes: dict) -> list[dict]:
    candidates = [
        asset for asset in assets
        if asset["status"] == "resolved" and asset["redistributable"] is True and not asset.get("generation")
        and asset["format"] != "zim"
        and (not routes[asset["id"]] or asset.get("browser_fetch", {}).get("cors") is not True)
        # Reader binaries come directly from the Kiwix project's release mirror.
        and asset["id"] not in READER_IDS
    ]
    return sorted(candidates, key=lambda asset: (TIER[asset["utility_tier"]], asset["selection"]["rank"], asset["id"]))


def copy_pinned(stream, target, asset: dict) -> None:
    digest = sha256()
    remaining = asset["size_bytes"]
    while remaining:
        data = stream.read(min(BLOCK, remaining))
        if not data:
            raise ValueError("source was shorter than the pinned byte count")
        target.write(data)
        digest.update(data)
        remaining -= len(data)
    if stream.read(1) or digest.hexdigest() != asset["sha256"]:
        raise ValueError("source differs from its pinned byte count or SHA-256")


def verified_source(asset: dict, cache: Path) -> Path:
    path = cache / asset["sha256"]
    if path.exists():
        with path.open("rb") as stream, open(os.devnull, "wb") as sink:
            copy_pinned(stream, sink, asset)
        return path
    urls = [asset["source_url"]] + [
        url for url in asset.get("mirrors", [])
        if asset.get("mirror_fetch", {}).get(url, {}).get("sha256_verified") is True
    ]
    last_error = "No HTTPS source"
    for url in urls:
        if urlsplit(url).scheme != "https":
            continue
        temporary = path.with_suffix(".download")
        try:
            request = Request(url, headers={"Accept-Encoding": "identity"})
            with urlopen(request, timeout=25) as response, temporary.open("wb") as output:
                if response.status != 200 or urlsplit(response.url).scheme != "https":
                    raise ValueError("source did not return an HTTPS file")
                copy_pinned(response, output, asset)
            temporary.replace(path)
            return path
        except (OSError, ValueError) as error:
            last_error = str(error)
        finally:
            temporary.unlink(missing_ok=True)
    raise ValueError(last_error)


def publish_asset(asset: dict, assets: dict, site: Path, cache: Path) -> list[dict]:
    member = asset.get("archive_member")
    if member:
        source = assets[member["source_asset_id"]]
        if source["redistributable"] is not True:
            raise ValueError("archive source does not permit redistribution")
        path = cache / asset["sha256"]
        try:
            with ZipFile(verified_source(source, cache)) as archive, archive.open(member["path"]) as stream, path.open("wb") as output:
                copy_pinned(stream, output, asset)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    else:
        path = verified_source(asset, cache)

    entries = []
    directory = site / "mirrors"
    directory.mkdir(exist_ok=True)
    with path.open("rb") as stream:
        for offset in range(0, asset["size_bytes"], PUBLISH_PART):
            chunk = stream.read(PUBLISH_PART)
            filename = asset["id"] + "-" + str(offset // PUBLISH_PART) + ".bin"
            (directory / filename).write_bytes(chunk)
            entries.append({"url": "./mirrors/" + filename, "bytes": len(chunk), "sha256": sha256(chunk).hexdigest()})
    return entries


def generate_archive_pins(asset: dict, path: Path) -> dict:
    if asset["format"] != "zim" or asset["size_bytes"] <= ZIM_PART:
        raise ValueError("archive part manifests require a multipart ZIM")
    whole, hashes = sha256(), []
    with path.open("rb") as stream:
        remaining = asset["size_bytes"]
        while remaining:
            part = sha256()
            part_bytes = min(ZIM_PART, remaining)
            left = part_bytes
            while left:
                block = stream.read(min(BLOCK, left))
                if not block:
                    raise ValueError("archive was shorter than its pinned byte count")
                whole.update(block)
                part.update(block)
                left -= len(block)
            hashes.append(part.hexdigest())
            remaining -= part_bytes
        if stream.read(1) or whole.hexdigest() != asset["sha256"]:
            raise ValueError("archive differs from its whole-file pin")
    return {"sha256": asset["sha256"], "part_bytes": ZIM_PART, "hashes": hashes}


def build_site(site: Path, *, fetch_mirrors: bool, cache: Path, search_commit=None) -> dict:
    if site.exists() and any(site.iterdir()):
        raise ValueError("Choose an empty output directory")
    site.mkdir(parents=True, exist_ok=True)
    model = make_model(CATALOG, PROFILES, ROOT / "catalog/resources.yaml")
    assets = load_catalog(CATALOG, load_profiles(PROFILES))
    by_id = {asset["id"]: asset for asset in assets}
    routes = {asset["id"]: browser_routes(asset) for asset in assets}
    navigation = load_navigation(ROOT / "catalog/navigation", assets)
    records, _ = compile_records(assets, navigation)
    search_index = load_manifest()
    search_base = "./search/"
    if search_commit:
        if len(search_commit) != 40 or any(char not in "0123456789abcdef" for char in search_commit):
            raise ValueError("Search distribution needs an immutable Git commit")
        search_base = ("https://raw.githubusercontent.com/jonaraphael/offline-wandering-library/"
                       + search_commit + "/catalog/search/")
    elif search_index["sources"]:
        shutil.copytree(SEARCH_ROOT, site / "search")
    templates = ROOT / "src/owl/templates"
    page = (render_search_page().replace("INDEX/categories.html", "INDEX/topics.html")
            .replace("INDEX/A.html", "../START_HERE.html#files")
            .replace("INDEX/textbooks.html", "INDEX/shelf-textbooks.html")
            .replace("INDEX/illustrated-guides.html", "INDEX/shelf-illustrated-guides.html")
            .replace("INDEX/critical.html", "INDEX/shelf-critical.html")
            .replace("INVENTORY.html", "INVENTORY.json"))
    write_json(site / "search-build.json", {"manifest": search_index, "base": search_base, "records": records,
        "page": page, "runtime": (templates / "search.js").read_text(encoding="utf-8"),
        "rankRuntime": (templates / "rank.js").read_text(encoding="utf-8")})
    navigation = {key: navigation[key] for key in ("topics", "entrances", "assignments")}
    navigation.update(css=CSS, groups=GROUPS, verify=(ROOT / "src/owl/verify.py").read_text(encoding="utf-8"),
                      assets={asset["id"]: {
                          "document": is_document(asset), "shelves": sorted(learning_shelves(asset)),
                          "group": _group(asset), "publisher": asset.get("publisher"), "attribution": asset.get("attribution"),
                          "legacy": bool(asset.get("legacy"))
                      } for asset in assets})
    write_json(site / "catalog.json", {"planner": model, "routes": routes, "navigation": navigation})
    (site / "index.html").write_text(render_selector(model, pages=True), encoding="utf-8")
    (site / "SELECT.html").write_bytes((ROOT / "SELECT.html").read_bytes())
    (site / ".nojekyll").touch()
    for path in sorted(SOURCE.glob("*.mjs")):
        shutil.copyfile(path, site / path.name)
    shutil.copytree(SOURCE / "vendor", site / "vendor")

    candidates = mirror_candidates(assets, routes)
    manifest = {"files": {}, "chunks": json.loads((SOURCE / "archive-pins.json").read_text(encoding="utf-8"))}
    for asset_id, entry in manifest["chunks"].items():
        asset = by_id[asset_id]
        expected_parts = (asset["size_bytes"] + ZIM_PART - 1) // ZIM_PART
        if (asset["format"] != "zim" or asset["sha256"] != entry["sha256"] or entry["part_bytes"] != ZIM_PART or
                len(entry["hashes"]) != expected_parts or any(len(value) != 64 or
                any(char not in "0123456789abcdef" for char in value) for value in entry["hashes"])):
            raise ValueError(f"Archive part manifest is stale: {asset_id}")
    omissions = {}
    used = sum(path.stat().st_size for path in site.rglob("*") if path.is_file())
    if fetch_mirrors:
        cache.mkdir(parents=True, exist_ok=True)
        for asset in candidates:
            if used + asset["size_bytes"] > SITE_LIMIT - 2_000_000:
                omissions[asset["id"]] = "Pages storage budget"
                continue
            try:
                manifest["files"][asset["id"]] = publish_asset(asset, by_id, site, cache)
                used += asset["size_bytes"]
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                omissions[asset["id"]] = str(error)
                print(f"Mirror unavailable for {asset['id']}: {error}", file=sys.stderr)
    write_json(site / "chunk-manifests.json", manifest)
    (site / "mirror-credits.txt").write_text("Published source copies\n\n" + "\n\n".join(
        "\n".join((by_id[identity]["title"], by_id[identity]["license"],
                   by_id[identity].get("attribution", ""), by_id[identity]["source_url"],
                   *(entry["url"] for entry in entries)))
        for identity, entries in manifest["files"].items()
    ) + "\n", encoding="utf-8")

    sizes = [path.stat().st_size for path in site.rglob("*") if path.is_file()]
    if sum(sizes) > SITE_LIMIT or max(sizes) > FILE_LIMIT:
        raise ValueError("Generated artifact exceeds the Pages size budget")
    return {"site_bytes": sum(sizes), "largest_file_bytes": max(sizes), "direct_assets": sum(map(bool, routes.values())),
            "mirror_candidates": len(candidates), "mirror_candidate_bytes": sum(asset["size_bytes"] for asset in candidates),
            "mirrored_assets": len(manifest["files"]), "archive_manifests": len(manifest["chunks"]), "mirror_omissions": omissions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", help="fresh Pages output directory")
    parser.add_argument("--fetch-mirrors", action="store_true", help="include verified, redistributable source files")
    parser.add_argument("--cache", type=Path, help="external cache for verified mirror downloads")
    parser.add_argument("--archive-pins", nargs=2, metavar=("ASSET_ID", "FILE"),
                        help="emit pins for a local ZIM whose complete SHA-256 matches the catalog")
    parser.add_argument("--search-commit", help="serve search data from this full Git commit instead of copying it into Pages")
    args = parser.parse_args()
    if args.archive_pins:
        identity, path = args.archive_pins
        asset = next(asset for asset in load_catalog(CATALOG, load_profiles(PROFILES)) if asset["id"] == identity)
        print(json.dumps({identity: generate_archive_pins(asset, Path(path))}, indent=2))
        return 0
    if args.output is None:
        parser.error("supply an output directory or --archive-pins")
    with tempfile.TemporaryDirectory(prefix="owl-pages-") as scratch:
        result = build_site(args.output, fetch_mirrors=args.fetch_mirrors, cache=args.cache or Path(scratch), search_commit=args.search_commit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
