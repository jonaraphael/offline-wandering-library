#!/usr/bin/env python3
"""Bounded source-header and SHA256-sidecar probe; never requests resource bodies."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.pins import PinProbe, probe_manifest
from owl.acquisition.model import AcquisitionError
from owl.safety import atomic_write, reject_symlinks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".owl/acquisition/source-pins"))
    parser.add_argument("--id", action="append", help="Limit to these source ids (repeatable)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.offline and args.refresh:
            raise AcquisitionError("--offline and --refresh cannot be combined")
        reject_symlinks(args.manifest)
        reject_symlinks(args.output)
        if args.manifest.stat().st_size > 512 * 1024:
            raise AcquisitionError("Source probe manifest exceeds bound")
        result = probe_manifest(json.loads(args.manifest.read_text()),
                                PinProbe(args.cache_dir, offline=args.offline, refresh=args.refresh), ids=args.id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
        print(json.dumps({key: result[key] for key in ("operation", "body_downloads", "proposed_count", "pending_count")} |
                         {"detail": str(args.output.resolve())}, indent=2))
    except (AcquisitionError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)[:500]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
