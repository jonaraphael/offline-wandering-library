#!/usr/bin/env python3
"""Review headings from the default library and compile its emergency search routes."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re

from owl.catalog import load_catalog, load_profiles, resolve_content
from owl.search_shards import ROOT, SEARCH_ROOT, load_manifest, part_location, payload, read_file, shard_chunks
from owl.selection import load_ladder, recommended_profile


DATA = ROOT / "catalog/emergency-sections.json"
RUNTIME = ROOT / "src/owl/templates/search.js"
START = "  // BEGIN GENERATED EMERGENCY SECTIONS\n"
END = "  // END GENERATED EMERGENCY SECTIONS\n"
SOURCE_IDS = {"cert", "medical_bec", "msf_guideline-170-en", "msf_guideline-449-en", "fema_are_you_ready_2020"}
HESPERIAN_CHAPTER = re.compile(r"hesperian_en_(?:wtnd_2025|midw_2026)_\d{2}$")


def default_library():
    catalog = ROOT / "catalog/library.yaml"
    profiles = load_profiles(ROOT / "profiles")
    assets = load_catalog(catalog, profiles)
    profile = recommended_profile(profiles["flash-16gb"], 16 * 10**9, load_ladder(catalog))
    selected, _, _ = resolve_content(assets, profile, resources_path=catalog.with_name("resources.yaml"))
    return {asset["id"]: asset for asset in selected
            if asset["id"] in SOURCE_IDS or HESPERIAN_CHAPTER.fullmatch(asset["id"])}


def collect_candidates(sources, directory):
    """Keep the physical page on every bookmark, contents entry and heading candidate."""
    import pymupdf

    for asset_id, asset in sorted(sources.items()):
        path = directory / asset["destination"]
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != asset["sha256"]:
                raise ValueError(f"{asset_id}: source edition differs from the catalog")
        with pymupdf.open(path) as document:
            print(f"\n{asset_id}\t{asset['title']}\t{asset['sha256']}")
            for _depth, title, page in document.get_toc():
                if 1 <= page <= len(document):
                    print(f"{page}\tbookmark\t{title}")
            for page in document:
                seen = set()
                for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
                    for line in block["lines"]:
                        spans = line["spans"]
                        text = " ".join("".join(span["text"] for span in spans).replace("\0", "").split())
                        if not 4 <= len(text) <= 140 or not any(char.isalpha() for char in text):
                            continue
                        contents = re.search(r"(?:\.\s*){3,}\d+$", text)
                        heading = text.isupper() or any(span["flags"] & 16 for span in spans)
                        if (contents or heading) and text not in seen:
                            seen.add(text)
                            print(f"{page.number + 1}\t{'contents' if contents else 'heading'}\t{text}")


def indexed_pages(manifest, digest):
    shard = manifest["sources"][digest]
    for pool, number, pin in shard_chunks(manifest, digest, shard):
        raw = read_file(SEARCH_ROOT, part_location(pool, number, pin), pin)
        packed = payload(raw, "OWLShardBlob") if pin.get("path") else payload(raw, "OWLShardPart")[2]
        chunk = json.loads(gzip.decompress(base64.b64decode(packed)))
        yield from (row[1] for row in chunk["records"] if type(row[1]) is int)


def compile_routes(sources):
    review = json.loads(DATA.read_text(encoding="utf-8"))
    manifest = load_manifest()
    source_ids, source_pages = {}, {}
    for key, (asset_id, digest) in review["sources"].items():
        asset = sources.get(asset_id)
        if not asset or asset["sha256"] != digest or asset["format"] != "pdf":
            raise ValueError(f"{asset_id}: review the sections against the selected catalog edition")
        source_ids[key] = asset_id
        source_pages[key] = set(indexed_pages(manifest, digest))

    used, topics, destinations, lines = set(), set(), set(), []
    for topic, title, locations, aliases in review["situations"]:
        if not topic or topic in topics or not title or not locations:
            raise ValueError(f"Invalid or duplicate situation {topic!r}")
        topics.add(topic)
        routes = []
        for key, page, heading in locations:
            if (type(page) is not int or page not in source_pages[key]
                    or not heading or [source_ids[key], page, heading] in routes):
                raise ValueError(f"Invalid destination for {topic}: {key}, {page}")
            used.add(key)
            destinations.add((source_ids[key], page, heading))
            routes.append([source_ids[key], page, heading])
        lines.append("    " + json.dumps([topic, title, routes, aliases], ensure_ascii=True, separators=(",", ":")) + ",\n")
    if used != source_ids.keys():
        raise ValueError("Review contains unused editions")
    body = "  const sectionRoutes = compileSectionRoutes([\n" + "".join(lines) + "  ]);\n"
    return body, len(destinations), len(topics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--candidates", type=Path, metavar="LIBRARY", help="extract review candidates from installed pinned PDFs")
    mode.add_argument("--check", action="store_true", help="check that the generated reader table is current")
    args = parser.parse_args()
    sources = default_library()
    if args.candidates:
        collect_candidates(sources, args.candidates)
        return
    body, destinations, situations = compile_routes(sources)
    original = RUNTIME.read_text(encoding="utf-8")
    head, _, old = original.partition(START)
    _, marker, tail = old.partition(END)
    if not marker:
        raise SystemExit("Emergency section markers are missing from search.js")
    generated = head + START + body + END + tail
    if args.check and original != generated:
        raise SystemExit("Emergency section routes are stale. Run scripts/build_search_emergency.py.")
    if not args.check:
        RUNTIME.write_text(generated, encoding="utf-8")
    print(f"{destinations} reviewed section destinations across {situations} situations")


if __name__ == "__main__":
    main()
