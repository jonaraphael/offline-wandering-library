"""Probe published source pins without requesting any library resource body.

A header-only observation is not a content review. Complete pins may be proposed
only when exact identity byte size and an explicitly whole-file SHA-256 agree.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..safety import atomic_write, reject_symlinks
from .metadata import Fetcher
from .model import AcquisitionError

MAX_PROBES = 200
MAX_CHECKSUM_BYTES = 64 * 1024
HEAD_HEADERS = {"content-length", "content-type", "content-encoding", "content-range",
                "last-modified", "etag", "digest", "repr-digest", "content-digest",
                "x-amz-checksum-sha256", "x-amz-checksum-type"}


def source_url(url):
    if not isinstance(url, str):
        raise AcquisitionError("Source URL must be text")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.fragment or parts.port not in {None, 443}):
        raise AcquisitionError(f"Source probe requires an HTTPS identity: {url}")
    return url


class HeadRedirect(HTTPRedirectHandler):
    """urllib's default redirect handler can change a HEAD into a GET."""
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source_url(newurl)
        return Request(newurl, method="HEAD", headers=dict(req.headers))

    def http_error_302(self, req, fp, code, msg, headers):
        # The stock handler drains a redirect response with read(). Do not even
        # attempt that for these header-only probes, including malformed servers.
        location = headers.get("location", headers.get("Location", headers.get("URI")))
        if not location:
            return None
        try:
            hops = getattr(req, "_owl_redirect_hops", 0)
            if hops >= self.max_redirections:
                raise AcquisitionError("Source HEAD exceeded five redirects")
            new = self.redirect_request(req, fp, code, msg, headers, urljoin(req.full_url, location))
            new._owl_redirect_hops = hops + 1
        finally:
            fp.close()
        return self.parent.open(new, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _decode_sha256(value):
    try:
        digest = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return digest.hex() if len(digest) == 32 else None


def header_sha256(headers):
    """Ignore ETags, MD5/SHA-1, Content-Digest of empty HEAD and S3 composites."""
    headers = {key.lower(): value for key, value in headers.items()}
    digests = set()
    for name in ("repr-digest", "digest"):
        for item in headers.get(name, "").split(","):
            match = re.fullmatch(r"\s*sha-256\s*=\s*(:?)([A-Za-z0-9+/]+=*)\1\s*", item, re.I)
            if match:
                digest = _decode_sha256(match[2])
                if digest:
                    digests.add(digest)
    if headers.get("x-amz-checksum-type", "").upper() == "FULL_OBJECT":
        digest = _decode_sha256(headers.get("x-amz-checksum-sha256"))
        if digest:
            digests.add(digest)
    if len(digests) > 1:
        raise AcquisitionError("Conflicting whole-file SHA-256 response headers")
    return next(iter(digests), None)


def sidecar_sha256(data, *, source, checksum_url):
    """Read standard GNU/BSD SHA256 lists, requiring the exact target filename."""
    if len(data) > MAX_CHECKSUM_BYTES:
        raise AcquisitionError("Checksum sidecar exceeds its bound")
    filename = unquote(urlsplit(source).path.rsplit("/", 1)[-1])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise AcquisitionError("Checksum sidecar must be UTF-8 text") from error
    found = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[* ]?(.+)", line)
        if match and match[2] in {filename, "./" + filename}:
            found.add(match[1].lower())
        match = re.fullmatch(r"SHA256 \((.+)\) = ([0-9a-fA-F]{64})", line)
        if match and match[1] in {filename, "./" + filename}:
            found.add(match[2].lower())
        # A bare checksum is unambiguous only for a per-file sidecar, not SHA256SUMS.
        side_path = unquote(urlsplit(checksum_url).path)
        if re.fullmatch(r"[0-9a-fA-F]{64}", line) and side_path.endswith("/" + filename + ".sha256"):
            found.add(line.lower())
    if len(found) != 1:
        raise AcquisitionError("Checksum sidecar must name exactly one matching SHA-256")
    return next(iter(found))


class PinProbe:
    def __init__(self, cache_dir, *, offline=False, refresh=False, opener=None, fetcher=None, timeout=25):
        self.cache_dir = Path(cache_dir)
        self.offline, self.refresh, self.timeout = offline, refresh, timeout
        self.opener = opener or build_opener(HeadRedirect()).open
        self.fetcher = fetcher or Fetcher(self.cache_dir / "metadata", offline=offline, refresh=refresh)

    def _head(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / "head" / (key + ".json")
        reject_symlinks(path)
        if path.exists() and not self.refresh:
            if path.stat().st_size > 16384:
                raise AcquisitionError("Cached HEAD record exceeds bound")
            record = json.loads(path.read_text())
            if (record.get("url") != url or record.get("method") != "HEAD"
                    or record.get("body_read") is not False or not isinstance(record.get("headers"), dict)
                    or type(record.get("status")) is not int
                    or not all(isinstance(k, str) and isinstance(v, str)
                               for k, v in record["headers"].items())):
                raise AcquisitionError("Cached HEAD record does not match its identity")
            source_url(record.get("final_url"))
            return {**record, "cached": True}
        if self.offline:
            raise AcquisitionError(f"No cached HEAD metadata for {url}")
        request = Request(url, method="HEAD", headers={"Accept-Encoding": "identity",
                          "User-Agent": "Offline-Wandering-Library/0.1 metadata pin probe"})
        try:
            response = self.opener(request, timeout=self.timeout)
        except HTTPError as error:
            response = error
        # Never call read() here, including errors. All redirects preserve HEAD.
        with response:
            final = source_url(response.geturl())
            headers = {key.lower(): str(value) for key, value in response.headers.items()
                       if key.lower() in HEAD_HEADERS}
            if any(len(value) > 2048 for value in headers.values()):
                raise AcquisitionError("Source response header exceeds bound")
            record = {"url": url, "final_url": final, "method": "HEAD", "body_read": False,
                      "status": response.status, "headers": headers,
                      "checked_at": datetime.now(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
        return {**record, "cached": False}

    def probe(self, request):
        url = source_url(request["url"])
        record = {"id": request["id"], "source_url": url, "status": "pending", "body_downloads": 0,
                  "size_bytes": None, "sha256": None, "blockers": [], "evidence": []}
        try:
            head = self._head(url)
            record["evidence"].append(head)
            headers = head["headers"]
            if head["status"] != 200:
                raise AcquisitionError(f"Source HEAD returned HTTP {head['status']}; availability is unresolved")
            if headers.get("content-encoding", "identity").lower() != "identity" or "content-range" in headers:
                raise AcquisitionError("Source HEAD does not describe an entire identity representation")
            length = headers.get("content-length", "")
            if not re.fullmatch(r"[0-9]+", length) or int(length) <= 0:
                raise AcquisitionError("Exact positive Content-Length is unavailable")
            record["size_bytes"] = int(length)
            if request.get("expected_size_bytes", record["size_bytes"]) != record["size_bytes"]:
                record["blockers"].append("Source size changed from accepted metadata")
            digest = header_sha256(headers)
            if request.get("checksum_url"):
                checksum_url = source_url(request["checksum_url"])
                data = self.fetcher.fetch(checksum_url, kind="sha256-sidecar", max_bytes=MAX_CHECKSUM_BYTES)
                published = sidecar_sha256(data, source=url, checksum_url=checksum_url)
                record["evidence"].extend(self.fetcher.evidence[-1:])
                if digest and published != digest:
                    raise AcquisitionError("Header and sidecar SHA-256 disagree")
                digest = published
            if digest is None:
                raise AcquisitionError("Publisher metadata supplies no whole-file SHA-256; ETag/MD5/SHA-1 are not pins")
            if request.get("expected_sha256", digest) != digest:
                raise AcquisitionError("Source SHA-256 changed from accepted metadata")
            if not record["blockers"]:
                record.update(sha256=digest, status="proposed")
        except (AcquisitionError, URLError, OSError, ValueError) as error:
            record["blockers"].append(str(error)[:500])
        return record


def probe_manifest(document, probe, *, ids=None):
    requests = document.get("requests")
    if document.get("schema_version") != 1 or not isinstance(requests, list) or not 0 < len(requests) <= MAX_PROBES:
        raise AcquisitionError(f"Pin request manifest must contain 1–{MAX_PROBES} requests")
    seen = set()
    for request in requests:
        if not isinstance(request, dict) or not isinstance(request.get("id"), str) or not request["id"]:
            raise AcquisitionError("Every source probe requires an id")
        if request["id"] in seen:
            raise AcquisitionError("Duplicate source probe id")
        seen.add(request["id"])
        source_url(request.get("url"))
        if "expected_size_bytes" in request and (type(request["expected_size_bytes"]) is not int
                                                  or request["expected_size_bytes"] <= 0):
            raise AcquisitionError("Expected source size must be an exact positive integer")
        if "expected_sha256" in request and not re.fullmatch(r"[0-9a-f]{64}", str(request["expected_sha256"])):
            raise AcquisitionError("Expected source checksum must be a whole-file lowercase SHA-256")
    if ids and not set(ids) <= seen:
        raise AcquisitionError("Requested source probe id is absent from manifest")
    records = [probe.probe(request) for request in requests if not ids or request["id"] in ids]
    return {"schema_version": 1, "operation": "source-pin-probe", "body_downloads": 0,
            "records": records, "proposed_count": sum(r["status"] == "proposed" for r in records),
            "pending_count": sum(r["status"] != "proposed" for r in records)}


def stackoverflow_input_candidates(document, metadata_evidence):
    """Freeze the four required publisher dump identities, retaining weak hash labels.

    This deliberately emits discovery candidates, never catalog assets. The archive
    and unpacked XML hashes, metadata completeness and illustration pins still need
    verification before the static-corpus adapter can consume them.
    """
    if metadata_evidence.get("url") != "https://archive.org/metadata/stackexchange":
        raise AcquisitionError("Expected the original publisher Stack Exchange item metadata")
    roles = {"posts": "Posts", "comments": "Comments", "users": "Users", "links": "PostLinks"}
    candidates = []
    for role, member in roles.items():
        filename = f"stackoverflow.com-{member}.7z"
        matches = [item for item in document.get("files", []) if item.get("name") == filename
                   and item.get("source") == "original"]
        if len(matches) != 1:
            raise AcquisitionError(f"Exactly one original publisher file is required: {filename}")
        item = matches[0]
        if not re.fullmatch(r"[0-9]+", str(item.get("size", ""))) or int(item["size"]) <= 0:
            raise AcquisitionError(f"Missing exact archive size: {filename}")
        hashes = {algorithm: item[algorithm] for algorithm in ("md5", "sha1", "crc32") if algorithm in item}
        candidates.append({"id": f"stackoverflow_publisher_{role}", "input_role": role,
                           "source_url": f"https://archive.org/download/stackexchange/{filename}",
                           "archive_filename": filename, "expected_member": member + ".xml",
                           "size_bytes": int(item["size"]), "publisher_mtime": item.get("mtime"),
                           "publisher_checksums": hashes, "sha256": None,
                           "status": "pending_whole_file_sha256_and_xml_evidence"})
    return {"schema_version": 1, "resource_ids": ["stackoverflow-durable", "stackoverflow-legacy"],
            "source_item": "stackexchange", "metadata_evidence": metadata_evidence,
            "candidates": candidates, "download_bytes": sum(item["size_bytes"] for item in candidates),
            "body_downloads": 0,
            "blockers": ["Publisher MD5/SHA-1/CRC32 checksums cannot stand in for whole-file SHA-256 pins.",
                         "Pinned safe 7z extraction and exact unpacked XML pins remain required.",
                         "Per-post licenses, author names, comments, duplicate links and image dependencies are unverified.",
                         "Durable/legacy question selection and full document review remain required."]}
