#!/usr/bin/env python3
"""Precompute immutable shards from a verified source cache or ZIM range receipts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from gzip import open as gzip_open
from hashlib import sha256
from heapq import nlargest
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
                               SEARCH_ROOT, Record, encode, info, load_manifest, packed_part, part_path,
                               payload, read_file, script)
from owl.selection import CAPACITY_GRID_GB, load_ladder, recommended_profile
from owl.zim_directory import Directory, RangeSource


NOTICE = """Potion-base-2M by Minish Lab (Stephan Tulkens and Thomas van Dongen)
Model card and MIT license: {url}
OWL ships the leading 32 components quantized to signed 8-bit weights.
""".format(url=UPSTREAM)
FORMATS = {"pdf", "zim", "html", "htm"}
HTML_MIMES = {"text/html", "application/xhtml+xml"}
PASSAGE_SIZE = 1600


class Article(HTMLParser):
    """Extract paragraph leads, accepted answers, or section text from HTML."""
    SKIP = {"script", "style", "head", "template", "nav", "noscript"}
    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self, *, document=False):
        super().__init__(convert_charrefs=True)
        self.document = document
        self.stack = []
        self.lead = []
        self.accepted = []
        self.visible = []
        self.sections = []
        self.text = []
        self.header = []
        self.heading = self.anchor = ""
        self.lead_size = self.accepted_size = self.visible_size = 0

    def finish_section(self):
        if self.document and self.text:
            self.sections.append((self.heading, self.anchor, " ".join(self.text)))
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        attributes = dict(attrs)
        parent = self.stack[-1][1:] if self.stack else (False, False, False, "")
        hidden = parent[0] or tag in self.SKIP or "hidden" in attributes
        classes = set((attributes.get("class") or "").split())
        accepted = parent[1] or bool(classes & {"accepted-answer", "answer-accepted", "accepted"})
        anchor = attributes.get("id") or attributes.get("name") or parent[3]
        self.stack.append((tag, hidden, accepted, parent[2] or tag == "p", anchor))
        if self.document and not hidden and tag in self.HEADINGS:
            self.finish_section()
            self.anchor = anchor
            self.header = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                hidden = self.stack[index][1]
                del self.stack[index:]
                if self.document and not hidden and tag in self.HEADINGS:
                    self.heading = " ".join(self.header)
                return

    def handle_data(self, value):
        tag, hidden, accepted, paragraph, _ = self.stack[-1] if self.stack else ("", False, False, False, "")
        if hidden:
            return
        value = " ".join(value.split())
        if not value:
            return
        if not self.document and self.visible_size < 800:
            self.visible.append(value[:800 - self.visible_size])
            self.visible_size += len(value) + 1
        if self.document:
            if tag in self.HEADINGS or any(frame[0] in self.HEADINGS for frame in self.stack):
                self.header.append(value)
            else:
                self.text.append(value)
        if paragraph and self.lead_size < 800:
            self.lead.append(value[:800 - self.lead_size])
            self.lead_size += len(value) + 1
        if accepted and self.accepted_size < 800:
            self.accepted.append(value[:800 - self.accepted_size])
            self.accepted_size += len(value) + 1


def passage_text(text):
    """Split on word boundaries, keeping the physical page or section locator."""
    while len(text) > PASSAGE_SIZE:
        end = text.rfind(" ", PASSAGE_SIZE // 2, PASSAGE_SIZE + 1)
        if end < 0:
            end = PASSAGE_SIZE
        yield text[:end]
        text = text[end:].lstrip()
    if text:
        yield text


def html_records(path, asset):
    parser = Article(document=True)
    with path.open(encoding=asset.get("text_encoding", "utf-8"), errors="replace") as file:
        for block in iter(lambda: file.read(256_000), ""):
            parser.feed(block)
    parser.close()
    parser.finish_section()
    titled = False
    for heading, anchor, text in parser.sections:
        for body in passage_text(text):
            titled = True
            yield Record(heading or asset["title"], anchor, heading,
                         body=body, show_lead=bool(asset.get("redistributable")))
    if not titled:
        yield Record(asset["title"], "")


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
        heading = ""
        for index in range(pages):
            page = index + 1
            if page in sections:
                heading = " · ".join(sections[page])
            title = f"{heading} · Page {page}" if heading else f"Page {page}"
            text = " ".join(extract(index).split())
            for body in passage_text(text):
                yield Record(title, page, heading, body=body,
                             show_lead=bool(asset.get("redistributable")))
            if not text:
                yield Record(title, page, heading)

    finally:
        if hasattr(doc, "close"):
            doc.close()


def prioritized_leads(directory, limit):
    """Rank HTML entries by the number of direct redirect aliases that target them."""
    if not limit:
        return set()
    with gzip_open(directory, "rt", encoding="utf-8") as file:
        redirects = Counter()
        for line in file:
            _, _, _, redirect, _, target = json.loads(line)
            if redirect and target is not None:
                redirects[target] += 1

    def candidates():
        with gzip_open(directory, "rt", encoding="utf-8") as file:
            for line in file:
                _, path, mime, redirect, offset, _ = json.loads(line)
                if not redirect and mime.split(";", 1)[0] in HTML_MIMES:
                    yield redirects[offset], -offset, path

    return {path for _, _, path in nlargest(limit, candidates())}


def archive_records(rows, local, asset, metrics, *, lead_paths=None):
    archive = None
    if local:
        from libzim.reader import Archive
        archive = Archive(local)
    question_site = "/stack_exchange/" in asset.get("source_url", "") or "stackexchange" in asset.get("id", "")
    for title, location, mime, redirect, *_ in rows:
        lead = ""
        accepted_answer = False
        if archive and not redirect and mime.split(";", 1)[0] in HTML_MIMES:
            metrics["eligible_html"] += 1
            if lead_paths is None or location in lead_paths:
                try:
                    item = archive.get_entry_by_path(location).get_item()
                    parser = Article()
                    parser.feed(bytes(item.content).decode("utf-8", "replace"))
                    parser.close()
                    if parser.accepted and question_site:
                        lead = " ".join(parser.accepted)
                        accepted_answer = True
                        metrics["accepted_answers"] += 1
                    else:
                        lead = " ".join(parser.lead or parser.visible)
                    metrics["leads"] += bool(lead)
                except (KeyError, RuntimeError, ValueError):
                    metrics["read_errors"] += 1
        yield Record(title, location, lead=lead, redirect=redirect, accepted_answer=accepted_answer,
                     show_lead=bool(asset.get("redistributable")))

def directory_receipt(asset, ranges, path=None, *, sample=None):
    """Save the proof for every read and a compact title/path intermediate."""
    ranges.mkdir(parents=True, exist_ok=True)
    identity = asset["id"]
    directory_file = ranges / (identity + ".jsonl.gz")
    if path is None:
        source = RangeSource(asset, budget=350_000_000 if sample is not None else 2_500_000_000)
        reader = source.read
        proof = {"source_verification": "catalog byte count and mirror ETag", "ranges": source.receipts, "range_url": source.url}
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
                output.write(json.dumps([entry.title, entry.path, entry.mime, entry.redirect,
                                         entry.offset, entry.target_offset], ensure_ascii=False) + "\n")
                count += 1
        if path is None:
            proof["etag"] = source.etag
        proof.update(source_sha256=asset["sha256"], entries=count, namespace_counts=dict(directory.counts),
                     uuid=directory.uuid, main_path=directory.main_path, redirect_targets=sample is None,
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


def build_shard(output, asset, rows, model, proof, *, limit, metrics=None):
    source = asset["sha256"]
    final = output / part_path(source, 0)
    final.parent.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shard-", dir=final.parent.parent) as temporary:
        staging = Path(temporary)
        whole = sha256()
        parts = []
        records = leads = size = passages = 0
        entrypoints = []
        entrypoint_locations = set()
        iterator = iter(rows)
        for index in range(100_000):
            batch = list(islice(iterator, COUNT_PER_PART))
            if not batch:
                break
            data, vectors, bloom, body_vectors = packed_part(
                source, index, batch, model, title_paths=asset["format"] == "zim")
            records += len(batch)
            lead_vectors = sum(bool(row.lead) for row in batch)
            leads += lead_vectors
            passages += sum(bool(row.body) for row in batch)
            if len(entrypoints) < 24:
                marks = [row for row in batch if (asset["format"] == "pdf" or
                         asset["format"] == "zim" and (row.title.casefold().startswith("category:") or
                                                     row.title.casefold() == "contents"))]
                for row in marks:
                    if row.locator not in entrypoint_locations:
                        entrypoints.append([row.locator, row.title])
                        entrypoint_locations.add(row.locator)
                    if len(entrypoints) == 24:
                        break
            size += len(data) + len(bloom)
            if size > limit:
                return None
            whole.update(data)
            parts.append({**info(data), "records": len(batch), "vectors": vectors,
                          "passages": body_vectors, "lead_vectors": lead_vectors, "bloom": bloom})
            (staging / f"{index:05}.js").write_bytes(data)
        if not parts:
            return None
        final.parent.mkdir(exist_ok=True)
        for file in staging.iterdir():
            file.replace(final.parent / file.name)
        for file in final.parent.glob("[0-9][0-9][0-9][0-9][0-9].js"):
            if int(file.stem) >= len(parts):
                file.unlink()
    receipt = {key: proof[key] for key in ("source_verification", "uuid", "namespace_counts", "etag",
                                          "directory_coverage", "range_url", "lead_source_sha256", "lead_selection")
               if key in proof}
    if "ranges" in proof:
        receipt["range_bytes"] = sum(row[1] for row in proof["ranges"])
        receipt["range_receipts_sha256"] = sha256(encode(proof["ranges"])).hexdigest()
    return {"format": asset["format"], "asset_id": asset["id"], "sha256": whole.hexdigest(),
            "records": records, "lead_records": leads, "passage_records": passages,
            "parts": parts, "main": proof.get("main_path", ""),
            **({"extraction": dict(metrics)} if metrics else {}),
            "entrypoints": entrypoints,
            "source_evidence": receipt}


def defaults(assets, catalog, profiles):
    priority = {}
    ladder = load_ladder(catalog)
    for capacity in CAPACITY_GRID_GB:
        profile = recommended_profile(profiles["flash-16gb"], capacity * 10**9, ladder)
        selected, _, _ = resolve_content(assets, profile, resources_path=catalog.with_name("resources.yaml"))
        for asset in selected:
            priority.setdefault(asset["id"], capacity)
    return priority


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    model_options = parser.add_mutually_exclusive_group(required=True)
    model_options.add_argument("--model-input", type=Path, help="folder with the pinned potion-* inputs")
    model_options.add_argument("--packed-model", type=Path, help="use a previously generated model and notice")
    parser.add_argument("--cache", action="append", default=[], type=Path, help="directory of sources named by source SHA-256")
    parser.add_argument("--directories", type=Path, help="directory of reusable ZIM directory receipts")
    parser.add_argument("--range-zim", action="store_true", help="read missing ZIM directories from the pinned mirror")
    parser.add_argument("--sample-zim", type=int, help="read this many evenly spaced directory blocks instead of every entry")
    parser.add_argument("--output", type=Path, default=SEARCH_ROOT)
    parser.add_argument("--asset", action="append", default=[])
    parser.add_argument("--replace", action="store_true", help="replace the selected source shards")
    parser.add_argument("--lead-limit", type=int, help="select the N HTML entries with the most direct redirect aliases")

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
    if args.lead_limit is not None and args.lead_limit < 0:
        parser.error("--lead-limit must be non-negative")
    if args.packed_model:
        pins = load_manifest(args.packed_model)
        model_data = read_file(args.packed_model, MODEL_FILE, pins["model"])
        license_data = read_file(args.packed_model, LICENSE_FILE, pins["license"])
        model = Potion(payload(model_data, "OWLShardModel"))
    else:
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
    remaining = REPO_LIMIT - len(model_data) - len(license_data) - len(encode(manifest)) - 1
    remaining -= sum(part["bytes"] for shard in (*sources.values(), *manifest.get("shared", {}).values())
                     for part in shard.get("parts", ()))
    for asset in assets:
        source, identity = asset["sha256"], asset["id"]
        old = sources.get(source)
        if old and not args.replace:
            continue
        if old and old.get("shared"):
            raise ValueError("Rebuild shared directories together in a separate output")
        old_cost = sum(part["bytes"] for part in old.get("parts", ())) + len(encode(old)) if old else 0
        limit = remaining + old_cost
        path = find_source(asset, args.cache)
        receipt = {"source_verification": "whole-file SHA-256"}
        try:
            if asset["format"] == "zim":
                if args.directories is None:
                    if path:
                        raise ValueError("Use --directories to keep ZIM extraction receipts outside the shard output")
                    continue
                directories = args.directories
                data = directories / (identity + ".jsonl.gz")
                if not data.is_file() and (path or args.range_zim):
                    directory_receipt(asset, directories, path, sample=args.sample_zim)
                if not data.is_file():
                    continue
                receipt = json.loads((directories / (identity + ".json")).read_bytes())
                receipt.setdefault("directory_coverage", "complete")
                if receipt["source_sha256"] != source:
                    raise ValueError("Directory receipt differs from catalog")
                needs_targets = args.lead_limit is not None and not receipt.get("redirect_targets")
                if path and (receipt["directory_coverage"] != "complete" or needs_targets):
                    directory_receipt(asset, directories, path)
                    receipt = json.loads((directories / (identity + ".json")).read_bytes())
                lead_paths = None
                if path:
                    receipt["lead_source_sha256"] = source
                    if args.lead_limit is not None:
                        lead_paths = prioritized_leads(data, args.lead_limit)
                        receipt["lead_selection"] = "direct redirect alias count; ties use directory order"
                with gzip_open(data, "rt", encoding="utf-8") as file:
                    metrics = defaultdict(int)
                    rows = archive_records(map(json.loads, file), path, asset, metrics, lead_paths=lead_paths)
                    result = build_shard(output, asset, rows, model, receipt, limit=limit, metrics=metrics)
            elif path and asset["format"] != "zim":
                rows = pdf_records(path, asset) if asset["format"] == "pdf" else html_records(path, asset)
                result = build_shard(output, asset, rows, model, receipt, limit=limit)
            else:
                continue
            if result:
                sources[source] = result
                remaining = limit - sum(part["bytes"] for part in result["parts"]) - len(encode(result))
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
