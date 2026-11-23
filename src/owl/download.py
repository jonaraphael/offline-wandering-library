"""Streaming, resumable downloads. Completed bytes are always hashed before use."""
from __future__ import annotations

import http.client
import errno
from hashlib import sha256
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

from . import __version__
from .safety import atomic_write, reject_symlinks, safe_path, sha256_file
from .transfer import (ChecksumMismatchError, TransferError, _check_directory, _directory_identity,
                       _open_regular, durable_writer, resume_copy)

USER_AGENT = f"Offline-Wandering-Library/{__version__} (+offline library builder)"
BROWSER_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")


class DownloadError(RuntimeError):
    pass


class TransientDownloadError(DownloadError):
    """A bounded transport failure that a saved build job may retry unchanged."""


class _SplitResumeError(DownloadError):
    """A range was rejected, so restart this source with a whole request."""


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
    from .verify import file_hash

    for path, row in zip(paths, layout, strict=True):
        reject_symlinks(path)
        if not path.is_file() or path.stat().st_size != row["bytes"]:
            return None
    whole = sha256()
    parts = [{**row, "sha256": file_hash(path, whole)} for path, row in zip(paths, layout, strict=True)]
    return parts if whole.hexdigest() == checksum else None


def _local_source(parsed, repo_root):
    if parsed.scheme == "repo":
        return safe_path(repo_root, (parsed.netloc + parsed.path).lstrip("/"))
    if parsed.netloc not in {"", "localhost"} or parsed.path.startswith("//"):
        raise DownloadError("File sources must be local file URLs, not remote authorities or UNC paths")
    # Convert a Windows drive prefix and decode percent escapes exactly once.
    return Path(url2pathname(parsed.path))


def _split_checkpoint(path, staged, layout):
    reject_symlinks(path)
    try:
        with _open_regular(path) as handle:
            metadata = json.loads(handle.read(128 * 1024))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None, None, []
    if not isinstance(metadata, dict) or not isinstance(metadata.get("parts"), list):
        return None, None, []
    validator = metadata.get("validator")
    if not isinstance(validator, str) or not validator or "\r" in validator or "\n" in validator:
        validator = None
    prefix = []
    for path, row, digest in zip(staged, layout, metadata["parts"]):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) or not verified(path, row["bytes"], digest):
            break
        prefix.append(digest)
    return metadata.get("url"), validator, prefix


def download_split_zim(asset, layout, destination, staged, *, repo_root, cached=None, progress=print):
    """Resume from closed, rehashed parts and verify the whole archive before publishing."""
    expected = asset["size_bytes"]
    meta_path = staged[0].with_suffix(".part.json")
    staging_dir = _directory_identity(meta_path.parent)
    final_dir = _directory_identity(destination[0].parent)

    def save_checkpoint(url, validator, prefix):
        _check_directory(meta_path.parent, staging_dir)
        atomic_write(meta_path, json.dumps({"url": url, "validator": validator, "parts": prefix}).encode())

    def write_parts(source, url, prefix):
        for path, row in zip(staged[len(prefix):], layout[len(prefix):], strict=True):
            _check_directory(meta_path.parent, staging_dir)
            digest = sha256()
            with _open_regular(path, writable=True) as handle, durable_writer(handle) as checkpoint:
                handle.truncate(0)
                left = row["bytes"]
                while left:
                    block = source.read(min(left, 1024 * 1024))
                    if not block:
                        raise TransientDownloadError("archive ended before its pinned byte count")
                    handle.write(block)
                    digest.update(block)
                    left -= len(block)
                    checkpoint.written(len(block))
            # Save only complete, durable parts. The next run checks these
            # hashes before reusing the prefix, then checks the catalog pin.
            complete = [*prefix, digest.hexdigest()]
            save_checkpoint(url, validator, complete)
            prefix[:] = complete
            progress(f"{asset['id']}: wrote {row['start'] + row['bytes']:,} / {expected:,} bytes")
        if source.read(1):
            raise DownloadError("archive exceeds its pinned byte count")
        parts = inspect_zim_parts(staged, layout, asset["sha256"])
        if parts is None:
            raise ChecksumMismatchError(f"{asset['id']}: split archive SHA-256 mismatch")
        return parts

    def fetch_parts(url, headers, prefix):
        nonlocal validator
        parsed = urlsplit(url)
        offset = layout[len(prefix)]["start"] if prefix else 0
        if parsed.scheme in {"repo", "file"}:
            with _open_regular(_local_source(parsed, repo_root)) as source:
                source.seek(offset)
                return write_parts(source, url, prefix)
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if validator:
                headers["If-Range"] = validator
        with urlopen(Request(url, headers=headers), timeout=60) as response:
            if (response.headers.get("Content-Encoding", "identity") != "identity" or
                    (parsed.scheme == "https" and urlsplit(response.url).scheme != "https")):
                raise DownloadError("expected an unencoded archive response without an HTTPS downgrade")
            if response.status == 200:
                prefix.clear()
                offset = 0
            elif response.status == 206:
                if response.headers.get("Content-Range") != f"bytes {offset}-{expected - 1}/{expected}":
                    raise _SplitResumeError("Invalid Content-Range; refusing unsafe split archive resume")
                if validator and (response.headers.get("ETag" if validator.startswith('"') else "Last-Modified")
                                  != validator):
                    raise _SplitResumeError("Split archive resume validator changed")
            else:
                raise DownloadError(f"Unexpected archive HTTP status {response.status}")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) != expected - offset):
                raise DownloadError("Remote archive size differs from the catalog pin")
            etag = response.headers.get("ETag", "")
            validator = etag if etag.startswith('"') else response.headers.get("Last-Modified")
            # Replace a prior checkpoint before overwriting any of its bytes.
            save_checkpoint(url, validator, prefix)
            if offset:
                progress(f"{asset['id']}: resuming at {offset:,} / {expected:,} bytes")
            return write_parts(response, url, prefix)

    # An interruption during publication can leave verified parts in both
    # locations. Reassemble that staging set before requesting bytes again.
    candidates = [partial if partial.is_file() else final
                  for partial, final in zip(staged, destination, strict=True)]
    parts = inspect_zim_parts(candidates, layout, asset["sha256"])
    if parts is None:
        saved_url, validator, prefix = _split_checkpoint(meta_path, staged, layout)
        # A complete set that failed the whole pin must be overwritten.
        if len(prefix) == len(layout):
            prefix.clear()
        if not prefix:
            saved_url, validator = None, None
        sources = list(dict.fromkeys([asset["source_url"], *asset.get("mirrors", [])]))
        if cached is not None and cached.is_file():
            sources = list(dict.fromkeys([cached.as_uri(), *sources]))
        if prefix and saved_url in sources:
            sources.remove(saved_url)
            sources.insert(0, saved_url)
        headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
        last_error = None
        for url in sources:
            if url != saved_url:
                validator, prefix = None, []
            for attempt in range(3):
                try:
                    request_headers = dict(headers) if attempt == 0 else {"Accept-Encoding": "identity"}
                    parts = fetch_parts(url, request_headers, prefix)
                    break
                except (OSError, http.client.HTTPException, DownloadError, TransferError) as error:
                    last_error = error
                    if isinstance(error, HTTPError):
                        error.close()
                    if isinstance(error, ChecksumMismatchError):
                        _check_directory(meta_path.parent, staging_dir)
                        meta_path.unlink(missing_ok=True)
                        for path in staged:
                            reject_symlinks(path)
                            path.unlink(missing_ok=True)
                        break
                    rejected_range = (isinstance(error, _SplitResumeError) or
                                      isinstance(error, HTTPError) and error.code == 416)
                    if prefix and rejected_range:
                        validator, prefix = None, []
                        save_checkpoint(url, validator, prefix)
                        continue
                    if attempt == 2 or not (_transient(error) or isinstance(error, HTTPError) and error.code == 403):
                        break
                    if len(prefix) == len(layout):
                        validator, prefix = None, []
                    time.sleep(2 ** attempt)
            if parts is not None:
                break
        if parts is None:
            error_type = TransientDownloadError if _transient(last_error) else DownloadError
            raise error_type(f"{asset['id']}: split ZIM download failed: {last_error}") from last_error
    _check_directory(meta_path.parent, staging_dir)
    _check_directory(destination[0].parent, final_dir)
    for partial, final in zip(staged, destination, strict=True):
        if partial.exists():
            reject_symlinks(partial)
            reject_symlinks(final)
            os.replace(partial, final)
    reject_symlinks(meta_path)
    meta_path.unlink(missing_ok=True)
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
