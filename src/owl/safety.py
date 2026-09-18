"""Portable paths and streaming integrity helpers. No cleanup outside owned files."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


class SafetyError(ValueError):
    pass


_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)


def validate_relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 220:
        raise SafetyError(f"Invalid portable path: {value!r}")
    if value.startswith("/") or "\\" in value or any(ord(c) < 32 for c in value):
        raise SafetyError(f"Unsafe path: {value!r}")
    parts = value.split("/")
    for part in parts:
        if (part in ("", ".", "..") or len(part) > 100 or
                part.endswith((".", " ")) or any(c in part for c in '<>:"|?*') or
                _RESERVED.fullmatch(part) or not part.isascii()):
            raise SafetyError(f"Unsafe or nonportable path: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise SafetyError(f"Absolute path: {value!r}")
    return value


def reject_symlinks(path: Path) -> None:
    # Inspect lexical ancestors: resolve() alone would hide symlink traversal.
    absolute = Path(os.path.abspath(path))
    for candidate in [absolute, *absolute.parents]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            # macOS /tmp and /var are system aliases. Callers canonicalize their
            # existing base directory before deriving any untrusted child paths.
            raise SafetyError(f"Refusing symlink/junction/reparse point: {candidate}")


def safe_path(root: Path, relative: str) -> Path:
    validate_relative(relative)
    result = root / relative
    reject_symlinks(result)
    if result.exists() and not result.is_file() and not result.is_dir():
        raise SafetyError(f"Not a regular file or directory: {result}")
    return result


def atomic_write(path: Path, data: bytes) -> None:
    reject_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".owl-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        reject_symlinks(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    reject_symlinks(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
