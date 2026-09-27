#!/usr/bin/env python3
"""Verify the included 2026 Midwives PDFs against their own printed contents."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pymupdf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path


def inspect(catalog, library):
    selected = [a for a in catalog["assets"] if a["id"].startswith("hesperian_en_midw_2026_")]
    required = {"hesperian_en_midw_2026_" + suffix for suffix in [*(f"{i:02d}" for i in range(1, 26)), "fm", "gp", "resc", "gloss", "indx", "ddc"]}
    if {a["id"] for a in selected} != required or len(selected) != len(required):
        raise SafetyError("Midwives scope differs from the 31 reviewed publisher chapter identities")
    documents, printed = [], Counter()
    for asset in sorted(selected, key=lambda a: a["id"]):
        path = safe_path(library, asset["destination"])
        if asset["size_bytes"] > 16 * 1024 * 1024 or path.stat().st_size != asset["size_bytes"]:
            raise SafetyError("Midwives PDF size differs or exceeds the inspection bound")
        with path.open("rb") as handle:
            data = handle.read(16 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise SafetyError("Midwives PDF differs from its whole-file catalog pin")
        pages = []
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.is_encrypted or len(pdf) > 100:
                raise SafetyError("Unexpected encrypted or oversized chapter PDF")
            for number, page in enumerate(pdf):
                text = page.get_text()
                if len(text.encode()) > 128 * 1024:
                    raise SafetyError("Chapter page text exceeds the inspection bound")
                candidates = [int(word[4]) for word in page.get_text("words") if word[4].isdigit()
                    and .90 * page.rect.height < word[1] < .95 * page.rect.height and 1 <= int(word[4]) <= 531]
                if asset["id"].endswith("_fm"):
                    candidates = []  # Contents references are not printed folios.
                candidates = sorted(set(candidates))
                if len(candidates) == 1:
                    printed[candidates[0]] += 1
                row = {"pdf_page": number + 1, "printed_page_candidates": candidates,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "text_characters": len(text),
                    "image_objects": len(page.get_images()), "opening_text": " ".join(text.split())[:130],
                    "edition_2026_label": "2026" in text}
                if asset["id"].endswith("_fm") and number >= 7:
                    row["toc_text"] = text
                pages.append(row)
            metadata = pdf.metadata
        documents.append({key: asset[key] for key in ("id", "title", "source_url", "version", "size_bytes", "sha256")} |
            {"pdf_page_count": len(pages), "edition_2026_label_present": any(p["edition_2026_label"] for p in pages),
             "pdf_metadata": metadata, "pages": pages})
    return {"schema_version": 1, "content_ready": False, "uncaptured_whole_book_complete": False,
        "source_count": len(documents), "whole_file_pins_verified": True, "pdf_pages": sum(d["pdf_page_count"] for d in documents),
        "printed_page_labels_found": sorted(printed), "missing_printed_labels_1_to_531": sorted(set(range(1, 532)) - printed.keys()),
        "duplicate_printed_labels": {str(page): count for page, count in printed.items() if count > 1},
        "documents": documents, "required_review": ["Resolve missing or ambiguous printed labels using the complete captured chapter and front-matter contents.",
            "The absent publisher back-matter file has not been inspected; do not invent its page count or claim the uncaptured whole-book PDF is complete."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("catalog/library.yaml"))
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reject_symlinks(args.catalog)
    reject_symlinks(args.output)
    if args.catalog.stat().st_size > 16 * 1024 * 1024:
        parser.error("Catalog exceeds 16 MiB")
    result = inspect(yaml.safe_load(args.catalog.read_text()), args.library_root)
    atomic_write(args.output, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({key: value for key, value in result.items() if key not in {"documents", "printed_page_labels_found"}}, sort_keys=True))


if __name__ == "__main__":
    main()
