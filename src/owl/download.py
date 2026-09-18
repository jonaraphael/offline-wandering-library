"""Streaming, resumable downloads. Completed bytes are always hashed before use."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from .safety import atomic_write, reject_symlinks, safe_path, sha256_file


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
            parsed = urlsplit(url)
            if parsed.scheme in {"file", "repo"}:
                if parsed.scheme == "repo":
                    relative = (parsed.netloc + parsed.path).lstrip("/")
                    source = safe_path(repo_root, relative)
                else:
                    source = Path(unquote(parsed.path))
                    reject_symlinks(source)
                if source.stat().st_size != expected:
                    raise DownloadError(f"{asset['id']}: local source size differs from manifest")
                with source.open("rb") as src, part.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
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
                    atomic_write(meta_path, json.dumps({"url": url, "validator": validator}).encode())
                    last_report = time.monotonic()
                    progress(f"{asset['id']}: {'resuming' if offset else 'downloading'} at {offset:,} / {expected:,} bytes")
                    with part.open("ab" if offset else "wb") as handle:
                        while True:
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            offset += len(block)
                            if offset > expected:
                                raise DownloadError("Response exceeds catalog size")
                            handle.write(block)
                            if time.monotonic() - last_report >= 5:
                                progress(f"{asset['id']}: {offset:,} / {expected:,} bytes ({offset / expected:.1%})")
                                last_report = time.monotonic()
                        handle.flush()
                        os.fsync(handle.fileno())
            digest = _complete(part, asset)
            os.replace(part, destination)
            meta_path.unlink(missing_ok=True)
            return digest
        except (OSError, URLError, HTTPError, http.client.HTTPException, socket.timeout, ValueError, DownloadError) as error:
            last_error = error
            if isinstance(error, DownloadError) and "SHA-256 mismatch" in str(error):
                # Corrupt bytes must never be reused, including on the next run.
                part.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
            if attempt < retries:
                progress(f"{asset['id']}: retry {attempt + 1}/{retries}: {error}")
                sleep(min(2 ** attempt, 30))
    raise DownloadError(f"{asset['id']}: download failed: {last_error}")
