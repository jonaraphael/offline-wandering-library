"""Bounded, hash-bound inspection of captured map PDFs; never approves content."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from ..safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file
from ..runtime import file_lock
from .capture import _digest, _json, _read, _staging, load_manifest, normalize_manifest

VERSION = "map-pdf-review-1"
MAX_PDF_BYTES = 96 * 1024 * 1024
MAX_PAGES = 8
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_SOURCE_OUTPUT = 64 * 1024 * 1024
GEOMETRY_WARNING = "GeoPDF registration bounds can include margins and locator insets; they are not certified map-frame or land coverage."


def review_owner(output, manifest_digest, output_budget, reserve):
    """Do not adopt or overwrite an unrelated populated directory."""
    expected = {"schema_version": 1, "owner": "owl-map-pdf-review", "manifest_sha256": manifest_digest,
        "output_budget_bytes": output_budget, "reserve_bytes": reserve}
    marker = output / "owner.json"
    if marker.exists():
        if _read(marker) != expected:
            raise SafetyError("Review directory ownership or declared budget differs")
    else:
        if output.exists() and any(output.iterdir()):
            raise SafetyError("Review directory is populated but has no matching owner")
        if shutil.disk_usage(output if output.exists() else output.parent).free < reserve + MAX_SOURCE_OUTPUT:
            raise SafetyError("Review filesystem cannot preserve its free-space reserve")
        output.mkdir(parents=True, exist_ok=True)
        atomic_write(marker, _json(expected))
    return expected


def review_write(root, path, data, owner):
    """Verify the owned volume is still present and reserve space before writes."""
    if _read(root / "owner.json") != owner or root not in path.parents:
        raise SafetyError("Review output ownership changed")
    if shutil.disk_usage(root).free < owner["reserve_bytes"] + len(data):
        raise SafetyError("Review write would consume the filesystem free-space reserve")
    atomic_write(path, data)


def verified_payload(staging, source, receipt, manifest_digest):
    """Read each original once into bounded memory and bind all receipt identity."""
    expected = {"source_id": source["id"], "source_record_sha256": _digest(source),
                "manifest_sha256": manifest_digest, "source_url": source["source_url"],
                "version": source["version"], "relative_path": "sources/" + source["id"],
                "size_bytes": source["size_bytes"], "metadata_evidence": source["metadata_evidence"],
                "publisher_checksums_verified": source["publisher_checksums"],
                "content_ready": False, "status": "captured_awaiting_review"}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise SafetyError("PDF receipt differs from frozen source identity")
    checksum = receipt.get("sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise SafetyError("PDF receipt lacks a whole-file SHA256")
    if source.get("sha256") not in (None, checksum):
        raise SafetyError("PDF receipt differs from the expected source pin")
    size = source["size_bytes"]
    if not 0 < size <= MAX_PDF_BYTES:
        raise SafetyError("PDF exceeds the 96 MiB per-worker input bound")
    path = safe_path(staging, receipt["relative_path"])
    if not path.is_file() or path.stat().st_size != size or path.stat().st_nlink != 1:
        raise SafetyError("Captured PDF size or file identity changed")
    with path.open("rb") as handle:
        data = handle.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != checksum:
        raise SafetyError("Captured PDF differs from its whole-file receipt hash")
    if not data.startswith(b"%PDF-"):
        raise SafetyError("Captured map does not have a PDF header")
    return data


def _numbers(value, maximum=64):
    if value is None:
        return None
    if len(value) > maximum:
        raise SafetyError("GeoPDF coordinate array exceeds its inspection bound")
    result = [float(number) for number in value]
    if not all(math.isfinite(number) for number in result):
        raise SafetyError("GeoPDF contains nonfinite coordinates")
    return result


def inspect_pdf(data, source, *, render=False):
    import pymupdf
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise SafetyError("Map PDF requires decryption")
    count = len(reader.pages)
    if not 0 < count <= MAX_PAGES:
        raise SafetyError("PDF page count exceeds the eight-page inspection bound")
    root = reader.trailer["/Root"]
    names = root.get("/Names", {})
    names = names.get_object() if hasattr(names, "get_object") else names
    actions = bool(root.get("/OpenAction") or root.get("/AA") or names.get("/JavaScript"))
    pages, images, text_parts, text_bytes = [], [], [], 0
    bbox = source["map_metadata"].get("bbox")
    expected_labels = [f"{number:.4f}°" for number in bbox] if bbox else []
    coordinates = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.page_count != count:
            raise SafetyError("PDF parsers disagree about the page count")
        metadata = {key: str(value)[:2048] for key, value in document.metadata.items() if value}
        for number, (page, pdf_page) in enumerate(zip(document, reader.pages)):
            if not (0 < page.rect.width <= 20000 and 0 < page.rect.height <= 20000):
                raise SafetyError("Map page dimensions exceed inspection bounds")
            text = page.get_text("text")
            text_bytes += len(text.encode())
            if text_bytes > MAX_TEXT_BYTES:
                raise SafetyError("PDF text exceeds its 2 MiB inspection bound")
            text_parts.append(text)
            if expected_labels:
                for word in page.get_text("words"):
                    if word[4] in expected_labels:
                        coordinates.append({"page": number + 1, "text": word[4], "bbox_points": list(word[:4])})
                        if len(coordinates) > 128:
                            raise SafetyError("Too many candidate map-frame coordinate labels")
            viewports = []
            for viewport in pdf_page.get("/VP", []):
                if len(viewports) >= 16:
                    raise SafetyError("PDF has too many geospatial viewports")
                viewport = viewport.get_object()
                measure = viewport.get("/Measure", {})
                measure = measure.get_object() if hasattr(measure, "get_object") else measure
                gcs = measure.get("/GCS", {})
                gcs = gcs.get_object() if hasattr(gcs, "get_object") else gcs
                viewports.append({"name": str(viewport.get("/Name", ""))[:256],
                    "page_bbox": _numbers(viewport.get("/BBox")), "gpts": _numbers(measure.get("/GPTS")),
                    "lpts": _numbers(measure.get("/LPTS")), "bounds": _numbers(measure.get("/Bounds")),
                    "gcs_type": str(gcs.get("/Type", "")), "wkt": str(gcs.get("/WKT", ""))[:8192]})
            pages.append({"page": number + 1, "points": [page.rect.width, page.rect.height],
                "text_characters": len(text), "image_objects": len(page.get_images()),
                "geospatial_viewports": viewports, "legacy_lgidict_present": "/LGIDict" in pdf_page})
            actions = actions or bool(pdf_page.get("/AA"))
            if render:
                # Render full sheet and bottom legend at bounded dimensions. The
                # original PDF remains the authoritative, zoomable reading file.
                for label, clip, desired_scale in (("sheet", page.rect, 2400 / max(page.rect.width, page.rect.height)),
                        ("legend", pymupdf.Rect(0, page.rect.height * .72, page.rect.width, page.rect.height), 2)):
                    scale = min(desired_scale, 3600 / max(clip.width, clip.height))
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
                    if pixmap.width * pixmap.height > 13_000_000:
                        raise SafetyError("Rendered map exceeds its pixel bound")
                    payload = pixmap.tobytes("png")
                    if len(payload) > 16 * 1024 * 1024 or sum(len(i[1]) for i in images) + len(payload) > MAX_SOURCE_OUTPUT - MAX_RECORD_BYTES:
                        raise SafetyError("Map render exceeds the per-source output allowance")
                    images.append((f"page-{number + 1}-{label}.png", payload))
        metadata["renderer"] = "PyMuPDF " + pymupdf.VersionBind
    text = "\n".join(text_parts)
    scale = source["map_metadata"]["scale"]
    digits = r"[\s,]*".join(str(scale))
    scale_matches = [match.group(0) for match in re.finditer(r"\b(?:SCALE\s*)?1\s*:\s*" + digits + r"(?!\d)", text, re.I)]
    year = re.match(r"(\d{4})", source["version"])
    year_matches = re.findall(r"(?<!\d)" + year.group(1) + r"(?!\d)", text) if year else []
    checks = {"scale_label_present": bool(scale_matches), "edition_year_in_page_text": bool(year_matches),
        "no_document_actions": not actions, "all_pages_have_content": all(p["text_characters"] or p["image_objects"] for p in pages),
        "every_page_rendered": bool(render) and len(images) == count * 2}
    if expected_labels:
        checks["publisher_bbox_labels_repeated"] = all(sum(row["text"] == label for row in coordinates) >= 2 for label in expected_labels)
    return {"metadata": metadata, "pages": pages, "page_count": count, "checks": checks,
        "scale_labels": scale_matches[:16], "expected_scale": scale, "expected_edition": source["version"],
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "text_excerpt": text[-4096:],
        "publisher_bbox": bbox, "candidate_frame_coordinate_labels": coordinates,
        "geographic_coverage_approved": False, "geometry_warning": GEOMETRY_WARNING,
        "required_review": ["Verify map-frame extent, readable labels/contours/legend and original notices on every sheet.",
            "A matching year anywhere in extracted text is only a review locator, not approval of the edition.",
            "Resolve explicit fine-scale coastal gaps separately; registration viewports cannot certify them."]}, images


def _cached(record_path, binding, output):
    if not record_path.exists():
        return None
    record = _read(record_path, MAX_RECORD_BYTES)
    if (record.get("binding") != binding or record.get("content_ready") is not False
            or record.get("status") != "inspected_awaiting_review"):
        return None
    for row in record.get("renders", []):
        path = safe_path(output, row["path"])
        if not path.is_file() or path.stat().st_size != row["size_bytes"] or sha256_file(path) != row["sha256"]:
            return None
    return record


def worker(task):
    import pypdf
    import pymupdf

    source, receipt = task["source"], task["receipt"]
    data = verified_payload(Path(task["staging"]), source, receipt, task["manifest_sha256"])
    output = Path(task["output"])
    review_root = Path(task["review_root"])
    owner = task["review_owner"]
    if _read(review_root / "owner.json") != owner:
        raise SafetyError("PDF worker review owner differs from its parent scope")
    reject_symlinks(output)
    record_path = output / "inspection.json"
    binding = {"tool": VERSION, "code_sha256": sha256_file(Path(__file__)), "source_sha256": receipt["sha256"],
        "source_record_sha256": _digest(source), "receipt_sha256": _digest(receipt), "render": task["render"],
        "pypdf_version": pypdf.__version__, "pymupdf_version": pymupdf.VersionBind}
    cached = _cached(record_path, binding, output)
    if cached is not None:
        return cached
    result, images = inspect_pdf(data, source, render=task["render"])
    result.update(schema_version=1, source_id=source["id"], source_url=source["source_url"],
        status="inspected_awaiting_review", content_ready=False, binding=binding, renders=[])
    for name, payload in images:
        review_write(review_root, safe_path(output, name), payload, owner)
        result["renders"].append({"path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    encoded = _json(result)
    if len(encoded) > MAX_RECORD_BYTES:
        raise SafetyError("Map inspection record exceeds its 1 MiB bound")
    review_write(review_root, record_path, encoded, owner)
    return result


def _usage(path):
    total, count = 0, 0
    for item in path.rglob("*") if path.exists() else []:
        reject_symlinks(item)
        count += 1
        if count > 20000:
            raise SafetyError("Review directory exceeds its file-count bound")
        if item.is_file():
            total += item.stat().st_size
    return total


def wait_for_receipt(job, receipt_path, output, deadline, owner):
    """Follow one existing capture; never starts, retries or modifies that job."""
    from ..jobs import status_job

    while not receipt_path.exists():
        status = status_job(job)
        review_write(output, output / "follow-status.json", _json({"capture_job_id": status["job_id"],
            "capture_state": status["state"], "completed_sources": status.get("completed_assets", 0),
            "waiting_for_receipt": receipt_path.name, "content_ready": False}), owner)
        if (status["state"] not in {"running", "retry_wait", "starting"}
                or not status.get("worker_active") or time.monotonic() >= deadline):
            return False
        time.sleep(min(30, max(0, deadline - time.monotonic())))
    return True


def inspect_capture(staging, output, *, render=False, output_budget=10_000_000_000, limit=None, timeout=120,
                    follow_job=None, follow_seconds=28800, reserve=10_000_000_000, production_root=None):
    staging, _ = _staging(staging)
    output, _ = _staging(output, production_root=production_root)
    if output == staging or staging in output.parents or output in staging.parents:
        raise SafetyError("Keep review outputs separate from immutable capture sources")
    manifest = normalize_manifest(_read(staging / "manifest.json"), allow_local=True)
    digest = _digest(manifest)
    owner = _read(staging / "owner.json")
    if owner.get("manifest_sha256") != digest or owner.get("owner") != "owl-acquisition-capture":
        raise SafetyError("Map review requires an owned source capture")
    if any(not s.get("map_metadata") or s.get("fullasset_metadata", {}).get("format") != "pdf" for s in manifest["sources"]):
        raise SafetyError("Map review requires explicit map PDF source metadata")
    if output_budget < MAX_SOURCE_OUTPUT or reserve < 0 or limit is not None and limit < 1:
        raise SafetyError("Invalid review output budget or source limit")
    if follow_job:
        recipe = _read(follow_job / "recipe.json")
        if recipe.get("kind") != "acquisition" or Path(recipe.get("target", "")) != staging or limit is not None:
            raise SafetyError("Follow requires the matching full-scope acquisition job")
        acquisition = recipe["acquisition"]
        settings = acquisition["kwargs"]
        frozen = load_manifest(Path(acquisition["manifest"]), allow_local=settings.get("allow_local", False),
            profile=settings.get("profile"), resource_ids=settings.get("resource_ids", ()))
        if _digest(frozen) != digest:
            raise SafetyError("Follow acquisition manifest differs from the captured source set")
        if not 1 <= follow_seconds <= 43200:
            raise SafetyError("Follow deadline must be within twelve hours")
    deadline = time.monotonic() + follow_seconds
    review_scope = review_owner(output, digest, output_budget, reserve)
    with file_lock(output / "review.lock"):
        return _inspect_owned(staging, output, manifest, digest, review_scope, render=render,
            output_budget=output_budget, reserve=reserve, limit=limit, timeout=timeout,
            follow_job=follow_job, deadline=deadline)


def _inspect_owned(staging, output, manifest, digest, review_scope, *, render, output_budget,
                   reserve, limit, timeout, follow_job, deadline):
    rows, completed = [], 0
    used = _usage(output)
    sources = manifest["sources"] if limit is None else manifest["sources"][:limit]
    for source in sources:
        source_id = source["id"]
        receipt_path = safe_path(staging, "receipts/" + source_id + ".json")
        if not receipt_path.exists() and follow_job:
            if not wait_for_receipt(follow_job, receipt_path, output, deadline, review_scope):
                # Once a capture stops or its deadline expires, report every
                # missing receipt without repeated waits or a success claim.
                follow_job = None
        if not receipt_path.exists():
            rows.append({"source_id": source_id, "status": "pending_capture"})
            continue
        if used + MAX_SOURCE_OUTPUT + MAX_RECORD_BYTES > output_budget:
            raise SafetyError("Review output allowance cannot reserve another bounded source")
        if shutil.disk_usage(output).free < reserve + MAX_SOURCE_OUTPUT:
            raise SafetyError("Review filesystem cannot reserve another bounded worker")
        directory = safe_path(output, source_id)
        directory.mkdir(exist_ok=True)
        previous_size = _usage(directory)
        task = {"staging": str(staging), "output": str(directory), "source": source,
            "receipt": _read(receipt_path), "manifest_sha256": digest, "render": render,
            "review_root": str(output), "review_owner": review_scope}
        task_path = directory / "task.json"
        review_write(output, task_path, _json(task), review_scope)
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[3] / "scripts/inspect_map_capture.py"),
                "--worker", str(task_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            if process.returncode:
                error_path = directory / "error.json"
                error_record = _read(error_path, 4096) if error_path.exists() else {}
                error = (error_record.get("error") if error_record.get("task_sha256") == _digest(task) else
                         "PDF worker failed before writing current bounded evidence")
                rows.append({"source_id": source_id, "status": "failed", "error": error})
            else:
                record = _read(directory / "inspection.json", MAX_RECORD_BYTES)
                completed += 1
                rows.append({"source_id": source_id, "status": record["status"], "source_sha256": record["binding"]["source_sha256"],
                    "checks": record["checks"], "evidence": source_id + "/inspection.json"})
        except subprocess.TimeoutExpired:
            rows.append({"source_id": source_id, "status": "failed", "error": "PDF inspection exceeded bounded worker timeout"})
        used += _usage(directory) - previous_size
        if completed and completed % 25 == 0:
            review_write(output, output / "checkpoint.json", _json({"manifest_sha256": digest, "rows": rows}), review_scope)
    checks = Counter(key for row in rows for key, value in row.get("checks", {}).items() if not value)
    counts = Counter(row["status"] for row in rows)
    result = {"schema_version": 1, "tool": VERSION, "manifest_sha256": digest, "content_ready": False,
        "status": "awaiting_review" if completed == len(manifest["sources"]) else "incomplete",
        "requested_sources": len(manifest["sources"]), "inspected_sources": completed,
        "status_counts": dict(counts), "failed_check_counts": dict(checks), "output_bytes": _usage(output),
        "output_budget_bytes": output_budget, "capture_storage_peak_bytes": manifest["storage_peak_bytes"],
        "combined_reserved_peak_bytes": manifest["storage_peak_bytes"] + output_budget,
        "geographic_coverage_approved": False, "geometry_warning": GEOMETRY_WARNING,
        "coverage": manifest.get("coverage"), "blockers": manifest.get("blockers", []), "rows": rows}
    review_write(output, output / "report.json", _json(result), review_scope)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output-budget-bytes", type=int, default=10_000_000_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--follow-job", type=Path, help="Follow this already-running acquisition for up to eight hours")
    parser.add_argument("--follow-seconds", type=int, default=28800)
    parser.add_argument("--reserve-bytes", type=int, default=10_000_000_000)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        task = _read(args.worker)
        try:
            worker(task)
            return 0
        except Exception as error:
            review_write(Path(task["review_root"]), Path(task["output"]) / "error.json",
                         _json({"error": str(error)[-1200:], "task_sha256": _digest(task)}), task["review_owner"])
            return 1
    if not args.staging or not args.output or not 1 <= args.timeout <= 600:
        parser.error("Require --staging, --output and a 1–600 second worker timeout")
    result = inspect_capture(args.staging, args.output, render=args.render, output_budget=args.output_budget_bytes,
                             limit=args.limit, timeout=args.timeout, follow_job=args.follow_job,
                             follow_seconds=args.follow_seconds, reserve=args.reserve_bytes, production_root=args.production_root)
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "coverage", "blockers"}}, sort_keys=True))
    return int(bool(result["status_counts"].get("failed")))
