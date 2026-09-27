"""Deterministic local EPUB pagination, retaining the pinned original as input.

No extraction, network fetches or subprocesses: MuPDF reads only the validated
EPUB container. The fixed renderer and layout are part of each reviewed recipe.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from html.parser import HTMLParser
import importlib
import io
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import threading
import unicodedata
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from ..download import verified
from ..safety import SafetyError, atomic_write, reject_symlinks, safe_path

PYMUPDF_VERSION = "1.28.2"
LAYOUT = {"width": 600, "height": 800, "fontsize": 16}
PRINT_CSS = "pre { white-space: pre-wrap !important; overflow-wrap: anywhere !important; }"
BOOKDASH_POLICY = "bookdash-pages-v1"
BOOKDASH_CSS = ".owl-print-spread { page-break-after: always; } .copyright-text img.imprint-logo { width: 3em; height: auto; }"
PDF_PROVENANCE = "PDF layout adapted by OWL from the publisher EPUB; original text, illustrations and credits retained."
KNOWN_WARNINGS = {"unknown epub version: 3.0"}
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_MARKUP_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_PAGES = 20000
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
_RENDER_LOCK = threading.RLock()  # MuPDF diagnostics are process-global.


def validate_recipe(recipe: dict, assets: dict | None = None) -> None:
    selection = recipe["selection"]
    outputs = selection.get("outputs")
    if (not isinstance(outputs, dict) or set(outputs) != set(recipe["output_asset_ids"])
            or any(not isinstance(value, str) for value in outputs.values())
            or set(outputs.values()) != set(recipe["source_asset_ids"])
            or len(set(outputs.values())) != len(outputs) or recipe.get("dependency_asset_ids")):
        raise SafetyError("EPUB recipe must map every PDF output to its own source EPUB")
    if selection.get("pymupdf_version") != PYMUPDF_VERSION:
        raise SafetyError(f"EPUB recipes require PyMuPDF {PYMUPDF_VERSION}")
    _options(selection.get("layout"), selection.get("allowed_warnings", []),
             selection.get("trim_image_only_cover", True), selection.get("print_css", ""),
             selection.get("illustration_policy", ""))
    if assets is not None:
        for output_id, source_id in outputs.items():
            source, output = assets.get(source_id, {}), assets.get(output_id, {})
            if source.get("format") != "epub" or source.get("supporting_file") is not True:
                raise SafetyError(f"EPUB input must be a hidden supporting EPUB: {source_id}")
            if output.get("format") != "pdf":
                raise SafetyError(f"EPUB output must be an ordinary PDF: {output_id}")


def _options(layout, allowed_warnings, trim_image_only_cover, print_css, illustration_policy=""):
    if layout != LAYOUT or any(type(value) is not int for value in layout.values()):
        raise SafetyError("EPUB PDF layout must be exactly 600 x 800 points at fontsize 16")
    if (not isinstance(allowed_warnings, (list, tuple)) or
            any(not isinstance(w, str) or w not in KNOWN_WARNINGS for w in allowed_warnings)):
        raise SafetyError("EPUB warning allowance contains an unreviewed diagnostic")
    if type(trim_image_only_cover) is not bool or print_css not in ("", PRINT_CSS):
        raise SafetyError("EPUB cover or print-CSS policy differs from a supported fixed policy")
    if illustration_policy not in ("", BOOKDASH_POLICY):
        raise SafetyError("EPUB illustration policy differs from a supported fixed policy")


def preflight(recipe: dict | None = None):
    if recipe is not None:
        validate_recipe(recipe)
    try:
        module = importlib.import_module("pymupdf")
    except ImportError as error:
        raise SafetyError(f"EPUB PDF generation requires PyMuPDF=={PYMUPDF_VERSION}; install with pip install -e '.[pdf]'") from error
    if module.VersionBind != PYMUPDF_VERSION or module.version[1] != PYMUPDF_VERSION:
        raise SafetyError(f"EPUB PDF generation requires exact PyMuPDF/MuPDF {PYMUPDF_VERSION}")
    return module


def _member_name(name: str) -> str:
    if (not name or len(name) > 1024 or "\\" in name or ":" in name or "\x00" in name
            or name.startswith("/") or any(ord(char) < 32 for char in name)
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))):
        raise SafetyError(f"Unsafe EPUB archive path: {name!r}")
    return name.rstrip("/")


def _resource(reference: str, base: str, members: set[str]) -> str:
    value = unquote(reference.strip())
    url = urlsplit(value)
    if (url.scheme or url.netloc or url.query or "\\" in value or "\x00" in value
            or url.path.startswith("/")):
        raise SafetyError(f"External or unsafe EPUB resource: {reference[:180]}")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), url.path)) if url.path else base
    _member_name(path)
    if path not in members:
        raise SafetyError(f"Missing EPUB resource: {path}")
    return path


def _css(text: str, base: str, members: set[str]) -> None:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Decode CSS escapes before checking resource references (including escaped
    # url/@import tokens); no CSS evaluation or external resolver is provided.
    text = re.sub(r"\\(?:([0-9a-fA-F]{1,6})\s?|([^\n\r]))",
                  lambda m: chr(int(m[1], 16)) if m[1] else m[2], text)
    for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text, re.I | re.S):
        _resource(match[2], base, members)
    for match in re.finditer(r"@import\s+(['\"])(.*?)\1", text, re.I | re.S):
        _resource(match[2], base, members)


class _Markup(HTMLParser):
    def __init__(self, base, members):
        super().__init__(convert_charrefs=True)
        self.base, self.members, self.in_style = base, members, False
        self.styles = []
        self.in_body, self.body_text = False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "iframe", "frame", "object", "embed", "audio", "video", "base"}:
            raise SafetyError(f"Unsupported active or embedded EPUB content: {tag}")
        if "xml:base" in attrs or "srcset" in attrs:
            raise SafetyError("Unsupported EPUB resource base or srcset")
        for name, value in attrs.items():
            if (name == "src" or (name in {"href", "xlink:href"} and tag in {"image", "use"})
                    or (name == "href" and tag == "link" and "stylesheet" in (attrs.get("rel") or "").lower().split())):
                _resource(value or "", self.base, self.members)
            if name == "style":
                _css(value or "", self.base, self.members)
        if tag == "style":
            self.in_style = True
        if tag == "body":
            self.in_body = True

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)
        elif self.in_body:
            self.body_text.append(data)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "body":
            self.in_body = False

    def close(self):
        super().close()
        _css("\n".join(self.styles), self.base, self.members)


def _archive(source: Path) -> dict:
    if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
        raise SafetyError("EPUB exceeds the bounded source size")
    with zipfile.ZipFile(source) as archive:
        rows = archive.infolist()
        if len(rows) > MAX_MEMBERS or sum(row.file_size for row in rows) > MAX_EXPANDED_BYTES:
            raise SafetyError("EPUB archive exceeds member-count or expanded-byte bounds")
        members = set()
        markup_text = {}
        for row in rows:
            name = _member_name(row.filename)
            if (name in members or row.file_size > MAX_MEMBER_BYTES or row.flag_bits & 1
                    or stat.S_ISLNK(row.external_attr >> 16)):
                raise SafetyError("EPUB has duplicate, oversized, encrypted or symlink members")
            members.add(name)
        if "META-INF/encryption.xml" in members:
            raise SafetyError("Encrypted or obfuscated EPUB content is unsupported")

        def read(name):
            info = archive.getinfo(name)
            if info.file_size > MAX_MARKUP_BYTES:
                raise SafetyError(f"EPUB markup exceeds its size bound: {name}")
            data = archive.read(name)
            if b"<!ENTITY" in data.upper():
                raise SafetyError("EPUB XML entities are unsupported")
            return data

        container = ET.fromstring(read("META-INF/container.xml"))
        roots = container.findall(".//{*}rootfile")
        if len(roots) != 1:
            raise SafetyError("EPUB requires one unambiguous package document")
        package_path = _resource(roots[0].get("full-path", ""), "container.xml", members)
        package = ET.fromstring(read(package_path))
        manifest = {}
        for item in package.findall("./{*}manifest/{*}item"):
            identity = item.get("id")
            if not identity or identity in manifest:
                raise SafetyError("EPUB manifest has missing or duplicate IDs")
            manifest[identity] = {"path": _resource(item.get("href", ""), package_path, members),
                                  "media_type": item.get("media-type", "")}
        spine = package.findall("./{*}spine/{*}itemref")
        ids = [item.get("idref") for item in spine]
        if not ids or any(identity not in manifest for identity in ids):
            raise SafetyError("EPUB spine has missing or unknown chapters")
        for row in rows:
            if row.is_dir():
                continue
            suffix = PurePosixPath(row.filename).suffix.lower()
            if suffix in {".xhtml", ".html", ".htm", ".svg", ".css"}:
                data = read(row.filename)
                text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
                if suffix == ".css":
                    _css(text, row.filename, members)
                else:
                    parser = _Markup(row.filename, members)
                    parser.feed(text)
                    parser.close()
                    markup_text[row.filename] = _normalized("".join(parser.body_text))
        first = manifest[ids[0]]["path"]
        metadata = package.find("./{*}metadata")
        return {"spine_count": len(ids), "cover_first": bool(re.search(r"(?:^|[\W_])cover(?:$|[\W_])", ids[0], re.I)
                    or re.search(r"(?:^|[\W_])cover(?:$|[\W_])", PurePosixPath(first).stem, re.I)),
                "source_texts": [markup_text.get(manifest[identity]["path"], "") for identity in ids],
                "source_metadata_xml": ET.tostring(metadata, encoding="unicode") if metadata is not None else "",
                "declared_images": sum(item["media_type"].startswith("image/") for item in manifest.values())}


def _bookdash_pages(source: Path) -> tuple[bytes, int]:
    """Group existing illustrated paragraphs in RAM; never rewrite the source ZIP."""
    ET.register_namespace("", "http://www.w3.org/1999/xhtml")
    stream = io.BytesIO()
    groups, changed = 0, 0
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(stream, "w") as output:
        for info in original.infolist():
            payload = original.read(info)
            if info.filename.lower().endswith((".html", ".xhtml")):
                tree = ET.fromstring(payload)
                body = tree.find(".//{*}body")
                if body is not None and "chapter" in body.get("class", "").split():
                    wrappers = [node for node in body.iter() if node.get("id") == "wrapper"]
                    if len(wrappers) != 1:
                        raise SafetyError("Book Dash page policy requires one story wrapper")
                    wrapper = wrappers[0]
                    children = list(wrapper)
                    credits = [node for node in children if "copyright-text" in node.get("class", "").split()]
                    if len(credits) != 1 or children[-1] is not credits[0]:
                        raise SafetyError("Book Dash page policy requires a final original credits block")
                    text = "".join(wrapper.itertext())
                    images = [node.attrib.copy() for node in wrapper.iter() if node.tag.endswith("}img")]
                    wrapper[:] = []
                    group, has_image = None, False
                    for child in children:
                        copyright = child is credits[0]
                        pictures = child.findall(".//{*}img")
                        story_image = bool(pictures) and not copyright
                        if story_image and (not child.tag.endswith("}p") or len(pictures) != 1):
                            raise SafetyError("Book Dash page policy requires one illustration per paragraph")
                        if (story_image and has_image) or copyright:
                            if group is None or not has_image:
                                raise SafetyError("Book Dash story group is missing its illustration")
                            wrapper.append(group)
                            groups += 1
                            group, has_image = None, False
                        if copyright:
                            wrapper.append(child)
                            continue
                        if group is None:
                            group = ET.Element("{http://www.w3.org/1999/xhtml}div", {"class": "owl-print-spread"})
                        group.append(child)
                        has_image |= story_image
                    if ("".join(wrapper.itertext()) != text or
                            [node.attrib for node in wrapper.iter() if node.tag.endswith("}img")] != images):
                        raise SafetyError("Book Dash pagination changed original text or image references")
                    payload = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
                    changed += 1
            output.writestr(info, payload)
    if changed != 1 or not 1 <= groups <= 32 or stream.tell() > MAX_SOURCE_BYTES:
        raise SafetyError("Book Dash page policy requires one bounded illustrated chapter")
    return stream.getvalue(), groups


def _warnings(module, allowed):
    messages = [line.strip() for line in module.TOOLS.mupdf_warnings(reset=True).splitlines() if line.strip()]
    unexpected = [message for message in messages if message not in allowed]
    if unexpected:
        raise SafetyError("MuPDF could not completely render EPUB: " + "; ".join(unexpected)[:1000])
    return messages


def _page_evidence(module, page):
    text = page.get_text("dict", clip=module.INFINITE_RECT())
    strings = []
    for block in text["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    bounds = module.Rect(span["bbox"])
                    if not (page.rect + (-2, -2, 2, 2)).contains(bounds):
                        raise SafetyError("EPUB/PDF text extends outside the page; review print CSS instead of accepting clipped content")
                strings.append(span["text"])
    normalized = _normalized("".join(strings))
    images = page.get_image_info(hashes=True)
    for image in images:
        bounds = module.Rect(image["bbox"])
        if bounds.is_empty or bounds.is_infinite or not (page.rect + (-2, -2, 2, 2)).contains(bounds):
            raise SafetyError("EPUB/PDF image extends outside the page; review layout instead of accepting clipped illustrations")
    return {"text_sha256": hashlib.sha256(normalized.encode()).hexdigest(), "text_characters": len(normalized), "text": normalized,
            "images": Counter((row["width"], row["height"], row["digest"].hex()) for row in images)}, images


def _normalized(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text)
                   if not char.isspace() and unicodedata.category(char) != "Cf")


def _source_text_coverage(source_text, rendered_text):
    # Generated bullets/page labels may add characters; every source character
    # must still appear in order. This also catches CSS-hidden source text.
    offset = 0
    for char in source_text:
        offset = rendered_text.find(char, offset)
        if offset < 0:
            return False
        offset += 1
    return True


def _transparent_images_preserved(module, source_page, pdf_page):
    """Compare split PDF soft masks in the same premultiplied space as EPUB PNGs."""
    def blocks(page):
        return [block for block in page.get_text("dict", clip=module.INFINITE_RECT())["blocks"]
                if block["type"] == 1]

    def pixmap(block):
        image = module.Pixmap(block["image"])
        if block.get("mask"):
            if image.alpha:
                raise SafetyError("Ambiguous EPUB/PDF image transparency")
            image = module.Pixmap(image, module.Pixmap(block["mask"]))
        return image

    source, output = blocks(source_page), blocks(pdf_page)
    if len(source) != len(output):
        raise SafetyError("EPUB conversion changed displayed image count")
    normalized = 0
    for original, converted in zip(source, output):
        if (any(original[key] != converted[key] for key in ("width", "height"))
                or any(abs(a - b) > 0.001 for a, b in zip(original["bbox"], converted["bbox"]))
                or any(abs(a - b) > 0.001 for a, b in zip(original["transform"], converted["transform"]))):
            raise SafetyError("EPUB conversion changed image dimensions or placement")
        first, second = pixmap(original), pixmap(converted)
        if (first.width, first.height, first.n, first.alpha) != (second.width, second.height, second.n, second.alpha):
            raise SafetyError("EPUB conversion changed image channels or transparency")
        one, two = first.samples, second.samples
        if one == two:
            continue
        # PDF stores RGB and alpha independently; reconstituting the premultiplied
        # pixels can round a colour channel by one. Alpha itself must be exact.
        if (not first.alpha or one[first.n - 1::first.n] != two[second.n - 1::second.n]
                or any(abs(a - b) > 1 for a, b in zip(one, two))):
            raise SafetyError("EPUB conversion changed image pixels")
        normalized += 1
    return normalized


def convert(source: Path, destination: Path, *, metadata: dict | None = None,
            layout: dict | None = None, allowed_warnings=(), trim_image_only_cover: bool = True,
            print_css: str = "", illustration_policy: str = "") -> dict:
    """Convert in memory and atomically publish only after text/image coverage passes."""
    layout = LAYOUT.copy() if layout is None else layout
    _options(layout, allowed_warnings, trim_image_only_cover, print_css, illustration_policy)
    module = preflight()
    source, destination = Path(source), Path(destination)
    reject_symlinks(source)
    reject_symlinks(destination)
    if source.resolve() == destination.resolve():
        raise SafetyError("EPUB source cannot be overwritten by its generated PDF")
    archive = _archive(source)
    signature = (source.stat().st_size, source.stat().st_mtime_ns)
    with _RENDER_LOCK:
        module.TOOLS.mupdf_warnings(reset=True)
        try:
            prepared, story_groups = None, 0
            if illustration_policy:
                if archive["spine_count"] != 2 or not archive["cover_first"]:
                    raise SafetyError("Book Dash page policy requires an original cover and story spine")
                prepared, story_groups = _bookdash_pages(source)
            with (module.open(stream=prepared, filetype="epub") if prepared else module.open(source)) as document:
                if print_css:
                    document.apply_css(print_css, append=True)
                if illustration_policy:
                    document.apply_css(BOOKDASH_CSS, append=True)
                document.layout(**layout)
                if document.chapter_count != archive["spine_count"]:
                    raise SafetyError("MuPDF chapter count differs from the complete EPUB spine")
                chapters = [document.chapter_page_count(i) for i in range(document.chapter_count)]
                if any(count < 1 for count in chapters) or not 0 < sum(chapters) <= MAX_PAGES:
                    raise SafetyError("EPUB chapter/page coverage is empty or exceeds its bound")
                before, cover_images = [], []
                for page in document:
                    evidence, images = _page_evidence(module, page)
                    before.append(evidence)
                    if page.number == 0:
                        cover_images = images
                if illustration_policy and sum(sum(row["images"].values()) for row in before) != archive["declared_images"]:
                    raise SafetyError("Book Dash pagination must display every declared illustration")
                start = 0
                for number, count in enumerate(chapters):
                    chapter = before[start:start + count]
                    if not _source_text_coverage(archive["source_texts"][number],
                                                 "".join(row["text"] for row in chapter)):
                        raise SafetyError(f"EPUB source text is missing from rendered chapter {number + 1}")
                    if (not any(row["text_characters"] or row["images"] for row in chapter)
                            and not any(document[page].get_drawings() for page in range(start, start + count))):
                        raise SafetyError(f"EPUB chapter {number + 1} has no visible text, images or vector content")
                    start += count
                warnings = _warnings(module, allowed_warnings)
                toc, source_metadata = document.get_toc(), document.metadata
                normalized_images = 0
                with module.open("pdf", document.convert_to_pdf()) as pdf:
                    if len(pdf) != len(before):
                        raise SafetyError("EPUB conversion lost pages")
                    for number, page in enumerate(pdf):
                        after, _ = _page_evidence(module, page)
                        if after != before[number]:
                            if any(after[key] != before[number][key] for key in ("text", "text_sha256", "text_characters")):
                                raise SafetyError(f"EPUB conversion lost text on page {number + 1}")
                            normalized_images += _transparent_images_preserved(module, document[number], page)
                    keys = ("title", "author", "subject", "keywords", "creator", "producer")
                    kept = {key: source_metadata.get(key) or "" for key in keys}
                    kept["producer"] = f"OWL EPUB-to-PDF; PyMuPDF {PYMUPDF_VERSION}"
                    kept["subject"] = "\n".join(part for part in (kept["subject"], PDF_PROVENANCE) if part)
                    if metadata is not None:
                        if not isinstance(metadata, dict) or set(metadata) - set(keys) or any(not isinstance(v, str) for v in metadata.values()):
                            raise SafetyError("Unsupported EPUB PDF metadata override")
                        kept.update(metadata)
                    kept.update(creationDate="", modDate="")
                    pdf.set_metadata(kept)
                    pdf.set_toc(toc)
                    pdf.xref_set_key(pdf.pdf_catalog(), "OWLSourceEPUBMetadata", module.get_pdf_str(archive["source_metadata_xml"]))
                    pdf.xref_set_key(-1, "ID", "[<00000000000000000000000000000000><00000000000000000000000000000000>]")
                    trimmed = False
                    if (trim_image_only_cover and archive["cover_first"] and chapters[0] == 1
                            and not before[0]["text_characters"] and len(cover_images) == 1):
                        bounds = module.Rect(cover_images[0]["bbox"])
                        if not bounds.is_empty and pdf[0].rect.contains(bounds):
                            pdf[0].set_cropbox(bounds)
                            trimmed = True
                    data = pdf.tobytes(garbage=4, deflate=True, no_new_id=True, reproducible=True)
                    warnings.extend(_warnings(module, allowed_warnings))
                    if len(data) > MAX_OUTPUT_BYTES:
                        raise SafetyError("Generated EPUB PDF exceeds its bounded output size")
                    if signature != (source.stat().st_size, source.stat().st_mtime_ns):
                        raise SafetyError("EPUB changed during conversion")
                    atomic_write(destination, data)
        finally:
            module.TOOLS.mupdf_warnings(reset=True)
    return {"spine_count": archive["spine_count"], "chapter_pages": chapters, "pages": len(before),
            "illustration_policy": illustration_policy, "story_groups": story_groups,
            "text_characters": sum(row["text_characters"] for row in before),
            "displayed_images": sum(sum(row["images"].values()) for row in before),
            "transparency_normalized_images": normalized_images,
            "declared_images": archive["declared_images"], "toc_entries": len(toc), "cover_trimmed": trimmed,
            "warnings": sorted(set(warnings)), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def render(recipe: dict, sources: dict[str, Path], assets: dict[str, dict], output_dir: Path) -> dict[str, Path]:
    validate_recipe(recipe, assets)
    preflight(recipe)
    if set(sources) != set(recipe["source_asset_ids"]):
        raise SafetyError("EPUB renderer source selection differs from the recipe")
    selection, result = recipe["selection"], {}
    for output_id, source_id in sorted(selection["outputs"].items()):
        source = assets[source_id]
        if not verified(sources[source_id], source["size_bytes"], source["sha256"]):
            raise SafetyError(f"EPUB source hash/size mismatch: {source_id}")
        destination = safe_path(output_dir, assets[output_id]["destination"])
        convert(sources[source_id], destination, layout=selection["layout"],
                allowed_warnings=selection.get("allowed_warnings", []),
                trim_image_only_cover=selection.get("trim_image_only_cover", True),
                print_css=selection.get("print_css", ""),
                illustration_policy=selection.get("illustration_policy", ""))
        result[output_id] = destination
    return result
