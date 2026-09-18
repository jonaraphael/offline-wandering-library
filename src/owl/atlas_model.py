"""Strict, source-pinned metadata for OWL's static topic atlas.

Editorial labels are plain text. This module never executes media, extracts an
archive, invents a locator, or silently accepts a stale reviewed section map.
"""
from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
from datetime import date
import hashlib
from html.parser import HTMLParser
import math
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit
import zipfile

import yaml

from .safety import reject_symlinks, safe_path, sha256_file, validate_relative


class AtlasError(ValueError):
    """Navigation metadata or its selected source bytes cannot be published."""


_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_HASH = re.compile(r"[0-9a-f]{64}")
_PURPOSES = {"start-here", "practical", "explanation", "reference"}
_PROVENANCE = {"publisher-outline", "publisher-heading", "manual"}
_LOCATOR_FORMATS = {
    "pdf-page": {"pdf"}, "html-anchor": {"html", "htm"},
    "text-lines": {"txt", "text", "md", "markdown"},
    "epub-entry": {"epub"}, "zim-entry": {"zim"},
    "image": {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "tif", "tiff"},
    "media-time": {"mp3", "mp4", "m4a", "m4v", "wav", "ogg", "oga", "ogv", "webm", "flac", "mov"},
}


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise AtlasError("Navigation mapping keys must be strings")
        if key in result:
            raise AtlasError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _read(path: Path, root: Path, hashes: dict) -> dict:
    reject_symlinks(path)
    if not path.is_file():
        raise AtlasError(f"Missing navigation metadata file: {path}")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise AtlasError(f"Navigation metadata file exceeds 16 MiB: {path}")
    raw = path.read_bytes()
    try:
        document = yaml.load(raw, Loader=_UniqueLoader)
    except yaml.YAMLError as error:
        raise AtlasError(f"Invalid navigation YAML in {path.name}: {error}") from error
    hashes[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise AtlasError(f"{path.name}: requires schema_version: 1")
    return document


def _keys(row, required: set[str], optional: set[str], where: str) -> None:
    if not isinstance(row, dict):
        raise AtlasError(f"{where}: expected a mapping")
    missing, unknown = required - row.keys(), row.keys() - required - optional
    if missing or unknown:
        raise AtlasError(f"{where}: missing fields {sorted(missing)}, unknown fields {sorted(unknown)}")


def _identifier(value, where: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AtlasError(f"{where}: requires a portable lowercase identifier (1–80 characters)")
    validate_relative(value + ".html")
    return value


def _text(value, where: str, maximum: int = 500, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum or
            any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise AtlasError(f"{where}: requires plain text of at most {maximum} characters")
    value = value.strip()
    if not empty and not value:
        raise AtlasError(f"{where}: text cannot be empty")
    return value


def _list(value, where: str) -> list:
    if not isinstance(value, list):
        raise AtlasError(f"{where}: requires a list")
    return value


def _ids(value, where: str) -> list[str]:
    result = [_identifier(x, where) for x in _list(value, where)]
    if len(set(result)) != len(result):
        raise AtlasError(f"{where}: duplicate identifiers")
    return result


def _integer(value, where: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise AtlasError(f"{where}: requires an integer >= {minimum}")
    return value


def _order(value, where: str):
    if value is not None and (type(value) is not int or not -1_000_000_000 <= value <= 1_000_000_000):
        raise AtlasError(f"{where}: order must be an integer or null")
    return value


def _review(value, where: str) -> dict:
    _keys(value, {"by", "date"}, set(), where)
    reviewer = _text(value["by"], where + ".by", 200)
    when = value["date"]
    if type(when) is date:
        when = when.isoformat()
    if not isinstance(when, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
        raise AtlasError(f"{where}: review date must be YYYY-MM-DD")
    try:
        date.fromisoformat(when)
    except ValueError as error:
        raise AtlasError(f"{where}: invalid calendar date") from error
    return {"by": reviewer, "date": when}


def _archive_path(value, where: str) -> str:
    value = _text(value, where, 2048)
    for candidate in (value, unquote(value)):
        parsed = urlsplit(candidate)
        if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
                candidate.startswith("/") or "\\" in candidate or
                any(ord(c) < 32 for c in candidate) or
                any(part in {"", ".", ".."} for part in candidate.split("/"))):
            raise AtlasError(f"{where}: requires a relative archive entry, not a URL or traversal path")
    return value


def _locator(value, asset: dict, where: str) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise AtlasError(f"{where}: locator requires a type")
    kind = value["type"]
    if kind not in _LOCATOR_FORMATS or asset.get("format", "").lower() not in _LOCATOR_FORMATS[kind]:
        raise AtlasError(f"{where}: locator type does not match the asset format")
    result = dict(value)
    if kind == "pdf-page":
        _keys(value, {"type", "page"}, {"end_page", "printed_label"}, where)
        _integer(value["page"], where + ".page")
        if "end_page" in value:
            _integer(value["end_page"], where + ".end_page", value["page"])
        if "printed_label" in value:
            result["printed_label"] = _text(value["printed_label"], where + ".printed_label", 100)
    elif kind == "html-anchor":
        _keys(value, {"type", "id"}, set(), where)
        result["id"] = _text(value["id"], where + ".id", 1024)
        if any(c.isspace() or ord(c) < 32 for c in result["id"]):
            raise AtlasError(f"{where}: HTML anchor IDs cannot contain whitespace")
    elif kind == "text-lines":
        _keys(value, {"type", "start"}, {"end"}, where)
        _integer(value["start"], where + ".start")
        if "end" in value:
            _integer(value["end"], where + ".end", value["start"])
    elif kind in {"epub-entry", "zim-entry"}:
        _keys(value, {"type", "path"}, set(), where)
        result["path"] = _archive_path(value["path"], where + ".path")
    elif kind == "image":
        _keys(value, {"type"}, set(), where)
    else:
        _keys(value, {"type", "seconds"}, {"end_seconds"}, where)
        for field in ("seconds", "end_seconds"):
            if field in value and (type(value[field]) not in {int, float} or
                                   not math.isfinite(value[field]) or value[field] < 0):
                raise AtlasError(f"{where}: timestamps must be finite nonnegative numbers")
        if value.get("end_seconds", value["seconds"]) < value["seconds"]:
            raise AtlasError(f"{where}: end timestamp precedes start")
    return result


def _acyclic(rows: dict, parents, where: str) -> dict[str, list[str]]:
    children = {identity: [] for identity in rows}
    indegree = {}
    for identity, row in rows.items():
        broader = parents(row)
        indegree[identity] = len(broader)
        for parent in broader:
            if parent not in rows:
                raise AtlasError(f"{where}: unknown parent {parent} for {identity}")
            children[parent].append(identity)
    pending = deque(identity for identity, count in indegree.items() if count == 0)
    visited = 0
    while pending:
        identity = pending.popleft()
        visited += 1
        for child in children[identity]:
            indegree[child] -= 1
            if not indegree[child]:
                pending.append(child)
    if visited != len(rows):
        raise AtlasError(f"{where}: hierarchy contains a cycle")
    return children


def _section_map(document: dict, assets: dict, filename: str) -> dict:
    _keys(document, {"schema_version", "asset_id", "source_sha256", "sections"}, set(), filename)
    identity = _identifier(document["asset_id"], filename + ".asset_id")
    if identity not in assets or filename != identity + ".yaml":
        raise AtlasError(f"{filename}: unknown asset or filename does not match asset_id")
    checksum = document["source_sha256"]
    if not isinstance(checksum, str) or not _HASH.fullmatch(checksum):
        raise AtlasError(f"{filename}: source_sha256 must be an exact lowercase SHA-256")
    sections = {}
    for raw in _list(document["sections"], filename + ".sections"):
        _keys(raw, {"id", "title", "locator", "provenance"}, {"parent", "review", "illustrations"}, filename)
        sid = _identifier(raw["id"], filename + ".section.id")
        if sid in sections:
            raise AtlasError(f"{filename}: duplicate section {sid}")
        where = f"{filename}:{sid}"
        provenance = raw["provenance"]
        if not isinstance(provenance, str) or provenance not in _PROVENANCE:
            raise AtlasError(f"{where}: unknown section provenance")
        row = {"id": sid, "title": _text(raw["title"], where + ".title"),
               "parent": _identifier(raw["parent"], where + ".parent") if raw.get("parent") is not None else None,
               "locator": _locator(raw["locator"], assets[identity], where), "provenance": provenance}
        illustrations = []
        for item in _list(raw.get("illustrations", []), where + ".illustrations"):
            _keys(item, {"kind", "label"}, {"figure_id", "caption"}, where + ".illustration")
            if not isinstance(item["kind"], str) or item["kind"] not in {"diagram", "photograph", "procedure", "figure"}:
                raise AtlasError(f"{where}: unsupported illustration kind")
            illustration = {"kind": item["kind"], "label": _text(item["label"], where + ".illustration.label")}
            for field in ("figure_id", "caption"):
                if field in item:
                    illustration[field] = _text(item[field], where + ".illustration." + field)
            illustrations.append(illustration)
        row["illustrations"] = illustrations
        if "review" in raw:
            row["review"] = _review(raw["review"], where + ".review")
        if (provenance == "manual" or illustrations or row["locator"]["type"] == "media-time") and "review" not in row:
            raise AtlasError(f"{where}: manual locations, illustrations and media timestamps require review")
        sections[sid] = row
    _acyclic(sections, lambda row: [row["parent"]] if row["parent"] else [], filename)
    return {"schema_version": 1, "asset_id": identity, "source_sha256": checksum, "sections": list(sections.values())}


def load_navigation(directory: Path, catalog_assets: list[dict]) -> dict:
    """Validate every metadata/reference globally, without opening source files.

    Excluded and unresolved assets still receive schema/reference checks. Their
    bytes and reviewed hashes are checked only when selected by validate_sources.
    Repeated topic/asset/section assignments retain the first declaration.
    """
    directory = Path(directory)
    reject_symlinks(directory)
    assets = {}
    for asset in catalog_assets:
        identity = _identifier(asset.get("id"), "catalog asset")
        if identity in assets:
            raise AtlasError(f"Duplicate catalog asset: {identity}")
        assets[identity] = asset
    hashes = {}
    document = _read(directory / "topics.yaml", directory, hashes)
    _keys(document, {"schema_version", "topics", "entrances"}, set(), "topics.yaml")
    topics = {}
    for raw in _list(document["topics"], "topics"):
        _keys(raw, {"id", "title", "description"}, {"parents", "related", "aliases", "order"}, "topic")
        identity = _identifier(raw["id"], "topic.id")
        if identity in topics:
            raise AtlasError(f"Duplicate topic: {identity}")
        aliases, seen = [], set()
        for alias in _list(raw.get("aliases", []), identity + ".aliases"):
            label = _text(alias, identity + ".alias")
            key = " ".join(label.split()).casefold()
            if key not in seen:
                aliases.append(label)
                seen.add(key)
        topics[identity] = {"id": identity, "title": _text(raw["title"], identity + ".title"),
                            "description": _text(raw["description"], identity + ".description", 4000),
                            "parents": _ids(raw.get("parents", []), identity + ".parents"),
                            "related": _ids(raw.get("related", []), identity + ".related"),
                            "aliases": aliases, "order": _order(raw.get("order"), identity)}
    _keys(document["entrances"], {"subjects", "tasks", "learn"}, set(), "entrances")
    entrances = {kind: _ids(document["entrances"][kind], "entrances." + kind)
                 for kind in ("subjects", "tasks", "learn")}
    for row in topics.values():
        for related in row["related"]:
            if related not in topics:
                raise AtlasError(f"{row['id']}: unknown related topic {related}")
    children = _acyclic(topics, lambda row: row["parents"], "topics")
    reachable, pending = set(), deque(x for ids in entrances.values() for x in ids)
    while pending:
        identity = pending.popleft()
        if identity not in topics:
            raise AtlasError(f"Unknown entrance topic: {identity}")
        if identity not in reachable:
            reachable.add(identity)
            pending.extend(children[identity])
    if topics.keys() - reachable:
        raise AtlasError(f"Topics unreachable from entrances: {', '.join(sorted(topics.keys() - reachable))}")
    sections = {}
    folder = directory / "sections"
    reject_symlinks(folder)
    if folder.exists() and not folder.is_dir():
        raise AtlasError("Navigation sections must be a directory")
    if folder.exists():
        for path in sorted(folder.glob("*.yaml")):
            section_map = _section_map(_read(path, directory, hashes), assets, path.name)
            sections[section_map["asset_id"]] = section_map
    document = _read(directory / "assignments.yaml", directory, hashes)
    _keys(document, {"schema_version", "assignments"}, set(), "assignments.yaml")
    section_ids = {identity: {row["id"] for row in value["sections"]} for identity, value in sections.items()}
    assignments, seen = [], set()
    for raw in _list(document["assignments"], "assignments"):
        _keys(raw, {"topic_id", "asset_id"}, {"section_id", "purpose", "order", "description"}, "assignment")
        tid, aid = _identifier(raw["topic_id"], "assignment.topic_id"), _identifier(raw["asset_id"], "assignment.asset_id")
        sid = _identifier(raw["section_id"], "assignment.section_id") if raw.get("section_id") is not None else None
        if tid not in topics or aid not in assets:
            raise AtlasError(f"Assignment references unknown topic or asset: {tid}/{aid}")
        if sid is not None and sid not in section_ids.get(aid, set()):
            raise AtlasError(f"Assignment references unknown section: {aid}/{sid}")
        purpose = raw.get("purpose", "reference")
        if not isinstance(purpose, str) or purpose not in _PURPOSES:
            raise AtlasError(f"Assignment has unknown purpose: {purpose!r}")
        row = {"topic_id": tid, "asset_id": aid, "section_id": sid, "purpose": purpose,
               "order": _order(raw.get("order"), "assignment")}
        if "description" in raw:
            row["description"] = _text(raw["description"], "assignment.description", 2000)
        identity = (tid, aid, sid)
        if identity not in seen:
            assignments.append(row)
            seen.add(identity)
    return {"topics": topics, "entrances": entrances, "assignments": assignments,
            "sections": sections, "input_hashes": dict(sorted(hashes.items()))}


class _Anchors(HTMLParser):
    def __init__(self, wanted):
        super().__init__(convert_charrefs=True)
        self.counts = dict.fromkeys(wanted, 0)

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id" and value in self.counts:
                self.counts[value] += 1


def _validate_locators(path: Path, section_map: dict, asset: dict) -> None:
    sections = section_map["sections"]
    if not sections:
        return
    kinds = {row["locator"]["type"] for row in sections}
    if "pdf-page" in kinds:
        from pypdf import PdfReader
        with path.open("rb") as source:
            count = len(PdfReader(source).pages)
        for section in sections:
            loc = section["locator"]
            if loc.get("end_page", loc["page"]) > count:
                raise AtlasError(f"{path.name}/{section['id']}: PDF page is outside 1–{count}")
    elif "html-anchor" in kinds:
        parser = _Anchors(row["locator"]["id"] for row in sections)
        with path.open(encoding=asset.get("text_encoding", "utf-8-sig"), errors="strict") as source:
            for chunk in iter(lambda: source.read(65536), ""):
                parser.feed(chunk)
                if len(parser.rawdata) > 1024 * 1024:
                    raise AtlasError(f"{path.name}: HTML has an unterminated token larger than 1 MiB")
        parser.close()
        for anchor, count in parser.counts.items():
            if count != 1:
                raise AtlasError(f"{path.name}: HTML anchor {anchor!r} must occur exactly once; found {count}")
    elif "text-lines" in kinds:
        count, last = 0, ""
        with path.open(encoding=asset.get("text_encoding", "utf-8-sig"), errors="strict") as source:
            for chunk in iter(lambda: source.read(65536), ""):
                count += chunk.count("\n")
                last = chunk[-1]
        count += bool(last and last != "\n")
        for section in sections:
            loc = section["locator"]
            if loc.get("end", loc["start"]) > count:
                raise AtlasError(f"{path.name}/{section['id']}: text line is outside 1–{count}")
    elif "epub-entry" in kinds:
        with zipfile.ZipFile(path) as archive:
            members = Counter(info.filename for info in archive.infolist())
            for section in sections:
                member = section["locator"]["path"]
                if members[member] != 1:
                    raise AtlasError(f"{path.name}: EPUB entry missing or ambiguous: {member}")
                info = archive.getinfo(member)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise AtlasError(f"{path.name}: EPUB locator must identify a regular member: {member}")
    elif "zim-entry" in kinds:
        from libzim.reader import Archive
        archive = Archive(path)
        for section in sections:
            entry = section["locator"]["path"]
            if not archive.has_entry_by_path(entry):
                raise AtlasError(f"{path.name}: ZIM entry does not exist: {entry}")
    # Images link to the whole already-verified asset. Media duration is not
    # guessed from filenames or container bytes: valid ranges require review.


def validate_sources(target: Path, assets: list[dict], navigation: dict) -> dict:
    """Verify selected atlas sources and return only their valid section maps.

    Hash only selected sources referenced by assignments or section maps. A
    selected reviewed map always needs exact source agreement, even when none of
    its sections has a topic assignment. Excluded maps receive no file access.
    The caller can set navigation['sections'] to this returned mapping once.
    """
    selected = {asset["id"]: asset for asset in assets if asset.get("status", "resolved") == "resolved"}
    referenced = set(navigation["sections"]) | {row["asset_id"] for row in navigation["assignments"]}
    validated = {}
    for identity in sorted(selected.keys() & referenced):
        asset = selected[identity]
        path = safe_path(Path(target), asset["destination"])
        if not path.is_file():
            raise AtlasError(f"Selected atlas source is missing: {asset['destination']}")
        before = path.stat()
        if type(asset.get("size_bytes")) is not int or before.st_size != asset["size_bytes"]:
            raise AtlasError(f"{identity}: source size differs from catalog")
        digest = sha256_file(path)
        if asset.get("sha256") is not None and digest != asset["sha256"]:
            raise AtlasError(f"{identity}: source SHA-256 differs from catalog")
        section_map = navigation["sections"].get(identity)
        if section_map is not None:
            if digest != section_map["source_sha256"]:
                raise AtlasError(f"{identity}: stale section map; reviewed source SHA-256 differs")
            try:
                _validate_locators(path, section_map, asset)
            except AtlasError:
                raise
            except Exception as error:
                raise AtlasError(f"{identity}: could not validate source locators: {error}") from error
            validated[identity] = deepcopy(section_map)
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise AtlasError(f"{identity}: source changed during navigation validation")
    return validated
