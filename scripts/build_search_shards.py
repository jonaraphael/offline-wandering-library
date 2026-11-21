#!/usr/bin/env python3
"""Precompute immutable shards from a verified source cache or ZIM range receipts."""
from __future__ import annotations

import argparse
from collections import defaultdict
from gzip import open as gzip_open
from hashlib import sha256
from html.parser import HTMLParser
from itertools import islice
import json
from pathlib import Path
import sys
import tempfile

from owl.atlas_import import import_sections
from owl.catalog import load_catalog, load_profiles, resolve_content
from owl.safety import atomic_write, sha256_file
from owl.search_model import Potion, UPSTREAM
from owl.search_shards import (COUNT_PER_PART, LICENSE_FILE, MODEL_FILE, REPO_LIMIT, ROOT, SCHEMA,
                               SEARCH_ROOT, Record, encode, info, load_manifest, packed_part, part_path, script)
from owl.selection import BUILTIN_CAPACITIES, load_ladder, recommended_profile
from owl.zim_directory import Directory, RangeSource


NOTICE = """Potion-base-2M by Minish Lab (Stephan Tulkens and Thomas van Dongen)
Model card and MIT license: {url}
OWL ships the leading 32 components quantized to signed 8-bit weights.
""".format(url=UPSTREAM)
FORMATS = {"pdf", "zim", "html", "htm"}
SAMPLED_LEADS = 2048


class Article(HTMLParser):
    """Collect visible text and paragraph leads without retaining HTML markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = []
        self.paragraph = False
        self.text = []
        self.lead = []
        self.text_size = self.lead_size = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head", "template", "nav"}:
            self.skip.append(tag)
        elif tag == "p":
            self.paragraph = True

    def handle_endtag(self, tag):
        if self.skip and self.skip[-1] == tag:
            self.skip.pop()
        elif tag == "p":
            self.paragraph = False

    def handle_data(self, value):
        if self.skip:
            return
        value = " ".join(value.split())
        if value and self.text_size < 16000:
            self.text.append(value[:16000 - self.text_size])
            self.text_size += len(value)
        if value and self.paragraph and self.lead_size < 1200:
            self.lead.append(value[:1200 - self.lead_size])
            self.lead_size += len(value)


def html_records(path, asset):
    parser = Article()
    with path.open(encoding=asset.get("text_encoding", "utf-8"), errors="replace") as file:
        parser.feed(file.read(2_000_000))
    yield Record(asset["title"], "", lead=" ".join(parser.lead), body=" ".join(parser.text))


def pdf_sections(path, asset):
    """Use the existing validated outline importer, with page ranges as fallback."""
    try:
        sections, _ = import_sections(path.resolve(), asset)
    except (ValueError, OSError):
        return {}
    headings = defaultdict(list)
    for section in sections["sections"]:
        loc = section.get("locator")
        if loc and loc["type"] == "pdf-page":
            headings[loc["page"]].append(section["title"])
    return headings


def pdf_records(path, asset):
    try:
        from pymupdf import open as open_pdf
    except ImportError:
        from pypdf import PdfReader
        doc = PdfReader(path)
        pages = len(doc.pages)
        extract = lambda index: doc.pages[index].extract_text() or ""
    else:
        doc = open_pdf(path)
        pages = len(doc)
        extract = lambda index: doc[index].get_text(sort=True)
    try:
        sections = pdf_sections(path, asset)
        starts = sorted({1, *sections})
        ranges = set(starts)
        for first, stop in zip(starts, starts[1:] + [pages + 1]):
            ranges.update(range(first + 5, stop, 5))
        starts = sorted(ranges)
        for first, stop in zip(starts, starts[1:] + [pages + 1]):
            end = stop - 1
            body = " ".join(" ".join(extract(index).split())[:3600] for index in range(first - 1, end))
            heading = " · ".join(sections.get(first, ()))
            label = f"Page {first}" if first == end else f"Pages {first}–{end}"
            yield Record(heading or label, first, heading, body[:650], body)
    finally:
        if hasattr(doc, "close"):
            doc.close()


def archive_records(rows, report, local, asset):
    archive = None
    if local and asset.get("redistributable"):
        from libzim.reader import Archive
        archive = Archive(local)
    step = max(1, report["entries"] // SAMPLED_LEADS)
    sampled = 0
    for index, (title, location, mime, redirect) in enumerate(rows):
        lead = ""
        if archive and not redirect and mime.startswith("text/html") and index % step == 0 and sampled < SAMPLED_LEADS:
            try:
                item = archive.get_entry_by_path(location).get_item()
                if item.size <= 2_000_000:
                    parser = Article()
                    parser.feed(bytes(item.content).decode("utf-8", "replace"))
                    lead = " ".join(parser.lead)
                    sampled += bool(lead)
            except (KeyError, RuntimeError, ValueError):
                pass
        yield Record(title, location, lead=lead, redirect=redirect,
                     vector=not redirect and (bool(lead) or report["entries"] <= 4096))


def directory_receipt(asset, ranges, path=None, *, sample=None):
    """Save the proof for every read and a compact title/path intermediate."""
    ranges.mkdir(parents=True, exist_ok=True)
    identity = asset["id"]
    directory_file = ranges / (identity + ".jsonl.gz")
    if path is None:
        source = RangeSource(asset, budget=350_000_000 if sample is not None else 2_500_000_000)
        reader = source.read
        proof = {"source_verification": "catalog byte count and mirror ETag", "ranges": source.receipts}
    else:
        file = path.open("rb")
        proof = {"source_verification": "whole-file SHA-256"}
        def reader(start, length):
            file.seek(start)
            return file.read(length)
    temporary = directory_file.with_suffix(".part")
    try:
        directory = Directory(reader, asset["size_bytes"])
        entries = directory if sample is None else directory.sample(windows=sample)
        count = 0
        with gzip_open(temporary, "wt", encoding="utf-8", compresslevel=3) as output:
            for entry in entries:
                output.write(json.dumps([entry.title, entry.path, entry.mime, entry.redirect], ensure_ascii=False) + "\n")
                count += 1
        if path is None:
            proof["etag"] = source.etag
        proof.update(source_sha256=asset["sha256"], entries=count, namespace_counts=dict(directory.counts),
                     uuid=directory.uuid, main_path=directory.main_path,
                     directory_coverage="complete" if sample is None else "sampled" if sample else "entry-point")
        temporary.replace(directory_file)
        (ranges / (identity + ".json")).write_bytes(encode(proof) + b"\n")
    finally:
        temporary.unlink(missing_ok=True)
        if path is not None:
            file.close()


def find_source(asset, directories):
    for folder in directories:
        source = folder / asset["sha256"]
        if source.is_file():
            if source.stat().st_size != asset["size_bytes"] or sha256_file(source) != asset["sha256"]:
                raise ValueError(f"Cached source differs from its catalog pin: {asset['id']}")
            return source
    return None


def build_shard(output, asset, rows, model, proof, *, limit):
    source = asset["sha256"]
    final = output / part_path(source, 0)
    final.parent.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shard-", dir=final.parent.parent) as temporary:
        staging = Path(temporary)
        whole = sha256()
        parts = []
        records = leads = size = 0
        entrypoints = []
        iterator = iter(rows)
        for index in range(100_000):
            batch = list(islice(iterator, COUNT_PER_PART))
            if not batch:
                break
            data, vectors, bloom = packed_part(source, index, batch, model)
            records += len(batch)
            leads += sum(bool(row.lead) for row in batch)
            if len(entrypoints) < 24:
                marks = [row for row in batch if (asset["format"] == "pdf" or
                         asset["format"] == "zim" and (row.title.casefold().startswith("category:") or
                                                     row.title.casefold() == "contents"))]
                entrypoints.extend([row.locator, row.title] for row in marks[:24 - len(entrypoints)])
            size += len(data) + len(bloom)
            if size > limit:
                return None
            whole.update(data)
            parts.append({**info(data), "records": len(batch), "vectors": vectors, "bloom": bloom})
            (staging / f"{index:05}.js").write_bytes(data)
        if not parts:
            return None
        final.parent.mkdir(exist_ok=True)
        for file in staging.iterdir():
            file.replace(final.parent / file.name)
        for file in final.parent.glob("[0-9][0-9][0-9][0-9][0-9].js"):
            if int(file.stem) >= len(parts):
                file.unlink()
    receipt = {key: proof[key] for key in ("source_verification", "uuid", "namespace_counts", "etag", "directory_coverage") if key in proof}
    if "ranges" in proof:
        receipt["range_bytes"] = sum(row[1] for row in proof["ranges"])
        receipt["range_receipts_sha256"] = sha256(encode(proof["ranges"])).hexdigest()
    return {"format": asset["format"], "asset_id": asset["id"], "sha256": whole.hexdigest(),
            "records": records, "lead_records": leads, "parts": parts, "main": proof.get("main_path", ""),
            "entrypoints": entrypoints,
            "source_evidence": receipt}


def defaults(assets, catalog, profiles):
    priority = {}
    ladder = load_ladder(catalog)
    for capacity in sorted({128, *BUILTIN_CAPACITIES.values()}):
        profile = recommended_profile(profiles["flash-16gb"], capacity * 10**9, ladder)
        selected, _, _ = resolve_content(assets, profile, resources_path=catalog.with_name("resources.yaml"))
        for asset in selected:
            priority.setdefault(asset["id"], capacity)
    return priority


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-input", required=True, type=Path, help="folder with the pinned potion-* inputs")
    parser.add_argument("--cache", action="append", default=[], type=Path, help="directory of sources named by source SHA-256")
    parser.add_argument("--directories", type=Path, help="directory of reusable ZIM directory receipts")
    parser.add_argument("--range-zim", action="store_true", help="read missing ZIM directories from the pinned mirror")
    parser.add_argument("--sample-zim", type=int, help="read this many evenly spaced directory blocks instead of every entry")
    parser.add_argument("--output", type=Path, default=SEARCH_ROOT)
    parser.add_argument("--asset", action="append", default=[])
    args = parser.parse_args(argv)
    catalog = ROOT / "catalog/library.yaml"
    profiles = load_profiles(ROOT / "profiles")
    assets = load_catalog(catalog, profiles)
    priority = defaults(assets, catalog, profiles)
    assets = [a for a in assets if a["format"] in FORMATS and (a["id"] in args.asset if args.asset else a["id"] in priority)]
    assets.sort(key=lambda a: (priority.get(a["id"], 1001), a["format"] == "zim", a["size_bytes"], a["id"]))
    if args.sample_zim is not None and not args.range_zim:
        parser.error("--sample-zim requires --range-zim")
    if args.range_zim and (not args.directories or len(args.asset) != 1):
        parser.error("--range-zim requires --directories and one --asset to bound the transfer")
    model = Potion.convert(args.model_input)
    model_data = script("OWLShardModel", model.table)
    license_input = (args.model_input / "potion-license.txt").read_bytes()
    if sha256(license_input).hexdigest() != "b0214f148eceae739f916209e78cfe15712c4b810c8bc9d44b6c2d1d1616aab6":
        raise ValueError("Potion MIT notice differs from its pin")
    license_data = NOTICE.encode("utf-8") + b"\n" + license_input
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(output)
    if manifest["sources"] and manifest["model"] != info(model_data):
        parser.error("use a new output directory to rebuild all sources for a different model")
    sources = manifest["sources"]
    manifest.update(version=SCHEMA, model=info(model_data), license=info(license_data))
    atomic_write(output / MODEL_FILE, model_data)
    atomic_write(output / LICENSE_FILE, license_data)
    remaining = REPO_LIMIT - len(model_data) - len(encode(manifest))
    remaining -= sum(part["bytes"] for shard in sources.values() for part in shard["parts"])
    for asset in assets:
        source, identity = asset["sha256"], asset["id"]
        if source in sources:
            continue
        path = find_source(asset, args.cache)
        receipt = {"source_verification": "whole-file SHA-256"}
        try:
            if asset["format"] == "zim" and args.directories:
                data = args.directories / (identity + ".jsonl.gz")
                if not data.is_file() and (path or args.range_zim):
                    directory_receipt(asset, args.directories, path, sample=args.sample_zim)
                if not data.is_file():
                    continue
                receipt = json.loads((args.directories / (identity + ".json")).read_bytes())
                if receipt["source_sha256"] != source or not data.is_file():
                    raise ValueError("Directory receipt differs from catalog")
                with gzip_open(data, "rt", encoding="utf-8") as file:
                    rows = archive_records(map(json.loads, file), receipt, path, asset)
                    result = build_shard(output, asset, rows, model, receipt, limit=remaining)
            elif path and asset.get("redistributable"):
                rows = pdf_records(path, asset) if asset["format"] == "pdf" else html_records(path, asset)
                result = build_shard(output, asset, rows, model, receipt, limit=remaining)
            else:
                continue
            if result:
                sources[source] = result
                remaining -= sum(part["bytes"] for part in result["parts"]) + len(encode(result))
                temporary = output / "manifest.json.tmp"
                temporary.write_bytes(encode(manifest) + b"\n")
                temporary.replace(output / "manifest.json")
                print(identity, result["records"], result["lead_records"], flush=True)
            else:
                print(identity, "omitted: empty source or shard budget", flush=True)
        except (ValueError, OSError) as error:
            print(identity, "omitted:", error, file=sys.stderr, flush=True)
    atomic_write(output / "manifest.json", encode(manifest) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
