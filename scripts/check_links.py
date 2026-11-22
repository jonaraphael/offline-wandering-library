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
CHECKER_BLOCKS = {
    "openknowledge.fao.org": {403},
    "iris.who.int": {403},
    "cdn.sanity.io": {403},
    "upload.wikimedia.org": {429},
}
STREAM_MAX_BYTES = 64 * 1024 * 1024
STREAM_INTERVAL = 0.5
STREAM_CHUNK_BYTES = 64 * 1024


class StreamSize:
    """Count unknown lengths with one bounded stream at a time."""

    def __init__(self):
        self.lock = Lock()
        self.next_start = 0.0

    def __call__(self, url, headers, expected, timeout):
        if expected >= STREAM_MAX_BYTES:
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


def probe(url: str, size: int, origin: str | None, timeout: float, *, stream_size=StreamSize(),
          reviewed_mirror=False, whole_get=False, browser_expected=False) -> dict:
    """Read response headers first, then count bytes for a small unknown length."""
    headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
    if origin:
        headers["Origin"] = origin

    def request(method, extra, request_headers):
        req = Request(url, method=method, headers={**request_headers, **extra})
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.status, response.headers, response.url
        except HTTPError as error:
            with error:
                return error.code, error.headers, error.url
        except (OSError, http.client.HTTPException) as error:
            return 0, {}, str(error)

    host = urlsplit(url).hostname
    head_status, head, _ = request("HEAD", {}, headers)
    range_headers = {} if whole_get else {"Range": "bytes=0-0"}
    status, ranged, final_url = request("GET", range_headers, headers)
    if status == 403 and host not in CHECKER_BLOCKS and (whole_get or head_status != 200):
        # The download CLI also falls back to urllib's standard identifier.
        standard = {name: value for name, value in headers.items() if name != "User-Agent"}
        fallback_status, fallback_headers, fallback_url = request("GET", range_headers, standard)
        if 200 <= fallback_status < 300:
            status, ranged, final_url = fallback_status, fallback_headers, fallback_url
            headers = standard
    match = re.fullmatch(r"bytes 0-0/(\d+)", ranged.get("Content-Range", ""))
    range_supported = status == 206 and match is not None
    full_length = ranged.get("Content-Length") if status == 200 else (
        head.get("Content-Length") if head_status == 200 else None)
    observed = int(match[1]) if range_supported else (
        int(full_length) if full_length and full_length.isascii() and full_length.isdigit() else None
    )
    size_method = "range" if range_supported else "header" if observed is not None else None
    stream_error = None
    streamed = False
    response_headers = ranged
    needs_stream = (status == 200 and observed is None
                    or (head_status == 200 or reviewed_mirror) and not 200 <= status < 300)
    if needs_stream:
        try:
            observed, response_headers, final_url = stream_size(url, headers, size, timeout)
            size_method = "stream"
            streamed = True
        except (OSError, ValueError, http.client.HTTPException) as error:
            stream_error = str(error)
            if isinstance(error, HTTPError):
                error.close()
    reachable = streamed or 200 <= status < 300
    ok = reachable and observed == size
    blocked = not reachable and (status in CHECKER_BLOCKS.get(host, set()) or
                                 (status == 403 and browser_expected))
    outcome = ("matching" if ok else "blocked for this checker" if blocked else
               "gone" if status in {404, 410} else "size mismatch" if reachable and observed is not None else
               "unverified")
    cors = bool(origin and reachable and response_headers.get("Access-Control-Allow-Origin") in {"*", origin})
    exposed = {header.strip().lower() for header in response_headers.get("Access-Control-Expose-Headers", "").split(",")}
    return {
        "url": url, "final_url": final_url, "expected_bytes": size, "observed_bytes": observed,
        "head_status": head_status, "get_status": status, "cors": cors, "range": range_supported,
        "exposes_content_range": cors and bool(exposed & {"*", "content-range"}),
        "size_method": size_method, "stream_error": stream_error,
        "ok": ok, "outcome": outcome,
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
            yield "browser-direct", identity, url, asset["size_bytes"], expected, asset["format"] != "zim"
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
    parser.add_argument("--sample", type=int, default=0, help="maximum sample per group, zero for all")
    parser.add_argument("--route-sample", type=int, help="override the sample for browser routes only")
    parser.add_argument("--stream-missing-size", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help="save every response as JSON")
    args = parser.parse_args(argv)
    route_sample = args.sample if args.route_sample is None else args.route_sample
    if args.workers < 1 or args.timeout <= 0 or min(args.sample, route_sample) < 0:
        parser.error("--workers and --timeout must be positive and sample sizes must be nonnegative")
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
            metadata = sources.setdefault(url, {"size": asset["size_bytes"], "reviewed_mirror": False,
                                                "browser_expected": False, "whole_get": False})
            if metadata["size"] != asset["size_bytes"]:
                parser.error(f"Conflicting pinned sizes for {url}")
            metadata["reviewed_mirror"] |= expected.get("sha256_verified") is True
            metadata["browser_expected"] |= expected.get("cors") is True
            metadata["whole_get"] |= expected.get("range") is False and asset.get("format") != "zim"
            urls.append(url)
        if urls:
            asset_sources[asset["id"]] = urls
    stream_size = StreamSize()
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        def check(source):
            url, metadata = source
            row = probe(url, metadata["size"], None, args.timeout, stream_size=stream_size,
                        reviewed_mirror=metadata["reviewed_mirror"], browser_expected=metadata["browser_expected"],
                        whole_get=metadata["whole_get"])
            row.update(route="publisher", browser_drift=[])
            return row
        results = list(workers.map(check, sources.items()))
        def check_route(route):
            kind, identity, url, size, required, whole_get = route
            row = probe(url, size, args.origin, args.timeout, whole_get=whole_get, stream_size=stream_size,
                        browser_expected=kind == "browser-direct")
            row.update(route=kind, id=identity, browser_drift=sorted(field for field in required if not row[field]))
            return row
        routes = list(workers.map(check_route, deployed_routes(
            assets, args.pages_base, args.relay_base, route_sample, archive_relay=args.archive_relay))) if (
                args.pages_base or args.relay_base) else []

    by_url = {row["url"]: row for row in results}
    def blocked(row):
        return row.get("outcome") == "blocked for this checker"

    unmatched = {identity: urls for identity, urls in asset_sources.items() if not any(by_url[url]["ok"] for url in urls)}
    blocked_assets = [identity for identity, urls in unmatched.items() if any(blocked(by_url[url]) for url in urls)]
    failed_assets = sorted(set(unmatched) - set(blocked_assets))
    blocked_routes = [row for row in routes if blocked(row)]
    failed_routes = [row for row in routes if not blocked(row) and (not row["ok"] or row["browser_drift"])]
    if args.output:
        args.output.write_text(json.dumps({"failed_assets": failed_assets, "failed_routes": failed_routes,
                                           "blocked_assets": blocked_assets, "blocked_routes": blocked_routes,
                                           "responses": [*results, *routes]}, indent=2) + "\n", encoding="utf-8")
    for row in [*results, *routes]:
        if not row["ok"] or row["browser_drift"]:
            print(json.dumps(row), file=sys.stderr)
    if failed_assets:
        print("No publisher URL with the pinned size: " + ", ".join(failed_assets), file=sys.stderr)
    asset_label = "asset" if len(blocked_assets) == 1 else "assets"
    route_label = "browser route" if len(blocked_routes) == 1 else "browser routes"
    print(f"{len(asset_sources) - len(unmatched)}/{len(asset_sources)} assets have a matching source "
          f"across {len(results)} publisher URLs. "
          f"{len(routes) - len(failed_routes) - len(blocked_routes)}/{len(routes)} browser routes passed. "
          f"Blocked for this checker: {len(blocked_assets)} {asset_label}, {len(blocked_routes)} {route_label}.")
    return int(bool(failed_assets or failed_routes))


if __name__ == "__main__":
    raise SystemExit(main())
