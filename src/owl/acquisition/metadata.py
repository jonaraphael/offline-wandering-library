"""Bounded HTTPS metadata cache. This module never acquires library bodies."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote, urljoin, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..safety import atomic_write, reject_symlinks
from .model import AcquisitionError

MAX_METADATA_BYTES = 8 * 1024 * 1024
# The supported publisher CSV is larger than ordinary discovery pages. Only
# this exact metadata identity gets a separate, still finite allowance.
CATALOG_LIMITS = {"https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv": 64 * 1024 * 1024}
BODY_SUFFIX = re.compile(r"\.(?:pdf|zim|zip|epub|gz|xz|bz2|7z|tar|mp[34]|webm|ogg|wav|png|jpe?g|gif|apk|exe|dmg)$", re.I)


def metadata_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or BODY_SUFFIX.search(unquote(parsed.path))):
        raise AcquisitionError(f"Refusing non-metadata HTTPS URL: {url}")
    return url


class _MetadataRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        metadata_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_302(self, req, fp, code, msg, headers):
        # urllib otherwise drains redirect bodies with an unbounded read(),
        # before Fetcher's response length/type safeguards can run.
        location = headers.get("location", headers.get("Location", headers.get("URI")))
        if not location:
            return None
        try:
            hops = getattr(req, "_owl_metadata_redirect_hops", 0)
            if hops >= self.max_redirections:
                raise AcquisitionError("Metadata request exceeded five redirects")
            new = self.redirect_request(req, fp, code, msg, headers, urljoin(req.full_url, location))
            if new is None:
                raise AcquisitionError("Unsupported metadata redirect")
            new._owl_metadata_redirect_hops = hops + 1
        finally:
            fp.close()
        return self.parent.open(new, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class Fetcher:
    def __init__(self, cache_dir: Path, *, offline=False, refresh=False, opener=None, timeout=30):
        self.cache_dir = Path(cache_dir)
        self.offline, self.refresh = offline, refresh
        self.opener, self.timeout = opener or build_opener(_MetadataRedirect()).open, timeout
        self.evidence = []

    def fetch(self, url, *, kind="metadata", max_bytes=None):
        metadata_url(url)
        limit = MAX_METADATA_BYTES if max_bytes is None else max_bytes
        if type(limit) is not int or not 0 < limit <= CATALOG_LIMITS.get(url, MAX_METADATA_BYTES):
            raise AcquisitionError("Metadata limit exceeds this publisher metadata allowance")
        key = hashlib.sha256(url.encode()).hexdigest()
        record = self.cache_dir / (key + ".json")
        failure = self.cache_dir / (key + ".failure.json")
        reject_symlinks(record)
        reject_symlinks(failure)
        if failure.exists() and not self.refresh:
            if failure.stat().st_size > 16384:
                raise AcquisitionError("Cached failure exceeds metadata bound")
            evidence = json.loads(failure.read_text())
            if evidence.get("url") != url:
                raise AcquisitionError("Cached failure URL mismatch")
            self.evidence.append({**evidence, "cached": True})
            raise AcquisitionError(f"Cached HTTP {evidence['status']} for {url}; use --refresh to recheck")
        if record.exists() and not self.refresh:
            if record.stat().st_size > 16384:
                raise AcquisitionError("Cached metadata exceeds its bound")
            evidence = json.loads(record.read_text())
            digest = evidence.get("sha256", "")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise AcquisitionError("Cached metadata checksum is invalid")
            body = self.cache_dir / "objects" / (digest + ".bin")
            reject_symlinks(body)
            if not body.is_file() or body.stat().st_size > limit:
                raise AcquisitionError("Cached metadata body is missing or exceeds its bound")
            data = body.read_bytes()
            if evidence.get("url") != url or hashlib.sha256(data).hexdigest() != digest:
                raise AcquisitionError("Cached metadata failed integrity verification")
            self.evidence.append({**evidence, "cached": True})
            return data
        if self.offline:
            raise AcquisitionError(f"No verified cached metadata for {url}")
        request = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "Offline-Wandering-Library/0.1 metadata acquisition"})
        try:
            response = self.opener(request, timeout=self.timeout)
        except HTTPError as error:
            evidence = {"url": url, "kind": kind, "status": error.code,
                        "checked_at": datetime.now(timezone.utc).isoformat(), "body_read": False}
            self.evidence.append({**evidence, "cached": False})
            if 400 <= error.code < 500 and error.code not in {408, 425, 429}:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(failure, (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode())
            error.close()
            raise AcquisitionError(f"Metadata HTTP {error.code} for {url}") from error
        with response:
            final = response.geturl()
            metadata_url(final)
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise AcquisitionError("Compressed metadata response is unsupported")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime and not (mime.startswith("text/") or mime.endswith(("json", "xml")) or mime in {"application/javascript"}):
                raise AcquisitionError(f"Refusing resource-body content type: {mime}")
            length = response.headers.get("Content-Length")
            if length is not None and not 0 <= int(length) <= limit:
                raise AcquisitionError("Metadata response exceeds bound")
            chunks, size = [], 0
            deadline = time.monotonic() + self.timeout
            read = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() > deadline:
                    raise AcquisitionError(f"Metadata response exceeded time budget: {url}")
                chunk = read(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise AcquisitionError(f"Metadata response exceeds bound: {url}")
            data = b"".join(chunks)
            if length is not None and len(data) != int(length):
                raise AcquisitionError(f"Incomplete metadata response: {url}")
            if data.startswith((b"%PDF-", b"PK\x03\x04", b"ZIM\x04", b"\x1f\x8b")):
                raise AcquisitionError("Resource body masquerades as metadata")
            evidence = {"url": url, "kind": kind, "final_url": final, "status": getattr(response, "status", 200),
                        "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "checked_at": datetime.now(timezone.utc).isoformat(), "content_type": mime}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        body = self.cache_dir / "objects" / (evidence["sha256"] + ".bin")
        reject_symlinks(body)
        body.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(body, data)
        atomic_write(record, (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode())
        failure.unlink(missing_ok=True)
        self.evidence.append({**evidence, "cached": False})
        return data
