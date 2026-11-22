"""Independent standard-library-only verifier; also copied onto each built SSD."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat


MANIFEST = "LIBRARY/SHA256SUMS.txt"
STATE = "LIBRARY/.owl/state.json"
BUILD_INFO = "LIBRARY/BUILD_INFO.json"
INVENTORY = "LIBRARY/INVENTORY.json"
ZIM_PART_BYTES = 1 << 30
VOLUME_METADATA_DIRS = {".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems"}


def _is_link(info: os.stat_result) -> bool:
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, "st_file_attributes", 0) &
                 getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def file_hash(path: Path, whole=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            if whole is not None:
                whole.update(block)
    return digest.hexdigest()


def _path(root: Path, relative: str) -> Path:
    if (not relative or relative.startswith("/") or "\\" in relative or
            any(p in {"", ".", ".."} for p in relative.split("/")) or
            any(ord(c) < 32 or ord(c) == 127 for c in relative) or ":" in relative):
        raise ValueError("unsafe checksum path")
    path = root
    for part in relative.split("/"):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info):
            raise ValueError("symlink/junction/reparse point")
    return path


def _record(root: Path, name: str) -> dict | None:
    try:
        path = _path(root, name)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("expected a regular JSON file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def zim_part_paths(destination: str, size: int, part_bytes: int = ZIM_PART_BYTES):
    count = (size + part_bytes - 1) // part_bytes
    if count < 2 or count > 26 ** 2 or not destination.endswith(".zim"):
        raise ValueError("invalid split ZIM layout")
    for index in range(count):
        suffix = chr(97 + index // 26) + chr(97 + index % 26)
        start = index * part_bytes
        yield {"path": "LIBRARY/" + destination + suffix, "start": start,
               "bytes": min(part_bytes, size - start)}


def split_inventory(asset: dict) -> list[dict]:
    parts = asset.get("parts", [])
    if not isinstance(parts, list):
        raise ValueError("invalid inventory parts")
    if len(parts) < 2:
        return []
    size = asset.get("size_bytes", asset.get("bytes"))
    destination = asset.get("destination")
    if (asset.get("format") != "zim" or type(size) is not int or not isinstance(destination, str) or
            any(not isinstance(part, dict) for part in parts) or
            not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256")))):
        raise ValueError("invalid split ZIM inventory")
    part_bytes = parts[0].get("bytes")
    if type(part_bytes) is not int or not 0 < part_bytes <= ZIM_PART_BYTES:
        raise ValueError("invalid split ZIM part size")
    # Browser inventories use the path readers open, whereas Python keeps
    # the unsuffixed catalog destination for locked selections.
    if destination.endswith(".zimaa"):
        destination = destination[:-2]
    layout = list(zim_part_paths(destination, size, part_bytes))
    if len(parts) != len(layout) or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256"))) or
            any(type(row.get(key)) is not type(value) or row[key] != value for key, value in expected.items())
            for row, expected in zip(parts, layout)):
        raise ValueError("invalid split ZIM part inventory")
    return parts


class _EntryScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        source = dict(attrs).get("src") if tag == "script" else None
        if source:
            self.sources.append(source)


def support_status(root: Path, info: dict | None) -> tuple[bool, str]:
    info = info or {}
    missing = info.get("support_missing", [])
    complete = info.get("support_complete")
    if complete is not None and type(complete) is not bool:
        raise ValueError("invalid support_complete flag")
    if not isinstance(missing, list) or any(
            not isinstance(row, dict) or row.get("kind") not in {"reader", "search", "phone", "app"} or
            not isinstance(row.get("reason"), str) for row in missing):
        raise ValueError("invalid support_missing list")
    kinds = {row["kind"] for row in missing}

    def exists(name):
        return _path(root, name).is_file()

    def declaration(name, prefix):
        if not exists(name):
            return {}
        text = _path(root, name).read_text(encoding="utf-8").strip()
        if not text.startswith(prefix) or not text.endswith(");"):
            raise ValueError(f"invalid support declaration: {name}")
        data = json.loads(text[len(prefix):-2].lstrip())
        if not isinstance(data, dict):
            raise ValueError(f"invalid support declaration: {name}")
        return data

    scripts = _EntryScripts()
    if exists("START_HERE.html"):
        scripts.feed(_path(root, "START_HERE.html").read_text(encoding="utf-8"))
    reader = next((match[1] for source in scripts.sources
                   if (match := re.fullmatch(r"(LIBRARY/INDEX/[0-9a-f]{12})/search\.js", source))), None)
    if reader or info.get("reader"):
        if reader is None or any(not exists(f"{reader}/{name}")
                                 for name in ("search.js", "reader.js", "home.js", "search-paths.js")):
            kinds.add("reader")
    home = declaration(f"{reader}/home.js", 'globalThis.OWLReaderData("home",') if reader else {}
    search = info.get("search")
    declared_search = (search is True or isinstance(search, dict) or home.get("search") is True or
                       "LIBRARY/SEARCH/search.js" in scripts.sources or
                       exists("LIBRARY/SEARCH/manifest.js"))
    if declared_search:
        manifest_path = "LIBRARY/SEARCH/manifest.js"
        files = {"LIBRARY/SEARCH.html", "LIBRARY/SEARCH/search.js", manifest_path, "LIBRARY/SEARCH/coverage.json"}
        if reader:
            files.add(f"{reader}/manifest.js")
        manifest = declaration(manifest_path, "globalThis.OWLDiscoveryManifest(")
        data_path = manifest.get("path")
        if isinstance(data_path, str):
            files.add("LIBRARY/" + data_path)
        if manifest.get("shards"):
            files.update(("LIBRARY/SEARCH/rank.js", "LIBRARY/SEARCH/shards.js"))
            if reader:
                files.update((f"{reader}/rank.js", f"{reader}/shards.js"))
        if isinstance(search, dict):
            generated = search.get("generated_files", [])
            if not isinstance(generated, list) or not all(isinstance(name, str) for name in generated):
                raise ValueError("invalid generated search files")
            files.update("LIBRARY/" + name for name in generated)
        if not isinstance(data_path, str) or any(not exists(name) for name in files):
            kinds.add("search")
    phone_count = sum(row["kind"] == "phone" for row in missing)
    phone = home.get("phone", [])
    if not isinstance(phone, list) or any(not isinstance(row, dict) or not isinstance(row.get("path"), str)
                                          for row in phone):
        raise ValueError("invalid WikiMed phone volume declaration")
    phone_count += sum(not exists(row["path"]) for row in phone)
    details = [label for kind, label in (("reader", "reader files missing"), ("search", "search index missing"))
               if kind in kinds]
    apps = [row for row in missing if row["kind"] == "app"]
    if apps:
        titles = ", ".join(row["title"] for row in apps if isinstance(row.get("title"), str) and row["title"])
        detail = f"{len(apps)} reader app{'s' if len(apps) != 1 else ''} missing"
        details.append(detail + (f" ({titles})" if titles else ""))
    if phone_count:
        details.append(f"{phone_count} phone volume{'s' if phone_count != 1 else ''} missing")
    if details or complete is False:
        return True, "SUPPORT INCOMPLETE: " + ("; ".join(details) or "the build report marks support incomplete")
    if complete is True or reader or declared_search:
        return False, "SUPPORT COMPLETE"
    return False, "SUPPORT UNKNOWN: no support status in the build report"


def _completeness(root: Path, info: dict | None) -> tuple[bool, str]:
    if info is None:
        return False, "COMPLETENESS UNKNOWN: no build report on this drive"
    present = info.get("asset_count")
    selected = info.get("selected_count")
    knowledge = info.get("knowledge_count")
    missing = info.get("missing", [])
    complete = info.get("content_complete")
    for count in (present, selected, knowledge):
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("invalid completeness counts")
    if not isinstance(missing, list) or any(not isinstance(row, dict) for row in missing):
        raise ValueError("invalid missing-file list")
    if complete is not None and type(complete) is not bool:
        raise ValueError("invalid content_complete flag")
    if knowledge is None and present:
        # Older builds counted apps and supporting files as assets, too.
        inventory = _record(root, "LIBRARY/INVENTORY.json") or {}
        assets = inventory.get("assets")
        if isinstance(assets, list) and len(assets) == present and all(
                isinstance(asset, dict) and isinstance(asset.get("destination"), str) for asset in assets):
            knowledge = 0
            for asset in assets:
                member = asset.get("archive_member") or {}
                if not isinstance(member, dict):
                    raise ValueError("invalid archive member in inventory")
                knowledge += (not asset["destination"].startswith("SOFTWARE/") and
                              not asset.get("supporting_file") and member.get("document", True) is not False)
    # Both builders count verified split archives once, through asset_count.
    absent = max(len(missing), selected - present if selected is not None and present is not None else 0)
    empty = knowledge == 0 or present == 0
    if complete is False or absent or empty:
        if absent and selected is not None:
            critical = sum(row.get("utility_tier") == "CRITICAL" for row in missing)
            detail = f"{absent} of {selected} selected files missing ({critical} critical)"
        elif empty:
            detail = "zero knowledge files present"
        else:
            detail = "the build report marks this selection incomplete"
        if empty and absent and selected is not None:
            detail += ". Zero knowledge files present"
        return True, f"INCOMPLETE: {detail}"
    if selected is not None and present is not None:
        return False, f"COMPLETE: {present} of {selected} selected files present"
    if complete is True:
        return False, f"COMPLETE: {present} files present" if present is not None else "COMPLETE: build report confirms selection"
    return False, "COMPLETENESS UNKNOWN: build report has no selection status"


def verify_drive(target: Path, *, emit=print, allow_incomplete: bool = False) -> dict:
    root = target.resolve()
    counts = {"OK": 0, "MISSING": 0, "FAILED": 0, "UNKNOWN": 0}
    def report(status, path, detail=""):
        counts[status] += 1
        emit(f"{status:7} {path}" + (f" ({detail})" if detail else ""))
    if not allow_incomplete:
        try:
            state = _record(root, STATE)
            # A published partial build has a verified manifest and reports
            # its omissions through the separate completeness checks.
            if (state is not None and state.get("complete") is not True and
                    state.get("phase") != "partial-published"):
                report("FAILED", STATE, "build was interrupted; rerun the builder")
        except (OSError, ValueError) as error:
            report("FAILED", STATE, str(error))

    def summaries():
        try:
            info = _record(root, BUILD_INFO)
            incomplete, detail = _completeness(root, info)
            support_incomplete, support = support_status(root, info)
        except (OSError, ValueError) as error:
            report("FAILED", BUILD_INFO, str(error))
            incomplete, detail = False, "COMPLETENESS UNKNOWN: build metadata could not be read"
            support_incomplete, support = False, "SUPPORT UNKNOWN: build metadata could not be read"
        emit("Integrity: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        emit(detail)
        emit(support)
        if incomplete:
            counts["INCOMPLETE"] = 1
        if support_incomplete:
            counts["SUPPORT_INCOMPLETE"] = 1
        return counts

    try:
        manifest = _path(root, MANIFEST)
        entries = {}
        seen = set()
        for line in manifest.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match or match[2].casefold() in seen:
                raise ValueError("malformed or duplicate checksum entry")
            relative = match[2]
            folded = relative.casefold()
            _path(root, relative)
            if (relative != "START_HERE.html" and not relative.startswith("LIBRARY/")):
                raise ValueError("checksum paths must use the outer START_HERE.html and LIBRARY/ layout")
            if (folded == MANIFEST.casefold() or folded == "library/.owl" or
                    folded.startswith("library/.owl/")):
                raise ValueError("invalid checksum manifest self/internal entry")
            seen.add(folded)
            entries[relative] = match[1]
        if "START_HERE.html" not in entries:
            raise ValueError("checksum manifest must include outer START_HERE.html")
    except FileNotFoundError:
        report("MISSING", MANIFEST)
        return summaries()
    except (OSError, ValueError) as error:
        report("FAILED", MANIFEST, str(error))
        return summaries()
    grouped = {}
    try:
        inventory = _record(root, INVENTORY) if INVENTORY in entries else None
        for asset in (inventory or {}).get("assets", []):
            if not isinstance(asset, dict):
                raise ValueError("invalid inventory asset")
            parts = split_inventory(asset)
            if not parts:
                continue
            whole = hashlib.sha256()
            for index, part in enumerate(parts):
                name = part["path"]
                if name in grouped or entries.get(name) != part["sha256"]:
                    raise ValueError(f"split ZIM part differs from checksum manifest: {name}")
                grouped[name] = whole, part["bytes"], asset["sha256"] if index == len(parts) - 1 else None
    except (OSError, TypeError, ValueError) as error:
        report("FAILED", INVENTORY, str(error))
    for relative, expected in sorted(entries.items()):
        try:
            path = _path(root, relative)
            whole, size, final = grouped.get(relative, (None, None, None))
            if not path.exists():
                report("MISSING", relative)
            elif (not path.is_file() or (size is not None and path.stat().st_size != size) or
                  (file_hash(path, whole) if whole is not None else file_hash(path)) != expected):
                report("FAILED", relative, "SHA-256 differs or not a regular file")
            elif final is not None and whole.hexdigest() != final:
                report("FAILED", relative, "whole split ZIM SHA-256 differs")
            else:
                report("OK", relative)
        except (OSError, ValueError) as error:
            report("FAILED", relative, str(error))
    def walk_error(error):
        report("FAILED", os.fspath(error.filename or root), str(error))

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(directory)
        for name in dirs[:]:
            path = base / name
            try:
                linked = _is_link(path.lstat())
            except OSError as error:
                dirs.remove(name)
                report("FAILED", path.relative_to(root).as_posix(), str(error))
                continue
            if linked:
                dirs.remove(name)
                report("FAILED", path.relative_to(root).as_posix(), "symlink/junction/reparse point")
        if base == root:
            # macOS protects these volume directories. Reject links above before
            # excluding their contents; the exemption never applies in LIBRARY.
            dirs[:] = [d for d in dirs if d not in VOLUME_METADATA_DIRS]
        elif base == root / "LIBRARY":
            dirs[:] = [d for d in dirs if d != ".owl"]
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative not in entries and relative != MANIFEST:
                try:
                    report("FAILED" if _is_link(path.lstat()) else "UNKNOWN", relative)
                except OSError as error:
                    report("FAILED", relative, str(error))
    return summaries()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="outer drive folder containing START_HERE.html and LIBRARY/")
    parser.add_argument("--strict", action="store_true", help="also fail on incomplete content or support and unrelated files")
    parser.add_argument("--accept-partial", action="store_true", help="accept incomplete content and support with --strict")
    args = parser.parse_args(argv)
    result = verify_drive(args.target)
    return int(bool(result["FAILED"] or result["MISSING"] or
                    args.strict and (result["UNKNOWN"] or
                                     (result.get("INCOMPLETE") or result.get("SUPPORT_INCOMPLETE")) and not args.accept_partial)))


if __name__ == "__main__":
    raise SystemExit(main())
