"""Portable paths and streaming integrity helpers. No cleanup outside owned files."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


class SafetyError(ValueError):
    pass


_GUARDS = ContextVar("owl_directory_guards", default=())


def _check_guards(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for root, identity in _GUARDS.get():
        if absolute != root and root not in absolute.parents:
            continue
        try:
            info = root.stat(follow_symlinks=False)
            current = (info.st_dev, info.st_ino)
        except OSError as error:
            raise SafetyError(f"Build directory disappeared; reconnect the original drive and rerun: {root}") from error
        if current != identity or not stat.S_ISDIR(info.st_mode):
            raise SafetyError(f"Build directory changed; reconnect the original drive and rerun: {root}")


@contextmanager
def guard_directory(path: Path):
    """Do not recreate a vanished USB mount on the computer's underlying disk.

    Identity is checked on subsequent path validations and atomic writes. This
    catches normal removal/replacement; it is not a filesystem transaction or a
    promise that an unsafe unplug cannot damage exFAT.
    """
    root = Path(os.path.abspath(path))
    reject_symlinks(root)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise SafetyError(f"Build directory is not a directory: {root}")
    token = _GUARDS.set((*_GUARDS.get(), (root, (info.st_dev, info.st_ino))))
    try:
        yield
    finally:
        _GUARDS.reset(token)


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
    _check_guards(path)
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
        try:
            _check_guards(Path(name))
        except SafetyError:
            pass  # A disconnected/replaced volume is no longer ours to clean.
        else:
            Path(name).unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    reject_symlinks(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
