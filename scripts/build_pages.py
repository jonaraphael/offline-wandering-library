#!/usr/bin/env python3
"""Build the GitHub Pages artifact and optionally publish pinned, licensed copies."""
from __future__ import annotations

import argparse
from base64 import b64decode
from hashlib import sha256
from itertools import chain
import json
import re
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

from owl.atlas import reader_topics
from owl.atlas_model import load_navigation
from owl.catalog import load_catalog, load_profiles
from owl.navigation import reader_payload
from owl.discovery import compile_records
from owl.search_ui import render_search_page
from owl.search_shards import SEARCH_ROOT, compile_search_plan, load_impact, load_manifest, load_routes, load_transformer
from owl.selector import ROOT, make_model, render_selector
from owl.verify import ZIM_PART_BYTES


CATALOG = ROOT / "catalog/library.yaml"
PROFILES = ROOT / "profiles"
SOURCE = ROOT / "web"
SITE_LIMIT = 950_000_000
FILE_LIMIT = 100_000_000
PUBLISH_PART = 80_000_000
ZIM_PART = ZIM_PART_BYTES
RELAY_RANGE = 64 * 2**20
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


def relay_allowlist(assets):
    """A closed mapping from catalog IDs to exact reviewed publisher URLs."""
    allowed = {asset["id"]: {"url": asset["source_url"], "bytes": asset["size_bytes"]}
               for asset in assets if asset["status"] == "resolved" and asset["utility_tier"] == "CRITICAL"
               and asset["redistributable"] is False and not browser_routes(asset)
               and not asset.get("archive_member") and not asset.get("generation")
               and urlsplit(asset["source_url"]).scheme == "https"}
    alternate_archives = json.loads((SOURCE / "archive-relay.json").read_text(encoding="utf-8"))
    for asset in assets:
        pin = alternate_archives.get(asset["id"])
        if not pin:
            continue
        if (asset["format"] != "zim" or asset["sha256"] != pin["sha256"]
                or asset["size_bytes"] != pin["bytes"] or urlsplit(pin["url"]).scheme != "https"):
            raise ValueError(f"Relay archive route is stale: {asset['id']}")
        for name, url in {"nluug": pin["url"], **pin.get("peers", {})}.items():
            peer = urlsplit(url)
            source = urlsplit(asset["source_url"])
            if (peer.scheme != "https" or not peer.hostname or peer.username or peer.password or
                    peer.query or peer.fragment or not peer.path.endswith(source.path)):
                raise ValueError(f"Invalid archive peer URL: {asset['id']}/{name}")
            key = asset["id"] if name == "nluug" else asset["id"] + "--" + name
            allowed[key] = {"url": url, "bytes": pin["bytes"], "max_range_bytes": RELAY_RANGE,
                            "archive": asset["id"]}
    return allowed


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
        try:
            with path.open("rb") as stream, open(os.devnull, "wb") as sink:
                copy_pinned(stream, sink, asset)
            return path
        except ValueError:
            path.unlink()
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


def publish_locked_mirrors(by_id, site, cache, used):
    lock = json.loads((SOURCE / "pages-mirrors.json").read_text(encoding="utf-8"))
    for identity, digest in lock.items():
        asset = by_id.get(identity)
        if (not asset or asset["sha256"] != digest or asset["status"] != "resolved"
                or asset["redistributable"] is not True or asset.get("generation")):
            raise ValueError(f"Update the Pages mirror lock for {identity}")
    if used + sum(by_id[identity]["size_bytes"] for identity in lock) > SITE_LIMIT - 2_000_000:
        raise ValueError("The locked Pages mirrors exceed the available site budget")
    cache.mkdir(parents=True, exist_ok=True)
    files = {}
    for identity in lock:
        try:
            files[identity] = publish_asset(by_id[identity], by_id, site, cache)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            raise ValueError(f"Required Pages mirror {identity} is unavailable: {error}") from error
    return files


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


MODULE_IMPORT = re.compile(r"""((?:\bfrom|\bimport)\s*\(?\s*)(["'])(\./[^"'?#]+\.m?js)\2""")


def version_module_imports(text: str, version) -> str:
    """Append ?v=<commit> to relative module imports.

    GitHub Pages serves modules with max-age=600, so a reload within ten
    minutes of a deploy ran stale builder code on the owner's drive. Commit-
    versioned URLs make each deploy take effect on the next reload."""
    if not version:
        return text
    return MODULE_IMPORT.sub(lambda match: match[1] + match[2] + match[3] + "?v=" + version + match[2], text)


def connect_origins(urls):
    origins = set()
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname:
            origin = f"https://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
            if not re.fullmatch(r"https://[a-z0-9.-]+(?::[0-9]+)?", origin):
                raise ValueError(f"Invalid browser route origin: {origin}")
            origins.add(origin)
    return tuple(sorted(origins))


def build_site(site: Path, *, fetch_mirrors: bool, cache: Path, search_commit=None, relay_base=None, archive_relay=False) -> dict:
    if site.exists() and any(site.iterdir()):
        raise ValueError("Choose an empty output directory")
    site.mkdir(parents=True, exist_ok=True)
    model = make_model(CATALOG, PROFILES, ROOT / "catalog/resources.yaml")
    assets = load_catalog(CATALOG, load_profiles(PROFILES))
    by_id = {asset["id"]: asset for asset in assets}
    routes = {asset["id"]: browser_routes(asset) for asset in assets}
    archive_routes = {}
    if archive_relay and not relay_base:
        raise ValueError("Archive relay requires a relay origin")
    if relay_base:
        relay = urlsplit(relay_base)
        if (relay.scheme != "https" or not relay.hostname or relay.username or relay.password or
                relay.query or relay.fragment or relay.path not in {"", "/"}):
            raise ValueError("Relay base must be an HTTPS origin")
        for aid, entry in relay_allowlist(assets).items():
            url = relay_base.rstrip("/") + "/assets/" + aid
            if "archive" not in entry:
                routes[aid].append(url)
            elif archive_relay:
                archive_routes.setdefault(entry["archive"], []).append(url)
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
        # These source indexes are already compiled into search-build.json.
        # The local site only needs the pinned payloads they reference.
        shutil.copytree(SEARCH_ROOT, site / "search",
                        ignore=lambda directory, names: {"manifest.json", "routes.json"} & set(names)
                        if Path(directory) == SEARCH_ROOT else set())
    templates = ROOT / "src/owl/templates"
    page = render_search_page()
    write_json(site / "search-build.json", {"plan": compile_search_plan(assets, search_index, load_routes(), load_impact(), load_transformer()), "base": search_base, "records": records,
        "page": page,
        "runtime": (templates / "search.js").read_text(encoding="utf-8"),
        "rerankRuntime": (templates / "rerank.js").read_text(encoding="utf-8"),
        "rankRuntime": (templates / "rank.js").read_text(encoding="utf-8")})
    labels = reader_topics(navigation)
    navigation = {"reader": reader_payload(assets, collections=model["resources"], topics=labels),
                  "atlas": bool(navigation["topics"]), "input_hashes": navigation["input_hashes"],
                  "verify": (ROOT / "src/owl/verify.py").read_text(encoding="utf-8")}
    from owl.wikimed_phone import DESTINATION, manifest as phone_manifest, verified_volume
    phone = phone_manifest()
    if phone and by_id[phone["source_id"]]["sha256"] != phone["source_sha256"]:
        raise ValueError("The WikiMed phone layer needs rebuilding for this edition")
    if phone:
        (site / "wikimed-phone").mkdir()
        for volume in phone["volumes"]:
            (site / "wikimed-phone" / volume["file"]).write_bytes(verified_volume(volume))
        navigation["phone"] = {**phone, "destination": DESTINATION, "base": "./wikimed-phone/"}
    write_json(site / "catalog.json", {"planner": model, "routes": routes, "navigation": navigation})
    version = search_commit[:12] if search_commit else None
    origins = connect_origins(chain.from_iterable((*routes.values(), *archive_routes.values(), (search_base,))))
    (site / "index.html").write_text(render_selector(model, pages=True, connect_origins=origins, version=version),
                                     encoding="utf-8")
    (site / "SELECT.html").write_bytes((ROOT / "SELECT.html").read_bytes())
    (site / ".nojekyll").touch()
    hosted_scripts = [templates / name for name in ("pages-entry.mjs", "selector.js", "selector-map.js")]
    for path in [*sorted(SOURCE.glob("*.mjs")), *hosted_scripts]:
        (site / path.name).write_text(version_module_imports(path.read_text(encoding="utf-8"), version), encoding="utf-8")
    shutil.copytree(SOURCE / "vendor", site / "vendor")

    pieces = json.loads((SOURCE / "kiwix-pieces.json").read_text(encoding="utf-8"))
    piece_bytes = pieces["piece_bytes"]
    archives = {asset["id"]: asset for asset in assets if asset["format"] == "zim"}
    if piece_bytes != 4 * BLOCK or pieces["archives"].keys() != archives.keys():
        raise ValueError("Run scripts/build_kiwix_pins.py to refresh publisher piece coverage")
    for identity, record in pieces["archives"].items():
        asset = archives[identity]
        count = (asset["size_bytes"] + piece_bytes - 1) // piece_bytes
        if record["sha256"] != asset["sha256"] or len(b64decode(record["sha1"], validate=True)) != count * 20:
            raise ValueError(f"Publisher piece manifest is stale: {identity}")
    shutil.copyfile(SOURCE / "kiwix-pieces.json", site / "kiwix-pieces.json")

    candidates = mirror_candidates(assets, routes)
    manifest = {"files": {}, "chunks": json.loads((SOURCE / "archive-pins.json").read_text(encoding="utf-8"))}
    if archive_routes:
        manifest["archiveRelay"] = archive_routes
    for asset_id, entry in manifest["chunks"].items():
        asset = by_id[asset_id]
        expected_parts = (asset["size_bytes"] + ZIM_PART - 1) // ZIM_PART
        if (asset["format"] != "zim" or asset["sha256"] != entry["sha256"] or entry["part_bytes"] != ZIM_PART or
                len(entry["hashes"]) != expected_parts or any(len(value) != 64 or
                any(char not in "0123456789abcdef" for char in value) for value in entry["hashes"])):
            raise ValueError(f"Archive part manifest is stale: {asset_id}")
    used = sum(path.stat().st_size for path in site.rglob("*") if path.is_file())
    if fetch_mirrors:
        manifest["files"] = publish_locked_mirrors(by_id, site, cache, used)
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
            "mirrored_assets": len(manifest["files"]), "archive_manifests": len(manifest["chunks"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", help="fresh Pages output directory")
    parser.add_argument("--relay-base", help="enable approved relay routes at this HTTPS origin")
    parser.add_argument("--archive-relay", action="store_true", help="sample approved archive peers through the relay")
    parser.add_argument("--relay-allowlist", type=Path, help="generate the relay's exact publisher URL mapping")
    parser.add_argument("--fetch-mirrors", action="store_true", help="include verified, redistributable source files")
    parser.add_argument("--cache", type=Path, help="external cache for verified mirror downloads")
    parser.add_argument("--archive-pins", nargs=2, metavar=("ASSET_ID", "FILE"),
                        help="emit pins for a local ZIM whose complete SHA-256 matches the catalog")
    parser.add_argument("--search-commit", help="serve search data from this full Git commit instead of copying it into Pages")
    args = parser.parse_args()
    if args.fetch_mirrors and not args.relay_base:
        parser.error("--fetch-mirrors requires --relay-base for a production Pages build")
    if args.archive_pins:
        identity, path = args.archive_pins
        asset = next(asset for asset in load_catalog(CATALOG, load_profiles(PROFILES)) if asset["id"] == identity)
        print(json.dumps({identity: generate_archive_pins(asset, Path(path))}, indent=2))
        return 0
    if args.relay_allowlist:
        write_json(args.relay_allowlist, relay_allowlist(load_catalog(CATALOG)))
        return 0
    if args.output is None:
        parser.error("supply an output directory or --archive-pins")
    with tempfile.TemporaryDirectory(prefix="owl-pages-") as scratch:
        result = build_site(args.output, fetch_mirrors=args.fetch_mirrors, cache=args.cache or Path(scratch),
                            search_commit=args.search_commit, relay_base=args.relay_base,
                            archive_relay=args.archive_relay)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
