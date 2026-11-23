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
from owl.search_model import Potion
from owl.search_shards import (ROOT, SEARCH_ROOT, MODEL_FILE, load_manifest, model_files, part_location, payload,
                               read_file, shard_chunks)
from owl.selection import load_ladder, recommended_profile


DATA = ROOT / "catalog/emergency-sections.json"
DESCRIPTIONS = ROOT / "catalog/emergency-descriptions.json"
RUNTIME = ROOT / "src/owl/templates/search.js"
RANK_RUNTIME = RUNTIME.with_name("rank.js")
START = "  // BEGIN GENERATED EMERGENCY SECTIONS\n"
END = "  // END GENERATED EMERGENCY SECTIONS\n"
SEMANTIC_START = "  // BEGIN GENERATED EMERGENCY VECTORS\n"
SEMANTIC_END = "  // END GENERATED EMERGENCY VECTORS\n"
NAVIGATION_START = "  // BEGIN GENERATED NAVIGATION SECTIONS\n"
NAVIGATION_END = "  // END GENERATED NAVIGATION SECTIONS\n"
SOURCE_IDS = {
    "cert", "medical_bec", "msf_guideline-170-en", "msf_guideline-449-en",
    "fema_are_you_ready_2020", "wikimed_en", "fao_family_metal_silos",
    "ucdavis_smallscale_postharvest", "who_emergency_medical-algorithm",
    "hesperian_en_cgeh_2012_17", "navigation", "survival_shelter",
}
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
        if asset["format"] != "pdf":
            continue
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


def indexed_locations(manifest, digest):
    shard = manifest["sources"][digest]
    for pool, number, pin in shard_chunks(manifest, digest, shard):
        raw = read_file(SEARCH_ROOT, part_location(pool, number, pin), pin)
        packed = payload(raw, "OWLShardBlob") if pin.get("path") else payload(raw, "OWLShardPart")[2]
        chunk = json.loads(gzip.decompress(base64.b64decode(packed)))
        yield from (row[1] for row in chunk["records"])


def compile_descriptions(manifest, topics, established):
    review = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
    descriptions = review["situations"]
    safety = set(review["safety"])
    if descriptions.keys() != topics | established or not safety <= descriptions.keys():
        missing = (topics | established) - descriptions.keys()
        extra = descriptions.keys() - (topics | established)
        raise ValueError(f"Descriptions must cover exactly the reviewed situations: missing {sorted(missing)}, extra {sorted(extra)}")
    verified = dict(model_files(manifest))
    model_data = read_file(SEARCH_ROOT, MODEL_FILE, verified[MODEL_FILE])
    weights = b"".join(base64.b64decode(payload(read_file(SEARCH_ROOT, path, pin), "OWLModelWeights")[1])
                       for path, pin in verified.items() if path.startswith("model/"))
    model = Potion(payload(model_data, "OWLShardModel"), weights)
    lines = []
    for topic, sentences in descriptions.items():
        if not isinstance(sentences, list) or not 3 <= len(sentences) <= 6 or any(
            not isinstance(line, str) or not line.endswith((".", "?", "!")) or not 15 <= len(line) <= 240
            for line in sentences
        ):
            raise ValueError(f"{topic}: write three to six short complete sentences")
        packed = base64.b64encode(b"".join(model.unit_code(line) for line in sentences)).decode("ascii")
        lines.append("    " + json.dumps([topic, "safety" if topic in safety else "health", packed],
                                         separators=(",", ":")) + ",\n")
    data = "".join(lines)
    if len(data.encode("ascii")) >= 200_000:
        raise ValueError("Emergency description vectors must stay below 200 KB")
    return "  const semanticRoutes = [\n" + data + "  ];\n"


def _compile_tables(sources):
    review = json.loads(DATA.read_text(encoding="utf-8"))
    manifest = load_manifest()
    source_ids, source_locations, source_formats = {}, {}, {}
    for key, (asset_id, digest) in review["sources"].items():
        asset = sources.get(asset_id)
        if not asset or asset["sha256"] != digest or asset["format"] not in {"pdf", "zim"}:
            raise ValueError(f"{asset_id}: review the sections against the selected catalog edition")
        source_ids[key] = asset_id
        source_formats[key] = asset["format"]
        source_locations[key] = set(indexed_locations(manifest, digest))

    used, topics, destinations, lines, archive_only = set(), set(), set(), [], set()

    def compile_locations(topic, locations, title=None):
        routes, seen = [], set()
        for key, locator, heading in locations:
            locator_type = int if source_formats[key] == "pdf" else str
            destination = (source_ids[key], locator, heading)
            if (type(locator) is not locator_type or locator not in source_locations[key]
                    or not heading or destination in seen):
                raise ValueError(f"Invalid destination for {topic}: {key}, {locator}")
            used.add(key)
            destinations.add(destination)
            seen.add(destination)
            routes.append([key, locator] if heading == title else [key, locator, heading])
        return routes

    for topic, title, locations, aliases in review["situations"]:
        if not topic or topic in topics or not title or not locations:
            raise ValueError(f"Invalid or duplicate situation {topic!r}")
        topics.add(topic)
        if all(source_formats[key] == "zim" for key, _, _ in locations):
            archive_only.add(topic)
        routes = compile_locations(topic, locations, title)
        lines.append("    " + json.dumps([topic, title, routes, aliases], ensure_ascii=True, separators=(",", ":")) + ",\n")
    body = "  const sectionRoutes = compileSectionRoutes([\n" + "".join(lines) + "  ]);\n"
    runtime = RUNTIME.read_text(encoding="utf-8")
    established_source = runtime.split("  const reviewedRoutes = [", 1)[1].split("  const routePhrase", 1)[0]
    established = set(re.findall(r"^    \['([a-z0-9-]+)',", established_source, re.MULTILINE))
    established_archives = set(re.findall(r"^    \['([a-z0-9-]+)', '[^']+', 'wikimed_en',", established_source,
                                         re.MULTILINE))
    companions = review["companions"]
    if companions.keys() - established_archives:
        raise ValueError("PDF companions must belong to established WikiMed routes")
    archive_only.update(established_archives - companions.keys())
    exceptions = review["archiveOnly"]
    if archive_only != exceptions.keys() or not all(exceptions.values()):
        raise ValueError(f"Review and explain all routes without a PDF: {sorted(archive_only)}")
    lines = []
    for topic, locations in companions.items():
        if not locations or any(source_formats[key] != "pdf" for key, _, _ in locations):
            raise ValueError(f"{topic}: companions must be PDF sections")
        routes = compile_locations(topic, locations)
        lines.append("    " + json.dumps([topic, routes], ensure_ascii=True, separators=(",", ":")) + ",\n")
    body += "  const reviewedCompanions = new Map([\n" + "".join(lines) + "  ].map(([topic, locations]) =>\n"
    body += "    [topic, resolveSectionLocations(locations)]));\n"
    emergency_sources = {key: asset for key, asset in source_ids.items() if key in used}
    body = "  const sectionSources = " + json.dumps(emergency_sources, separators=(",", ":")) + ";\n" + body
    emergency_destinations = len(destinations)
    lines = []
    navigation_topics = set()
    for topic, title, locations, aliases in review["navigation"]:
        if (not topic or topic in topics or topic in navigation_topics or not title or not locations
                or any(source_formats[key] != "pdf" for key, _, _ in locations)):
            raise ValueError(f"Invalid or duplicate navigation route {topic!r}")
        navigation_topics.add(topic)
        compile_locations(topic, locations, title)
        routes = [[source_ids[key], locator, heading] for key, locator, heading in locations]
        lines.append("    " + json.dumps([title, routes, aliases], ensure_ascii=True, separators=(",", ":")) + ",\n")
    navigation = "  const navigationSections = [\n" + "".join(lines) + "  ];\n"
    if used != source_ids.keys():
        raise ValueError("Review contains unused editions")
    vectors = compile_descriptions(manifest, topics, established)
    return body, vectors, navigation, emergency_destinations, len(topics)


def compile_routes(sources):
    body, vectors, _, destinations, situations = _compile_tables(sources)
    return body, vectors, destinations, situations


def publish_table(path, start, end, body, check):
    original = path.read_text(encoding="utf-8")
    head, _, old = original.partition(start)
    _, marker, tail = old.partition(end)
    if not marker:
        raise SystemExit(f"Emergency table markers are missing from {path.name}")
    generated = head + start + body + end + tail
    if check and original != generated:
        raise SystemExit(f"Emergency table in {path.name} is stale. Run scripts/build_search_emergency.py.")
    if not check and original != generated:
        path.write_text(generated, encoding="utf-8")


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
    body, vectors, navigation, destinations, situations = _compile_tables(sources)
    publish_table(RUNTIME, START, END, body, args.check)
    publish_table(RANK_RUNTIME, SEMANTIC_START, SEMANTIC_END, vectors, args.check)
    publish_table(RANK_RUNTIME, NAVIGATION_START, NAVIGATION_END, navigation, args.check)
    print(f"{destinations} reviewed section destinations across {situations} situations")
    print(f"{len(vectors.encode('ascii')):,} bytes of vectors in the indexed ranker")
    archive_only = json.loads(DATA.read_text(encoding="utf-8"))["archiveOnly"]
    print(f"{len(archive_only)} emergency situations with only WikiMed destinations")


if __name__ == "__main__":
    main()
