#!/usr/bin/env python3
"""Inspect captured OCW packages, then freeze deduplicated media metadata only.

Runs as a dependent detached review job. No media bodies or catalog admissions
are performed. Each course is a bounded media group; overlap references remain
explicit so a shared source is never downloaded or credited twice.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from owl.acquisition.capture import _digest, _usage, load_manifest, normalize_manifest
from owl.acquisition.metadata import Fetcher
from owl.acquisition.ocw import inspect_capture, MAX_REPORT_BYTES
from owl.acquisition.ocw_expansion import immutable_json, canonical
from owl.acquisition.ocw_media import freeze
from owl.runtime import file_lock
from owl.safety import SafetyError, atomic_write, reject_symlinks


class BudgetMetadata:
    """Bound total metadata traffic as well as every individual response."""
    def __init__(self, fetcher, check_space, maximum=256 * 1024**2):
        self.fetcher, self.check_space, self.maximum = fetcher, check_space, maximum
        self.used, self.identities = 0, set()

    def fetch(self, url, *, kind):
        self.check_space(16 * 1024**2)
        remaining = self.maximum - self.used
        if remaining <= 0:
            raise SafetyError("OCW follow-up metadata byte allowance exhausted")
        body = self.fetcher.fetch(url, kind=kind, max_bytes=min(8 * 1024**2, remaining))
        if url not in self.identities:
            self.used += len(body); self.identities.add(url)
        return body


def deduplicate_manifest(manifest, known):
    """Remove exact source overlap, retaining references for course assembly."""
    sources, reused = [], []
    for source in manifest["sources"]:
        url = source["source_url"]
        if url in known:
            prior = known[url]
            if prior["id"] != source["id"] or prior["size_bytes"] != source["size_bytes"]:
                raise SafetyError("Shared course media identity/size differs from frozen selection")
            if prior.get('publisher_checksums', {}) != source.get('publisher_checksums', {}):
                raise SafetyError("Shared course media checksum metadata differs from frozen selection")
            reused.append({"id": prior["id"], "source_url": url, "size_bytes": prior["size_bytes"]})
        else:
            sources.append(source)
    if not sources:
        return None, reused
    result = normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": manifest["id"],
        "profile": "full-1tb", "content_ready": False, "sources": sources,
        "budget": {"download_bytes": sum(s["size_bytes"] for s in sources), "expanded_bytes": 0,
                   "preview_bytes": 0, "scratch_bytes": 0, "cache_bytes": 0},
        "review_requirements": manifest.get("review_requirements", [])})
    return result, reused


def run(args):
    staging, output = args.package_staging, args.output
    reject_symlinks(staging); reject_symlinks(output)
    manifest = load_manifest(staging / "manifest.json")
    if not 1 <= len(manifest["sources"]) <= 100:
        raise SafetyError("OCW follow-up requires1–100 captured packages")
    if args.output_budget_bytes != 3_000_000_000 or args.reserve_bytes < 10_000_000_000:
        raise SafetyError("OCW follow-up requires its registered3GB peak and10GB reserve")
    prior_manifests = []
    if args.prior_review:
        # A later acquisition lane can run immediately, but its metadata freeze
        # waits for the previous immutable report so cross-batch media dedup is
        # deterministic and requires no repeated model polling.
        reject_symlinks(args.prior_review)
        prior_report = args.prior_review / "report.json"
        deadline = time.monotonic() + 6 * 3600
        while not prior_report.exists():
            if time.monotonic() >= deadline:
                raise SafetyError("Prior OCW review did not finish within the six-hour dependency wait")
            time.sleep(15)
        reject_symlinks(prior_report)
        if prior_report.stat().st_size > MAX_REPORT_BYTES:
            raise SafetyError("Prior OCW review report exceeds16MiB")
        prior = json.loads(prior_report.read_text())
        prior_rows = prior.get('rows', [])
        inspected_prior = sum(row.get('status') == 'inspected_awaiting_review' for row in prior_rows)
        failed_prior = sum(row.get('status') == 'package_inventory_failed' for row in prior_rows)
        if (prior.get("status") not in {"awaiting_review", "awaiting_review_with_failures"}
                or prior.get("content_ready") is not False
                or prior.get("requested_sources") != len(prior_rows)
                or prior.get("inspected_sources") != inspected_prior
                or inspected_prior + failed_prior != len(prior_rows)
                or len({row['source_id'] for row in prior_rows}) != len(prior_rows)):
            raise SafetyError("Prior OCW review lacks complete pending-review inventory evidence")
        prior_manifests = sorted((args.prior_review / "media-proposals").glob("*.json"))
        if len(prior_manifests) > 100:
            raise SafetyError("Prior OCW review exceeds100 bounded course proposals")
    owner = {"owner": "owl-ocw-expansion-review", "schema_version": 1,
        "manifest_sha256": _digest(manifest), "output_budget_bytes": args.output_budget_bytes,
        "reserve_bytes": args.reserve_bytes}
    if output.exists() and not (output / "owner.json").exists():
        raise SafetyError("Refusing to adopt an existing unowned OCW review directory")
    output.mkdir(parents=True, exist_ok=True)
    immutable_json(output / "owner.json", owner)

    def check_space(additional=0):
        used = _usage(output)
        if used + additional > args.output_budget_bytes:
            raise SafetyError("OCW review would exceed its registered output peak")
        if shutil.disk_usage(output).free < additional + args.reserve_bytes:
            raise SafetyError("OCW review reserve would be exhausted")

    with file_lock(output / "review.lock"):
        # Existing inspector hashes each captured ZIP's bounded members and
        # caches a <=16MiB inventory per course. It writes no extracted bodies.
        check_space(len(manifest["sources"]) * MAX_REPORT_BYTES)
        inventories = output / "inventories"
        inspected = inspect_capture(staging, inventories,
            isolate_package_failures=args.isolate_package_failures)
        immutable_json(output / "package-inspection.json", inspected)
        known = {}
        for path in [*args.exclude_media_manifest, *prior_manifests]:
            prior = load_manifest(path)
            for source in prior["sources"]:
                if source["source_url"] in known and known[source["source_url"]] != source:
                    raise SafetyError("Excluded source manifests conflict")
                known[source["source_url"]] = source
        fetcher = BudgetMetadata(Fetcher(output / "metadata", offline=args.offline), check_space)
        rows, new_bytes, new_sources = [], 0, 0
        for path in sorted(inventories.glob("*.json")):
            check_space(2 * MAX_REPORT_BYTES)
            inventory = json.loads(path.read_text())
            identity = "ocw-expansion-media-" + inventory["source_id"]
            row = {"source_id": inventory["source_id"], "title": inventory["course"]["course_title"],
                "status": "inspected_awaiting_review", "expanded_package_bytes": inventory["expanded_bytes"],
                "inventory_gaps": inventory["gaps"], "excluded_translations": inventory["excluded_translations"],
                "content_ready": False, "accepted_useful_bytes": 0, "expected_useful_bytes": None,
                "remaining_reviews": inventory["remaining_reviews"]}
            try:
                result = freeze([inventory], fetcher, identity=identity)
                if result.get("exceptions"):
                    row["media_exceptions"] = result["exceptions"]
                else:
                    selection, reused = deduplicate_manifest(result, known)
                    row["shared_media_references"] = reused
                    row["media_sources"] = len(result["sources"])
                    row["media_source_bytes"] = sum(s["size_bytes"] for s in result["sources"])
                    if selection:
                        destination = output / "media-proposals" / (inventory["source_id"] + ".json")
                        immutable_json(destination, selection)
                        row["media_capture_manifest"] = str(destination)
                        row["new_media_source_bytes"] = selection["budget"]["download_bytes"]
                        new_bytes += row["new_media_source_bytes"]; new_sources += len(selection["sources"])
                        known.update({s["source_url"]: s for s in selection["sources"]})
            except (OSError, ValueError, KeyError, TypeError) as error:
                row["media_exceptions"] = [{"reason": str(error)[:500]}]
            rows.append(row)
            checkpoint = {"schema_version": 1, "manifest_sha256": owner["manifest_sha256"],
                "content_ready": False, "rows": rows}
            payload = (json.dumps(checkpoint, indent=2, sort_keys=True) + "\n").encode()
            if len(payload) > MAX_REPORT_BYTES:
                raise SafetyError("OCW follow-up checkpoint exceeds16MiB")
            check_space(len(payload))
            atomic_write(output / "checkpoint.json", payload)
            print(json.dumps({"courses_inspected": len(rows), "courses_total": len(manifest["sources"]),
                "unique_new_media_source_bytes": new_bytes, "body_downloads": 0}), flush=True)
        successful = len(rows)
        failures = inspected.get('failures', [])
        rows.extend({**failure, 'title':failure['source_id'], 'accepted_useful_bytes':0,
            'expected_useful_bytes':None, 'remaining_reviews':['Resolve the package inventory failure without relaxing archive limits.']}
            for failure in failures)
        if {row['source_id'] for row in rows} != {source['id'] for source in manifest['sources']} or len(rows) != len(manifest['sources']):
            raise SafetyError('OCW follow-up did not account for every captured package exactly once')
        checkpoint = {"schema_version":1, "manifest_sha256":owner["manifest_sha256"],
            "content_ready":False, "rows":rows}
        if not rows:
            raise SafetyError('OCW follow-up produced no inventory results')
        report = {**checkpoint, "status": "awaiting_review_with_failures" if failures else "awaiting_review", "inspected_sources": successful,
            "requested_sources": len(manifest["sources"]), "failed_check_counts": {"package_inventory":len(failures)} if failures else {},
            "unique_new_media_sources": new_sources, "unique_new_media_source_bytes": new_bytes,
            "accepted_useful_bytes": 0, "expected_useful_bytes": None,
            "metadata_bytes": fetcher.used, "body_downloads": 0,
            "next_gate": "Budget and acquire frozen media proposals, resolve all inventory gaps and essential readings, review ordinary complete-course outputs before admission."}
        immutable_json(output / "report.json", report)
        check_space()
        return {k: v for k, v in report.items() if k not in {"rows", "manifest_sha256"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-staging", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-media-manifest", type=Path, action="append", default=[])
    parser.add_argument("--prior-review", type=Path, help="Wait for and deduplicate against a preceding immutable OCW review")
    parser.add_argument("--output-budget-bytes", type=int, default=3_000_000_000)
    parser.add_argument("--reserve-bytes", type=int, default=10_000_000_000)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--isolate-package-failures", action="store_true",
        help="Report bounded per-package inventory failures while completing independent courses")
    print(json.dumps(run(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
