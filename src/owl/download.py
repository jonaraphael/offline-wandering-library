"""Streaming, resumable downloads. Completed bytes are always hashed before use."""
from __future__ import annotations

import http.client
import errno
import json
import os
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, url2pathname, urlopen

from .safety import atomic_write, reject_symlinks, safe_path, sha256_file
from .transfer import (ChecksumMismatchError, TransferError, _check_directory, _directory_identity,
                       _open_regular, durable_writer, resume_copy)

USER_AGENT = "Offline-Wandering-Library/0.1 (+offline library builder)"


class DownloadError(RuntimeError):
    pass


class TransientDownloadError(DownloadError):
    """A bounded transport failure that a saved build job may retry unchanged."""


class MissingSourceError(DownloadError):
    """An explicitly opted-in acquisition stopped at an HTTP 404 or 410."""

    def __init__(self, source_id, requested_url, http_status):
        self.requested_url = requested_url
        self.http_status = http_status
        super().__init__(f"{source_id}: source unavailable: HTTP {http_status}")


def _transient(error: BaseException) -> bool:
    if isinstance(error, HTTPError):
        return error.code in {408, 425, 429, 500, 502, 503, 504}
    if isinstance(error, ssl.SSLCertVerificationError):
        return False
    if isinstance(error, URLError):
        return not isinstance(error.reason, ssl.SSLCertVerificationError)
    if isinstance(error, (TransientDownloadError, TimeoutError, ConnectionError, http.client.HTTPException)):
        return True
    return isinstance(error, OSError) and error.errno in {
        None, errno.ECONNRESET, errno.ECONNREFUSED, errno.ECONNABORTED,
        errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPIPE}


def verified(path: Path, size: int, checksum: str | None) -> bool:
    reject_symlinks(path)
    return bool(checksum and path.is_file() and path.stat().st_size == size and sha256_file(path) == checksum)


def inspect_zim_parts(paths, layout, checksum):
    """Return per-part pins only when the ordered on-disk bytes match the whole pin."""
    from hashlib import sha256
    from .verify import file_hash

    whole = sha256()
    parts = []
    for path, row in zip(paths, layout, strict=True):
        reject_symlinks(path)
        if not path.is_file() or path.stat().st_size != row["bytes"]:
            return None
        parts.append({**row, "sha256": file_hash(path, whole)})
    return parts if whole.hexdigest() == checksum else None


def _local_source(parsed, repo_root):
    if parsed.scheme == "repo":
        return safe_path(repo_root, (parsed.netloc + parsed.path).lstrip("/"))
    if parsed.netloc not in {"", "localhost"} or parsed.path.startswith("//"):
        raise DownloadError("File sources must be local file URLs, not remote authorities or UNC paths")
    # Convert a Windows drive prefix and decode percent escapes exactly once.
    return Path(url2pathname(parsed.path))


def download_split_zim(asset, layout, destination, staged, *, repo_root, cached=None, progress=print):
    """Stream a pinned ZIM into owned partials without allocating a whole file."""
    from contextlib import closing

    def write_parts(source):
        for path, row in zip(staged, layout, strict=True):
            with _open_regular(path, writable=True) as handle, durable_writer(handle) as checkpoint:
                handle.truncate(0)
                left = row["bytes"]
                while left:
                    block = source.read(min(left, 1024 * 1024))
                    if not block:
                        raise TransientDownloadError("archive ended before its pinned byte count")
                    handle.write(block)
                    left -= len(block)
                    checkpoint.written(len(block))
            progress(f"{asset['id']}: wrote {row['start'] + row['bytes']:,} / {asset['size_bytes']:,} bytes")
        if source.read(1):
            raise DownloadError("archive exceeds its pinned byte count")
        parts = inspect_zim_parts(staged, layout, asset["sha256"])
        if parts is None:
            raise ChecksumMismatchError(f"{asset['id']}: split archive SHA-256 mismatch")
        return parts

    def open_source(url, headers):
        parsed = urlsplit(url)
        if parsed.scheme in {"repo", "file"}:
            return _open_regular(_local_source(parsed, repo_root))
        response = urlopen(Request(url, headers=headers), timeout=60)
        if (response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity" or
                (parsed.scheme == "https" and urlsplit(response.url).scheme != "https")):
            response.close()
            raise DownloadError("expected a full, unencoded archive response")
        return response

    # An interruption during publication can leave verified parts in both
    # locations. Reassemble that staging set before requesting bytes again.
    candidates = [partial if partial.is_file() else final
                  for partial, final in zip(staged, destination, strict=True)]
    parts = inspect_zim_parts(candidates, layout, asset["sha256"])
    if parts is None:
        sources = list(dict.fromkeys([asset["source_url"], *asset.get("mirrors", [])]))
        if cached is not None and cached.is_file():
            sources.insert(0, cached.as_uri())
        headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
        last_error = None
        for url in sources:
            for attempt in range(3):
                try:
                    request_headers = headers if attempt == 0 else {"Accept-Encoding": "identity"}
                    with closing(open_source(url, request_headers)) as stream:
                        parts = write_parts(stream)
                    break
                except (OSError, http.client.HTTPException, DownloadError, TransferError) as error:
                    last_error = error
                    if isinstance(error, HTTPError):
                        error.close()
                    if attempt == 2 or not (_transient(error) or isinstance(error, HTTPError) and error.code == 403):
                        break
                    time.sleep(2 ** attempt)
            if parts is not None:
                break
        if parts is None:
            # A complete-looking rejected set must never be promoted on retry.
            for path in staged:
                path.unlink(missing_ok=True)
            error_type = TransientDownloadError if _transient(last_error) else DownloadError
            raise error_type(f"{asset['id']}: split ZIM download failed: {last_error}") from last_error
    for partial, final in zip(staged, destination, strict=True):
        if partial.exists():
            reject_symlinks(partial)
            reject_symlinks(final)
            os.replace(partial, final)
    return parts


def _complete(part: Path, asset: dict) -> str:
    if part.stat().st_size != asset["size_bytes"]:
        error = TransientDownloadError if part.stat().st_size < asset["size_bytes"] else DownloadError
        raise error(f"{asset['id']}: size mismatch: {part.stat().st_size} != {asset['size_bytes']}")
    digest = sha256_file(part)
    if asset["sha256"] and digest != asset["sha256"]:
        raise ChecksumMismatchError(f"{asset['id']}: SHA-256 mismatch; refusing completed download")
    return digest


def capture_bounded_response(asset: dict, destination: Path, *, timeout=25, response_evidence=None):
    """Quarantine one unknown-length response; never resume or imply source acceptance.

    This is only for explicitly bounded acquisition diagnostics. Partial bodies
    cannot identify a full entity and are preserved, not appended or retried.
    """
    maximum = asset.get("max_size_bytes")
    if type(maximum) is not int or not 1 <= maximum <= 1024 * 1024:
        raise DownloadError("Diagnostic response requires a positive bound of at most 1 MiB")
    url = asset["source_url"]
    if urlsplit(url).scheme != "https":
        raise DownloadError("Diagnostic response requires HTTPS")
    reject_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent_identity = _directory_identity(destination.parent)
    part = destination.with_name(destination.name + ".part")
    reject_symlinks(part)
    if destination.exists() or part.exists():
        raise DownloadError("Diagnostic response already has bytes; preserve evidence and use new staging")
    headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        if urlsplit(response.url).scheme != "https" or response.status != 200:
            raise DownloadError("Diagnostic response requires a whole HTTPS 200 response")
        if response.headers.get("Content-Encoding", "identity") != "identity" or response.headers.get("Content-Range"):
            raise DownloadError("Diagnostic response must be an uncompressed whole entity")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or not 0 < int(length) <= maximum):
            raise DownloadError("Diagnostic response declared length exceeds its bound or is invalid")
        record = {"kind": "http", "requested_url": url, "final_url": response.url, "status": response.status,
                  "offset": 0, "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                  "content_length": length, "content_range": None, "content_encoding": "identity",
                  "content_type": response.headers.get("Content-Type"), "eof": False,
                  "max_size_bytes": maximum, "resumed": False}
        if response_evidence is not None:
            response_evidence(record)
        observed = 0
        _check_directory(destination.parent, parent_identity)
        with _open_regular(part, writable=True) as handle, durable_writer(handle) as checkpoint:
            while True:
                # Read only one byte past the bound to distinguish EOF from overflow.
                block = response.read(min(65536, maximum - observed + 1))
                if not block:
                    break
                if observed + len(block) > maximum:
                    raise DownloadError("Diagnostic response exceeds its enforced maximum")
                handle.write(block)
                observed += len(block)
                checkpoint.written(len(block))
        if observed == 0 or length is not None and observed != int(length):
            raise DownloadError("Diagnostic response ended before its declared length or was empty")
        record.update(eof=True, observed_size_bytes=observed, observed_sha256=sha256_file(part))
        if response_evidence is not None:
            response_evidence(record)
        _check_directory(destination.parent, parent_identity)
        reject_symlinks(destination)
        os.replace(part, destination)
        return record


def download(asset: dict, destination: Path, *, repo_root: Path, retries: int = 3,
             timeout: float = 60, progress=print, sleep=time.sleep, response_evidence=None,
             stop_on_missing=False) -> str:
    """Destination must be in the builder-owned staging/cache directory."""
    reject_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent_identity = _directory_identity(destination.parent)
    part = destination.with_name(destination.name + ".part")
    meta_path = destination.with_name(destination.name + ".part.json")
    reject_symlinks(part)
    reject_symlinks(meta_path)
    expected = asset["size_bytes"]
    urls = list(dict.fromkeys([asset["source_url"], *asset.get("mirrors", [])]))
    standard_user_agent_urls = set()
    attempted_urls = set()
    last_error = None
    saw_bad_hash = False
    attempt = route = 0
    while urls and attempt <= retries:
        index = route % len(urls)
        url = urls[index]
        route = index + 1
        attempted_urls.add(url)
        try:
            _check_directory(destination.parent, parent_identity)
            parsed = urlsplit(url)
            if parsed.scheme in {"file", "repo"}:
                source = _local_source(parsed, repo_root)
                digest = resume_copy(source, destination, size=expected, checksum=asset["sha256"],
                                     part=part, progress=progress)
                _check_directory(destination.parent, parent_identity)
                reject_symlinks(meta_path)
                if response_evidence is not None:
                    response_evidence({"kind": "local", "requested_url": url, "final_url": url, "size_bytes": expected})
                meta_path.unlink(missing_ok=True)
                return digest
            else:
                offset = part.stat().st_size if part.exists() else 0
                metadata = {}
                if meta_path.exists():
                    try:
                        metadata = json.loads(meta_path.read_text())
                    except (ValueError, OSError):
                        pass
                if offset == expected and asset["sha256"]:
                    if verified(part, expected, asset["sha256"]):
                        _check_directory(destination.parent, parent_identity)
                        with _open_regular(part, writable=True) as handle, durable_writer(handle):
                            pass
                        reject_symlinks(destination)
                        if response_evidence is not None:
                            response_evidence(metadata.get("response_evidence", {"kind": "unavailable", "requested_url": url}))
                        os.replace(part, destination)
                        meta_path.unlink(missing_ok=True)
                        return asset["sha256"]
                    _check_directory(destination.parent, parent_identity)
                    part.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    offset = 0
                validator = metadata.get("validator") if metadata.get("url") == url else None
                if offset >= expected or (offset and not asset["sha256"] and not validator):
                    offset = 0
                headers = {"Accept-Encoding": "identity"}
                if url not in standard_user_agent_urls:
                    headers["User-Agent"] = USER_AGENT
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                    if validator:
                        headers["If-Range"] = validator
                with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                    if parsed.scheme == "https" and urlsplit(response.url).scheme != "https":
                        raise DownloadError("Refusing HTTPS downgrade redirect")
                    if response.headers.get("Content-Encoding", "identity") != "identity":
                        raise DownloadError("Unexpected compressed transfer; byte offsets would be unsafe")
                    status = response.status
                    if status == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                        if not match or int(match[1]) != offset or int(match[3]) != expected or int(match[2]) != expected - 1:
                            raise DownloadError("Invalid Content-Range; refusing unsafe resume")
                        if offset and not asset["sha256"] and validator:
                            returned = response.headers.get("ETag") if validator.startswith('"') else response.headers.get("Last-Modified")
                            if returned != validator:
                                _check_directory(destination.parent, parent_identity)
                                atomic_write(meta_path, b"{}")
                                raise TransientDownloadError("Resume validator changed or missing; next attempt restarts from byte zero")
                    elif status == 200:
                        offset = 0  # Server ignored Range or entity changed; restart safely.
                    else:
                        raise DownloadError(f"Unexpected HTTP status {status}")
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) != expected - offset:
                        raise DownloadError(f"{asset['id']}: remote size changed; update reviewed catalog")
                    etag = response.headers.get("ETag", "")
                    validator = etag if etag and not etag.startswith("W/") else response.headers.get("Last-Modified")
                    _check_directory(destination.parent, parent_identity)
                    response_record = {"kind": "http", "requested_url": url, "final_url": response.url,
                                       "status": status, "offset": offset, "etag": response.headers.get("ETag"),
                                       "last_modified": response.headers.get("Last-Modified"),
                                       "content_length": response.headers.get("Content-Length"),
                                       "content_range": response.headers.get("Content-Range"),
                                       "content_encoding": response.headers.get("Content-Encoding", "identity")}
                    atomic_write(meta_path, json.dumps({"url": url, "validator": validator,
                                                       "response_evidence": response_record}).encode())
                    last_report = time.monotonic()
                    progress(f"{asset['id']}: {'resuming' if offset else 'downloading'} at {offset:,} / {expected:,} bytes")
                    _check_directory(destination.parent, parent_identity)
                    with _open_regular(part, writable=True) as handle, durable_writer(handle) as checkpoint:
                        handle.seek(offset)
                        handle.truncate(offset)
                        while True:
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            offset += len(block)
                            if offset > expected:
                                raise DownloadError("Response exceeds catalog size")
                            handle.write(block)
                            checkpoint.written(len(block))
                            if time.monotonic() - last_report >= 5:
                                progress(f"{asset['id']}: {offset:,} / {expected:,} bytes ({offset / expected:.1%})")
                                last_report = time.monotonic()
            digest = _complete(part, asset)
            _check_directory(destination.parent, parent_identity)
            reject_symlinks(destination)
            if response_evidence is not None:
                response_evidence(response_record)
            os.replace(part, destination)
            meta_path.unlink(missing_ok=True)
            return digest
        except (OSError, URLError, HTTPError, http.client.HTTPException, socket.timeout, ValueError, DownloadError, TransferError) as error:
            last_error = error
            # Publishers differ on accepted client identifiers. Change only this
            # URL's next existing retry after a transport failure, never a bad pin.
            if isinstance(error, HTTPError):
                switch_agent = error.code == 403 and url not in standard_user_agent_urls
                error.close()
                if stop_on_missing and error.code in {404, 410}:
                    raise MissingSourceError(asset['id'], url, error.code) from error
            else:
                switch_agent = isinstance(error, (URLError, TimeoutError, ConnectionError, http.client.HTTPException))
            if switch_agent:
                standard_user_agent_urls.add(url)
            if isinstance(error, ChecksumMismatchError):
                # Keep a lone local copy as evidence. A different route must
                # always start without bytes from the rejected source.
                if len(urls) > 1 or parsed.scheme not in {"file", "repo"}:
                    _check_directory(destination.parent, parent_identity)
                    part.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                urls.pop(index)
                route = index
                saw_bad_hash = True
                if urls:
                    progress(f"{asset['id']}: {error}; trying another source")
                continue
            if saw_bad_hash:
                # A transport error on one fallback must not hide an untried
                # pinned mirror after the original source failed integrity.
                untried = next((i for i, candidate in enumerate(urls) if candidate not in attempted_urls), None)
                if untried is not None:
                    route = untried
                    continue
            # A rejected identifier or untried reviewed mirror gets its existing
            # bounded fallback. Permanent pins, local I/O and safety errors do
            # not become repeatable job failures.
            fallback = isinstance(error, HTTPError) and (switch_agent or any(candidate not in attempted_urls for candidate in urls))
            if not _transient(error) and not fallback:
                break
            if attempt < retries:
                progress(f"{asset['id']}: retry {attempt + 1}/{retries}: {error}")
                sleep(min(2 ** attempt, 30))
            attempt += 1
    error_type = TransientDownloadError if _transient(last_error) else DownloadError
    raise error_type(f"{asset['id']}: download failed: {last_error}") from last_error
