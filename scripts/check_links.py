#!/usr/bin/env python3
"""Check source sizes and browser response headers without downloading files."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.catalog import load_catalog

DEFAULT_ORIGIN = "https://example.github.io"


def probe(url: str, size: int, origin: str, timeout: float) -> dict:
    """Inspect headers only and close the connection even if Range is ignored."""
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
    cors = 200 <= status < 300 and ranged.get("Access-Control-Allow-Origin") in {"*", origin}
    exposed = {header.strip().lower() for header in ranged.get("Access-Control-Expose-Headers", "").split(",")}
    return {
        "url": url, "final_url": final_url, "expected_bytes": size, "observed_bytes": observed,
        "head_status": head_status, "get_status": status, "cors": cors, "range": range_supported,
        "exposes_content_range": cors and bool(exposed & {"*", "content-range"}),
        "ok": 200 <= status < 300 and observed == size,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "catalog/library.yaml")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output", type=Path, help="save every response as JSON")
    args = parser.parse_args(argv)
    sources = {}
    for asset in load_catalog(args.catalog):
        if asset.get("archive_member") or asset.get("generation"):
            continue
        for url in [asset["source_url"], *asset.get("mirrors", [])]:
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            expected = asset.get("browser_fetch", {}) if url == asset["source_url"] else {}
            size, _ = sources.setdefault(url, (asset["size_bytes"], expected))
            if size != asset["size_bytes"]:
                parser.error(f"Conflicting pinned sizes for {url}")
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        def check(source):
            url, (size, expected) = source
            row = probe(url, size, args.origin, args.timeout)
            if expected.get("scope") == "url":
                row["browser_drift"] = [field for field in ("cors", "range") if expected[field] and not row[field]]
                row["ok"] = row["ok"] and not row["browser_drift"]
            return row
        results = list(workers.map(check, sources.items()))
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    failed = [row for row in results if not row["ok"]]
    for row in failed:
        print(json.dumps(row), file=sys.stderr)
    print(f"{len(results) - len(failed)}/{len(results)} URLs reachable with pinned size and expected browser support")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
