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


def verify_drive(target: Path, *, emit=print, allow_incomplete: bool = False) -> dict:
    root = target.resolve()
    counts = {"OK": 0, "MISSING": 0, "FAILED": 0, "UNKNOWN": 0}
    def report(status, path, detail=""):
        counts[status] += 1
        emit(f"{status:7} {path}" + (f" ({detail})" if detail else ""))
    if not allow_incomplete:
        try:
            state_path = _path(root, STATE)
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("complete") is not True:
                    report("FAILED", STATE, "build is incomplete; rerun the builder")
        except (OSError, ValueError) as error:
            report("FAILED", STATE, str(error))
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
        return counts
    except (OSError, ValueError) as error:
        report("FAILED", MANIFEST, str(error))
        return counts
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
        if base == root / "LIBRARY":
            dirs[:] = [d for d in dirs if d != ".owl"]
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative not in entries and relative != MANIFEST:
                try:
                    report("FAILED" if _is_link(path.lstat()) else "UNKNOWN", relative)
                except OSError as error:
                    report("FAILED", relative, str(error))
    emit("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="outer drive folder containing START_HERE.html and LIBRARY/")
    parser.add_argument("--strict", action="store_true", help="also fail on unrelated/unknown files")
    args = parser.parse_args(argv)
    result = verify_drive(args.target)
    return int(bool(result["FAILED"] or result["MISSING"] or (args.strict and result["UNKNOWN"])))


if __name__ == "__main__":
    raise SystemExit(main())
