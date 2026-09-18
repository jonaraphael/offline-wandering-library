"""Durable local transfers into caller-owned files, with validated resumption."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import time

from .safety import SafetyError, reject_symlinks


CHUNK_BYTES = 1024 * 1024
CHECKPOINT_BYTES = 64 * 1024 * 1024
CHECKPOINT_SECONDS = 5.0


class TransferError(RuntimeError):
    pass


class _Checkpoint:
    def __init__(self, handle):
        self.handle = handle
        self.pending = 0
        self.last_flush = time.monotonic()

    def flush(self):
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.pending = 0
        self.last_flush = time.monotonic()

    def written(self, count: int) -> bool:
        self.pending += count
        if (self.pending >= CHECKPOINT_BYTES or
                time.monotonic() - self.last_flush >= CHECKPOINT_SECONDS):
            self.flush()
            return True
        return False


@contextmanager
def durable_writer(handle):
    """Checkpoint a writable file periodically, on success, and on interruption.

    Call ``checkpoint.written(len(block))`` after each write. If an operation
    fails, a best-effort final checkpoint must not hide the original exception.
    Previously checkpointed bytes remain usable even if that final fsync fails.
    """
    checkpoint = _Checkpoint(handle)
    try:
        yield checkpoint
    except BaseException:
        try:
            checkpoint.flush()
        except OSError:
            pass
        raise
    else:
        checkpoint.flush()


def _regular(path: Path) -> None:
    reject_symlinks(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise SafetyError(f"Refusing nonregular transfer file: {path}")


def _open_regular(path: Path, *, writable: bool = False):
    _regular(path)
    flags = os.O_RDWR | os.O_CREAT if writable else os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SafetyError(f"Refusing nonregular transfer file: {path}")
        # Truncating or appending a linked partial would also alter another name.
        if writable and info.st_nlink > 1:
            raise SafetyError(f"Refusing hard-linked transfer partial: {path}")
        return os.fdopen(fd, "r+b" if writable else "rb")
    except BaseException:
        os.close(fd)
        raise


def _digest(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    with _open_regular(path) as handle:
        if os.fstat(handle.fileno()).st_size != size:
            raise TransferError(f"{path.name}: size mismatch; expected {size} bytes")
        count = 0
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            count += len(block)
            if count > size:
                raise TransferError(f"{path.name}: source changed while verifying")
            digest.update(block)
        if count != size:
            raise TransferError(f"{path.name}: incomplete file; expected {size} bytes")
    return digest.hexdigest()


def _same_file(left: Path, right: Path) -> bool:
    # exFAT/Windows may alias case variants even before either file exists.
    if os.path.abspath(left).casefold() == os.path.abspath(right).casefold():
        return True
    try:
        return os.path.samefile(left, right)
    except FileNotFoundError:
        return False


def _directory_identity(path: Path) -> tuple[int, int]:
    reject_symlinks(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise SafetyError(f"Transfer directory is not a directory: {path}")
    return info.st_dev, info.st_ino


def _check_directory(path: Path, expected: tuple[int, int]) -> None:
    try:
        current = _directory_identity(path)
    except FileNotFoundError as error:
        raise SafetyError(f"Transfer directory disappeared; reconnect the original drive: {path}") from error
    if current != expected:
        raise SafetyError(f"Transfer directory changed; refusing to write to a replacement: {path}")


def resume_copy(source: Path, destination: Path, *, size: int,
                checksum: str | None, part: Path | None = None, progress=print) -> str:
    """Copy into caller-owned storage, returning the verified on-disk SHA-256.

    The caller owns both ``destination`` and ``part`` and must serialize writes
    to them. The default partial is ``destination.name + '.part'``. An explicit
    partial may be in another directory on the destination's filesystem.

    A saved prefix is compared to the source before appending. A bad/oversized
    prefix resets only this owned partial. All writes receive periodic durable
    checkpoints. Interruptions, I/O errors and checksum failures retain it;
    the previous destination is replaced only after full size/hash validation.
    Use a pinned checksum for cache deployment; None is supported for local
    sources whose observed digest will subsequently be recorded by the caller.
    """
    source, destination = Path(source), Path(destination)
    part = Path(part) if part is not None else destination.with_name(destination.name + ".part")
    if type(size) is not int or size < 0:
        raise ValueError("Transfer size must be a nonnegative integer")
    if checksum is not None and (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)):
        raise ValueError("Transfer checksum must be a lowercase SHA-256 or None")
    for path in (source, destination, part):
        _regular(path)
    for left, right in ((source, destination), (source, part), (destination, part)):
        if _same_file(left, right):
            raise SafetyError(f"Transfer paths must not alias each other: {left}, {right}")

    with _open_regular(source) as src:
        before = os.fstat(src.fileno())
        if before.st_size != size:
            raise TransferError(f"{source.name}: local source size differs from manifest")
        if checksum and destination.exists() and destination.stat().st_size == size:
            if _digest(destination, size) == checksum:
                progress(f"{destination.name}: reusing verified copy")
                return checksum
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_parent = _directory_identity(destination.parent)
        part.parent.mkdir(parents=True, exist_ok=True)
        partial_parent = _directory_identity(part.parent)
        for path in (destination, part):
            _regular(path)
        _check_directory(destination.parent, destination_parent)
        _check_directory(part.parent, partial_parent)
        with _open_regular(part, writable=True) as output, durable_writer(output) as checkpoint:
            offset = os.fstat(output.fileno()).st_size
            valid = offset <= size
            checked = 0
            last_report = time.monotonic()
            if valid and offset:
                progress(f"{destination.name}: validating {offset:,} saved prefix bytes")
            while valid and checked < offset:
                amount = min(CHUNK_BYTES, offset - checked)
                previous = output.read(amount)
                original = src.read(amount)
                valid = len(previous) == amount and previous == original
                checked += len(previous)
                if time.monotonic() - last_report >= 5:
                    progress(f"{destination.name}: checked {checked:,} / {offset:,} saved prefix bytes")
                    last_report = time.monotonic()
            if not valid:
                progress(f"{destination.name}: saved prefix differs; restarting owned partial")
                output.seek(0)
                output.truncate(0)
                src.seek(0)
                offset = 0
            else:
                output.seek(offset)
                src.seek(offset)
            progress(f"{destination.name}: {'resuming copy' if offset else 'copying'} at {offset:,} / {size:,} bytes")
            while offset < size:
                block = src.read(min(CHUNK_BYTES, size - offset))
                if not block:
                    raise TransferError(f"{source.name}: source ended before {size} bytes")
                output.write(block)
                offset += len(block)
                if checkpoint.written(len(block)):
                    progress(f"{destination.name}: {offset:,} / {size:,} bytes")
            after = os.fstat(src.fileno())
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                raise TransferError(f"{source.name}: local source changed during transfer")

    digest = _digest(part, size)
    if checksum is not None and digest != checksum:
        raise TransferError(f"{destination.name}: SHA-256 mismatch; refusing completed copy")
    _check_directory(destination.parent, destination_parent)
    _check_directory(part.parent, partial_parent)
    for path in (destination, part):
        _regular(path)
    os.replace(part, destination)
    return digest
