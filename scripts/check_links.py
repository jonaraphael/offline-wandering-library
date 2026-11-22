#!/usr/bin/env python3
"""Check pinned source sizes and browser response headers."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
import http.client
import json
from pathlib import Path
import re
import sys
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.catalog import load_catalog
from owl.download import USER_AGENT

DEFAULT_ORIGIN = "https://jonaraphael.github.io"
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


def probe(url: str, size: int, origin: str | None, timeout: float, *, stream_size=None,
          reviewed_mirror=False, whole_get=False) -> dict:
    """Read response headers first and stream unknown lengths only when enabled."""
    headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
    if origin:
        headers["Origin"] = origin

    def request(method, extra):
        req = Request(url, method=method, headers={**headers, **extra})
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.status, response.headers, response.url
        except HTTPError as error:
            with error:
                return error.code, error.headers, error.url
        except (OSError, http.client.HTTPException) as error:
            return 0, {}, str(error)

    head_status, head, _ = request("HEAD", {})
    status, ranged, final_url = request("GET", {} if whole_get else {"Range": "bytes=0-0"})
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
    cors = bool(origin and reachable and response_headers.get("Access-Control-Allow-Origin") in {"*", origin})
    exposed = {header.strip().lower() for header in response_headers.get("Access-Control-Expose-Headers", "").split(",")}
    return {
        "url": url, "final_url": final_url, "expected_bytes": size, "observed_bytes": observed,
        "head_status": head_status, "get_status": status, "cors": cors, "range": range_supported,
        "exposes_content_range": cors and bool(exposed & {"*", "content-range"}),
        "size_method": size_method, "stream_error": stream_error,
        "ok": reachable and observed == size,
    }


def sample(items, limit):
    """Rotate the sample weekly and represent different hosts first."""
    if not limit or len(items) <= limit:
        return list(items)
    week = date.today().toordinal() // 7
    ordered = sorted(items, key=lambda pair: sha256(f"{week}:{pair[0]}".encode()).digest())
    first, rest, seen = [], [], set()
    for pair in ordered:
        host = pair[1]["host"]
        (rest if host in seen else first).append(pair)
        seen.add(host)
    return (first + rest)[:limit]


def deployed_routes(assets, pages_base, relay_base, limit, *, archive_relay):
    """Use the checked-in mirror and relay pins for the browser's actual URLs."""
    from build_pages import PUBLISH_PART, browser_routes

    for identity, metadata in sample([(a["id"], {"asset": a, "host": urlsplit(a["source_url"]).hostname})
                                      for a in assets if browser_routes(a)], limit):
        asset = metadata["asset"]
        for url in browser_routes(asset):
            expected = {"cors", "range", "exposes_content_range"} if asset["format"] == "zim" else {"cors"}
            yield "browser-direct", identity, url, asset["size_bytes"], expected, False
    if pages_base:
        lock = json.loads((ROOT / "web/pages-mirrors.json").read_text(encoding="utf-8"))
        for asset in assets:
            identity, size = asset["id"], asset["size_bytes"]
            if identity in lock:
                for index, offset in enumerate(range(0, size, PUBLISH_PART)):
                    path = urljoin(pages_base.rstrip("/") + "/", f"mirrors/{identity}-{index}.bin")
                    yield "pages-mirror", identity, path, min(PUBLISH_PART, size - offset), set(), False
    if relay_base:
        allowlist = json.loads((ROOT / "relay/allowlist.json").read_text(encoding="utf-8"))
        for archive in False, True:
            if archive and not archive_relay:
                continue
            entries = [(identity, {**entry, "host": urlsplit(entry["url"]).hostname})
                       for identity, entry in allowlist.items() if bool(entry.get("archive")) == archive]
            for identity, entry in sample(entries, limit):
                expected = {"cors", "range", "exposes_content_range"} if archive else {"cors"}
                yield ("relay-archive" if archive else "relay-publisher"), identity, (
                    relay_base.rstrip("/") + "/assets/" + identity), entry["bytes"], expected, not archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "catalog/library.yaml")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--pages-base", help="check the published Pages mirrors and direct routes")
    parser.add_argument("--relay-base", help="check the deployed relay IDs and response headers")
    parser.add_argument("--archive-relay", action="store_true", help="include relay archive routes")
    parser.add_argument("--sample", type=int, default=0, help="maximum sample per route group, zero for all")
    parser.add_argument("--stream-missing-size", action="store_true",
                        help="count unknown lengths for pins up to 64 MiB using rate-limited streams")
    parser.add_argument("--output", type=Path, help="save every response as JSON")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.timeout <= 0 or args.sample < 0:
        parser.error("--workers and --timeout must be positive and --sample must be nonnegative")
    sources = {}
    asset_sources = {}
    assets = load_catalog(args.catalog)
    publisher_assets = [(asset["id"], {"asset": asset, "host": urlsplit(asset["source_url"]).hostname})
                        for asset in assets if not asset.get("archive_member") and not asset.get("generation")]
    for _, entry in sample(publisher_assets, args.sample):
        asset = entry["asset"]
        if asset.get("archive_member") or asset.get("generation"):
            continue
        urls = []
        for url in [asset["source_url"], *asset.get("mirrors", [])]:
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            expected = (asset.get("browser_fetch", {}) if url == asset["source_url"]
                        else asset.get("mirror_fetch", {}).get(url, {}))
            metadata = sources.setdefault(url, {"size": asset["size_bytes"], "reviewed_mirror": False})
            if metadata["size"] != asset["size_bytes"]:
                parser.error(f"Conflicting pinned sizes for {url}")
            metadata["reviewed_mirror"] |= expected.get("sha256_verified") is True
            urls.append(url)
        if urls:
            asset_sources[asset["id"]] = urls
    stream_size = StreamSize() if args.stream_missing_size else None
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        def check(source):
            url, metadata = source
            row = probe(url, metadata["size"], None, args.timeout, stream_size=stream_size,
                        reviewed_mirror=metadata["reviewed_mirror"])
            row.update(route="publisher", browser_drift=[])
            return row
        results = list(workers.map(check, sources.items()))
        def check_route(route):
            kind, identity, url, size, required, whole_get = route
            row = probe(url, size, args.origin, args.timeout, whole_get=whole_get)
            row.update(route=kind, id=identity, browser_drift=sorted(field for field in required if not row[field]))
            return row
        routes = list(workers.map(check_route, deployed_routes(
            assets, args.pages_base, args.relay_base, args.sample, archive_relay=args.archive_relay))) if (
                args.pages_base or args.relay_base) else []

    by_url = {row["url"]: row for row in results}
    failed_assets = [identity for identity, urls in asset_sources.items() if not any(by_url[url]["ok"] for url in urls)]
    failed_routes = [row for row in routes if not row["ok"] or row["browser_drift"]]
    if args.output:
        args.output.write_text(json.dumps({"failed_assets": failed_assets, "failed_routes": failed_routes,
                                           "responses": [*results, *routes]}, indent=2) + "\n", encoding="utf-8")
    for row in [*results, *routes]:
        if not row["ok"] or row["browser_drift"]:
            print(json.dumps(row), file=sys.stderr)
    if failed_assets:
        print("No publisher URL with the pinned size: " + ", ".join(failed_assets), file=sys.stderr)
    print(f"{len(asset_sources) - len(failed_assets)}/{len(asset_sources)} assets have a matching source "
          f"across {len(results)} publisher URLs. {len(routes) - len(failed_routes)}/{len(routes)} browser routes passed.")
    return int(bool(failed_assets or failed_routes))


if __name__ == "__main__":
    raise SystemExit(main())
