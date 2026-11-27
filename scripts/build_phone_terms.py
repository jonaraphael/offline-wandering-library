#!/usr/bin/env python3
"""Refresh catalog/phone-terms.json from the search shards. Run after scripts/build_search_shards.py."""
from __future__ import annotations

import argparse
import sys

from owl.phone_terms import TERMS_FILE, compile_terms, encode_terms
from owl.safety import atomic_write


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file differs")
    args = parser.parse_args(argv)
    data = encode_terms(compile_terms())
    if args.check:
        if not TERMS_FILE.is_file() or TERMS_FILE.read_bytes() != data:
            print("catalog/phone-terms.json is out of date; run scripts/build_phone_terms.py", file=sys.stderr)
            return 1
        return 0
    atomic_write(TERMS_FILE, data)
    print(f"wrote {TERMS_FILE} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
