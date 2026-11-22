#!/usr/bin/env python3
"""Generate read-only test fixtures or a fresh macOS exFAT disk image."""
from __future__ import annotations

import argparse
from base64 import b64decode
from hashlib import sha256
from pathlib import Path
import shutil
from subprocess import run
import sys
import tempfile

from libzim.writer import Creator, Hint, Item, StringProvider
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from owl.discovery import plan_discovery
from owl.search_shards import (MODEL_FILE, SEARCH_ROOT, Record, load_manifest, model_files,
                               packed_part, part_path, payload, read_file, script)
from owl.search_model import Potion


ARTICLE = "OWL test article: the archive reader worked."
DOCUMENT = "OWL phone fixture: a weather vane shows the direction of the wind."


class Article(Item):
    def get_path(self):
        return "owl-test"

    def get_title(self):
        return "OWL test article"

    def get_mimetype(self):
        return "text/html"

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: True}

    def get_contentprovider(self):
        return StringProvider(f"<!doctype html><meta charset=utf-8><p>{ARTICLE}</p>")


def create_pdf(path):
    writer = PdfWriter()
    pdf = writer.add_blank_page(width=620, height=460)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    pdf[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 15 Tf 48 400 Td ({DOCUMENT}) Tj ET".encode("ascii"))
    pdf[NameObject("/Contents")] = stream
    with path.open("wb") as output:
        writer.write(output)


def create_fixtures(drive, readers_from=None):
    library = drive / "LIBRARY"
    install = library / "SOFTWARE"
    for folder in ("BOOKS", "ZIM", "INDEX"):
        (library / folder).mkdir(parents=True, exist_ok=True)
    pdf = library / "BOOKS/phone-test.pdf"
    create_pdf(pdf)
    whole = library / "ZIM/reader-test.zim"
    creator = Creator(whole)
    creator.config_indexing(False, "")
    with creator as archive:
        archive.add_item(Article())
        archive.set_mainpath("owl-test")
    data = whole.read_bytes()
    mid = len(data) // 2
    (whole.parent / "split-test.zimaa").write_bytes(data[:mid])
    (whole.parent / "split-test.zimab").write_bytes(data[mid:])
    if readers_from is not None:
        shutil.copytree(readers_from / "LIBRARY/SOFTWARE", install)
    (drive / "START_HERE.html").write_text("""<!doctype html><html lang="en"><meta charset="utf-8">
<title>OWL device test</title><main><h1>OWL device test</h1>
<p>Open <a href="LIBRARY/BOOKS/phone-test.pdf">the phone test PDF</a>.
If the link stays in preview, close it and open <code>LIBRARY/BOOKS/phone-test.pdf</code> in Files.</p>
<p><a href="LIBRARY/SEARCH.html">Search the test library</a> for weather vane wind direction.
Open the single-file example <code>LIBRARY/ZIM/reader-test.zim</code> in Kiwix.
Then try the first part of the split fallback, <code>LIBRARY/ZIM/split-test.zimaa</code>
and keep its sibling part in the same folder.</p></main></html>
""", encoding="utf-8")
    for name in ("textbooks", "illustrated-guides", "categories", "critical", "A"):
        (library / "INDEX" / (name + ".html")).write_text(
            '<!doctype html><title>Fixture index</title><a href="../BOOKS/phone-test.pdf">Test PDF</a>',
            encoding="utf-8")
    (library / "INVENTORY.html").write_text(
        '<!doctype html><title>Fixture inventory</title><p>One PDF and two copies of the same test archive.',
        encoding="utf-8")
    digest = sha256(pdf.read_bytes()).hexdigest()
    asset = {"id": "phone-test", "title": "OWL phone fixture", "destination": "BOOKS/phone-test.pdf",
             "sha256": digest, "format": "pdf", "description": DOCUMENT, "category": "test"}
    files, _ = plan_discovery([asset])
    manifest = payload(files["SEARCH/manifest.js"].encode("utf-8"), "OWLDiscoveryManifest")
    manifest["shards"] = True
    pins = load_manifest()
    weights = []
    for name, pin in model_files(pins):
        body = read_file(SEARCH_ROOT, name, pin)
        files["SEARCH/" + name] = body.decode("utf-8")
        if name.startswith("model/"):
            weights.append(b64decode(payload(body, "OWLModelWeights")[1]))
    model = Potion(payload(files["SEARCH/" + MODEL_FILE].encode(), "OWLShardModel"), b"".join(weights))
    row = Record("Weather vane", 1, lead="A vane shows the direction of the wind.")
    part, vectors, bloom, _ = packed_part(digest, 0, [row], model)
    entry = {**asset, "parts": [{"bloom": bloom, "vectors": vectors, "semantic_vectors": vectors}], "shelves": [], "records": 1,
             "legacy": False, "license": "MIT", "attribution": ""}
    files["SEARCH/manifest.js"] = script("OWLDiscoveryManifest", manifest).decode("ascii")
    files["SEARCH/shards.js"] = script("OWLShardSelection", {
        "version": 1, "sources": [entry], "model_parts": len(weights),
    }).decode("ascii")
    files["SEARCH/" + part_path(digest, 0)] = part.decode("ascii")
    files["SEARCH/rank.js"] = Path(__file__).resolve().parents[1].joinpath("src/owl/templates/rank.js").read_text(encoding="utf-8")
    for name, contents in files.items():
        path = library / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--image", type=Path, help="new .dmg path (macOS only)")
    outputs.add_argument("--folder", type=Path, help="new fixture directory to copy to an exFAT drive")
    parser.add_argument("--readers-from", type=Path, help="copy LIBRARY/SOFTWARE from a finished OWL build")
    args = parser.parse_args()
    output = args.image or args.folder
    if output.exists():
        parser.error("Choose a new output")
    if args.folder:
        args.folder.mkdir()
        create_fixtures(args.folder, args.readers_from)
        return
    if sys.platform != "darwin" or args.image.suffix.lower() != ".dmg":
        parser.error("Use macOS and a new .dmg filename, or generate a --folder")
    with tempfile.TemporaryDirectory(prefix="owl-device-fixtures-") as tmp:
        path = Path(tmp)
        mount = path / "mount"
        mount.mkdir()
        run(["hdiutil", "create", "-size", "768m" if args.readers_from else "64m",
             "-fs", "ExFAT", "-layout", "MBRSPUD", "-volname", "OWL_TEST", str(args.image)], check=True)
        run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(args.image)], check=True)
        try:
            create_fixtures(mount, args.readers_from)
        finally:
            run(["hdiutil", "detach", str(mount)], check=True)


if __name__ == "__main__":
    main()
