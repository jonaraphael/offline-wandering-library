#!/usr/bin/env python3
"""Collect Kiwix Metalink pieces bound to the catalog's whole-file SHA-256 pins."""
from __future__ import annotations

import argparse
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import urlopen
from xml.etree import ElementTree


METALINK = "{urn:ietf:params:xml:ns:metalink}"
METADATA_LIMIT = 5_000_000
PIECE_BYTES = 4 * 1024 * 1024


def parse_metainfo(asset, data):
    root = ElementTree.fromstring(data)
    files = root.findall(METALINK + "file")
    name = urlsplit(asset["source_url"]).path.rsplit("/", 1)[-1]
    if len(files) != 1 or files[0].get("name") != name:
        raise ValueError("Metalink must describe the pinned ZIM file")
    source = files[0]
    sha256s = [node.text for node in source.findall(METALINK + "hash") if node.get("type") == "sha-256"]
    if sha256s != [asset["sha256"]] or int(source.findtext(METALINK + "size")) != asset["size_bytes"]:
        raise ValueError("Metalink whole-file SHA-256 or size differs from the catalog")
    groups = source.findall(METALINK + "pieces")
    if len(groups) != 1 or groups[0].attrib != {"length": str(PIECE_BYTES), "type": "sha-1"}:
        raise ValueError("Expected 4 MiB SHA-1 pieces")
    hashes = [node.text or "" for node in groups[0].findall(METALINK + "hash")]
    if len(hashes) != (asset["size_bytes"] + PIECE_BYTES - 1) // PIECE_BYTES or any(
            not re.fullmatch(r"[a-f0-9]{40}", value) for value in hashes):
        raise ValueError("Invalid Metalink piece count or SHA-1")
    mirrors = [node.text for node in source.findall(METALINK + "url") if node.text]
    return {
        "sha256": asset["sha256"],
        "sha1": b64encode(bytes.fromhex("".join(hashes))).decode("ascii"),
    }, mirrors


def collect(asset):
    url = asset["digest_source"]
    if urlsplit(url).scheme != "https" or not urlsplit(url).path.endswith(".meta4"):
        raise ValueError(f"Expected an HTTPS Metalink for {asset['id']}")
    with urlopen(url, timeout=30) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError(f"Insecure Metalink redirect for {asset['id']}")
        data = response.read(METADATA_LIMIT + 1)
    if len(data) > METADATA_LIMIT:
        raise ValueError(f"Metalink exceeds the metadata limit for {asset['id']}")
    return parse_metainfo(asset, data)


def main(argv=None):
    from owl.catalog import load_catalog

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mirrors", type=Path, help="also save the publisher's current mirror URLs")
    args = parser.parse_args(argv)
    assets = [asset for asset in load_catalog(Path("catalog/library.yaml")) if asset["format"] == "zim"]
    with ThreadPoolExecutor(8) as workers:
        collected = dict(zip((asset["id"] for asset in assets), workers.map(collect, assets), strict=True))
    output = {"piece_bytes": PIECE_BYTES, "archives": {key: record[0] for key, record in collected.items()}}
    args.output.write_text(json.dumps(output, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    if args.mirrors:
        args.mirrors.write_text(json.dumps({key: row[1] for key, row in collected.items()}, indent=2) + "\n",
                                encoding="utf-8")
    print(f"{len(assets)} Metalinks, {sum((a['size_bytes'] + PIECE_BYTES - 1) // PIECE_BYTES for a in assets)} pieces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
