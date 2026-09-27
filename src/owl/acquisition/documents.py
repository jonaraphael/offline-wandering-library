"""Deterministic ordinary HTML from already verified publisher inputs.

This module has no network access. A recipe selects complete, counted elements,
declares every illustration and binds every input to its catalog hash. It is not
a general website crawler or a renderer for executable/interactive content.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from urllib.parse import urldefrag, urljoin, urlsplit

from ..safety import atomic_write, reject_symlinks, validate_relative


class DocumentError(ValueError):
    pass


MAX_SOURCE_BYTES = 16 * 1024 * 1024
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
DROP = set("script style iframe object embed button form input select textarea nav".split())
TAGS = set("a abbr address article aside b bdi bdo blockquote br caption cite code col colgroup dd del "
           "details dfn div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd "
           "li main mark ol p picture pre q rp rt ruby s samp section small source span strong sub "
           "summary sup table tbody td th thead time tr u ul var wbr center font".split())
ATTRS = set("id name title lang dir colspan rowspan scope headers alt start reversed value datetime open".split())
CSS = ("body{box-sizing:border-box;font:18px/1.6 system-ui,sans-serif;max-width:960px;width:100%;"
       "margin:2rem auto;padding:0 1rem;overflow-wrap:anywhere}"
       "img{max-width:100%;height:auto}.table-scroll{overflow-x:auto;max-width:100%;margin:1rem 0}"
       "table{border-collapse:collapse}"
       "td,th{padding:.45rem;border:1px solid #777;vertical-align:top;overflow-wrap:normal;word-break:normal}"
       "pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}"
       ".online:after{content:' [online]';font-size:.8em}.entry{margin-top:2rem;border-top:1px solid #aaa}"
       ".source{font-size:.8rem}.notice{padding:1rem;background:#eee;color:#222}")
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)


class _Tree(HTMLParser):
    def __init__(self, data: str):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(data)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise DocumentError("Duplicate HTML attribute")
        node = Node(tag, {k: v or "" for k, v in attributes.items()})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _walk(node):
    if isinstance(node, Node):
        yield node
        for child in node.children:
            yield from _walk(child)


def _removed(node):
    return node.tag in DROP or "print-button" in node.attrs.get("class", "").split()


def _text(node):
    if isinstance(node, str):
        return node
    if _removed(node):
        return ""
    return "".join(_text(child) for child in node.children)


def _selected(root, section):
    tag = section.get("tag")
    if not isinstance(tag, str) or not tag or tag in DROP:
        raise DocumentError("Each section requires a supported tag")
    attr, value = section.get("attribute"), section.get("value")
    if (attr is None) != (value is None):
        raise DocumentError("Section attribute and value must be specified together")
    matches = []
    for node in _walk(root):
        if node.tag != tag:
            continue
        if attr and (value not in node.attrs.get(attr, "").split() if attr == "class" and not section.get("class_exact")
                     else node.attrs.get(attr) != value):
            continue
        matches.append(node)
    count = section.get("expected_count")
    if type(count) is not int or count < 1 or len(matches) != count:
        raise DocumentError(f"Changed section structure: expected {count} {tag}, found {len(matches)}")
    if "match_index" in section:
        index = section["match_index"]
        if type(index) is not int or not 0 <= index < len(matches):
            raise DocumentError("Selected section index is outside the frozen match count")
        matches = [matches[index]]
    expected = section.get("expected_text_sha256")
    text = re.sub(r"\s+", " ", "".join(_text(node) for node in matches)).strip()
    if not text:
        raise DocumentError("Empty selected section")
    if expected and sha256(text.encode()).hexdigest() != expected:
        raise DocumentError("Selected text changed")
    return matches


def _image(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise DocumentError("Unsupported or invalid illustration; do not inline executable SVG")
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def _read(identity, sources, assets):
    if identity not in sources or identity not in assets:
        raise DocumentError(f"Missing declared source: {identity}")
    path, asset = Path(sources[identity]), assets[identity]
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise DocumentError(f"Source exceeds ordinary-document limit: {identity}")
    data = path.read_bytes()
    if len(data) != asset.get("size_bytes") or sha256(data).hexdigest() != asset.get("sha256"):
        raise DocumentError(f"Source differs from its pin: {identity}")
    return data


def _local_link(current, target, assets):
    if target not in assets:
        raise DocumentError(f"Unknown link target: {target}")
    start, end = assets[current]["destination"], assets[target]["destination"]
    validate_relative(start)
    validate_relative(end)
    return posixpath.relpath(end, posixpath.dirname(start) or ".")


def _serialize(node, *, base_url, images, links, ids, anchors, output_id, assets):
    if isinstance(node, str):
        return escape(node)
    if _removed(node):
        return ""
    if node.tag in {"head", "meta", "link", "title", "base"}:
        return ""
    if node.tag not in TAGS | {"body", "html", "root"}:
        raise DocumentError(f"Unsupported selected content: <{node.tag}>")
    children = "".join(_serialize(child, base_url=base_url, images=images, links=links,
                                  ids=ids, anchors=anchors, output_id=output_id, assets=assets) for child in node.children)
    if node.tag in {"html", "body", "root", "font", "picture", "source"}:
        # The img fallback is the declared preserved illustration. Responsive
        # source variants are not separate reading content.
        return children
    attrs = {key: value for key, value in node.attrs.items() if key in ATTRS}
    if "id" in attrs:
        attrs["id"] = ids[attrs["id"]]
    if node.tag == "a" and attrs.get("name"):
        attrs["name"] = ids[attrs["name"]]
        attrs.setdefault("id", attrs["name"])
    elif "name" in attrs:
        del attrs["name"]
    if node.tag == "img":
        source = node.attrs.get("src")
        if not source:
            raise DocumentError("Illustration has no ordinary src fallback")
        url = urljoin(base_url, source)
        if url not in images:
            raise DocumentError(f"Undeclared illustration dependency: {url}")
        attrs["src"] = images[url]
    if node.tag == "a" and node.attrs.get("href"):
        href = node.attrs["href"]
        absolute, fragment = urldefrag(urljoin(base_url, href))
        if href.startswith("#"):
            if fragment in ids:
                attrs["href"] = "#" + ids[fragment]
            elif absolute + "#" + fragment in anchors:
                target, name = anchors[absolute + "#" + fragment]
                attrs["href"] = ("" if target == output_id else _local_link(output_id, target, assets)) + "#" + name
            else:
                raise DocumentError(f"Missing selected fragment: {href}")
        elif absolute + ("#" + fragment if fragment else "") in anchors:
            target, name = anchors[absolute + ("#" + fragment if fragment else "")]
            attrs["href"] = ("" if target == output_id else _local_link(output_id, target, assets)) + "#" + name
        elif absolute in links:
            if fragment and links[absolute] in {target for target, _ in anchors.values()}:
                raise DocumentError(f"Missing cross-document selected fragment: {href}")
            attrs["href"] = _local_link(output_id, links[absolute], assets)
            if fragment:
                # IDs in transformed documents are namespaced. Only explicitly
                # frozen link fragments can safely cross outputs.
                attrs["href"] += "#" + fragment
        elif urlsplit(absolute).scheme in {"https", "http", "mailto"}:
            attrs.update(href=absolute + ("#" + fragment if fragment else ""),
                         **{"class": "online", "title": "Internet required"})
        else:
            raise DocumentError(f"Unsupported link: {href}")
    attributes = "".join(f' {key}="{escape(str(value), quote=True)}"' for key, value in sorted(attrs.items()))
    result = "<" + node.tag + attributes + ">" + ("" if node.tag in VOID else children + "</" + node.tag + ">")
    if node.tag == "table":
        result = '<div class="table-scroll" tabindex="0" role="region" aria-label="Scrollable table">' + result + "</div>"
    return result


def render(recipe: dict, sources: dict[str, Path], assets: dict[str, dict], output_dir: Path, *, output_writer=None) -> dict[str, Path]:
    """Render declared complete sections; return local outputs without downloads."""
    if recipe.get("adapter") not in {"html_snapshot", "manual_html"}:
        raise DocumentError("Unsupported ordinary-document adapter")
    selection = recipe.get("selection", {})
    outputs = selection.get("outputs", [])
    if not outputs or {row.get("asset_id") for row in outputs} != set(recipe.get("output_asset_ids", [])):
        raise DocumentError("Outputs differ from the recipe declaration")
    if len(outputs) != len(recipe["output_asset_ids"]):
        raise DocumentError("Duplicate output declaration")
    inputs = {identity: _read(identity, sources, assets) for identity in recipe.get("source_asset_ids", [])}
    dependencies = selection.get("dependencies", {})
    if any(identity not in inputs for identity in dependencies.values()):
        raise DocumentError("Illustration is not a declared recipe source")
    images = {url: _image(inputs[identity]) for url, identity in dependencies.items()}
    links = selection.get("links", {})
    result, prepared, selections, anchors = {}, {}, {}, {}
    for output in outputs:
        identity = output["asset_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identity) or identity not in assets:
            raise DocumentError("Invalid output asset")
        selections[identity] = []
        for number, section in enumerate(output.get("sections", [])):
            source_id = section.get("source_asset_id")
            if source_id not in inputs:
                raise DocumentError("Section is not a declared recipe source")
            try:
                tree = _Tree(inputs[source_id].decode("utf-8"))
            except UnicodeDecodeError as error:
                raise DocumentError("HTML input must be UTF-8") from error
            selected = _selected(tree.root, section)
            ids = {}
            for node in (n for item in selected for n in _walk(item)):
                names = {node.attrs.get("id")}
                if node.tag == "a":
                    names.add(node.attrs.get("name"))
                for old in names - {None, ""}:
                    if old in ids:
                        raise DocumentError("Duplicate selected HTML id")
                    ids[old] = f"s{number}-{old}"
            source_url = urldefrag(assets[source_id]["source_url"])[0]
            for old, name in ids.items():
                address = source_url + "#" + old
                if address in anchors:
                    raise DocumentError("Ambiguous selected source fragment")
                anchors[address] = (identity, name)
            anchors.setdefault(source_url, (identity, f"section-{number}"))
            selections[identity].append((number, section, source_id, selected, ids))
    for output in outputs:
        identity = output["asset_id"]
        title = output.get("title", assets[identity].get("title", identity))
        sections = []
        for number, section, source_id, selected, ids in selections[identity]:
            rendered = "".join(_serialize(node, base_url=assets[source_id]["source_url"], images=images,
                                          links=links, ids=ids, anchors=anchors, output_id=identity, assets=assets)
                               for node in selected)
            if section.get("heading"):
                rendered = "<h2>" + escape(section["heading"]) + "</h2>" + rendered
            if section.get("credit"):
                rendered = "<p>" + escape(section["credit"]) + "</p>" + rendered
            source_url = assets[source_id]["source_url"]
            sections.append(f'<section class="entry" id="section-{number}">' + rendered + '<p class="source">Publisher source: '
                            '<a class="online" href="' + escape(source_url, quote=True) + '">'
                            + escape(source_url) + "</a></p></section>")
        if not sections:
            raise DocumentError("Output has no selected sections")
        intro = "<p class=\"notice\">" + escape(output["intro"]) + "</p>" if output.get("intro") else ""
        document = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<meta http-equiv="Content-Security-Policy" content="' + escape(CSP, quote=True)
                    + '"><title>' + escape(title) + "</title><style>" + CSS + "</style></head><body><h1>"
                    + escape(title) + "</h1>" + intro + "<main>" + "".join(sections) + "</main></body></html>\n")
        prepared[identity] = document.encode()
    # Fail before producing any output if a dependency/selector is invalid.
    output_dir = Path(output_dir)
    reject_symlinks(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for identity, data in prepared.items():
        path = output_dir / (identity + ".html")
        reject_symlinks(path)
        (output_writer or atomic_write)(path, data)
        result[identity] = path
    return result
