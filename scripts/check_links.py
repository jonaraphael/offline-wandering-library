#!/usr/bin/env python3
"""Check pinned source sizes and browser response headers."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.catalog import load_catalog

DEFAULT_ORIGIN = "https://example.github.io"
STREAM_MAX_BYTES = 64 * 1024 * 1024
STREAM_INTERVAL = 0.5
STREAM_CHUNK_BYTES = 64 * 1024


class StreamSize:
    """Count unknown lengths with one bounded stream at a time."""

    def __init__(self):
        self.lock = Lock()
        self.next_start = 0.0

    def __call__(self, url, headers, expected, timeout):
        if expected > STREAM_MAX_BYTES:
            raise ValueError("Pin exceeds the missing-size streaming limit")
        with self.lock:
            sleep(max(0, self.next_start - monotonic()))
            self.next_start = monotonic() + STREAM_INTERVAL
            deadline = monotonic() + timeout
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError(f"Expected a full response, got HTTP {response.status}")
                count = 0
                while count <= expected:
                    if monotonic() > deadline:
                        raise TimeoutError("Missing-size stream exceeded its timeout")
                    chunk = response.read1(min(STREAM_CHUNK_BYTES, expected + 1 - count))
                    if not chunk:
                        break
                    count += len(chunk)
                return count, response.headers, response.url


def probe(url: str, size: int, origin: str, timeout: float, *, stream_size=None, reviewed_mirror=False) -> dict:
    """Read response headers first and stream unknown lengths only when enabled."""
    headers = {"Origin": origin, "Accept-Encoding": "identity", "User-Agent": "OWL-link-check/1"}

    def request(method, extra):
        req = Request(url, method=method, headers={**headers, **extra})
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.status, response.headers, response.url
        except HTTPError as error:
            with error:
                return error.code, error.headers, error.url
        except OSError as error:
            return 0, {}, str(error)

    head_status, head, _ = request("HEAD", {})
    status, ranged, final_url = request("GET", {"Range": "bytes=0-0"})
    match = re.fullmatch(r"bytes 0-0/(\d+)", ranged.get("Content-Range", ""))
    range_supported = status == 206 and match is not None
    full_length = ranged.get("Content-Length") if status == 200 else head.get("Content-Length")
    if full_length is None and head_status == 200:
        full_length = head.get("Content-Length")
    observed = int(match[1]) if range_supported else (
        int(full_length) if full_length and full_length.isascii() and full_length.isdigit() else None
    )
    size_method = "range" if range_supported else "header" if observed is not None else None
    stream_error = None
    streamed = False
    response_headers = ranged
    needs_stream = (status == 200 and observed is None
                    or (head_status == 200 or reviewed_mirror) and not 200 <= status < 300)
    if needs_stream and stream_size is not None:
        try:
            observed, response_headers, final_url = stream_size(url, headers, size, timeout)
            size_method = "stream"
            streamed = True
        except (OSError, ValueError) as error:
            stream_error = str(error)
            if isinstance(error, HTTPError):
                error.close()
    reachable = streamed or 200 <= status < 300
    cors = reachable and response_headers.get("Access-Control-Allow-Origin") in {"*", origin}
    exposed = {header.strip().lower() for header in response_headers.get("Access-Control-Expose-Headers", "").split(",")}
    return {
        "url": url, "final_url": final_url, "expected_bytes": size, "observed_bytes": observed,
        "head_status": head_status, "get_status": status, "cors": cors, "range": range_supported,
        "exposes_content_range": cors and bool(exposed & {"*", "content-range"}),
        "size_method": size_method, "stream_error": stream_error,
        "ok": reachable and observed == size,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "catalog/library.yaml")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--stream-missing-size", action="store_true",
                        help="count unknown lengths for pins up to 64 MiB using rate-limited streams")
    parser.add_argument("--output", type=Path, help="save every response as JSON")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.timeout <= 0:
        parser.error("--workers and --timeout must be positive")
    sources = {}
    asset_sources = {}
    for asset in load_catalog(args.catalog):
        if asset.get("archive_member") or asset.get("generation"):
            continue
        urls = []
        for url in [asset["source_url"], *asset.get("mirrors", [])]:
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            expected = (asset.get("browser_fetch", {}) if url == asset["source_url"]
                        else asset.get("mirror_fetch", {}).get(url, {}))
            metadata = sources.setdefault(url, {"size": asset["size_bytes"], "require": set(),
                                                 "reviewed_mirror": False})
            if metadata["size"] != asset["size_bytes"]:
                parser.error(f"Conflicting pinned sizes for {url}")
            metadata["reviewed_mirror"] |= expected.get("sha256_verified") is True
            if expected.get("scope") == "url" or expected.get("sha256_verified"):
                metadata["require"].update(field for field in ("cors", "range") if expected.get(field))
            urls.append(url)
        if urls:
            asset_sources[asset["id"]] = urls
    stream_size = StreamSize() if args.stream_missing_size else None
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        def check(source):
            url, metadata = source
            row = probe(url, metadata["size"], args.origin, args.timeout, stream_size=stream_size,
                        reviewed_mirror=metadata["reviewed_mirror"])
            row["browser_drift"] = sorted(field for field in metadata["require"] if not row[field])
            return row
        results = list(workers.map(check, sources.items()))
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    by_url = {row["url"]: row for row in results}
    failed_assets = []
    for identity, urls in asset_sources.items():
        expected = set().union(*(sources[url]["require"] for url in urls))
        if not any(by_url[url]["ok"] and all(by_url[url][field] for field in expected) for url in urls):
            failed_assets.append(identity)
    for row in results:
        if not row["ok"] or row["browser_drift"]:
            print(json.dumps(row), file=sys.stderr)
    if failed_assets:
        print("No matching source with the recorded browser support: " + ", ".join(failed_assets), file=sys.stderr)
    print(f"{len(asset_sources) - len(failed_assets)}/{len(asset_sources)} assets have a matching source "
          f"across {len(results)} checked URLs")
    return int(bool(failed_assets))


if __name__ == "__main__":
    raise SystemExit(main())
