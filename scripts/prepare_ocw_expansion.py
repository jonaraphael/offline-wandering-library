#!/usr/bin/env python3
"""Freeze broader distinct OCW course packages using publisher metadata and HEAD.

Then capture packages with acquire_content.py build, inspect with
inspect_ocw_packages.py, and freeze complete media with prepare_ocw_media.py.
This command makes no body downloads or catalog readiness changes.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.acquisition.metadata import Fetcher
from owl.acquisition.ocw_expansion import excluded_courses, freeze_packages, immutable_json, load_index, rank_courses
from owl.acquisition.pins import PinProbe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".owl/acquisition/ocw-expansion-metadata-v1")
    parser.add_argument("--exclude-manifest", action="append", type=Path, default=[])
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start", type=int, default=0, help="Zero-based rank offset for later bounded batches")
    parser.add_argument("--max-source-bytes", type=int, default=20_000_000_000)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--index-only", action="store_true", help="Rank identities without package page/HEAD probes")
    args = parser.parse_args(argv)
    try:
        exclusions = [ROOT / "catalog/acquisition/ocw-course-package-capture.json", *args.exclude_manifest]
        ids, urls = excluded_courses(exclusions)
        fetcher = Fetcher(args.cache_dir, offline=args.offline)
        rows, evidence = load_index(fetcher)
        candidates, available = rank_courses(rows, excluded_ids=ids, limit=args.limit, start=args.start)
        manifest = None
        if not args.index_only:
            def progress(done, total, sources, size):
                if done % 10 == 0 or done == total:
                    print(json.dumps({"courses_probed": done, "courses_selected": total, "package_sources": sources,
                        "source_bytes": size, "body_downloads": 0}), file=sys.stderr, flush=True)
            candidates, manifest = freeze_packages(candidates, fetcher,
                PinProbe(args.cache_dir / "pins", offline=args.offline), excluded_urls=urls,
                max_source_bytes=args.max_source_bytes, progress=progress)
        report = {"schema_version": 1, "operation": "prepare-ocw-expansion", "content_ready": False,
            "body_downloads": 0, "accepted_useful_bytes": 0, "expected_useful_bytes": None,
            "indexed_video_courses": len(rows), "distinct_ranked_courses": available,
            "excluded_course_ids": sorted(ids), "index_evidence": evidence,
            "selection": {"limit": args.limit, "start": args.start, "max_source_bytes": args.max_source_bytes},
            "candidates": candidates, "package_sources": len(manifest["sources"]) if manifest else 0,
            "package_source_bytes": manifest["budget"]["download_bytes"] if manifest else 0,
            "next_gate": "Capture packages, inspect complete members and media/captions, freeze exact media; then review and measure ordinary outputs."}
        immutable_json(args.output / "candidates.json", report)
        if manifest:
            immutable_json(args.output / "package-capture.json", manifest)
        print(json.dumps({k: v for k, v in report.items() if k not in {"candidates", "index_evidence", "excluded_course_ids", "selection"}} |
            {"output": str(args.output.resolve())}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)[:1000]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
