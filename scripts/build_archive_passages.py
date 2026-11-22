#!/usr/bin/env python3
"""Append source-pinned archive passages to existing search shards."""
from __future__ import annotations

import argparse
from collections import Counter
from gzip import open as gzopen
from hashlib import sha256
from heapq import nlargest
import json
from pathlib import Path
import re

from build_search_shards import (Article, HTML_MIMES, build_shard, directory_receipt, find_source)
from owl.catalog import load_catalog, load_profiles
from owl.safety import atomic_write
from owl.search_model import Potion
from owl.search_shards import (MODEL_FILE, MODEL_PART, REPO_LIMIT, ROOT, SEARCH_ROOT,
                               Record, encode, load_manifest, model_files, payload, read_file,
                               shard_chunks, part_location)
from base64 import b64decode

PARAGRAPH_SIZE = 640
STOP_HEADINGS = {
    "see also", "notes", "references", "citations", "external links",
    "further reading", "bibliography", "sources",
}


def select_articles(directory, limit):
    with gzopen(directory, "rt", encoding="utf-8") as source:
        redirects = Counter(mark[-1] for line in source if (mark := json.loads(line))[3])
    with gzopen(directory, "rt", encoding="utf-8") as source:
        rows = (json.loads(line) for line in source)
        eligible = (row for row in rows if not row[3] and row[2].split(";", 1)[0] in HTML_MIMES
                    and not re.match(r"(?i)(?:category|template|file|help|portal|user|talk):", row[1]))
        # Redirect popularity plus a stable spread over the rest of the edition.
        return nlargest(limit, eligible, key=lambda row: (redirects[row[4]], sha256(row[1].encode()).digest()))


def phrases(text):
    while text:
        end = len(text)
        if end > PARAGRAPH_SIZE:
            end = text.rfind(" ", 160, PARAGRAPH_SIZE + 1)
            if end < 0:
                end = PARAGRAPH_SIZE
        yield text[:end]
        text = text[end:].lstrip()


def body_records(read_html, candidates, asset, metrics, passages_per_article):
    discussion = "/stack_exchange/" in asset["source_url"]
    for title, path, *_ in candidates:
        try:
            parser = Article(document=True, archive_body=True)
            parser.feed(read_html(path))
            parser.close()
            parser.finish_section()
        except (KeyError, RuntimeError, ValueError):
            metrics["read_errors"] += 1
            continue
        title = parser.readable_title() if not re.search(r"\w", title) or re.search(r"\.html?$", title, re.I) else title
        if not title:
            title = asset["title"]
        if discussion:
            sections = [("Accepted answer", "", " ".join(parser.accepted))]
        else:
            sections = parser.sections
        used = 0
        for heading, _, text in sections:
            if heading.casefold() in STOP_HEADINGS:
                break
            # In Wiki articles the lead is already in the deployed index. A
            # passage needs a body heading or answer, beyond the lead.
            if not heading or heading == title:
                # Some crawled textbook pages put the article in an unheaded
                # wrapper. The part after the lead can still supply passages.
                text = text[900:].lstrip()
            for passage in phrases(text):
                if len(passage) < 100:
                    continue
                used += 1
                metrics["passages"] += 1
                yield Record(title, path, heading=heading[:180], body=passage,
                             show_lead=bool(asset.get("redistributable")), accepted_answer=discussion)
                if used == passages_per_article:
                    break
            if used == passages_per_article:
                break
        metrics["articles_with_passages"] += bool(used)


def lead_records(read_html, candidates, asset, metrics):
    for title, path, *_ in candidates:
        parser = Article()
        parser.feed(read_html(path))
        parser.close()
        lead = " ".join(parser.lead)
        if len(lead) >= 120:
            metrics["leads"] += 1
            yield Record(title, path, lead=lead, show_lead=bool(asset.get("redistributable")))


def append(output, asset, path, directory, model, manifest, article_limit, passages_per_article, leads=False):
    identity = asset["id"]
    digest = asset["sha256"]
    old = manifest["sources"][digest]
    coverage_key = "lead_extraction" if leads else "body_extraction"
    if old.get(coverage_key) or old.get("shared"):
        raise ValueError(f"Body passages already exist or the directory is shared: {identity}")
    if path:
        directory_receipt(asset, directory, path)
        candidates = select_articles(directory / (identity + ".jsonl.gz"), article_limit)
        from libzim.reader import Archive
        archive = Archive(path)
        def read_html(path):
            return bytes(archive.get_entry_by_path(path).get_item().content).decode("utf-8", "replace")
        proof = {"source_verification": "whole-file SHA-256"}
    else:
        data = json.loads((directory / (identity + ".json")).read_bytes())
        if data["source_sha256"] != digest or data["source"] != identity or not data["ranges"]:
            raise ValueError(f"Range receipt source differs: {identity}")
        candidates = [(title, location) for title, location, _ in data["articles"][:article_limit]]
        articles = {location: html for _, location, html in data["articles"][:article_limit]}
        read_html = articles.__getitem__
        proof = {"source_verification": "publisher SHA-1 pieces; catalog SHA-256 edition pin",
                 "range_bytes": sum(row[0] for row in data["ranges"].values()),
                 "range_receipts_sha256": sha256(encode(data["ranges"])).hexdigest()}
    metrics = Counter(article_budget=article_limit, candidates=len(candidates), passages_per_article=passages_per_article)
    rows = (lead_records(read_html, candidates, asset, metrics) if leads else
            body_records(read_html, candidates, asset, metrics, passages_per_article))
    # The archive title rows and previous lead vectors retain their identities
    # and ordinals. Supplemental passages are independent content-addressed files.
    owned = {part_location(pool, number, pin): pin for source, shard in manifest["sources"].items()
             for pool, number, pin in shard_chunks(manifest, source, shard)}
    occupied = sum(pin["bytes"] for pin in owned.values()) + len(encode(manifest))
    occupied += sum(pin["bytes"] for _, pin in model_files(manifest))
    for directory in ("impact", "transformer"):
        occupied += sum(file.stat().st_size for file in (output / directory).glob("*") if file.is_file())
    routes = output / "routes.json"
    occupied += routes.stat().st_size if routes.exists() else 16_000_000
    remaining = REPO_LIMIT - occupied - 2_000_000
    part = build_shard(output, asset, rows, model, proof, limit=remaining, metrics=metrics)
    if not part:
        print(json.dumps({"asset": identity, "edition_sha256": digest, **metrics, "bytes": 0}), flush=True)
        return
    parts = [*old["parts"], *part["parts"]]
    whole = sha256()
    for number, pin in enumerate(parts):
        whole.update(read_file(output, part_location(digest, number, pin), pin))
    old.update(parts=parts, sha256=whole.hexdigest(),
               records=old["records"] + part["records"],
               passage_records=old.get("passage_records", 0) + part["passage_records"],
               lead_records=old.get("lead_records", 0) + part["lead_records"])
    old[coverage_key] = {**metrics, **proof, "source_sha256": digest}
    atomic_write(output / "manifest.json", encode(manifest) + b"\n")
    print(json.dumps({"asset": identity, "edition_sha256": digest, **metrics, **proof,
                      "bytes": sum(row["bytes"] for row in part["parts"])}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", action="append", type=Path, default=[])
    parser.add_argument("--range-receipts", type=Path, help="body bytes extracted from catalog-pinned publisher pieces")
    parser.add_argument("--directories", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=SEARCH_ROOT)
    parser.add_argument("--article-limit", type=int, default=1500)
    parser.add_argument("--leads", action="store_true", help="add sampled leads instead of body passages")
    parser.add_argument("--passages", type=int, default=3)
    parser.add_argument("assets", nargs="+")
    args = parser.parse_args()
    if min(args.article_limit, args.passages) < 1:
        parser.error("Article and passage limits must be positive")
    assets = {a["id"]: a for a in load_catalog(ROOT / "catalog/library.yaml", load_profiles(ROOT / "profiles"))}
    manifest = load_manifest(args.output)
    table = payload(read_file(args.output, MODEL_FILE, manifest["model"]), "OWLShardModel")
    model = Potion(table, b"".join(b64decode(payload(read_file(args.output, MODEL_PART.format(i), pin),
                                                   "OWLModelWeights")[1])
                                   for i, pin in enumerate(manifest["model_parts"])))
    for identity in args.assets:
        asset = assets[identity]
        path = find_source(asset, args.cache)
        directory = args.directories if path is not None else args.range_receipts
        if directory is None:
            parser.error(f"No pinned source body in cache: {identity}")
        append(args.output, asset, path, directory, model, manifest, args.article_limit, args.passages, leads=args.leads)


if __name__ == "__main__":
    main()
