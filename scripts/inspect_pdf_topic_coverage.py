#!/usr/bin/env python3
"""Locate review evidence in existing pinned PDFs; matches never prove equivalence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import pymupdf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path


def inspect(catalog, recipe, library):
    patterns = {row["id"]: re.compile(row["pattern"], re.I) for row in recipe["topics"]}
    if not 1 <= len(patterns) == len(recipe["topics"]) <= 100:
        raise SafetyError("Topic recipe must have 1–100 unique probes")
    sources = [a for a in catalog["assets"] if a["id"] in recipe["asset_ids"] or
               any(a["id"].startswith(prefix) for prefix in recipe.get("asset_prefixes", []))]
    if not 1 <= len(sources) <= 300 or set(recipe["asset_ids"]) - {a["id"] for a in sources}:
        raise SafetyError("Topic recipe has missing or excessive source assets")
    records, missing = [], []
    for asset in sorted(sources, key=lambda a: a["id"]):
        path = safe_path(library, asset["destination"])
        if not path.exists():
            missing.append(asset["id"])
            continue
        if asset["format"] != "pdf" or not 0 < asset["size_bytes"] <= 96 * 1024 * 1024 or path.stat().st_size != asset["size_bytes"]:
            raise SafetyError("Coverage source is not an exact bounded PDF")
        with path.open("rb") as handle:
            data = handle.read(96 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise SafetyError("Coverage source differs from its whole-file pin")
        hits = {key: {"matching_pages": 0, "locations": []} for key in patterns}
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.is_encrypted or len(document) > 1500:
                raise SafetyError("Coverage PDF exceeds its page bound or is encrypted")
            for number, page in enumerate(document):
                text = " ".join(page.get_text().split())
                if len(text.encode()) > 128 * 1024:
                    raise SafetyError("Coverage page text exceeds its bound")
                for key, pattern in patterns.items():
                    match = pattern.search(text)
                    if match:
                        hits[key]["matching_pages"] += 1
                        if len(hits[key]["locations"]) < 12:
                            hits[key]["locations"].append({"pdf_page": number + 1,
                                "locator": text[max(0, match.start() - 50):match.end() + 90],
                                "page_text_sha256": hashlib.sha256(text.encode()).hexdigest()})
            records.append({key: asset[key] for key in ("id", "title", "source_url", "version", "size_bytes", "sha256")} |
                {"pdf_pages": len(document), "topics": {key: value for key, value in hits.items() if value["matching_pages"]}})
    topic_sources = {key: [r["id"] for r in records if key in r["topics"]] for key in patterns}
    return {"schema_version": 1, "recipe_id": recipe["id"], "source_count": len(records), "missing_sources": missing,
        "content_ready": False, "equivalence_established": False, "whole_file_pins_verified": True,
        "topics": recipe["topics"], "topic_sources": topic_sources, "sources": records,
        "limitations": ["Keyword matches locate original pages for review; they do not prove complete, equivalent or current clinical instructions.",
            "Absence means no matching wording was found in these exact scanned sources, not proof the topic is absent everywhere.",
            "Read full original statements, illustrations, cautions and surrounding chapter context before making any substitution decision."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/library.yaml"))
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path, maximum in ((args.catalog, 16 * 1024 * 1024), (args.recipe, 65536)):
        reject_symlinks(path)
        if path.stat().st_size > maximum:
            parser.error("Control document exceeds its bound")
    result = inspect(yaml.safe_load(args.catalog.read_text()), json.loads(args.recipe.read_text()), args.library_root)
    result["recipe_sha256"] = hashlib.sha256(args.recipe.read_bytes()).hexdigest()
    encoded = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > 16 * 1024 * 1024:
        raise SafetyError("Coverage evidence exceeds 16 MiB")
    atomic_write(args.output, encoded)
    print(json.dumps({"source_count": result["source_count"], "missing_sources": result["missing_sources"],
        "topics_without_matches": [key for key, ids in result["topic_sources"].items() if not ids],
        "equivalence_established": False, "output_bytes": len(encoded)}, sort_keys=True))


if __name__ == "__main__":
    main()
