#!/usr/bin/env python3
"""Preserve a prior map-review pass in owned staging, with verified file copies."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.capture import _digest, _json, _read, _staging, normalize_manifest
from owl.acquisition.map_review import MAX_SOURCE_OUTPUT, _usage, review_owner, review_write
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file


def relocate(source, destination, staging, *, budget, reserve, production_root=None):
    source, _ = _staging(source)
    destination, _ = _staging(destination, production_root=production_root)
    staging, _ = _staging(staging)
    if (source == destination or source in destination.parents or destination in source.parents
            or staging == destination or staging in destination.parents):
        raise SafetyError("Relocation requires separate source, review and capture directories")
    manifest = normalize_manifest(_read(staging / "manifest.json"), allow_local=True)
    digest = _digest(manifest)
    if _read(staging / "owner.json").get("manifest_sha256") != digest:
        raise SafetyError("Capture owner differs from relocation source")
    sources = {row["id"]: row for row in manifest["sources"]}
    for path in source.glob("*/inspection.json"):
        record = _read(path)
        identity = record.get("source_id")
        if identity != path.parent.name or identity not in sources or record.get("content_ready") is not False:
            raise SafetyError("Prior review contains an unrelated source")
        receipt = _read(staging / "receipts" / (identity + ".json"))
        binding = record.get("binding", {})
        if (binding.get("source_record_sha256") != _digest(sources[identity])
                or binding.get("receipt_sha256") != _digest(receipt)
                or binding.get("source_sha256") != receipt.get("sha256")):
            raise SafetyError("Prior review evidence differs from source receipts")
        for render in record.get("renders", []):
            image = safe_path(path.parent, render["path"])
            if image.stat().st_size != render["size_bytes"] or sha256_file(image) != render["sha256"]:
                raise SafetyError("Prior review render differs from its saved hash")
    if _read(source / "report.json").get("manifest_sha256") != digest:
        raise SafetyError("Prior review report belongs to a different capture")
    files = []
    for path in sorted(source.rglob("*")):
        reject_symlinks(path)
        if not path.is_file():
            continue
        if len(files) >= 20000 or path.stat().st_size > MAX_SOURCE_OUTPUT:
            raise SafetyError("Prior review exceeds bounded migration inventory")
        files.append({"path": str(path.relative_to(source)), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    owner = review_owner(destination, digest, budget, reserve)
    total = sum(row["size_bytes"] for row in files)
    if _usage(destination) + total + 1024 * 1024 > budget:
        raise SafetyError("Preserved review exceeds destination allowance")
    archive = destination / "prior-evidence" / _digest(files)[:16]
    for row in files:
        original, target = safe_path(source, row["path"]), safe_path(archive, row["path"])
        if target.exists():
            if sha256_file(target) != row["sha256"]:
                raise SafetyError("Preserved review archive changed")
            continue
        with original.open("rb") as handle:
            data = handle.read(MAX_SOURCE_OUTPUT + 1)
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise SafetyError("Prior review changed during relocation")
        review_write(destination, target, data, owner)
    # Preserve exact old evidence, including checkpoint hashes, before removing
    # only the inventoried copies from their former local review directory.
    for row in files:
        if sha256_file(safe_path(archive, row["path"])) != row["sha256"] or sha256_file(safe_path(source, row["path"])) != row["sha256"]:
            raise SafetyError("Relocation verification failed; originals retained")
    report = {"schema_version": 1, "manifest_sha256": digest, "status": "relocated",
        "content_ready": False, "files": files, "bytes": total, "preserved_directory": str(archive.relative_to(destination))}
    review_write(destination, archive / "relocation-manifest.json", _json(report), owner)
    for row in files:
        safe_path(source, row["path"]).unlink()
    for directory in sorted((p for p in source.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        directory.rmdir()
    atomic_write(source / "relocation.json", _json({key: value for key, value in report.items() if key != "files"} | {"review_staging": str(destination)}))
    return {key: value for key, value in report.items() if key != "files"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--budget-bytes", type=int, default=14_000_000_000)
    parser.add_argument("--reserve-bytes", type=int, default=10_000_000_000)
    args = parser.parse_args()
    print(json.dumps(relocate(args.source, args.output, args.staging, budget=args.budget_bytes,
        reserve=args.reserve_bytes, production_root=args.production_root), sort_keys=True))


if __name__ == "__main__":
    main()
