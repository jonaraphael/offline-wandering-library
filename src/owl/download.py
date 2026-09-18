"""Streaming, resumable downloads. Completed bytes are always hashed before use."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, url2pathname, urlopen

from .safety import atomic_write, reject_symlinks, safe_path, sha256_file
from .transfer import (TransferError, _check_directory, _directory_identity,
                       _open_regular, durable_writer, resume_copy)


class DownloadError(RuntimeError):
    pass


def verified(path: Path, size: int, checksum: str | None) -> bool:
    reject_symlinks(path)
    return bool(checksum and path.is_file() and path.stat().st_size == size and sha256_file(path) == checksum)


def _complete(part: Path, asset: dict) -> str:
    if part.stat().st_size != asset["size_bytes"]:
        raise DownloadError(f"{asset['id']}: size mismatch: {part.stat().st_size} != {asset['size_bytes']}")
    digest = sha256_file(part)
    if asset["sha256"] and digest != asset["sha256"]:
        raise DownloadError(f"{asset['id']}: SHA-256 mismatch; refusing completed download")
    return digest


def download(asset: dict, destination: Path, *, repo_root: Path, retries: int = 3,
             timeout: float = 60, progress=print, sleep=time.sleep) -> str:
    """Destination must be in the builder-owned staging/cache directory."""
    reject_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    parent_identity = _directory_identity(destination.parent)
    part = destination.with_name(destination.name + ".part")
    meta_path = destination.with_name(destination.name + ".part.json")
    reject_symlinks(part)
    reject_symlinks(meta_path)
    expected = asset["size_bytes"]
    urls = [asset["source_url"], *asset.get("mirrors", [])]
    last_error = None
    for attempt in range(retries + 1):
        url = urls[attempt % len(urls)]
        try:
            _check_directory(destination.parent, parent_identity)
            parsed = urlsplit(url)
            if parsed.scheme in {"file", "repo"}:
                if parsed.scheme == "repo":
                    relative = (parsed.netloc + parsed.path).lstrip("/")
                    source = safe_path(repo_root, relative)
                else:
                    if parsed.netloc not in {"", "localhost"} or parsed.path.startswith("//"):
                        raise DownloadError("File sources must be local file URLs, not remote authorities or UNC paths")
                    # URI paths use /C:/ on Windows; url2pathname converts the
                    # drive prefix and decodes percent escapes exactly once.
                    source = Path(url2pathname(parsed.path))
                    reject_symlinks(source)
                digest = resume_copy(source, destination, size=expected, checksum=asset["sha256"],
                                     part=part, progress=progress)
                _check_directory(destination.parent, parent_identity)
                reject_symlinks(meta_path)
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
                    digest = _complete(part, asset)
                    _check_directory(destination.parent, parent_identity)
                    with _open_regular(part, writable=True) as handle, durable_writer(handle):
                        pass
                    reject_symlinks(destination)
                    os.replace(part, destination)
                    meta_path.unlink(missing_ok=True)
                    return digest
                validator = metadata.get("validator") if metadata.get("url") == url else None
                if offset >= expected or (offset and not asset["sha256"] and not validator):
                    offset = 0
                headers = {"User-Agent": "Offline-Wandering-Library/0.1 (+offline library builder)",
                           "Accept-Encoding": "identity"}
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
                                raise DownloadError("Resume validator changed or missing; next attempt restarts from byte zero")
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
                    atomic_write(meta_path, json.dumps({"url": url, "validator": validator}).encode())
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
            os.replace(part, destination)
            meta_path.unlink(missing_ok=True)
            return digest
        except (OSError, URLError, HTTPError, http.client.HTTPException, socket.timeout, ValueError, DownloadError, TransferError) as error:
            last_error = error
            if isinstance(error, DownloadError) and "SHA-256 mismatch" in str(error):
                # Corrupt bytes must never be reused, including on the next run.
                _check_directory(destination.parent, parent_identity)
                part.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
            if attempt < retries:
                progress(f"{asset['id']}: retry {attempt + 1}/{retries}: {error}")
                sleep(min(2 ** attempt, 30))
    raise DownloadError(f"{asset['id']}: download failed: {last_error}")
