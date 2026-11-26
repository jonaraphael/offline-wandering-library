#!/usr/bin/env python3
"""Render the story ladder's reading PDFs from pinned Project Gutenberg HTML.

Each book in catalog/stories/ladder.yaml becomes catalog/stories/age-NN-<slug>.pdf.
catalog/stories/manifest.json pins every source package, font and PDF.

  build_story_ladder.py --work DIR        download sources and render every PDF
  build_story_ladder.py --entries COMMIT  print library.yaml entries for COMMIT
  build_story_ladder.py --check           check the PDFs and catalog entries

Rendering needs Google Chrome and Pillow. A source package that changed
upstream stops the build unless --refresh is given.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.download import USER_AGENT  # noqa: E402

STORIES = ROOT / "catalog/stories"
LADDER = STORIES / "ladder.yaml"
MANIFEST = STORIES / "manifest.json"
CATALOG = ROOT / "catalog/library.yaml"
RESOURCES = ROOT / "catalog/resources.yaml"
RESOURCE = "childrens-library"
SOURCE = "https://aleph.pglaf.org/cache/epub/{id}/pg{id}-h.zip"
EBOOK = "https://www.gutenberg.org/ebooks/{id}"
REPOSITORY = "https://raw.githubusercontent.com/jonaraphael/offline-wandering-library/{commit}/catalog/stories/{file}"
DESTINATION = "BOOKS/STORIES/{file}"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT_COMMIT = "d9ec0982cbe53f7b7bf4af3e6cdbda0dbd1dac10"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/" + FONT_COMMIT + "/ofl/{path}"
FONTS = {
    "Andika": [
        ("andika/Andika-Regular.ttf", "202b96b1f174a4a43baefe885b40dacacb81786755efd08ed4b7704e79c45515", "400", "normal"),
        ("andika/Andika-Bold.ttf", "4361126189a2d0e0da66999352db58aaf1b4ca940faf8a8239d725f8303d890d", "700", "normal"),
        ("andika/Andika-Italic.ttf", "6a4a0dd26d28f577b51dd6afb5acf6fd91ab21694e25649c270a32179bb52a62", "400", "italic"),
        ("andika/Andika-BoldItalic.ttf", "2d000f8791a1827c0c4d411e9f4593c4fc2db0fdbb868bb1f863593b3d3968e6", "700", "italic"),
    ],
    "Literata": [
        ("literata/Literata%5Bopsz,wght%5D.ttf", "b41138c9373112f32abb589cc22e8674b06ed4048b0c513be922bdd26f274440", "200 900", "normal"),
        ("literata/Literata-Italic%5Bopsz,wght%5D.ttf", "d483dfaeba9cbf4ce71d32a52ee65df82f7e35b15fff8d1011cdb242d1fcd465", "200 900", "italic"),
    ],
}
FONT_NAMES = {"Andika": "Andika (SIL International)", "Literata": "Literata (TypeTogether for Google)"}
# Font, base size, line height, printed picture height, longest picture side in
# pixels and JPEG quality. Picture-book scans keep the most detail.
LAYOUTS = {
    "picture": ("Andika", "17pt", 1.4, "6.2in", 1400, 80),
    "early": ("Andika", "14pt", 1.45, "5.6in", 1100, 62),
    "novel": ("Literata", "11.5pt", 1.45, "5.4in", 900, 68),
}
FIELDS = {"age", "gutenberg", "slug", "title", "byline", "published", "layout", "breaks", "why"}
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PICTURE = re.compile(r"\.(jpe?g|png|gif|webp)$", re.I)
SOURCE_LIMIT = 200_000_000
PDF_LIMIT = 15_000_000


def books() -> list[dict]:
    rows = yaml.safe_load(LADDER.read_text(encoding="utf-8"))["books"]
    if [row.get("age") for row in rows] != list(range(1, 19)):
        raise SystemExit("ladder.yaml needs exactly one book for each age from 1 to 18, in order")
    for row in rows:
        if set(row) != FIELDS or row["layout"] not in LAYOUTS or not ID_PATTERN.fullmatch(row["slug"]):
            raise SystemExit(f"age {row['age']}: book needs fields {sorted(FIELDS)} and a known layout")
        if type(row["gutenberg"]) is not int or row["gutenberg"] <= 0:
            raise SystemExit(f"age {row['age']}: gutenberg must be an eBook number")
        if any(not isinstance(row[key], str) or not row[key].strip()
               for key in FIELDS - {"age", "gutenberg"}):
            raise SystemExit(f"age {row['age']}: text fields must be nonempty strings")
        row["file"] = f"age-{row['age']:02d}-{row['slug']}.pdf"
        row["id"] = f"story_age{row['age']:02d}_" + row["slug"].replace("-", "_")
    return rows


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"books": []}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def fetch(url: str, path: Path, limit: int) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    temporary = path.with_suffix(path.suffix + ".part")
    with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        received = 0
        while chunk := response.read(1 << 20):
            received += len(chunk)
            if received > limit:
                raise SystemExit(f"{url} is larger than {limit} bytes")
            output.write(chunk)
    temporary.replace(path)


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()


def fonts(work: Path) -> dict[str, str]:
    """Return @font-face rules with each pinned font inlined."""
    rules = {}
    directory = work / "fonts"
    directory.mkdir(parents=True, exist_ok=True)
    for family, faces in FONTS.items():
        css = []
        for path, pin, weight, style in faces:
            local = directory / pin
            if not local.exists():
                fetch(FONT_URL.format(path=path), local, 5_000_000)
            if digest(local) != pin:
                local.unlink()
                raise SystemExit(f"{path} differs from its pin")
            data = base64.b64encode(local.read_bytes()).decode("ascii")
            css.append(f"@font-face{{font-family:{family};src:url(data:font/ttf;base64,{data});"
                       f"font-weight:{weight};font-style:{style}}}")
        rules[family] = "\n".join(css)
    return rules


def source(book: dict, work: Path, pinned: dict | None, refresh: bool) -> tuple[Path, dict]:
    url = SOURCE.format(id=book["gutenberg"])
    directory = work / "sources"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"pg{book['gutenberg']}-h.zip"
    if not path.exists() or (pinned and digest(path) != pinned["sha256"] and refresh):
        fetch(url, path, SOURCE_LIMIT)
    record = {"url": url, "bytes": path.stat().st_size, "sha256": digest(path)}
    if pinned and pinned["url"] == url and pinned["sha256"] != record["sha256"] and not refresh:
        raise SystemExit(f"age {book['age']}: {url} changed upstream; review it and rerun with --refresh")
    return path, record


def credits(header: str) -> dict[str, str]:
    rows = {}
    for name, value in re.findall(r"<p><strong>([^<]+)</strong>:\s*(.*?)</p>", header, re.S):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()
        rows[name.strip()] = text.replace("&amp;", "&")
    return rows


def shown_pictures(html: str) -> list[str]:
    """Pictures the page displays; linked full-size scans are not printed."""
    return list(dict.fromkeys(re.findall(r'<img\b[^>]*\bsrc="([^"#?]+)"', html)))


def shrink_pictures(directory: Path, names: list[str], layout: str) -> dict[str, str]:
    """Resize and recompress displayed pictures in place; return renamed files."""
    from PIL import Image, ImageStat

    longest, quality = LAYOUTS[layout][4], LAYOUTS[layout][5]
    renamed = {}
    for name in names:
        path = (directory / name).resolve()
        if not str(path).startswith(str(directory.resolve()) + os.sep) or not path.is_file():
            raise SystemExit(f"{directory.name}: picture {name} is missing")
        if not PICTURE.search(path.name):
            continue
        with Image.open(path) as original:
            original.load()
            image = original
            size = image.size
            heavy = path.stat().st_size > 60_000
            if max(size) <= longest and not heavy:
                continue
            if max(size) > longest:
                scale = longest / max(size)
                image = image.resize((max(1, round(size[0] * scale)), max(1, round(size[1] * scale))),
                                     Image.LANCZOS)
            transparent = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
            if transparent:
                image.save(path, optimize=True)
                continue
            colour = image.convert("RGB")
            grey = ImageStat.Stat(colour.convert("HSV")).mean[1] < 14
            target = path.with_suffix(".jpg")
            (colour.convert("L") if grey else colour).save(target, "JPEG", quality=quality, optimize=True)
            if target != path:
                path.unlink()
                renamed[name] = Path(name).with_suffix(".jpg").as_posix()
    return renamed


WEB_NOTE = re.compile(r"project gutenberg|gutenberg\.org|pgdp\.net|archive\.org|e-?book\W+#\s*\d|several editions of this ebook",
                      re.I)
EMPTY = re.compile(r"<(p|div|span|pre)\b(?![^>]*\bid=)[^>]*>(?:\s|&nbsp;|&#160;|\u00a0|<br\s*/?>)*</\1>", re.I)
INNERMOST = re.compile(r"<(p|div|h[1-6]|table)\b[^>]*>((?:(?!<(?:p|div|h[1-6]|table)\b).)*?)</\1>", re.S | re.I)
GUTENBERG_LINK = re.compile(r'href="https?://[^"]*gutenberg', re.I)


def tidy(body: str) -> tuple[str, list[str]]:
    """Drop empty blocks and notes that point readers to a website."""
    removed = []

    def note(match):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(2))).strip()
        if (WEB_NOTE.search(text) or GUTENBERG_LINK.search(match.group(2))) and len(text) < 600:
            removed.append(text[:120])
            return ""
        return match.group(0)

    body = INNERMOST.sub(note, body)
    body = re.sub(r'<a\b[^>]*href="https?://[^"]*gutenberg[^"]*"[^>]*>(.*?)</a>', r"\1", body, flags=re.S | re.I)
    while True:
        cleaned = EMPTY.sub("", body)
        if cleaned == body:
            return body, removed
        body = cleaned


def page(book: dict, html: str, faces: dict[str, str], made: str) -> tuple[str, dict]:
    header = re.search(r'<header\b[^>]*\bid="pg-header".*?</header>', html, re.S)
    footer = re.search(r'<footer\b[^>]*\bid="pg-footer".*?</footer>', html, re.S)
    if not header or not footer:
        raise SystemExit(f"age {book['age']}: the source lacks the expected Gutenberg header and footer")
    info = credits(header.group(0))
    body = html[header.end():footer.start()]
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html[:header.start()], re.S))
    styles = re.sub(r"#pg-(?:header|footer)[^{]*\{[^}]*\}", "", styles)
    if re.search(r"(START|END) OF (THE|THIS) PROJECT GUTENBERG", body, re.I):
        raise SystemExit(f"age {book['age']}: Gutenberg boilerplate remains in the body")
    body, removed = tidy(body)
    family, size, leading, picture_height, _, _ = LAYOUTS[book["layout"]]
    people = [f"{key}: {info[key]}" for key in ("Author", "Editor", "Illustrator", "Translator") if info.get(key)]
    release = info.get("Release date", "")
    transcribers = info.get("Credits", "")
    colophon = [
        f"This reading edition was made on {made} by the Offline Wandering Library from the "
        f"volunteer transcription published as Project Gutenberg eBook #{book['gutenberg']}"
        + (f" ({escape(release)})" if release else "") + ". Gutenberg's license pages were removed. "
        "The text is as transcribed; pictures were resized to keep the file small.",
    ]
    if people:
        colophon.append(escape("; ".join(people)) + ".")
    if transcribers:
        colophon.append("Transcribed by " + escape(transcribers.removeprefix("Produced by ").rstrip(".")) + ".")
    colophon += [
        f"First published {escape(book['published'])}. Public domain in the United States; "
        "copyright terms differ in some other countries.",
        f"Set in {FONT_NAMES[family]} under the SIL Open Font License.",
    ]
    css = f"""
{faces[family]}
@page {{ size: 5.5in 8.5in; margin: 0.55in 0.5in 0.6in; }}
html {{ font-size: {size} !important; }}
body {{ margin: 0 !important; padding: 0 !important; max-width: none !important; width: auto !important;
  text-align: left !important; line-height: {leading} !important; color: #1b1b1b; background: #fff;
  hyphens: auto; -webkit-hyphens: auto; widows: 2; orphans: 2; }}
body, body * {{ font-family: {family}, serif !important; }}
img {{ max-width: 100% !important; height: auto !important; max-height: {picture_height} !important;
  width: auto; object-fit: contain; }}
.fig, .figcenter, .figleft, .figright, .figc, .figl, .figr, .figure, .illus, .image, figure, .caption {{
  float: none !important; clear: both; break-inside: avoid; margin-left: auto !important;
  margin-right: auto !important; text-align: center !important; width: auto !important;
  max-width: 100% !important; }}
.pagenum, .pageno, .pagenumber, .pgnum, span.pagenum, a.pagenum {{ display: none !important; }}
div.wrap_area_left img, div.wrap_area_right img {{ position: static !important; display: block;
  margin: 0 auto 0.6em; }}
div.shape_wrap_left, div.shape_wrap_right {{ display: none !important; }}
h1, h2, h3, h4, h5, h6 {{ line-height: 1.25 !important; letter-spacing: normal !important;
  word-spacing: normal !important; }}
h2, h3, h4, h5, h6 {{ break-after: avoid; }}
h1 {{ font-size: 1.8rem !important; }}
h2 {{ font-size: 1.35rem !important; }}
h3 {{ font-size: 1.15rem !important; }}
h4, h5, h6 {{ font-size: 1rem !important; }}
p {{ text-align: left; }}
table {{ max-width: 100% !important; }}
pre {{ white-space: pre-wrap; }}
{book['breaks']} {{ break-before: page; }}
hr:has(+ :is(h1, h2, h3, h4, div.chapter)) {{ display: none !important; }}
.owl-title, .owl-title p {{ text-align: center !important; text-indent: 0 !important; }}
.owl-title {{ break-after: page; padding-top: 1.3in; }}
.owl-age {{ font-size: 1.1rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b4e16; margin: 0 0 1.2rem; }}
.owl-book {{ font-size: 2.1rem; line-height: 1.15; margin: 0 0 1rem; font-weight: 700; }}
.owl-byline, .owl-year {{ font-size: 1rem; margin: 0.3rem 0; }}
.owl-why {{ font-size: 1rem; margin: 1.6rem auto 0; max-width: 26em; font-style: italic; }}
.owl-shelf {{ font-size: 0.75rem; margin-top: 2.4rem; color: #555; }}
.owl-colophon {{ break-before: page; font-size: 0.8rem; text-align: left; }}
.owl-colophon p {{ margin: 0 0 0.7em; text-indent: 0; }}
"""
    title = escape(book["title"])
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>{styles}</style>
<style>{css}</style></head><body>
<div class="owl-title">
<p class="owl-age">Age {book['age']}</p>
<p class="owl-book">{title}</p>
<p class="owl-byline">{escape(book['byline'])}</p>
<p class="owl-year">First published {escape(book['published'])}</p>
<p class="owl-why">{escape(book['why'])}</p>
<p class="owl-shelf">Offline Wandering Library · Stories for every age</p>
</div>
{body}
<div class="owl-colophon">
<h2 style="break-before:auto">About this edition</h2>
{''.join(f'<p>{line}</p>' for line in colophon)}
</div>
</body></html>
"""
    author = info.get("Author") or info.get("Editor") or info.get("Illustrator") or ""
    return document, {"author": author, "credits": info, "removed": removed}


def chrome_pdf(chrome: str, html: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="owl-chrome-") as profile:
        subprocess.run([
            chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--no-pdf-header-footer", "--generate-pdf-document-outline", f"--user-data-dir={profile}",
            "--virtual-time-budget=30000", f"--print-to-pdf={output}", html.as_uri(),
        ], check=True, timeout=900, capture_output=True)


def finish_pdf(raw: Path, output: Path, book: dict, author: str) -> int:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(raw))
    writer.metadata = {
        "/Title": book["title"],
        "/Author": author,
        "/Subject": f"Offline Wandering Library story ladder, age {book['age']}",
        "/Creator": "Offline Wandering Library, scripts/build_story_ladder.py",
        "/Producer": "Google Chrome and pypdf",
    }
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    with output.open("wb") as stream:
        writer.write(stream)
    return len(writer.pages)


def render(args) -> int:
    from pypdf import PdfReader

    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    rows = books()
    manifest = load_manifest()
    pinned = {row["gutenberg"]: row["source"] for row in manifest.get("books", [])}
    previous = {row["age"]: row for row in manifest.get("books", [])}
    faces = fonts(work)
    made = date.today().isoformat()
    chrome = args.chrome or os.environ.get("CHROME") or CHROME
    version = subprocess.run([chrome, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    entries = []
    for book in rows:
        if args.only and book["age"] not in args.only and book["age"] in previous:
            entries.append(previous[book["age"]])
            continue
        package, record = source(book, work, pinned.get(book["gutenberg"]), args.refresh)
        build = work / "build" / book["slug"]
        shutil.rmtree(build, ignore_errors=True)
        build.mkdir(parents=True)
        with zipfile.ZipFile(package) as archive:
            for member in archive.infolist():
                target = (build / member.filename).resolve()
                if not str(target).startswith(str(build.resolve()) + os.sep):
                    raise SystemExit(f"{package}: unsafe member {member.filename}")
            archive.extractall(build)
        pages = sorted(build.glob("*.html"))
        if len(pages) != 1:
            raise SystemExit(f"{package}: expected one HTML file")
        html = pages[0].read_text(encoding="utf-8")
        shown = shown_pictures(html)
        renamed = shrink_pictures(build, shown, book["layout"])
        for old, new in renamed.items():
            html = html.replace(f'"{old}"', f'"{new}"')
        document, info = page(book, html, faces, made)
        reading = build / "reading.html"
        reading.write_text(document, encoding="utf-8")
        raw = build / "chrome.pdf"
        chrome_pdf(chrome, reading, raw)
        output = STORIES / book["file"]
        count = finish_pdf(raw, output, book, info["author"])
        size = output.stat().st_size
        if not 0 < size <= PDF_LIMIT:
            raise SystemExit(f"{output.name} is {size} bytes; the limit is {PDF_LIMIT}")
        if len(PdfReader(output).pages) != count:
            raise SystemExit(f"{output.name} did not read back")
        entries.append({
            "age": book["age"], "id": book["id"], "file": book["file"], "title": book["title"],
            "gutenberg": book["gutenberg"], "author": info["author"], "source": record,
            "pictures": len(shown),
            "pages": count, "bytes": size, "sha256": digest(output), "made": made,
        })
        print(f"age {book['age']:2d}  {size / 1e6:6.2f} MB  {count:4d} pages  {book['file']}")
        for text in info["removed"]:
            print(f"        removed note: {text}")
    keep = {row["file"] for row in rows}
    for stale in STORIES.glob("*.pdf"):
        if stale.name not in keep:
            stale.unlink()
    manifest = {
        "schema_version": 1,
        "renderer": version,
        "fonts": {path: pin for faces_ in FONTS.values() for path, pin, _, _ in faces_},
        "font_commit": FONT_COMMIT,
        "books": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in entries)
    print(f"total {total / 1e6:.2f} MB. Commit catalog/stories, then run --entries <that commit>.")
    return 0


def entry(book: dict, row: dict, commit: str) -> dict:
    illustrated = row["pictures"] > 1
    return {
        "id": book["id"],
        "title": f"{book['title']} (age {book['age']})",
        "category": "children",
        "format": "pdf",
        "source_url": REPOSITORY.format(commit=commit, file=book["file"]),
        "destination": DESTINATION.format(file=book["file"]),
        "version": f"OWL reading edition {row['made']} from Project Gutenberg eBook #{book['gutenberg']}",
        "size_bytes": row["bytes"],
        "sha256": row["sha256"],
        "license": "Public domain in the United States (first published "
                   f"{book['published']}); copyright terms differ in some other countries.",
        "redistributable": True,
        "required": False,
        "profiles": [],
        "critical": False,
        "reader_required": False,
        "publisher": "Offline Wandering Library, from a Project Gutenberg volunteer transcription",
        "source_page": EBOOK.format(id=book["gutenberg"]),
        "language": "en",
        "snapshot_date": row["made"],
        "attribution": f"{book['title']}. {book['byline']}. Transcription: Project Gutenberg eBook "
                       f"#{book['gutenberg']}; the PDF's last page lists the transcribers.",
        "resource_type": "reference",
        "illustrated": illustrated,
        "description": f"Story ladder, age {book['age']}. {book['why']} {row['pages']} pages"
                       + (", illustrated." if illustrated else "."),
        "utility_tier": "NONESSENTIAL",
        "utility_reason": "Shared stories connect a child to other children, older generations and "
                          "other cultures, and build reading skill.",
        "knowledge_domains": ["stories"],
        "selection": {"domain": "culture", "level": 0, "rank": book["age"]},
        "digest_algorithm": "sha256",
    }


def entries(commit: str) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("--entries needs a full 40-character commit hash")
    manifest = {row["age"]: row for row in load_manifest()["books"]}
    rows = [entry(book, manifest[book["age"]], commit) for book in books()]
    print(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=88), end="")
    return 0


def check() -> int:
    problems = []
    rows = books()
    manifest = {row["age"]: row for row in load_manifest()["books"]}
    catalog = {row["id"]: row for row in yaml.safe_load(CATALOG.read_text(encoding="utf-8"))["assets"]}
    resources = {row["id"]: row for row in yaml.safe_load(RESOURCES.read_text(encoding="utf-8"))["resources"]}
    for book in rows:
        row = manifest.get(book["age"])
        if not row or (row["file"], row["id"], row["gutenberg"]) != (book["file"], book["id"], book["gutenberg"]):
            problems.append(f"age {book['age']}: manifest does not match ladder.yaml; rerun the renderer")
            continue
        path = STORIES / book["file"]
        if not path.exists() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            problems.append(f"{book['file']}: differs from manifest")
        asset = catalog.get(book["id"])
        if not asset:
            problems.append(f"{book['id']}: missing from catalog/library.yaml")
            continue
        expected = entry(book, row, "0" * 40)
        for key, value in expected.items():
            if key == "source_url":
                if not re.fullmatch(REPOSITORY.format(commit="[0-9a-f]{40}", file=re.escape(book["file"])),
                                    asset[key]):
                    problems.append(f"{book['id']}: source_url must name a commit and {book['file']}")
            elif asset.get(key) != value:
                problems.append(f"{book['id']}: {key} differs from the generated entry")
    stray = sorted({path.name for path in STORIES.glob("*.pdf")} - {book["file"] for book in rows})
    problems += [f"{name}: not in ladder.yaml" for name in stray]
    if resources.get(RESOURCE, {}).get("asset_ids") != [book["id"] for book in rows]:
        problems.append(f"{RESOURCE}: asset_ids must list the ladder in age order")
    for problem in problems:
        print(problem, file=sys.stderr)
    return int(bool(problems))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--work", type=Path, help="cache and build directory")
    action.add_argument("--entries", metavar="COMMIT", help="print catalog entries for PDFs committed at COMMIT")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--only", type=int, action="append", help="render only this age (repeatable)")
    parser.add_argument("--refresh", action="store_true", help="accept changed upstream source packages")
    parser.add_argument("--chrome", help="Chrome or Chromium executable")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.entries:
        return entries(args.entries)
    return render(args)


if __name__ == "__main__":
    raise SystemExit(main())
