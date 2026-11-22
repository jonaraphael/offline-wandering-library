"""Independent standard-library-only verifier; also copied onto each built SSD."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


MANIFEST = "LIBRARY/SHA256SUMS.txt"
STATE = "LIBRARY/.owl/state.json"
BUILD_INFO = "LIBRARY/BUILD_INFO.json"
VOLUME_METADATA_DIRS = {".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems"}


def _is_link(info: os.stat_result) -> bool:
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, "st_file_attributes", 0) &
                 getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
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
            if state is not None and state.get("complete") is not True:
                report("FAILED", STATE, "build was interrupted; rerun the builder")
        except (OSError, ValueError) as error:
            report("FAILED", STATE, str(error))

    def summaries():
        try:
            incomplete, detail = _completeness(root, _record(root, BUILD_INFO))
        except (OSError, ValueError) as error:
            report("FAILED", BUILD_INFO, str(error))
            incomplete, detail = False, "COMPLETENESS UNKNOWN: build metadata could not be read"
        emit("Integrity: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        emit(detail)
        if incomplete:
            counts["INCOMPLETE"] = 1
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
    for relative, expected in sorted(entries.items()):
        try:
            path = _path(root, relative)
            if not path.exists():
                report("MISSING", relative)
            elif not path.is_file() or file_hash(path) != expected:
                report("FAILED", relative, "SHA-256 differs or not a regular file")
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
    parser.add_argument("--strict", action="store_true", help="also fail on incomplete selections and unrelated files")
    parser.add_argument("--accept-partial", action="store_true", help="accept incomplete content with --strict")
    args = parser.parse_args(argv)
    result = verify_drive(args.target)
    return int(bool(result["FAILED"] or result["MISSING"] or
                    args.strict and (result["UNKNOWN"] or (result.get("INCOMPLETE") and not args.accept_partial))))


if __name__ == "__main__":
    raise SystemExit(main())
