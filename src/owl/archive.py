"""Pinned ZIP members streamed to ordinary files during a serialized OWL build.

No archive paths become filesystem paths: the reviewed catalog supplies every
destination. A full central-directory audit rejects unsafe unselected entries
as well. The source and each output have independent size/SHA-256 pins.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import struct
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .catalog import is_document
from .safety import SafetyError, reject_symlinks, validate_relative
from .transfer import (_check_directory, _directory_identity, _open_regular,
                       durable_writer, _digest)

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPLICIT_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_FILES = 20_000
MAX_ITEM_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_RATIO = 1000
BLOCK = 1024 * 1024
RESERVE = 16 * 1024 * 1024


class ArchiveError(SafetyError):
    pass


def document_assets(assets: list[dict]) -> list[dict]:
    """Keep dependencies in inventory/checksums, but out of search/title shelves."""
    return [asset for asset in assets if is_document(asset)]


def order_archive_assets(assets: list[dict]) -> list[dict]:
    """Require explicitly selected ZIP inputs and place them before outputs."""
    by_id = {asset["id"]: asset for asset in assets}
    result, emitted = [], set()
    for asset in assets:
        member = asset.get("archive_member")
        if member:
            source = by_id.get(member["source_asset_id"])
            if not source or source.get("archive_member") or source["format"].lower() != "zip":
                raise ArchiveError(f"{asset['id']}: select its ZIP source asset {member['source_asset_id']} as well")
            if source["size_bytes"] > MAX_ARCHIVE_BYTES or asset["size_bytes"] > MAX_ITEM_BYTES:
                raise ArchiveError(f"{asset['id']}: ZIP source/member exceeds supported build-time size limits")
            if source["id"] not in emitted:
                result.append(source)
                emitted.add(source["id"])
        if asset["id"] not in emitted:
            result.append(asset)
            emitted.add(asset["id"])
    return result


def _identity(handle):
    info = os.fstat(handle.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class ZipSource:
    """Verified, audited source held open while multiple members are extracted.

    The caller owns destination/partial files and holds the normal build lock.
    Interrupted members restart from the beginning; completed members are reused
    by the builder's normal checksum check. No unbounded decompression occurs.
    """

    def __init__(self, path: Path, asset: dict, *, max_archive_bytes=None, allow_long_member_names=False):
        self.path, self.asset = Path(path), asset
        self.handle = self.archive = None
        self.allow_long_member_names = allow_long_member_names is True
        # Course packages may explicitly reserve a larger compressed input.
        # All member, expansion, directory and ratio limits remain unchanged;
        # ordinary document callers retain the original 128 MiB input bound.
        if max_archive_bytes is None:
            max_archive_bytes = MAX_ARCHIVE_BYTES
        if type(max_archive_bytes) is not int or not 0 < max_archive_bytes <= MAX_EXPLICIT_PACKAGE_BYTES:
            raise ArchiveError('Explicit ZIP package input bound must be positive and at most 512 MiB')
        if (type(asset.get("size_bytes")) is not int or
                not 0 < asset["size_bytes"] <= max_archive_bytes or not asset.get("sha256")):
            raise ArchiveError("ZIP source needs a pinned size and hash within the configured input limit")
        try:
            self.handle = _open_regular(self.path)
            self.identity = _identity(self.handle)
            if self.identity[2] != asset["size_bytes"]:
                raise ArchiveError("ZIP source size differs from its pin")
            digest = hashlib.sha256()
            count = 0
            for block in iter(lambda: self.handle.read(BLOCK), b""):
                count += len(block)
                if count > asset["size_bytes"]:
                    raise ArchiveError("ZIP source grew beyond its pinned size")
                digest.update(block)
            if digest.hexdigest() != asset["sha256"]:
                raise ArchiveError("ZIP source SHA-256 differs from its pin")
            self.check_source()
            self._preflight_directory()
            self.handle.seek(0)
            self.archive = ZipFile(self.handle)
            self.entries = self._audit()
        except BadZipFile as error:
            self.close()
            raise ArchiveError("Invalid ZIP source") from error
        except BaseException:
            self.close()
            raise

    def _preflight_directory(self):
        """Bound entry allocation before ZipFile constructs its ZipInfo list.

        Ordinary single-disk ZIPs suffice for documentation packages. ZIP64,
        split disks, appended records and self-extracting wrappers are rejected.
        Walk fixed-size headers without allocating names or member contents.
        """
        size = self.identity[2]
        self.handle.seek(0)
        if self.handle.read(4) not in {b'PK\x03\x04', b'PK\x05\x06'}:
            raise ArchiveError("ZIP has a prefixed/self-extracting wrapper")
        tail_size = min(size, 65535 + 22)
        self.handle.seek(size - tail_size)
        tail = self.handle.read(tail_size)
        offset = tail.rfind(b'PK\x05\x06')
        if offset < 0 or len(tail) - offset < 22:
            raise ArchiveError("ZIP end-of-directory record is missing")
        _, disk, directory_disk, disk_count, count, length, start, comment = struct.unpack(
            '<4s4H2LH', tail[offset:offset + 22])
        end = size - tail_size + offset
        if (disk or directory_disk or disk_count != count or count == 65535 or
                count > MAX_FILES or start == 0xffffffff or length == 0xffffffff or
                offset + 22 + comment != len(tail) or start + length != end):
            raise ArchiveError("ZIP directory exceeds limits or uses an unsupported layout")
        cursor = start
        observed = 0
        while cursor < end:
            self.handle.seek(cursor)
            header = self.handle.read(46)
            if len(header) != 46 or header[:4] != b'PK\x01\x02':
                raise ArchiveError("Invalid ZIP central-directory header")
            name_size, extra_size, comment_size = struct.unpack('<3H', header[28:34])
            cursor += 46 + name_size + extra_size + comment_size
            observed += 1
            if observed > MAX_FILES or cursor > end:
                raise ArchiveError("ZIP central directory exceeds entry/size limits")
        if cursor != end or observed != count:
            raise ArchiveError("ZIP central-directory entry count is inconsistent")

    def _audit(self):
        entries, spellings, files, directories, seen_entries = {}, {}, set(), set(), set()
        infos = self.archive.infolist()
        if len(infos) > MAX_FILES:
            raise ArchiveError("ZIP exceeds 20,000 entries")
        total = 0
        for info in infos:
            if info.orig_filename != info.filename:
                raise ArchiveError("ZIP contains a truncated/NUL filename")
            name = info.filename[:-1] if info.is_dir() else info.filename
            checked_name = name
            if self.allow_long_member_names:
                # Original course caption filenames can exceed our destination
                # component limit. Never materialize those names: reviewed
                # outputs still supply independently validated destinations.
                # This exception accepts only bounded simple ASCII components;
                # traversal, wrappers, links, collisions and expansion checks
                # remain identical to the ordinary document path.
                if len(name) > 1024:
                    raise ArchiveError('ZIP source member path exceeds 1024 bytes')
                checked_parts = []
                for part in name.split('/'):
                    if len(part) > 100:
                        if not re.fullmatch(r'[A-Za-z0-9_().@+=%, -]{101,255}', part) or part.endswith(('.', ' ')):
                            raise ArchiveError('Unsupported long ZIP source component')
                        checked_parts.append(hashlib.sha256(part.encode()).hexdigest())
                    else:
                        checked_parts.append(part)
                checked_name = '/'.join(checked_parts)
            validate_relative(checked_name)
            parts = name.split("/")
            for count in range(1, len(parts) + 1):
                prefix = "/".join(parts[:count])
                previous = spellings.setdefault(prefix.casefold(), prefix)
                if previous != prefix:
                    raise ArchiveError("ZIP contains case-colliding paths")
            key = name.casefold()
            parents = {"/".join(parts[:n]).casefold() for n in range(1, len(parts))}
            if key in seen_entries or parents & files:
                raise ArchiveError("ZIP contains duplicate or conflicting paths")
            seen_entries.add(key)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ArchiveError("ZIP contains a symlink or special file")
            if info.flag_bits & 1 or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                raise ArchiveError("ZIP uses encryption or an unsupported compression method")
            if info.is_dir():
                if key in files or info.file_size:
                    raise ArchiveError("ZIP contains a conflicting or nonempty directory")
                directories.add(key)
            else:
                if key in files or key in directories or parents & files or mode == stat.S_IFDIR:
                    raise ArchiveError("ZIP contains duplicate or conflicting file paths")
                if info.file_size > MAX_ITEM_BYTES or info.file_size > MAX_RATIO * max(1, info.compress_size):
                    raise ArchiveError("ZIP member exceeds size/compression-ratio limits")
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise ArchiveError("ZIP exceeds 512 MiB expanded-size limit")
                files.add(key)
                entries[name] = info
            directories.update(parents)
        return entries

    def check_source(self):
        reject_symlinks(self.path)
        if (_identity(self.handle) != self.identity or
                (self.path.stat().st_dev, self.path.stat().st_ino) != self.identity[:2]):
            raise ArchiveError("ZIP source changed during extraction")

    def extract(self, asset: dict, destination: Path, *, part: Path, progress=print) -> str:
        member = asset["archive_member"]
        if member["source_asset_id"] != self.asset["id"]:
            raise ArchiveError("ZIP member refers to a different source")
        self.check_source()
        info = self.entries.get(member["path"])
        if info is None or info.file_size != asset["size_bytes"]:
            raise ArchiveError(f"{asset['id']}: ZIP member missing or size differs from its pin")
        destination, part = Path(destination), Path(part)
        for path in (destination, part):
            reject_symlinks(path)
        if (os.path.abspath(destination).casefold() == os.path.abspath(part).casefold() or
                any(os.path.abspath(p).casefold() == os.path.abspath(self.path).casefold()
                    for p in (destination, part))):
            raise ArchiveError("ZIP source, destination and partial must not alias")
        destination.parent.mkdir(parents=True, exist_ok=True)
        part.parent.mkdir(parents=True, exist_ok=True)
        destination_parent = _directory_identity(destination.parent)
        partial_parent = _directory_identity(part.parent)
        if shutil.disk_usage(part.parent).free < info.file_size + RESERVE:
            raise ArchiveError("Insufficient space for ZIP member and working reserve")
        count, digest = 0, hashlib.sha256()
        progress(f"EXTRACT {asset['id']}: {member['path']}")
        try:
            with self.archive.open(info) as source, _open_regular(part, writable=True) as output, durable_writer(output) as checkpoint:
                output.seek(0)
                output.truncate(0)
                while block := source.read(min(BLOCK, info.file_size - count + 1)):
                    count += len(block)
                    if count > info.file_size:
                        raise ArchiveError("ZIP member expands beyond pinned size")
                    output.write(block)
                    digest.update(block)
                    checkpoint.written(len(block))
        except (BadZipFile, EOFError, RuntimeError) as error:
            raise ArchiveError(f"Invalid ZIP member: {member['path']}") from error
        if count != info.file_size or digest.hexdigest() != asset["sha256"]:
            raise ArchiveError(f"{asset['id']}: extracted member SHA-256/size mismatch")
        if _digest(part, count) != asset["sha256"]:
            raise ArchiveError("ZIP output failed readback verification")
        self.check_source()
        _check_directory(destination.parent, destination_parent)
        _check_directory(part.parent, partial_parent)
        reject_symlinks(destination)
        # Destination ownership was established by normal build preflight.
        if destination.exists() and not destination.is_file():
            raise ArchiveError("ZIP destination is not a regular file")
        os.replace(part, destination)
        return asset["sha256"]

    def close(self):
        if self.archive is not None:
            self.archive.close()
        if self.handle is not None:
            self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
