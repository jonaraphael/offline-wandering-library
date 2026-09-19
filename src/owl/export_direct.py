"""Bounded, resumable, offline export of static ZIM documents and their resources."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml

from .catalog import load_catalog
from .runtime import file_lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file


class ExportError(ValueError):
    pass


VERSION = 1
BLOCK = 1024 * 1024
RESERVE = 16 * BLOCK
MAX_STATE = 64 * BLOCK
DOCUMENTS = {"text/html": "html", "application/xhtml+xml": "html", "text/plain": "txt",
             "text/markdown": "md", "application/pdf": "pdf"}
RESOURCES = {"text/css": "css", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
             "image/webp": "webp", "image/avif": "avif", "image/svg+xml": "svg", "image/x-icon": "ico",
             "image/vnd.microsoft.icon": "ico", "font/woff": "woff", "font/woff2": "woff2",
             "font/ttf": "ttf", "font/otf": "otf", "application/font-woff": "woff",
             "application/vnd.ms-fontobject": "eot", "application/x-font-ttf": "ttf"}
CSP = ("default-src 'none'; script-src 'none'; connect-src 'none'; object-src 'none'; "
       "frame-src 'none'; base-uri 'none'; form-action 'none'; "
       "img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'")
TAGS = set("a abbr address article aside b bdi bdo blockquote br caption center cite code col colgroup "
           "dd del details dfn div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hgroup hr "
           "i img ins kbd li link main mark nav noscript ol p picture pre q rp rt ruby s samp section "
           "small source span strong style sub summary sup table tbody td th thead time tr u ul var wbr "
           "svg g path rect circle ellipse line polyline polygon text tspan defs symbol use image "
           "lineargradient radialgradient stop clippath mask pattern title desc".split())
VOID = {"br", "hr", "img", "source", "wbr", "col", "link"}
DROP_CONTENT = {"script", "iframe", "object", "embed", "applet", "template", "foreignobject"}
ATTRS = set("id class title lang dir role aria-label aria-describedby aria-hidden colspan rowspan scope "
            "headers alt width height loading decoding media rel type sizes datetime open start reversed "
            "value align valign border cellpadding cellspacing viewbox xmlns xmlns:xlink d x y x1 y1 x2 y2 cx cy "
            "r rx ry points fill fill-rule stroke stroke-width stroke-linecap stroke-linejoin opacity "
            "transform preserveaspectratio offset stop-color stop-opacity gradientunits gradienttransform "
            "patternunits patterntransform clip-path mask font-size text-anchor".split())


def _json(path: Path, value) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > MAX_STATE:
        raise ExportError("Export metadata exceeds 64 MiB; split this selection into smaller exports")
    atomic_write(path, data)


def _path(root: Path, relative: str) -> Path:
    result = safe_path(root, relative)
    current = root
    for part in relative.split("/"):
        if current.exists():
            if not current.is_dir():
                raise SafetyError(f"Not a directory: {current}")
            if any(p.name != part and p.name.casefold() == part.casefold() for p in current.iterdir()):
                raise SafetyError(f"Case-conflicting export path: {current / part}")
        current /= part
    if result.exists():
        info = result.stat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or info.st_nlink > 1 and result.is_file():
            raise SafetyError(f"Unsafe or hardlinked export file: {result}")
    return result


def _archive_path(value: str) -> str:
    # Archive paths are identifiers, never host filesystem paths. Hash them for
    # output names, but still reject traversal/control syntax rather than accept
    # a malformed archive that happens to hash to a safe destination.
    if not isinstance(value, str) or not value or len(value) > 4096 or value.startswith("/"):
        raise ExportError(f"Invalid archive path: {value!r}")
    decoded = unquote(value)
    if "\\" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
        raise ExportError(f"Unsafe archive path: {value!r}")
    if any(p in {".", ".."} for p in decoded.split("/")):
        raise ExportError(f"Traversal in archive path: {value!r}")
    return value


def _source_identity(path: Path):
    reject_symlinks(path)
    s = path.stat()
    if not stat.S_ISREG(s.st_mode):
        raise SafetyError(f"Source is not a regular file: {path}")
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns


class _Exporter:
    def __init__(self, archive, source, target, private, asset, job, state, progress):
        self.archive, self.source, self.target, self.private = archive, source, target, private
        self.asset, self.job, self.state, self.progress = asset, job, state, progress
        self.identity = _source_identity(source)
        self.selected = set(job["entries"])
        self.warnings = set(state.get("warnings", []))
        self.current = ""

    def check_source(self):
        if _source_identity(self.source) != self.identity:
            raise ExportError("Source archive changed during export; no completed manifest was published")

    def save(self):
        self.check_source()
        self.state["warnings"] = sorted(self.warnings)
        _json(_path(self.target, self.private + "/state.json"), self.state)

    def warn(self, message):
        # Resource limits bound this further, but malformed pages can mention
        # millions of distinct absent URLs. Keep diagnostics bounded too.
        if len(self.warnings) < 500:
            self.warnings.add(message[:500])
        else:
            self.warnings.add("Additional export warnings omitted after 500 distinct messages")

    def entry(self, name):
        name = _archive_path(name)
        try:
            entry = self.archive.get_entry_by_path(name)
            seen = set()
            while entry.is_redirect:
                if entry.path in seen or len(seen) >= 32:
                    raise ExportError(f"Redirect cycle/depth limit: {name}")
                seen.add(entry.path)
                entry = entry.get_redirect_entry()
            _archive_path(entry.path)
            item = entry.get_item()
        except (KeyError, RuntimeError) as error:
            raise ExportError(f"Missing archive entry: {name}") from error
        mime = item.mimetype.split(";", 1)[0].strip().lower()
        if item.size > self.job["max_item_bytes"]:
            raise ExportError(f"Entry exceeds --max-item-bytes: {entry.path} ({item.size} bytes)")
        return entry, item, mime

    def enqueue(self, name, document=False):
        entry, item, mime = self.entry(name)
        if mime not in (DOCUMENTS if document else RESOURCES):
            raise ExportError(f"Unsupported {'document' if document else 'resource'} MIME {mime}: {name}")
        name = entry.path
        ext = (DOCUMENTS if document else RESOURCES)[mime]
        key = hashlib.sha256(name.encode()).hexdigest()
        relative = f"REFERENCE/DIRECT/{self.job['export_id']}/{key[:2]}/{key}.{ext}"
        if name not in self.state["files"]:
            if len(self.state["files"]) >= self.job["max_files"]:
                raise ExportError("Export exceeds --max-files; increase the limit or narrow selection")
            if _path(self.target, relative).exists():
                raise SafetyError(f"Refusing unrelated existing export destination: {relative}")
            self.state["files"][name] = {"destination": relative, "mime": mime,
                                          "title": entry.title or name, "document": document}
        return relative

    def resolve_url(self, current, value):
        if not value or value.startswith("#"):
            return None, value
        value = value.strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None, ""
        fragment = parsed.fragment
        if parsed.scheme or parsed.netloc:
            # Some Zimit archives use absolute source URLs as exact entry names.
            # Resolve only actual local entries; never fetch or guess a website.
            if parsed.scheme not in {"https", "http"}:
                return None, ""
            candidates = [urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")),
                          urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))]
        else:
            path = unquote(parsed.path)
            if "\\" in path or any(ord(c) < 32 for c in path):
                return None, ""
            if current.startswith(("https://", "http://")):
                from urllib.parse import urljoin
                candidates = [urljoin(current, path)]
            else:
                joined = path.lstrip("/") if path.startswith("/") else posixpath.join(posixpath.dirname(current), path)
                normalized = posixpath.normpath(joined)
                if normalized == ".." or normalized.startswith("../"):
                    return None, ""
                candidates = [normalized]
        for candidate in candidates:
            try:
                entry, _, _ = self.entry(candidate)
                return entry.path, fragment
            except ExportError as error:
                if "exceeds --max-item-bytes" in str(error):
                    raise
        return None, ""

    def link(self, current, value, resource=False):
        if value.startswith("#"):
            return "#" + quote(unquote(value[1:]), safe="")
        if resource and re.fullmatch(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]+", value):
            return value
        name, fragment = self.resolve_url(current, value)
        if name is None:
            # Ordinary source/license hyperlinks are not active resource loads.
            # Retaining them preserves attribution links while reading the page
            # itself remains entirely offline.
            if not resource:
                try:
                    parsed = urlsplit(value)
                    if parsed.scheme in {"https", "http"} and parsed.netloc:
                        return value
                except ValueError:
                    pass
            self.warn(f"Unavailable or external {'resource' if resource else 'link'} removed from {current}: {value}")
            return None
        if not resource and name not in self.selected:
            # Figure thumbnails commonly link to a larger local image. These
            # are supporting resources, not an implicit selection of every
            # linked article in the archive.
            _, _, mime = self.entry(name)
            if mime in RESOURCES:
                resource = True
            else:
                self.warn(f"Unselected article link retained as archive-only text: {name}")
                return None
        relative = self.enqueue(name, document=not resource)
        current_dest = self.state["files"][current]["destination"]
        href = quote(posixpath.relpath(relative, posixpath.dirname(current_dest)), safe="/")
        return href + ("#" + quote(unquote(fragment), safe="") if fragment else "")

    def css(self, current, text):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        # A deliberately narrow CSS URL grammar. Escaped CSS requires a proper
        # tokenizer; fail closed rather than miss a remote active dependency.
        if "\\" in text:
            self.warn(f"CSS containing escape syntax omitted: {current}")
            return "/* OWL: unsupported CSS escape syntax omitted. */"
        text = re.sub(r"(?:expression|behavior|-moz-binding)\s*:[^;}]*", "", text, flags=re.I)
        def url(match):
            value = match.group(1).strip().strip("\"'")
            href = self.link(current, value, resource=True)
            return 'url("' + (href or "") + '")'
        text = re.sub(r"url\(\s*([^)]*)\)", url, text, flags=re.I)
        def imported(match):
            href = self.link(current, match.group(2), resource=True)
            return '@import "' + (href or "") + '"'
        return re.sub(r"@import\s+([\"'])(.*?)\1", imported, text, flags=re.I)

    def render(self, name, item, mime):
        self.check_source()
        # python-libzim exposes one complete item, not a streaming item reader.
        # item.size was checked before access; cluster and item limits bound RAM.
        raw = bytes(item.content)
        if len(raw) != item.size:
            raise ExportError(f"Archive item size mismatch: {name}")
        if mime in {"text/html", "application/xhtml+xml", "image/svg+xml"}:
            parser = _HTML(self, name, svg=mime == "image/svg+xml")
            parser.feed(raw.decode("utf-8-sig", errors="strict"))
            parser.close()
            body = "".join(parser.output)
            if mime == "image/svg+xml":
                return body.encode()
            title = self.state["files"][name]["title"]
            note = (f'<aside role="note"><p><strong>Offline extract: {escape(title)}</strong></p>'
                    f'<p>{escape(self.asset.get("attribution", self.asset["title"]))}</p>'
                    f'<p>License: {escape(self.asset["license"])}. Source edition: {escape(self.asset["version"])}. '
                    f'Archive entry: <code>{escape(name)}</code>.</p>'
                    f'<p>Source page: {escape(self.asset.get("source_page") or self.asset["source_url"])}. '
                    f'Archive download: {escape(self.asset["source_url"])}.</p>'
                    '<p>OWL changed links and removed scripts, forms and external active resources. '
                    'Some links need the original archive; external source links need internet. '
                    'Original content notices are retained below.</p></aside>')
            return ('<!doctype html><html><head><meta charset="utf-8">'
                    f'<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    f'<title>{escape(title)}</title><style>body{{max-width:72rem;margin:auto;padding:1rem;'
                    'overflow-wrap:anywhere}img,svg{max-width:100%;height:auto}aside[role=note]{'
                    'display:block!important;border:1px solid;padding:1rem;margin-bottom:1rem}</style>'
                    f'</head><body>{note}{body}</body></html>').encode()
        if mime == "text/css":
            return self.css(name, raw.decode("utf-8-sig", errors="strict")).encode()
        return raw

    def write(self, name):
        record = self.state["files"][name]
        entry, item, mime = self.entry(name)
        path = _path(self.target, record["destination"])
        if path.exists() and record.get("sha256") and path.stat().st_size == record["size_bytes"] and sha256_file(path) == record["sha256"]:
            self.progress(f"REUSE {record['destination']}")
            record["complete"] = True
            return
        data = self.render(name, item, mime)
        checksum = hashlib.sha256(data).hexdigest()
        total = len(data) + sum(v.get("size_bytes", 0) for k, v in self.state["files"].items() if k != name)
        if total > self.job["max_bytes"]:
            raise ExportError("Export exceeds --max-bytes; increase the limit or narrow selection")
        record.update(size_bytes=len(data), sha256=checksum, complete=False)
        self.save()  # Intent and checksum precede promotion: crash-safe ownership.
        part = _path(self.target, self.private + "/parts/" + hashlib.sha256(name.encode()).hexdigest() + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        offset = 0
        if part.exists():
            with part.open("rb") as stream:
                while block := stream.read(BLOCK):
                    if block != data[offset:offset + len(block)]:
                        offset = 0
                        break
                    offset += len(block)
        if shutil.disk_usage(self.target).free < len(data) - offset + RESERVE:
            raise ExportError("Insufficient target disk space for export and 16 MiB working reserve")
        with part.open("r+b" if part.exists() else "w+b") as stream:
            if offset == 0:
                stream.truncate(0)
            stream.seek(offset)
            try:
                for start in range(offset, len(data), BLOCK):
                    self.check_source()
                    _path(self.target, self.private)
                    stream.write(data[start:start + BLOCK])
                    self.progress(f"WRITE {record['destination']} {min(start + BLOCK, len(data))}/{len(data)}")
            finally:
                stream.flush()
                os.fsync(stream.fileno())
        if part.stat().st_size != len(data) or sha256_file(part) != checksum:
            raise ExportError(f"Export readback checksum failed: {name}")
        self.check_source()
        path = _path(self.target, record["destination"])
        path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(_path(self.target, part.relative_to(self.target).as_posix()), path)
        record["complete"] = True
        self.save()


class _HTML(HTMLParser):
    def __init__(self, exporter, current, svg=False):
        super().__init__(convert_charrefs=False)
        self.exporter, self.current, self.svg = exporter, current, svg
        self.output = []
        self.skip = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_CONTENT:
                self.skip.append(tag)
            return
        if tag in DROP_CONTENT:
            if tag not in {"embed"}:
                self.skip.append(tag)
            self.exporter.warn(f"Active element removed from {self.current}: {tag}")
            return
        if tag not in TAGS:
            return
        attr = dict(attrs)
        if tag == "link" and attr.get("rel", "").lower() not in {"stylesheet", "icon"}:
            return
        out = []
        image_source = False
        for key, value in attrs:
            if value is None:
                if key == "open": out.append("open")
                continue
            if key == "style":
                value = self.exporter.css(self.current, value)
            elif key in {"src", "href", "xlink:href", "background"}:
                resource = tag != "a"
                original = value
                value = self.exporter.link(self.current, value, resource=resource)
                if value is None:
                    if tag == "a": out.append('title="Available only in the original archive or online: ' + escape(original, quote=True) + '"')
                    continue
                if tag == "a" and urlsplit(value).scheme in {"https", "http"}:
                    out.append('title="Original source link; requires internet"')
                    out.append('rel="noreferrer noopener"')
            elif key == "srcset":
                # Simple local candidates are common in Wikimedia pages. Data
                # URLs have a different comma grammar; preserve only a fallback
                # src in that exceptional case and report the limitation.
                if "data:" in value.lower():
                    self.exporter.warn(f"Data-URL srcset omitted; fallback src retained: {self.current}")
                    continue
                candidates = []
                for candidate in value.split(","):
                    match = re.fullmatch(r"\s*(\S+)(?:\s+(\d+(?:\.\d+)?[wx]))?\s*", candidate)
                    if not match:
                        self.exporter.warn(f"Malformed srcset candidate omitted: {self.current}")
                        continue
                    href = self.exporter.link(self.current, match.group(1), resource=True)
                    if href: candidates.append(href + (" " + match.group(2) if match.group(2) else ""))
                value = ", ".join(candidates)
                if not value: continue
            elif key not in ATTRS:
                continue
            if key in {"src", "srcset"} and value:
                image_source = True
            # SVG paint references can reference external resources; only local
            # fragment references are retained in paint/clip attributes.
            if key in {"fill", "stroke", "clip-path", "mask"} and "url(" in value.lower():
                if not re.fullmatch(r"url\(#[A-Za-z0-9_.:-]+\)", value): continue
            key = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio",
                   "gradientunits": "gradientUnits", "gradienttransform": "gradientTransform",
                   "patternunits": "patternUnits", "patterntransform": "patternTransform"}.get(key, key)
            out.append(f'{key}="{escape(value, quote=True)}"')
        if tag == "img" and not image_source:
            # Removing a remote tracker must not leave a broken/empty image
            # box. Preserve meaningful alternative text when an illustration
            # itself was unavailable, so that omission remains visible.
            if attr.get("alt"):
                self.output.append('<span role="note">[Offline image unavailable: ' + escape(attr["alt"]) + ']</span>')
            return
        output_tag = {"lineargradient": "linearGradient", "radialgradient": "radialGradient",
                      "clippath": "clipPath"}.get(tag, tag)
        self.output.append("<" + output_tag + (" " + " ".join(out) if out else "") + ">")
        if tag == "style": self.in_style = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]: self.skip.pop()
            return
        if tag in TAGS and tag not in VOID:
            output_tag = {"lineargradient": "linearGradient", "radialgradient": "radialGradient",
                          "clippath": "clipPath"}.get(tag, tag)
            self.output.append(f"</{output_tag}>")
        if tag == "style": self.in_style = False

    def handle_data(self, data):
        if not self.skip:
            self.output.append(self.exporter.css(self.current, data) if self.in_style else escape(data))

    def handle_entityref(self, name):
        if not self.skip: self.output.append("&" + name + ";")

    def handle_charref(self, name):
        if not self.skip: self.output.append("&#" + name + ";")


def export_zim(source: Path, target: Path, *, source_asset: dict, entries=(), all_articles=False,
               max_bytes: int, max_files: int, max_item_bytes: int = 16 * BLOCK,
               export_id: str | None = None, progress=print) -> dict:
    """Export in place; publish an import catalog only after all outputs verify."""
    from .build import _owned_directory, _root
    try:
        from libzim.reader import Archive, set_cluster_cache_max_size
    except ImportError as error:
        raise ExportError("Install OWL's optional [zim] extra to export local archives") from error
    if source_asset.get("format") != "zim" or not re.fullmatch(r"[0-9a-f]{64}", source_asset.get("sha256") or ""):
        raise ExportError("A local ZIM with a pinned source SHA-256 is required")
    for value in (max_bytes, max_files, max_item_bytes):
        if type(value) is not int or value <= 0:
            raise ExportError("Byte, file and item limits must be positive integers")
    if max_files > 100000 or max_item_bytes > 64 * BLOCK:
        raise ExportError("Hard safety ceilings: 100,000 files and 64 MiB per item")
    entries = list(entries)
    if all_articles == bool(entries):
        raise ExportError("Choose explicit entries or --all, exclusively")
    export_id = export_id or source_asset["id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,49}", export_id):
        raise ExportError("Export ID must be 1-50 lowercase ASCII letters, digits, _ or -")
    from .layout import content_root
    source, target = _root(source), content_root(_root(target))
    if not source.is_file(): raise ExportError(f"Source archive missing: {source}")
    private = ".owl/exports/" + export_id
    with ExitStack() as contexts:
        contexts.enter_context(guard_directory(source.parent))
        # Hold both roots' standard build locks, once each, in deterministic
        # order. The ZIM may be in a partly built library; its own pin is enough.
        target.mkdir(parents=True, exist_ok=True)
        contexts.enter_context(guard_directory(target))
        roots = {target}
        for parent in source.parents:
            marker = safe_path(parent, ".owl/owner.json")
            if marker.exists():
                roots.add(parent)
                break
        for root in sorted(roots, key=str):
            _owned_directory(safe_path(root, ".owl"))
            contexts.enter_context(file_lock(safe_path(root, ".owl/build.lock")))
        identity = _source_identity(source)
        if identity[2] != source_asset.get("size_bytes") or sha256_file(source) != source_asset["sha256"]:
            raise ExportError("Source archive size/SHA-256 mismatch")
        if _source_identity(source) != identity:
            raise ExportError("Source archive changed during verification")
        folder = _path(target, private)
        marker = _path(target, private + "/owner.json")
        owner = {"owner": "offline-wandering-library-direct-export", "schema_version": VERSION}
        if folder.exists():
            if not marker.is_file() or marker.stat().st_size > 4096 or json.loads(marker.read_text(encoding="utf-8")) != owner:
                raise SafetyError(f"Export metadata folder is not owned by OWL: {folder}")
        else:
            folder.mkdir(parents=True)
            _json(marker, owner)
        contexts.enter_context(file_lock(_path(target, private + "/export.lock")))
        set_cluster_cache_max_size(2)
        archive = Archive(source)
        archive.dirent_cache_max_size = 4096
        if all_articles:
            entries = []
            for index in range(archive.all_entry_count):
                entry = archive._get_entry_by_id(index)
                if entry.is_redirect: continue
                # all_entry_count includes metadata such as Counter in a
                # separate namespace. Only public, addressable content belongs
                # in a directly readable collection.
                if not archive.has_entry_by_path(entry.path): continue
                entry = archive.get_entry_by_path(entry.path)
                if entry.is_redirect: continue
                item = entry.get_item()
                if item.mimetype.split(";", 1)[0].lower() in DOCUMENTS:
                    entries.append(_archive_path(entry.path))
                    if len(entries) > max_files: raise ExportError("Selection exceeds --max-files")
        if not entries or len(entries) > max_files:
            raise ExportError("Selection must be nonempty and within --max-files")
        job = {"schema_version": VERSION, "source_sha256": source_asset["sha256"],
               "source_asset": source_asset, "export_id": export_id, "entries": [],
               "max_bytes": max_bytes, "max_files": max_files, "max_item_bytes": max_item_bytes}
        state_path = _path(target, private + "/state.json")
        old = None
        if state_path.exists():
            if state_path.stat().st_size > MAX_STATE: raise ExportError("Oversized export checkpoint")
            old = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(old, dict) or old.get("schema_version") != VERSION:
                raise ExportError("Invalid export checkpoint")
        state = {"schema_version": VERSION, "complete": False, "files": {}, "warnings": []}
        worker = _Exporter(archive, source, target, private, source_asset, job, state, progress)
        canonical = sorted({worker.entry(name)[0].path for name in entries})
        job["entries"] = canonical
        worker.selected = set(canonical)
        if old:
            old_job = old.get("job", {})
            limits = {"max_bytes", "max_files", "max_item_bytes"}
            if not isinstance(old_job, dict) or any(type(old_job.get(k)) is not int for k in limits):
                raise ExportError("Invalid export checkpoint limits")
            if ({k: v for k, v in old_job.items() if k not in limits} !=
                    {k: v for k, v in job.items() if k not in limits} or
                    any(job[k] < old_job.get(k, 0) for k in limits)):
                raise ExportError("Checkpoint source/selection/limits changed; resume the original job or choose a new --export-id")
            if not isinstance(old.get("files"), dict) or len(old["files"]) > max_files:
                raise ExportError("Invalid export checkpoint")
            state = old
            worker.state = state
            if not isinstance(state.get("warnings"), list) or any(not isinstance(w, str) for w in state["warnings"]):
                raise ExportError("Invalid export checkpoint warnings")
            worker.warnings = set(state.get("warnings", []))
            for name, record in state["files"].items():
                _archive_path(name)
                if not isinstance(record, dict) or not isinstance(record.get("title"), str):
                    raise ExportError("Invalid export checkpoint file")
                entry, item, mime = worker.entry(name)
                document = name in worker.selected
                formats = DOCUMENTS if document else RESOURCES
                key = hashlib.sha256(name.encode()).hexdigest()
                if (mime not in formats or record.get("mime") != mime or
                        record.get("document") is not document or
                        record.get("destination") != f"REFERENCE/DIRECT/{export_id}/{key[:2]}/{key}.{formats[mime]}"):
                    raise SafetyError("Checkpoint destination does not match its archive entry")
                if record.get("sha256") and (not isinstance(record["sha256"], str) or
                                               not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
                    raise SafetyError("Invalid checkpoint checksum")
                if "size_bytes" in record and (type(record["size_bytes"]) is not int or record["size_bytes"] < 0):
                    raise SafetyError("Invalid checkpoint file size")
                if bool(record.get("sha256")) != ("size_bytes" in record):
                    raise SafetyError("Incomplete checkpoint checksum/size pair")
                _path(target, record["destination"])
        state["job"] = job
        state["complete"] = False
        # Existing completed manifests are invalidated before any mutation. The
        # manifest is owned metadata, never a user file selected for cleanup.
        for name in ("catalog.yaml", "inventory.json", "SHA256SUMS.txt"):
            path = _path(target, private + "/" + name)
            if path.exists():
                if not old: raise SafetyError(f"Unowned export metadata file: {path}")
                path.unlink()
        worker.save()
        for name in canonical: worker.enqueue(name, document=True)
        worker.save()
        # Each HTML/CSS/SVG pass may enqueue further local resources. Persisted
        # output checksums let interrupted jobs reuse already verified files.
        processed = set()
        while pending := sorted(set(state["files"]) - processed):
            for name in pending:
                worker.write(name)
                processed.add(name)
        worker.check_source()
        catalog_assets = []
        files = state["files"]
        for name, record in sorted(files.items()):
            relative = record["destination"]
            asset = {"id": "direct_" + export_id + "_" + hashlib.sha256(name.encode()).hexdigest()[:24],
                     "title": record["title"] if record["document"] else "Supporting resource: " + name,
                     "category": source_asset["category"], "format": relative.rsplit(".", 1)[-1],
                     "source_url": _path(target, relative).as_uri(), "destination": relative,
                     "version": source_asset["version"] + "; owl-export-v1", "size_bytes": record["size_bytes"],
                     "sha256": record["sha256"], "license": source_asset["license"],
                     "redistributable": source_asset["redistributable"], "required": False, "profiles": [],
                     "critical": False, "reader_required": False, "resource_type": "reference", "illustrated": False,
                     "publisher": source_asset.get("publisher", source_asset["title"]),
                     "attribution": source_asset.get("attribution", source_asset["title"]),
                     "source_page": source_asset.get("source_page", source_asset["source_url"]),
                     "derived_from_asset_id": source_asset["id"], "source_archive_sha256": source_asset["sha256"],
                     "source_archive_entry": name, "export_document": record["document"],
                     "description": "Offline ZIM extract. HTML/CSS/SVG links rewritten and active content removed; original notices retained. Supporting images/styles/fonts accompany selected documents."}
            catalog_assets.append(asset)
        report = {"schema_version": VERSION, "complete": True, "source_asset_id": source_asset["id"],
                  "source_sha256": source_asset["sha256"], "source_version": source_asset["version"],
                  "selected_entries": canonical, "documents": len(canonical), "files": len(files),
                  "size_bytes": sum(r["size_bytes"] for r in files.values()),
                  "warnings": sorted(worker.warnings), "assets": catalog_assets,
                  "static_conversion": True, "requires_review": bool(worker.warnings)}
        _json(_path(target, private + "/inventory.json"), report)
        checksums = "".join(f"{r['sha256']}  {r['destination']}\n" for r in sorted(files.values(), key=lambda r: r["destination"]))
        atomic_write(_path(target, private + "/SHA256SUMS.txt"), checksums.encode())
        atomic_write(_path(target, private + "/catalog.yaml"), yaml.safe_dump({"schema_version": 1, "assets": catalog_assets}, sort_keys=False, allow_unicode=True).encode())
        state["complete"] = True
        worker.save()
        progress(f"EXPORT COMPLETE: {len(canonical)} documents and {len(files)} verified files; import LIBRARY/{private}/catalog.yaml")
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Already downloaded local ZIM; never fetched from the network")
    parser.add_argument("target", type=Path, help="OWL root on the SSD; outputs are written in place under LIBRARY/")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--entries", type=Path, help="UTF-8 file containing one exact archive path per line")
    selection.add_argument("--all", action="store_true", dest="all_articles")
    parser.add_argument("--max-bytes", type=int, required=True, help="Maximum total exported payload bytes")
    parser.add_argument("--max-files", type=int, required=True, help="Documents plus all dependencies")
    parser.add_argument("--max-item-bytes", type=int, default=16 * BLOCK)
    parser.add_argument("--export-id")
    args = parser.parse_args(argv)
    try:
        assets = load_catalog(args.catalog, allow_local=True)
        asset = next((a for a in assets if a["id"] == args.asset), None)
        if asset is None: raise ExportError(f"Unknown source asset: {args.asset}")
        entries = []
        if args.entries:
            if args.entries.stat().st_size > 4 * BLOCK: raise ExportError("Entry selection file exceeds 4 MiB")
            entries = [line.strip() for line in args.entries.read_text(encoding="utf-8").splitlines() if line.strip()]
        with interrupt_signals():
            export_zim(args.source, args.target, source_asset=asset, entries=entries,
                       all_articles=args.all_articles, max_bytes=args.max_bytes, max_files=args.max_files,
                       max_item_bytes=args.max_item_bytes, export_id=args.export_id)
        return 0
    except KeyboardInterrupt:
        print("INTERRUPTED: owned partial files/checkpoints retained; rerun the same command", file=sys.stderr)
        return 130
    except (ExportError, SafetyError, OSError, ValueError, RuntimeError) as error:
        print(f"EXPORT FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
