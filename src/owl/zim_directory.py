"""Read ZIM directory records without fetching archive content clusters.

The URL pointer order identifies an entry; its physical offset identifies where
to read it. Version 6.1+ uses namespace C for user content, older writers use A.
"""
from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import re
from struct import Struct
import sys
from urllib.request import Request, urlopen


HEADER = Struct("<IHH16sIIQQQQIIQ")
DIRENT = Struct("<HBBI")
REDIRECT = Struct("<I")
BLOCK = 8 * 1024 * 1024
MAX_ENTRY = 65536
MAGIC = 0x044D495A
ARTICLE_MIME = {"text/html", "text/plain", "application/pdf", "application/epub+zip",
                "application/xhtml+xml"}


class RangeSource:
    """Bounded, edition-consistent reads of a published Kiwix ZIM."""
    def __init__(self, asset, *, budget=2_500_000_000, timeout=40):
        self.url = asset["source_url"]
        if not self.url.startswith("https://mirror.download.kiwix.org/zim/"):
            raise ValueError("Remote extraction requires the catalog's Kiwix mirror URL")
        self.size = asset["size_bytes"]
        self.budget = budget
        self.timeout = timeout
        self.etag = None
        self.receipts = []

    def read(self, start, length):
        if not 0 <= start < start + length <= self.size or length > BLOCK:
            raise ValueError("Invalid ZIM byte range")
        if length > self.budget:
            raise ValueError("ZIM range budget exceeded")
        end = start + length - 1
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity",
                   "Origin": "https://jonaraphael.com"}
        if self.etag is not None:
            headers["If-Match"] = self.etag
        self.budget -= length
        with urlopen(Request(self.url, headers=headers), timeout=self.timeout) as response:
            etag = response.headers.get("ETag", "")
            if (response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{self.size}"
                    or response.url != self.url or not re.fullmatch(r'"[^"]+"', etag)
                    or self.etag not in (None, etag)
                    or response.headers.get("Content-Encoding", "identity") != "identity"):
                raise ValueError(f"Unpinned or unexpected range response at {start}: "
                                 f"{response.status} {response.headers.get('Content-Range')}")
            data = response.read(length + 1)
        if len(data) != length:
            raise ValueError(f"Short ZIM byte range at {start}")
        self.etag = etag
        self.receipts.append([start, length, sha256(data).hexdigest()])
        return data


@dataclass(frozen=True)
class Entry:
    title: str
    path: str
    mime: str
    redirect: bool
    offset: int | None = None
    target_offset: int | None = None


class Directory:
    def __init__(self, read, size):
        self.read = read
        magic, major, self.minor, uuid, self.count, _, self.pointers, _, _, mime, self.main, _, end = (
            HEADER.unpack(read(0, HEADER.size)))
        self.limits = end
        self.uuid = uuid.hex()
        if (magic != MAGIC or major not in (5, 6) or not self.count
                or not HEADER.size <= mime < self.pointers < end or end + 16 != size
                or self.pointers + self.count * 8 > end):
            raise ValueError("Unsupported ZIM header or pointer table")
        self.namespaces = {"C"} if major == 6 and self.minor >= 1 else {"A"}
        mimes = read(mime, min(MAX_ENTRY, self.pointers - mime))
        if b"\0\0" not in mimes:
            raise ValueError("Unterminated ZIM MIME table")
        self.mimes = mimes.split(b"\0\0", 1)[0].decode("ascii").split("\0")
        self.counts = Counter()
        self.main_path = ""

    def __iter__(self):
        if self.count > 50_000_000:
            raise ValueError("Complete directory exceeds the in-memory pointer scan limit")
        pointers = array("Q")
        remaining = self.count * 8
        table = self.pointers
        while remaining:
            count = min(BLOCK, remaining)
            pointers.frombytes(self.read(table, count))
            table += count
            remaining -= count
        if sys.byteorder != "little":
            pointers.byteswap()
        main = pointers[self.main] if self.main < self.count else -1
        block_start = block_end = 0
        data = b""
        previous = -1
        for offset in sorted(pointers):
            if offset == previous or not HEADER.size <= offset < self.limits:
                raise ValueError("Invalid or duplicate ZIM directory pointer")
            previous = offset
            upper = self.pointers if offset < self.pointers else self.limits
            if not block_start <= offset < block_end or (offset + MAX_ENTRY > block_end and block_end < upper):
                block_start = offset
                data = self.read(offset, min(BLOCK, upper - offset))
                block_end = offset + len(data)
            entry = self.entry(data, offset - block_start, offset == main, pointers=pointers, offset=offset)
            if entry is not None:
                yield entry

    def sample(self, windows=24, rows=4096):
        """Read bounded, evenly spaced groups of actual URL-order entries."""
        if not 0 <= windows <= 32 or not 1 <= rows <= 4096:
            raise ValueError("Invalid directory sample size")
        main = None
        if self.main < self.count:
            pointer = array("Q")
            pointer.frombytes(self.read(self.pointers + 8 * self.main, 8))
            if sys.byteorder != "little":
                pointer.byteswap()
            offset = pointer[0]
            if HEADER.size <= offset < self.limits:
                main = self.entry(self.read(offset, min(MAX_ENTRY, self.limits - offset)), 0, True, include_main=True)
        if not windows:
            if main is not None:
                yield main
            return
        step = (self.count + windows - 1) // windows
        for begin in range(0, self.count, step):
            start = max(begin, min(self.count - rows, begin + step // 2 - rows // 2))
            items = min(rows, self.count - start, step)
            pointers = array("Q")
            pointers.frombytes(self.read(self.pointers + start * 8, items * 8))
            if sys.byteorder != "little":
                pointers.byteswap()
            data = b""
            location = 0
            for offset in sorted(pointers):
                if not HEADER.size <= offset < self.limits:
                    raise ValueError("Invalid ZIM sample pointer")
                upper = self.pointers if offset < self.pointers else self.limits
                if not location <= offset < location + len(data) or (offset + MAX_ENTRY > location + len(data) and location + len(data) < upper):
                    location = offset
                    data = self.read(offset, min(BLOCK, upper - offset))
                entry = self.entry(data, offset - location, False)
                if entry is not None:
                    yield entry

    def entry(self, data, index, main, *, include_main=False, pointers=None, offset=None):
        mime, _, namespace, _ = DIRENT.unpack_from(data, index)
        namespace = chr(namespace)
        self.counts[namespace] += 1
        redirect = mime == 0xffff
        content = mime < len(self.mimes) and self.mimes[mime].split(";", 1)[0] in ARTICLE_MIME
        if not main and (namespace not in self.namespaces or not (redirect or content)):
            return None
        if not (redirect or mime < len(self.mimes)):
            return None
        target_offset = None
        if redirect and pointers is not None:
            target, = REDIRECT.unpack_from(data, index + DIRENT.size)
            if target >= len(pointers):
                raise ValueError("Invalid ZIM redirect target")
            target_offset = pointers[target]
        index += DIRENT.size + (4 if redirect else 8)
        limit = min(index + MAX_ENTRY, len(data))
        end = data.find(b"\0", index, limit)
        stop = data.find(b"\0", end + 1, limit) if end >= 0 else -1
        if stop < 0:
            raise ValueError("Unterminated ZIM directory record")
        try:
            path = data[index:end].decode("utf-8")
            title = data[end + 1:stop].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 in ZIM directory record") from error
        if self.namespaces == {"A"}:
            path = namespace + "/" + path
        if main:
            self.main_path = path
        if path and (include_main or namespace in self.namespaces):
            return Entry(title or path.rsplit("/", 1)[-1].replace("_", " "), path,
                         "redirect" if redirect else self.mimes[mime], redirect, offset, target_offset)
        return None
