"""Independent standard-library-only verifier; also copied onto each built SSD."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(root: Path, relative: str) -> Path:
    if (not relative or relative.startswith("/") or "\\" in relative or
            any(p in {"", ".", ".."} for p in relative.split("/")) or
            any(ord(c) < 32 for c in relative) or ":" in relative):
        raise ValueError("unsafe checksum path")
    path = root
    for part in relative.split("/"):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("symlink/junction/reparse point")
    return path


def verify_drive(target: Path, *, emit=print, allow_incomplete: bool = False) -> dict:
    root = target.resolve()
    counts = {"OK": 0, "MISSING": 0, "FAILED": 0, "UNKNOWN": 0}
    def report(status, path, detail=""):
        counts[status] += 1
        emit(f"{status:7} {path}" + (f" ({detail})" if detail else ""))
    if not allow_incomplete and (root / ".owl/state.json").exists():
        try:
            state = json.loads(_path(root, ".owl/state.json").read_text(encoding="utf-8"))
            if state.get("complete") is not True:
                report("FAILED", ".owl/state.json", "build is incomplete; rerun the builder")
        except (OSError, ValueError) as error:
            report("FAILED", ".owl/state.json", str(error))
    try:
        manifest = _path(root, "SHA256SUMS.txt")
        entries = {}
        for line in manifest.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match or match[2].casefold() in {p.casefold() for p in entries}:
                raise ValueError("malformed or duplicate checksum entry")
            _path(root, match[2])
            if match[2] == "SHA256SUMS.txt" or match[2].startswith(".owl/"):
                raise ValueError("invalid checksum manifest self/internal entry")
            entries[match[2]] = match[1]
        if not entries:
            raise ValueError("empty checksum manifest")
    except FileNotFoundError:
        report("MISSING", "SHA256SUMS.txt")
        return counts
    except (OSError, ValueError) as error:
        report("FAILED", "SHA256SUMS.txt", str(error))
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
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        if base == root:
            dirs[:] = [d for d in dirs if d != ".owl"]
        for name in dirs[:]:
            path = base / name
            if path.is_symlink():
                dirs.remove(name)
                report("FAILED", path.relative_to(root).as_posix(), "symlink")
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative not in entries and relative != "SHA256SUMS.txt":
                report("FAILED" if path.is_symlink() else "UNKNOWN", relative)
    emit("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--strict", action="store_true", help="also fail on unrelated/unknown files")
    args = parser.parse_args(argv)
    result = verify_drive(args.target)
    return int(bool(result["FAILED"] or result["MISSING"] or (args.strict and result["UNKNOWN"])))


if __name__ == "__main__":
    raise SystemExit(main())
