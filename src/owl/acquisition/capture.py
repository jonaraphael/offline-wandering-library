"""Owned source-review builds: capture bytes, record observations, never publish.

Acquisition manifests and receipts live outside the active library catalog.
An observed hash identifies captured bytes; it is not a content-review approval.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from urllib.parse import urlsplit
import uuid
import zlib

from ..download import download, verified
from ..runtime import file_lock
from ..safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SOURCES = 10000
DEFAULT_RESERVE = 1024 * 1024 * 1024
COMPONENTS = ("download_bytes", "expanded_bytes", "preview_bytes", "scratch_bytes", "cache_bytes")
HASH_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64, "crc32": 8}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
REPO_ROOT = Path(__file__).resolve().parents[3]


def _json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _read(path, maximum=MAX_MANIFEST_BYTES):
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > maximum or path.stat().st_nlink != 1:
        raise SafetyError(f"Invalid acquisition metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SafetyError("Acquisition metadata must be an object")
    return value


def _url(value, *, allow_local=False):
    parts = urlsplit(value) if isinstance(value, str) else None
    allowed = {"https", "file", "repo"} if allow_local else {"https"}
    if (not parts or parts.scheme not in allowed or parts.username or parts.password or parts.fragment
            or (parts.scheme == "https" and not parts.hostname)):
        raise SafetyError("Capture requires a frozen HTTPS publisher source identity")
    return value


def normalize_manifest(document, *, allow_local=False):
    """Validate candidates without admitting them to the resolved catalog."""
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or document.get("kind") != "acquisition" or not IDENTIFIER.fullmatch(str(document.get("id", "")))):
        raise SafetyError("Capture manifest requires schema_version 1, kind acquisition and a portable id")
    result = deepcopy(document)
    sources = result.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        raise SafetyError(f"Capture manifest requires 1–{MAX_SOURCES} source records")
    ids, urls = set(), set()
    for source in sources:
        if not isinstance(source, dict) or not IDENTIFIER.fullmatch(str(source.get("id", ""))):
            raise SafetyError("Capture source requires a portable id")
        if source["id"] in ids or _url(source.get("source_url"), allow_local=allow_local) in urls:
            raise SafetyError("Duplicate capture source id or URL")
        ids.add(source["id"])
        urls.add(_url(source.get("source_url"), allow_local=allow_local))
        resources = source.get("resource_ids")
        if (not isinstance(resources, list) or not resources or any(not isinstance(i, str) or not IDENTIFIER.fullmatch(i) for i in resources)
                or len(resources) != len(set(resources))):
            raise SafetyError("Every capture source needs explicit resource_ids")
        if not isinstance(source.get("version"), str) or not source["version"].strip():
            raise SafetyError("Every capture source needs a frozen version")
        if type(source.get("size_bytes")) is not int or source["size_bytes"] <= 0:
            raise SafetyError("Capture source size must be exact and positive")
        source.setdefault("sha256", None)
        if source["sha256"] is not None and not re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            raise SafetyError("Capture SHA256 must be a whole-file lowercase hash or null")
        checksums = source.setdefault("publisher_checksums", {})
        if not isinstance(checksums, dict) or set(checksums) - HASH_LENGTHS.keys():
            raise SafetyError("Publisher checksums must retain supported algorithm labels")
        for algorithm, checksum in checksums.items():
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{" + str(HASH_LENGTHS[algorithm]) + "}", checksum):
                raise SafetyError("Malformed publisher checksum")
        if checksums.get("sha256") and source["sha256"] not in {None, checksums["sha256"]}:
            raise SafetyError("Conflicting publisher SHA256 pins")
        evidence = source.get("metadata_evidence")
        if not isinstance(evidence, list) or not evidence or len(evidence) > 100:
            raise SafetyError("Source capture requires bounded frozen metadata evidence")
        for row in evidence:
            if (not isinstance(row, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", "")))):
                raise SafetyError("Metadata evidence needs its own SHA256, distinct from a content pin")
            _url(row.get("url"))
        if "fullasset_metadata" in source and not isinstance(source["fullasset_metadata"], dict):
            raise SafetyError("fullasset_metadata must be an object")
    budget = result.get("budget")
    if not isinstance(budget, dict) or set(budget) != set(COMPONENTS):
        raise SafetyError("Capture budget needs download, expanded, preview, scratch and cache byte components")
    if any(type(budget[key]) is not int or budget[key] < 0 for key in COMPONENTS):
        raise SafetyError("Capture budget components must be nonnegative exact byte counts")
    if budget["download_bytes"] != sum(source["size_bytes"] for source in sources):
        raise SafetyError("Download budget must equal the selected source bytes without double counting")
    metadata_bytes = 1024 * 1024 + 16384 * len(sources) + 4 * len(_json(sources))
    minimum_peak = sum(budget.values()) + metadata_bytes
    peak = result.get("storage_peak_bytes", minimum_peak)
    if type(peak) is not int or peak < minimum_peak:
        raise SafetyError("storage_peak_bytes omits declared components or receipt allowance")
    result["storage_peak_bytes"] = peak
    result["metadata_allowance_bytes"] = metadata_bytes
    if len(_json(result)) > MAX_MANIFEST_BYTES:
        raise SafetyError("Capture manifest exceeds its 16 MiB bound")
    return result


def load_manifest(path, *, allow_local=False, resource_ids=(), profile=None):
    document = normalize_manifest(_read(Path(path)), allow_local=allow_local)
    if profile is not None and document.get("profile") != profile:
        raise SafetyError("Requested profile differs from the frozen acquisition manifest")
    if resource_ids:
        requested = set(resource_ids)
        known = {identity for source in document["sources"] for identity in source["resource_ids"]}
        if not requested <= known:
            raise SafetyError("Requested resource is absent from the acquisition manifest")
        document["sources"] = [source for source in document["sources"] if requested & set(source["resource_ids"])]
        document["budget"]["download_bytes"] = sum(source["size_bytes"] for source in document["sources"])
        document.pop("storage_peak_bytes", None)
        document["resource_filter"] = sorted(requested)
    return normalize_manifest(document, allow_local=allow_local)


def _existing(path):
    current = path
    while not current.exists():
        if current.parent == current:
            raise SafetyError("No existing acquisition staging filesystem")
        current = current.parent
    reject_symlinks(current)
    if not current.is_dir():
        raise SafetyError("Acquisition staging parent must be a directory")
    return current


def _staging(path, production_root=None):
    path = Path(os.path.abspath(path))
    reject_symlinks(path)
    for ancestor in (path, *path.parents):
        if (ancestor.name.upper() == "LIBRARY" or (ancestor / "START_HERE.html").exists()
                or (ancestor / "LIBRARY" / "BUILD_INFO.json").is_file()
                or (ancestor / "LIBRARY" / ".owl" / "state.json").is_file()):
            raise SafetyError("Source-review acquisition must use separate staging, outside the production library")
    anchor = _existing(path)
    if production_root is not None:
        production = Path(os.path.abspath(production_root))
        if not production.is_dir():
            raise SafetyError("Protected production root must be mounted before comparing filesystems")
        reject_symlinks(production)
        if production.stat().st_dev == anchor.stat().st_dev:
            raise SafetyError("Acquisition staging must use a different filesystem from the protected production library")
    return path, anchor


def _usage(path):
    size = 0
    if path.exists():
        for child in path.rglob("*"):
            reject_symlinks(child)
            info = child.stat()
            if child.is_file():
                if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
                    raise SafetyError("Acquisition workspace contains an unsafe file")
                size += info.st_size
            elif not child.is_dir():
                raise SafetyError("Acquisition workspace contains a nonregular entry")
    return size


def _owner(path, manifest_digest, *, held_lock=False):
    marker = path / "owner.json"
    if marker.exists():
        owner = _read(marker, 16384)
        if (owner.get("owner") != "owl-acquisition-capture" or owner.get("schema_version") != 1
                or owner.get("manifest_sha256") != manifest_digest):
            raise SafetyError("Staging belongs to a different acquisition manifest; choose a new staging directory")
        return owner
    if path.exists() and any(child.name != "capture.lock" or not held_lock for child in path.iterdir()):
        raise SafetyError("Acquisition staging is not empty and has no matching owner")
    return None


def _effective_peak(path, manifest):
    """Explicit preview phases may extend storage without changing source identity."""
    peak = manifest["storage_peak_bytes"]
    for marker in (path / "previews").glob("*/owner.json"):
        owner = _read(marker)
        budget = owner.get("phase_budget", {})
        if (owner.get("owner") != "owl-acquisition-preview" or owner.get("manifest_sha256") != _digest(manifest)
                or not isinstance(budget, dict) or set(budget) != set(COMPONENTS)
                or any(type(v) is not int or v < manifest["budget"][key] for key, v in budget.items())
                or owner.get("storage_peak_bytes") != sum(budget.values()) + manifest["metadata_allowance_bytes"]):
            raise SafetyError("Invalid recorded preview storage phase")
        peak = max(peak, owner["storage_peak_bytes"])
    return peak


def _space(path, peak, reserve):
    used = _usage(path)
    if used > peak:
        raise SafetyError("Retained acquisition files exceed the declared storage peak")
    required = max(0, peak - used) + reserve
    free = shutil.disk_usage(_existing(path)).free
    if free < required:
        raise SafetyError(f"Acquisition needs {required:,} free bytes including reserve; only {free:,} available")
    return {"retained_bytes": used, "required_free_bytes": required, "available_free_bytes": free}


def _transport_record(path, value):
    data = _json(value)
    if len(data) > 16384:
        raise SafetyError("Response identity evidence exceeds its bounded receipt allowance")
    atomic_write(path, data)


def _publisher_hashes(path, expected):
    hashes = {name: hashlib.new(name) for name in expected if name != "crc32"}
    crc = 0
    if expected:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                for digest in hashes.values():
                    digest.update(chunk)
                if "crc32" in expected:
                    crc = zlib.crc32(chunk, crc)
    actual = {name: value.hexdigest() for name, value in hashes.items()}
    if "crc32" in expected:
        actual["crc32"] = f"{crc & 0xffffffff:08x}"
    if actual != expected:
        raise SafetyError("Captured source differs from its frozen publisher checksum evidence")
    return actual


def _receipt(path, source, manifest_digest):
    receipt_path = safe_path(path, "receipts/" + source["id"] + ".json")
    if not receipt_path.exists():
        return None
    receipt = _read(receipt_path)
    if (receipt.get("manifest_sha256") != manifest_digest or receipt.get("source_record_sha256") != _digest(source)
            or receipt.get("source_id") != source["id"] or receipt.get("relative_path") != "sources/" + source["id"]
            or receipt.get("source_url") != source["source_url"] or receipt.get("version") != source["version"]
            or receipt.get("metadata_evidence") != source["metadata_evidence"]
            or receipt.get("size_bytes") != source["size_bytes"]
            or not isinstance(receipt.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])
            or receipt.get("publisher_checksums_verified") != source["publisher_checksums"]
            or receipt.get("content_ready") is not False or receipt.get("status") != "captured_awaiting_review"):
        raise SafetyError("Acquisition receipt differs from its frozen source identity")
    expected = source["sha256"] or source["publisher_checksums"].get("sha256")
    if expected and receipt["sha256"] != expected:
        raise SafetyError("Acquisition receipt differs from its publisher SHA256 pin")
    if not verified(safe_path(path, receipt["relative_path"]), receipt["size_bytes"], receipt["sha256"]):
        raise SafetyError("Captured original changed after its receipt; preserve evidence and capture into a new directory")
    return receipt


def _local_sources(local_manifest, manifest):
    if local_manifest is None:
        return {}
    values = _read(Path(local_manifest))
    records = {s["id"]: s for s in manifest["sources"]}
    if set(values) - records.keys():
        raise SafetyError("Local reuse manifest contains sources outside the selected capture")
    result = {}
    for identity, value in values.items():
        source = records[identity]
        if not (source["sha256"] or source["publisher_checksums"].get("sha256")):
            raise SafetyError("Local reuse requires the frozen publisher/catalog whole-file SHA256")
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise SafetyError("Local reuse paths must be explicit absolute paths")
        path = Path(value)
        reject_symlinks(path)
        if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != source["size_bytes"]:
            raise SafetyError("Local reuse source is not a regular file of the frozen size")
        result[identity] = path
    return result


def capture(manifest_path, staging, *, budget_bytes=None, reserve_bytes=DEFAULT_RESERVE,
            plan_only=False, allow_local=False, production_root=None, local_manifest=None,
            resource_ids=(), profile=None, progress=print):
    manifest = load_manifest(manifest_path, allow_local=allow_local, resource_ids=resource_ids, profile=profile)
    digest = _digest(manifest)
    local_sources = _local_sources(local_manifest, manifest)
    path, anchor = _staging(staging, production_root)
    owner = _owner(path, digest)
    peak = _effective_peak(path, manifest)
    budget_bytes = peak if budget_bytes is None else budget_bytes
    if type(budget_bytes) is not int or budget_bytes < peak or type(reserve_bytes) is not int or reserve_bytes < 0:
        raise SafetyError("Acquisition budget must cover the declared peak and reserve must be nonnegative")
    space = _space(path, peak, reserve_bytes)
    report = {"operation": "capture", "status": "planned" if plan_only else "awaiting_review",
              "content_ready": False, "manifest_id": manifest["id"], "manifest_sha256": digest,
              "source_count": len(manifest["sources"]), "local_source_count": len(local_sources), "budget": manifest["budget"],
              "storage_peak_bytes": peak, "budget_bytes": budget_bytes, "reserve_bytes": reserve_bytes,
              "staging": str(path), "staging_root": str(path), "free_bytes": space["available_free_bytes"], **space}
    if plan_only:
        report["body_downloads"] = 0
        return report
    # Protect the already mounted parent before creating child directories.
    with ExitStack() as stack:
        stack.enter_context(guard_directory(anchor))
        path.mkdir(parents=True, exist_ok=True)
        stack.enter_context(guard_directory(path))
        stack.enter_context(file_lock(path / "capture.lock"))
        owner = _owner(path, digest, held_lock=True)
        if owner is None:
            owner = {"schema_version": 1, "owner": "owl-acquisition-capture", "capture_id": uuid.uuid4().hex,
                     "manifest_sha256": digest, "manifest_id": manifest["id"]}
            atomic_write(path / "owner.json", _json(owner))
            atomic_write(path / "manifest.json", _json(manifest))
        _owner(path, digest)
        if _read(path / "manifest.json") != manifest:
            raise SafetyError("Frozen capture manifest changed")
        receipts, reused, downloads, local_copies = [], 0, 0, 0
        for number, source in enumerate(manifest["sources"]):
            if hasattr(progress, "event"):
                progress.event(phase="acquisition", active_asset=source["id"], completed_assets=number,
                               total_assets=len(manifest["sources"]))
            _space(path, peak, reserve_bytes)
            receipt = _receipt(path, source, digest)
            if receipt is None:
                destination = safe_path(path, "sources/" + source["id"])
                # A crash after rename but before receipt leaves a complete file.
                # Reobserve it against the frozen identity and publisher hashes.
                expected = source["sha256"] or source["publisher_checksums"].get("sha256")
                transport_path = safe_path(path, "transport/" + source["id"] + ".json")
                if destination.is_file():
                    if destination.stat().st_size != source["size_bytes"]:
                        raise SafetyError("Unreceipted captured original has an unexpected size")
                    observed = sha256_file(destination)
                    if expected and observed != expected:
                        raise SafetyError("Unreceipted captured original differs from its publisher pin")
                elif source["id"] in local_sources:
                    from ..transfer import resume_copy
                    original = local_sources[source["id"]]
                    if not verified(original, source["size_bytes"], expected):
                        raise SafetyError("Local reuse source SHA256 differs from the frozen publisher/catalog pin")
                    transport = {"kind": "local_reuse", "official_source_url": source["source_url"],
                                 "local_path": str(original), "size_bytes": source["size_bytes"], "sha256": expected}
                    _transport_record(transport_path, transport)
                    observed = resume_copy(original, destination, size=source["size_bytes"], checksum=expected, progress=progress)
                    local_copies += 1
                else:
                    observed = download({**source, "sha256": expected}, destination, repo_root=REPO_ROOT, progress=progress,
                                        response_evidence=lambda value: _transport_record(transport_path, value))
                    downloads += 1
                checksums = _publisher_hashes(destination, source["publisher_checksums"])
                receipt = {"schema_version": 1, "status": "captured_awaiting_review", "content_ready": False,
                           "source_id": source["id"], "source_record_sha256": _digest(source), "manifest_sha256": digest,
                           "source_url": source["source_url"], "version": source["version"],
                           "relative_path": "sources/" + source["id"], "size_bytes": source["size_bytes"],
                           "sha256": observed, "verification": "publisher-pinned" if expected else "observed",
                           "publisher_checksums_verified": checksums, "metadata_evidence": source["metadata_evidence"],
                           "response_evidence": _read(transport_path) if transport_path.exists() else {"kind": "unavailable", "reason": "Recovered original has no transport evidence"},
                           "captured_at": datetime.now(timezone.utc).isoformat()}
                receipt_path = safe_path(path, "receipts/" + source["id"] + ".json")
                atomic_write(receipt_path, _json(receipt))
            else:
                reused += 1
                progress("REUSE captured " + source["id"])
            receipts.append(receipt)
        pins = [{key: row[key] for key in ("source_id", "size_bytes", "sha256", "relative_path", "verification")} for row in receipts]
        report.update(body_downloads=downloads, local_copies=local_copies, reused_sources=reused, sources=pins,
                      local_manifest={row["source_id"]: str(path / row["relative_path"]) for row in receipts})
        candidate = {"schema_version": 1, "assets": [], "resource_updates": [],
                     "acquisition_capture": {"capture_id": owner["capture_id"], "manifest_sha256": digest}}
        by_id = {row["source_id"]: row for row in receipts}
        for source in manifest["sources"]:
            if source.get("fullasset_metadata"):
                receipt = by_id[source["id"]]
                candidate["assets"].append({**source["fullasset_metadata"], "id": source["id"],
                    "source_url": source["source_url"], "version": source["version"],
                    "size_bytes": receipt["size_bytes"], "sha256": receipt["sha256"],
                    "acquisition_provenance": {"manifest_sha256": digest, "source_id": source["id"]}})
        candidate_path = path / "candidate-fragment.json"
        if candidate_path.exists() and _read(candidate_path) != candidate:
            raise SafetyError("Capture candidate fragment changed; keep review edits in a separate file")
        if not candidate_path.exists():
            atomic_write(candidate_path, _json(candidate))
        report["candidate_fragment"] = str(candidate_path)
        atomic_write(path / "capture-report.json", _json(report))
        _space(path, peak, reserve_bytes)
        return report


def load_capture_sources(staging):
    """Return reverified captured bytes; never reinterpret them as approved."""
    path, _ = _staging(staging)
    manifest = _read(path / "manifest.json")
    # Source scheme permission was frozen by the capture operation. Revalidation
    # here does no acquisition, so local synthetic captures remain inspectable.
    manifest = normalize_manifest(manifest, allow_local=True)
    digest = _digest(manifest)
    _owner(path, digest)
    receipts = [_receipt(path, source, digest) for source in manifest["sources"]]
    if any(receipt is None for receipt in receipts):
        raise SafetyError("Capture is incomplete; source review requires every requested receipt")
    return manifest, receipts


class _ZimWriteLedger:
    """Conservative write accounting while the capture/export locks are held.

    Scan once, then charge every exporter callback. Atomic replacement credit is
    deferred until a later callback observes the new inode; interrupted writes
    never receive speculative credit. The caller still measures final usage.
    """
    def __init__(self, staging, export_root, identity, *, peak, workspace, reserve):
        self.staging, self.root = staging, export_root
        self.private = export_root / ".owl"
        self.peak, self.workspace, self.reserve = peak, workspace, reserve
        self.used = _usage(staging)
        self.control = sum(p.stat().st_size for p in self.private.rglob("*")
                           if p.is_file() and "parts" not in p.relative_to(self.private).parts)
        self.pending = None
        # Directory ownership and lock initialization are the exporter's only
        # writes outside its callback. Account their observed growth explicitly.
        paths = [self.private / "owner.json", self.private / "build.lock",
                 self.private / "exports" / identity / "export.lock"]
        self.unhooked = {p: p.stat().st_size if p.exists() else 0 for p in paths}

    def settle(self):
        if self.pending is not None:
            destination, size, old_size, old_inode, control = self.pending
            reject_symlinks(destination)
            info = destination.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != size
                    or old_inode is not None and (info.st_dev, info.st_ino) == old_inode):
                raise SafetyError("ZIM atomic write did not complete before another write")
            self.used -= old_size
            if control:
                self.control -= old_size
            self.pending = None
        for destination, previous in self.unhooked.items():
            reject_symlinks(destination)
            size = destination.stat().st_size if destination.exists() else 0
            if size < previous:
                raise SafetyError("ZIM ownership or lock file shrank during preview")
            self.used += size - previous
            self.control += size - previous
            self.unhooked[destination] = size

    def __call__(self, destination, amount):
        destination = Path(destination)
        if not destination.is_relative_to(self.root) or type(amount) is not int or amount < 0:
            raise SafetyError("ZIM exporter attempted an invalid write outside owned preview storage")
        self.settle()
        reject_symlinks(destination)
        info = destination.stat() if destination.exists() else None
        if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise SafetyError("ZIM output is not a regular owned file")
        control = destination.is_relative_to(self.private) and "parts" not in destination.relative_to(self.private).parts
        if self.used + amount > self.peak:
            raise SafetyError("ZIM preview exceeds its total peak before writing")
        if shutil.disk_usage(self.staging).free < amount + self.reserve:
            raise SafetyError("Insufficient free space before ZIM preview write")
        if control and self.control + amount > self.workspace:
            raise SafetyError("ZIM preview metadata exceeds its scratch allowance before writing")
        self.used += amount
        if control:
            self.control += amount
        if not (destination.is_relative_to(self.private) and "parts" in destination.relative_to(self.private).parts):
            self.pending = (destination, amount, info.st_size if info else 0,
                            (info.st_dev, info.st_ino) if info else None, control)


def _document(path):
    """Bound JSON/YAML control documents; never read a resource body here."""
    import yaml
    path = Path(path)
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES or path.stat().st_nlink != 1:
        raise SafetyError("Invalid or oversized acquisition control document")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SafetyError("Acquisition control document must be an object")
    return value


def _scope(manifest, *, resource_ids=(), profile=None):
    if profile is not None and manifest.get("profile") != profile:
        raise SafetyError("Requested profile differs from the frozen acquisition manifest")
    known = {identity for source in manifest["sources"] for identity in source["resource_ids"]}
    requested = set(resource_ids) if resource_ids else known
    if not requested <= known:
        raise SafetyError("Requested resource is absent from the acquisition manifest")
    return requested


def _immutable(path, value):
    if path.exists():
        if _read(path) != value:
            raise SafetyError("Immutable acquisition evidence changed: " + path.name)
    else:
        atomic_write(path, _json(value))


def _bounded_immutable(staging, destination, value, *, peak, reserve):
    """Control evidence has the same pre-write peak/reserve limits as bodies."""
    if destination.exists():
        return _immutable(destination, value)
    payload = _json(value)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise SafetyError("Acquisition control evidence exceeds its 16 MiB read/write bound")
    retained = _usage(staging)
    if retained + len(payload) > peak:
        raise SafetyError("Acquisition metadata exceeds the storage peak before writing")
    if shutil.disk_usage(_existing(destination.parent)).free < len(payload) + reserve:
        raise SafetyError("Insufficient free space before acquisition metadata write")
    _immutable(destination, value)


def _reserve_destination(reserved, relative):
    """Reject final/temporary and file/directory aliases before any body write."""
    folded = relative.casefold()
    if any(folded == item or folded.startswith(item + "/") or item.startswith(folded + "/")
           for item in reserved):
        raise SafetyError("Preview output/companion destination collision")
    reserved.add(folded)


def _preview_receipt(staging, path):
    record = _read(path)
    if (record.get("schema_version") != 1 or record.get("status") != "preview_awaiting_review"
            or record.get("content_ready") is not False or not isinstance(record.get("outputs"), list)):
        raise SafetyError("Invalid pending preview receipt")
    expected_root = path.parent / "files"
    for row in record["outputs"] + record.get("companions", []):
        target = safe_path(staging, row["relative_path"])
        if not target.is_relative_to(expected_root) or not verified(target, row["size_bytes"], row["sha256"]):
            raise SafetyError("Preview output changed or escaped its owned files directory")
    return record


def preview(staging, recipe_path, assets_path, *, preview_bytes=None, expanded_bytes=None, scratch_bytes=None,
            reserve_bytes=None, budget_bytes=None, shared_expansion=None, resource_ids=(), profile=None, progress=print):
    """Render known adapters from captured pins without approving any content.

    Preview files use production destinations and pins. Referenced companions
    are streamed into the preview within its explicitly declared byte budget.
    """
    from . import documents, mdoc, corpus, lessons, ocw_package, zip_localized
    adapters = {"html_snapshot": documents, "manual_html": documents, "mdoc": mdoc,
                "stackexchange": corpus, "lessons": lessons, "ocw_package": ocw_package, "zip_localized": zip_localized}
    path, _ = _staging(staging)
    manifest, receipts = load_capture_sources(path)
    shared_record = None
    if shared_expansion is not None:
        from .stackoverflow_trial import verified_shared
        shared_record = verified_shared(path, shared_expansion, manifest, receipts)
    requested = _scope(manifest, resource_ids=resource_ids, profile=profile)
    recipe = _document(recipe_path)
    if "recipes" in recipe:
        if len(recipe["recipes"]) != 1:
            raise SafetyError("Preview needs exactly one frozen recipe")
        recipe = recipe["recipes"][0]
    identity = recipe.get("id")
    if not isinstance(identity, str) or not IDENTIFIER.fullmatch(identity):
        raise SafetyError("Preview recipe needs a portable id")
    if recipe.get("resource_id") not in requested:
        raise SafetyError("Preview recipe is outside the requested resource scope")
    if recipe.get("adapter") == "zim_direct":
        return _preview_zim(path, manifest, receipts, recipe, assets_path, preview_bytes=preview_bytes,
                            expanded_bytes=expanded_bytes, scratch_bytes=scratch_bytes, reserve_bytes=reserve_bytes,
                            budget_bytes=budget_bytes, progress=progress)
    if recipe.get("adapter") not in adapters:
        raise SafetyError("Preview adapter is unsupported; keep this content gap pending")
    source_ids, output_ids = recipe.get("source_asset_ids"), recipe.get("output_asset_ids")
    if (not isinstance(source_ids, list) or not source_ids or not isinstance(output_ids, list) or not output_ids
            or any(not isinstance(i, str) or not IDENTIFIER.fullmatch(i) for i in source_ids + output_ids)
            or len(set(source_ids)) != len(source_ids) or len(set(output_ids)) != len(output_ids)
            or set(source_ids) & set(output_ids)):
        raise SafetyError("Preview source/output identities must be unique and disjoint")
    templates = _document(assets_path).get("assets")
    if not isinstance(templates, list) or any(not isinstance(a, dict) for a in templates):
        raise SafetyError("Preview requires an explicit assets template")
    assets = {a.get("id"): deepcopy(a) for a in templates if isinstance(a.get("id"), str)}
    if len(assets) != len(templates):
        raise SafetyError("Preview asset IDs are missing or duplicate")
    source_records = {s["id"]: s for s in manifest["sources"]}
    receipt_by_id = {r["source_id"]: r for r in receipts}
    sources = {}
    for source_id, source in source_records.items():
        row = receipt_by_id[source_id]
        metadata = {**source.get("fullasset_metadata", {}), **assets.get(source_id, {}),
                    "id": source_id, "source_url": source["source_url"], "version": source["version"],
                    "size_bytes": row["size_bytes"], "sha256": row["sha256"]}
        assets[source_id] = metadata
        sources[source_id] = safe_path(path, row["relative_path"])
    if any(i not in assets for i in output_ids):
        raise SafetyError("Preview output is missing an asset template")
    owner = _owner(path, _digest(manifest))
    report = _read(path / "capture-report.json")
    reserve = report["reserve_bytes"] if reserve_bytes is None else reserve_bytes
    allowances = dict(manifest["budget"])
    for key, value in (("preview_bytes", preview_bytes), ("expanded_bytes", expanded_bytes), ("scratch_bytes", scratch_bytes)):
        if value is not None:
            if type(value) is not int or value < allowances[key]:
                raise SafetyError("Preview phase allowance must be finite and cover the original declaration")
            allowances[key] = value
    allowance = allowances["preview_bytes"]
    phase_peak = sum(allowances.values()) + manifest["metadata_allowance_bytes"]
    if (allowance <= 0 or type(reserve) is not int or reserve < 0
            or budget_bytes is not None and (type(budget_bytes) is not int or budget_bytes < phase_peak)):
        raise SafetyError("Preview phase needs a positive preview allowance, nonnegative reserve and sufficient budget")
    workspace = recipe.get("workspace_bytes", 0)
    if type(workspace) is not int or workspace < 0 or workspace > allowances["scratch_bytes"]:
        raise SafetyError("Preview workspace exceeds declared scratch_bytes")
    signature = _digest({"recipe": recipe, "assets": templates, "manifest_sha256": _digest(manifest),
                         "source_receipts": receipts, "phase_budget": allowances, "reserve_bytes": reserve,
                         **({"shared_expansion_sha256": _digest(shared_record)} if shared_record else {})})
    preview_dir = safe_path(path, "previews/" + identity)
    preview_owner = {"owner": "owl-acquisition-preview", "schema_version": 1,
                     "signature": signature, "manifest_sha256": _digest(manifest), "preview_id": identity,
                     "phase_budget": allowances, "storage_peak_bytes": phase_peak, "reserve_bytes": reserve}
    with guard_directory(path), file_lock(path / "capture.lock"):
        _space(path, phase_peak, reserve)
        marker = preview_dir / "owner.json"
        if preview_dir.exists() and not marker.exists():
            raise SafetyError("Unowned preview directory")
        _bounded_immutable(path, marker, preview_owner, peak=phase_peak, reserve=reserve)
        receipt_path = preview_dir / "preview-receipt.json"
        if receipt_path.exists():
            record = _preview_receipt(path, receipt_path)
            if (record.get("signature") != signature
                    or record.get("candidate_sha256") != _digest(_read(preview_dir / "candidate-fragment.json"))):
                raise SafetyError("Preview receipt or candidate differs from frozen inputs")
            return {"operation": "preview", "status": "awaiting_review", "content_ready": False,
                    "reused": True, "receipt": str(receipt_path), "candidate_fragment": str(preview_dir / "candidate-fragment.json")}
        expanded = []
        extraction_specs = deepcopy(recipe.get("build_input_extractions", []))
        if not isinstance(extraction_specs, list):
            raise SafetyError("Preview archive declarations must be a list")
        if any(not isinstance(s, dict) or type(s.get("max_bytes")) is not int or s["max_bytes"] <= 0
               for s in extraction_specs):
            raise SafetyError("Archive declarations require positive finite expansion bounds")
        other_expanded = sum(_usage(p) for p in (path / "previews").glob("*/expanded") if p != preview_dir / "expanded")
        if other_expanded + (0 if shared_record else sum(s["max_bytes"] for s in extraction_specs)) > allowances["expanded_bytes"]:
            raise SafetyError("Archive declarations exceed the expanded_bytes allowance")
        member_ids, archive_ids = set(), set()
        for specification in extraction_specs:
            from . import sevenzip
            archive_id = specification.get("source_id")
            if specification.get("format") != "7z" or archive_id not in sources:
                raise SafetyError("Preview archive must be an explicitly captured 7z source")
            if archive_id in archive_ids:
                raise SafetyError("Duplicate preview archive declaration")
            archive_ids.add(archive_id)
            members = specification.get("members", [])
            if (not isinstance(members, list) or not members
                    or any(m.get("id") not in source_ids for m in members)):
                raise SafetyError("Expanded preview members must have declared virtual source IDs")
            for member in members:
                if member["id"] in member_ids or member["id"] in sources:
                    raise SafetyError("Duplicate or colliding virtual source identity")
                member_ids.add(member["id"])
            output_dir = safe_path(preview_dir, "expanded/" + archive_id)
            def before_expanded_write(amount):
                if shutil.disk_usage(path).free < amount + reserve:
                    raise SafetyError("Insufficient free space before expanded source write")
            _space(path, phase_peak, reserve)
            if shared_record:
                shared_specs={s['source_id']:s for s in shared_record['build_input_extractions']}
                if specification != shared_specs.get(archive_id):
                    raise SafetyError('Preview shared expansion must match the complete pinned archive allowlist')
                shared_rows=[row for row in shared_record['expanded_sources'] if row['source_id']==archive_id]
                observed={'members':[{key:row[key] for key in ('path','size_bytes','sha256')} for row in shared_rows],
                          'paths':{row['path']:safe_path(path,row['relative_path']) for row in shared_rows}}
            else:
                observed = sevenzip.observe_members(sources[archive_id], assets[archive_id],
                    [{k: v for k, v in m.items() if k != "id"} for m in members], output_dir,
                    max_bytes=specification["max_bytes"], max_files=specification["max_files"],
                    timeout=specification.get('timeout_seconds',3600), before_write=before_expanded_write)
            by_member = {row["path"]: row for row in observed["members"]}
            for member in members:
                row, member_id = by_member[member["path"]], member["id"]
                if member.get("sha256") and member["sha256"] != row["sha256"]:
                    raise SafetyError("Expanded source differs from its reviewed member pin")
                member["sha256"] = row["sha256"]
                member_path = Path(observed["paths"][member["path"]])
                sources[member_id] = member_path
                assets[member_id] = {**assets.get(member_id, {}), "id": member_id,
                    "source_url": assets[archive_id]["source_url"], "version": assets[archive_id]["version"],
                    "size_bytes": row["size_bytes"], "sha256": row["sha256"],
                    "destination": "build-inputs/" + member_id}
                expanded.append({"id": member_id, **row, "relative_path": member_path.relative_to(path).as_posix(), "source_id": archive_id})
        if any(i not in sources for i in source_ids):
            raise SafetyError("Preview source is not captured or declared as a bounded archive member")
        selected_archives = {s["source_id"] for s in extraction_specs}
        participating = set(source_ids) & source_records.keys() | selected_archives
        if any(recipe["resource_id"] not in source_records[i]["resource_ids"] for i in participating):
            raise SafetyError("Captured source is not assigned to this recipe resource")
        # Keep production destinations while rendering so measured hashes are
        # reproducible by a normal build. Only referenced local companions are
        # streamed into this preview tree; build-only corpora stay in sources/.
        originals = {i: deepcopy(assets[i]) for i in output_ids}
        targets = {}
        collisions = set()
        for i in output_ids:
            destination = originals[i].get("destination")
            target = safe_path(preview_dir / "files", destination)
            relative = target.relative_to(path).as_posix()
            _reserve_destination(collisions, relative)
            targets[i] = target
        work = preview_dir / "work"
        expected = {}
        for i in output_ids:
            if recipe["adapter"] in {"html_snapshot", "manual_html"}:
                candidate = safe_path(work, i + ".html")
            elif recipe["adapter"] == "mdoc":
                candidate = safe_path(work, i + "." + assets[i]["format"])
            else:
                candidate = safe_path(work, assets[i]["destination"])
            expected[candidate] = targets[i]
        other_work = sum(_usage(p) for p in (path / "previews").glob("*/work") if p != work)
        if other_work + workspace > allowances["scratch_bytes"]:
            raise SafetyError("Combined preview scratch work exceeds its allowance")
        def write_output(candidate, data):
            target = expected.get(Path(candidate))
            if target is None or not isinstance(data, bytes):
                raise SafetyError("Adapter attempted an undeclared preview output")
            reject_symlinks(target)
            existing = target.stat().st_size if target.exists() else 0
            if existing:
                if existing == len(data) and sha256_file(target) == hashlib.sha256(data).hexdigest():
                    return
                raise SafetyError("Interrupted preview output differs from deterministic rerender")
            retained = sum(_usage(p) for p in (path / "previews").glob("*/files"))
            if retained + len(data) > allowance:
                raise SafetyError("Generated preview exceeds preview_bytes before writing")
            _space(path, phase_peak, reserve)
            if shutil.disk_usage(path).free < len(data) + reserve:
                raise SafetyError("Insufficient free space before preview output write")
            atomic_write(target, data)
        companions = set(recipe.get("selection", {}).get("dependencies", {}).values()) & set(source_ids)
        if recipe["adapter"] == "mdoc":
            # Every rendered manual links its original release archive. Keep
            # the source/notice companion at the same path as a normal build.
            companions.add(recipe["selection"]["source_asset_id"])
        if recipe["adapter"] == "lessons":
            for lesson in recipe.get("selection", {}).get("lessons", []):
                for media in lesson.get("media", []):
                    companions.add(media["asset_id"])
                    companions.update(c["asset_id"] for c in media.get("captions", []))
        if recipe["adapter"] == "ocw_package":
            companions.update(media["asset_id"] for media in recipe["selection"].get("media", []))
        companion_records, companion_targets = [], {}
        for source_id in sorted(companions):
            target = safe_path(preview_dir / "files", assets[source_id].get("destination"))
            _reserve_destination(collisions, target.relative_to(path).as_posix())
            _reserve_destination(collisions, target.with_name(target.name + ".part").relative_to(path).as_posix())
            companion_targets[source_id] = target
        for source_id, target in companion_targets.items():
            source_asset = assets[source_id]
            retained = sum(_usage(p) for p in (path / "previews").glob("*/files"))
            if not verified(target, source_asset["size_bytes"], source_asset["sha256"]):
                if target.exists():
                    raise SafetyError("Preview companion changed")
                partial = target.with_name(target.name + ".part")
                partial_bytes = partial.stat().st_size if partial.exists() else 0
                if retained - partial_bytes + source_asset["size_bytes"] > allowance:
                    raise SafetyError("Preview companions exceed preview_bytes before copying")
                _space(path, phase_peak, reserve)
                if shutil.disk_usage(path).free < source_asset["size_bytes"] + reserve:
                    raise SafetyError("Insufficient free space before preview companion copy")
                from ..transfer import resume_copy
                resume_copy(sources[source_id], target, size=source_asset["size_bytes"],
                            checksum=source_asset["sha256"], progress=progress)
            companion_records.append({"id": source_id, "relative_path": target.relative_to(path).as_posix(),
                                      "size_bytes": source_asset["size_bytes"], "sha256": source_asset["sha256"]})
        rendered = adapters[recipe["adapter"]].render(recipe, {i: sources[i] for i in source_ids}, assets, work,
                                                     output_writer=write_output)
        if set(rendered) != set(output_ids):
            raise SafetyError("Adapter did not produce exactly the frozen output set")
        output_records = []
        for i in output_ids:
            target = targets[i]
            size, sha = target.stat().st_size, sha256_file(target)
            pinned = originals[i]
            if (pinned.get("sha256") is not None and pinned["sha256"] != sha
                    or pinned.get("size_bytes") is not None and pinned["size_bytes"] != size):
                raise SafetyError("Preview output differs from its expected pin")
            output_records.append({"id": i, "size_bytes": size, "sha256": sha,
                                   "relative_path": target.relative_to(path).as_posix()})
        load_capture_sources(path)  # Reject sources changed during rendering.
        record = {"schema_version": 1, "status": "preview_awaiting_review", "content_ready": False,
                  "preview_id": identity, "signature": signature, "manifest_sha256": _digest(manifest),
                  "resource_id": recipe["resource_id"], "outputs": output_records, "companions": companion_records, "expanded_sources": expanded,
                  "source_receipts": {r["source_id"]: _digest(r) for r in receipts}}
        if shared_record:
            record['shared_expansion']={'relative_path':Path(shared_expansion).absolute().relative_to(path).as_posix(),
                                        'sha256':_digest(shared_record)}
        candidate = {"schema_version": 1, "assets": [], "resource_updates": [],
                     "acquisition_capture": {"capture_id": owner["capture_id"], "manifest_sha256": _digest(manifest)}}
        for row in output_records:
            candidate["assets"].append({**originals[row["id"]], "size_bytes": row["size_bytes"], "sha256": row["sha256"],
                "acquisition_provenance": {"manifest_sha256": _digest(manifest), "preview_id": identity}})
        pending_recipe = deepcopy(recipe)
        pending_recipe["status"] = "pending"
        pending_recipe["review"] = {"status": "pending", "evidence": ["Captured preview requires content review"]}
        if extraction_specs:
            pending_recipe["build_input_extractions"] = extraction_specs
        for input_asset in pending_recipe.get("build_inputs", []):
            if input_asset["id"] in receipt_by_id:
                receipt = receipt_by_id[input_asset["id"]]
                input_asset.update(size_bytes=receipt["size_bytes"], sha256=receipt["sha256"])
        candidate["recipes"] = [pending_recipe]
        record["recipe_sha256"] = _recipe_digest(pending_recipe)
        record["candidate_sha256"] = _digest(candidate)
        _bounded_immutable(path, preview_dir / "candidate-fragment.json", candidate, peak=phase_peak, reserve=reserve)
        _bounded_immutable(path, receipt_path, record, peak=phase_peak, reserve=reserve)
        _space(path, phase_peak, reserve)
        progress("PREVIEW awaiting review " + identity)
        return {"operation": "preview", "status": "awaiting_review", "content_ready": False,
                "receipt": str(receipt_path), "candidate_fragment": str(preview_dir / "candidate-fragment.json"),
                "outputs": output_records, "expanded_sources": expanded, "staging_root": str(path)}


def _recipes(fragment):
    values = fragment.get("acquisition_recipes", fragment.get("recipes", []))
    if not isinstance(values, list) or any(not isinstance(r, dict) for r in values):
        raise SafetyError("Reviewed fragment recipes must be records")
    return values


def _updates(fragment):
    values = fragment.get("resource_updates", fragment.get("proposed_resource_updates", []))
    if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
        raise SafetyError("Reviewed fragment resource updates must be records")
    return values


def _recipe_digest(recipe):
    # Review/admission status may advance after rendering; transformation,
    # selection and source/member pins must remain exactly as previewed.
    return _digest({key: value for key, value in recipe.items() if key not in {"status", "review", "blockers"}})


def _fragment_artifacts(fragment):
    assets = fragment.get("assets", [])
    if not isinstance(assets, list) or any(not isinstance(a, dict) for a in assets):
        raise SafetyError("Reviewed fragment assets must be records")
    values = list(assets)
    for recipe in _recipes(fragment):
        values.extend(recipe.get("build_inputs", []))
    by_id = {}
    for asset in values:
        if asset.get("id") in by_id and by_id[asset["id"]] != asset:
            raise SafetyError("Reviewed fragment has conflicting artifact identities")
        by_id[asset.get("id")] = asset
    return by_id


def review(staging, fragment_path, *, evidence, reviewer="acquisition reviewer", output=None,
           resource_ids=(), profile=None):
    """Bind explicit review evidence to concrete pins; never clear catalog gates."""
    path, _ = _staging(staging)
    with guard_directory(path), file_lock(path / "capture.lock"):
        manifest, receipts = load_capture_sources(path)
        requested = _scope(manifest, resource_ids=resource_ids, profile=profile)
        owner = _owner(path, _digest(manifest))
        fragment = _document(fragment_path)
        binding = {"capture_id": owner["capture_id"], "manifest_sha256": _digest(manifest)}
        if fragment.get("acquisition_capture") != binding:
            raise SafetyError("Reviewed fragment is not bound to this capture")
        if (not isinstance(evidence, (list, tuple)) or not evidence or len(evidence) > 100
                or any(not isinstance(e, str) or not e.strip() or len(e) > 4096 for e in evidence)
                or not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200):
            raise SafetyError("Review requires bounded explicit evidence and reviewer identity")
        sources = {s["id"]: s for s in manifest["sources"]}
        source_receipts = {r["source_id"]: r for r in receipts}
        artifacts = {}
        for receipt in receipts:
            artifacts[receipt["source_id"]] = {"size_bytes": receipt["size_bytes"], "sha256": receipt["sha256"],
                "resource_ids": sources[receipt["source_id"]]["resource_ids"], "source_id": receipt["source_id"],
                "receipt_sha256": _digest(receipt)}
        preview_records = {}
        preview_ids = {r.get("id") for r in _recipes(fragment)}
        for asset in fragment.get("assets", []):
            provenance = asset.get("acquisition_provenance", {})
            if provenance.get("preview_id"):
                preview_ids.add(provenance["preview_id"])
        if any(not isinstance(i, str) or not IDENTIFIER.fullmatch(i) for i in preview_ids):
            raise SafetyError("Reviewed preview identities must be explicit portable IDs")
        for preview_id in sorted(preview_ids):
            receipt_path = safe_path(path, "previews/" + preview_id + "/preview-receipt.json")
            receipt = _preview_receipt(path, receipt_path)
            if receipt.get("preview_id") != preview_id:
                raise SafetyError("Preview receipt identity differs from its owned directory")
            if (receipt.get("manifest_sha256") != _digest(manifest)
                    or receipt.get("source_receipts") != {r["source_id"]: _digest(r) for r in receipts}):
                raise SafetyError("Preview evidence belongs to a different capture or changed source receipts")
            preview_records[receipt["preview_id"]] = receipt
            shared_rows = {}
            if receipt.get('shared_expansion'):
                from .stackoverflow_trial import verified_shared
                shared_binding=receipt['shared_expansion']
                shared=verified_shared(path,safe_path(path,shared_binding['relative_path']),manifest,receipts)
                if _digest(shared)!=shared_binding['sha256']:
                    raise SafetyError('Preview shared XML receipt changed')
                shared_rows={row['id']:row for row in shared['expanded_sources']}
            for row in receipt["expanded_sources"]:
                member_path = safe_path(path, row["relative_path"])
                if ((not member_path.is_relative_to(receipt_path.parent / "expanded") and shared_rows.get(row['id'])!=row)
                        or not verified(member_path, row["size_bytes"], row["sha256"])):
                    raise SafetyError("Expanded preview source changed")
            for row in receipt["outputs"]:
                if row["id"] in artifacts:
                    raise SafetyError("Duplicate observed artifact identity")
                artifacts[row["id"]] = {"size_bytes": row["size_bytes"], "sha256": row["sha256"],
                    "resource_ids": [receipt["resource_id"]], "preview_id": receipt["preview_id"],
                    "receipt_sha256": _digest(receipt)}
        supplied = _fragment_artifacts(fragment)
        if not supplied:
            raise SafetyError("Review fragment has no captured artifacts")
        reviewed = {}
        for identity, asset in supplied.items():
            actual = artifacts.get(identity)
            if actual is None or any(asset.get(key) != actual[key] for key in ("size_bytes", "sha256")):
                raise SafetyError("Reviewed fragment pin is not a verified captured artifact: " + str(identity))
            if not set(actual["resource_ids"]) & requested:
                raise SafetyError("Reviewed artifact is outside the requested resource scope")
            provenance = asset.get("acquisition_provenance")
            expected = {"manifest_sha256": _digest(manifest), **{key: actual[key] for key in ("source_id", "preview_id") if key in actual}}
            # Build-only inputs carry the recipe's top-level binding; final
            # catalog assets additionally keep an explicit provenance marker.
            if asset in fragment.get("assets", []) and provenance != expected:
                raise SafetyError("Reviewed asset is missing its capture provenance")
            if identity in sources:
                source = sources[identity]
                if source_receipts[identity].get("response_evidence", {}).get("kind") not in {"http", "local", "local_reuse"}:
                    raise SafetyError("Captured source lacks actual response identity evidence")
                if any(asset.get(key) != source[key] for key in ("source_url", "version")):
                    raise SafetyError("Reviewed source identity differs from captured publisher identity")
            reviewed[identity] = actual
        for recipe in _recipes(fragment):
            if recipe.get("resource_id") not in requested:
                raise SafetyError("Reviewed recipe is outside the requested resource scope")
            input_ids = set(recipe.get("source_asset_ids", [])) | {a["id"] for a in recipe.get("build_inputs", [])}
            for source_id in input_ids & sources.keys():
                if source_receipts[source_id].get("response_evidence", {}).get("kind") not in {"http", "local", "local_reuse"}:
                    raise SafetyError("Generation source lacks actual response identity evidence")
            preview_record = preview_records.get(recipe.get("id"))
            if preview_record is None or preview_record.get("recipe_sha256") != _recipe_digest(recipe):
                raise SafetyError("Reviewed recipe differs from its captured preview transformation")
            if not set(preview_record.get("blockers", [])) <= set(recipe.get("blockers", [])):
                raise SafetyError("Exporter warnings remain required review blockers until a clean preview resolves them")
        reviewed_recipe_ids = {r.get("id") for r in _recipes(fragment)}
        if any(a.get("preview_id") not in reviewed_recipe_ids for a in reviewed.values() if a.get("preview_id")):
            raise SafetyError("Reviewed preview outputs require their exact generation recipe")
        for update in _updates(fragment):
            if update.get("id") not in requested:
                raise SafetyError("Reviewed resource update is outside the requested scope")
        record = {"schema_version": 1, "kind": "acquisition-review", **binding,
                  "fragment_sha256": _digest(fragment), "artifacts": reviewed,
                  "review": {"status": "approved", "evidence": list(evidence), "reviewer": reviewer}}
        destination = Path(output) if output is not None else path / "reviews" / (_digest(fragment) + ".json")
        reject_symlinks(destination)
        peak = _effective_peak(path, manifest)
        reserve = _read(path / "capture-report.json")["reserve_bytes"]
        _space(path, peak, reserve)
        _bounded_immutable(path, destination, record, peak=peak, reserve=reserve)
        return {"operation": "review", "status": "review_recorded", "content_ready": False,
                "receipt": str(destination.absolute()), "fragment_sha256": _digest(fragment), "artifact_count": len(reviewed)}


def validate_review_binding(fragment, receipt_path):
    """Admission gate used by stage; recipe readiness is separately validated."""
    record = _read(Path(receipt_path))
    marker = fragment.get("acquisition_capture")
    if (record.get("schema_version") != 1 or record.get("kind") != "acquisition-review"
            or not isinstance(marker, dict) or not marker.get("capture_id")
            or marker != {"capture_id": record.get("capture_id"), "manifest_sha256": record.get("manifest_sha256")}
            or record.get("fragment_sha256") != _digest(fragment)
            or record.get("review", {}).get("status") != "approved"
            or not record.get("review", {}).get("evidence") or not record.get("review", {}).get("reviewer")):
        raise SafetyError("Review receipt does not approve this exact captured fragment")
    supplied = _fragment_artifacts(fragment)
    if set(supplied) != set(record.get("artifacts", {})):
        raise SafetyError("Review receipt artifact membership changed")
    for identity, asset in supplied.items():
        observed = record["artifacts"][identity]
        if any(asset.get(key) != observed.get(key) for key in ("size_bytes", "sha256")):
            raise SafetyError("Review receipt artifact pins changed")
        if asset in fragment.get("assets", []):
            expected = {"manifest_sha256": record["manifest_sha256"],
                        **{key: observed[key] for key in ("source_id", "preview_id") if key in observed}}
            if asset.get("acquisition_provenance") != expected:
                raise SafetyError("Review receipt artifact provenance changed")
    return record


def _preview_zim(path, manifest, receipts, recipe, assets_path, *, preview_bytes=None, expanded_bytes=None,
                 scratch_bytes=None, reserve_bytes=None, budget_bytes=None, progress=print):
    """Discover bounded direct outputs using the production static ZIM exporter."""
    from ..export_direct import export_zim
    identity, selection = recipe["id"], recipe.get("selection", {})
    source_id = selection.get("source_asset_id")
    records = {s["id"]: s for s in manifest["sources"]}
    observed = {r["source_id"]: r for r in receipts}
    if (source_id not in records or recipe.get("source_asset_ids") != [source_id]
            or recipe["resource_id"] not in records[source_id]["resource_ids"]):
        raise SafetyError("ZIM preview requires exactly one captured source assigned to the recipe resource")
    entries = selection.get("entries")
    if (not isinstance(entries, list) or not entries or any(not isinstance(e, str) or not e for e in entries)
            or len(set(entries)) != len(entries)):
        raise SafetyError("ZIM preview requires a nonempty frozen unique entry selection")
    limits = {key: selection.get(key, 16 * 1024 * 1024 if key == "max_item_bytes" else None)
              for key in ("max_bytes", "max_files", "max_item_bytes")}
    if (any(type(value) is not int or value <= 0 for value in limits.values())
            or limits["max_files"] > 100000 or limits["max_item_bytes"] > 64 * 1024 * 1024
            or len(entries) > limits["max_files"]):
        raise SafetyError("ZIM preview requires bounded max_bytes/max_files/max_item_bytes declarations")
    templates = _document(assets_path).get("assets", [])
    if not isinstance(templates, list) or any(not isinstance(a, dict) or not isinstance(a.get("id"), str) for a in templates):
        raise SafetyError("ZIM preview assets must be uniquely identified templates")
    by_id = {a["id"]: a for a in templates}
    if len(by_id) != len(templates):
        raise SafetyError("Duplicate ZIM preview asset template")
    source, receipt = records[source_id], observed[source_id]
    source_asset = {**source.get("fullasset_metadata", {}), **by_id.get(source_id, {}), "id": source_id,
                    "source_url": source["source_url"], "version": source["version"],
                    "size_bytes": receipt["size_bytes"], "sha256": receipt["sha256"]}
    if source_asset.get("format") != "zim" or any(key not in source_asset for key in ("title", "category", "license", "redistributable")):
        raise SafetyError("ZIM preview needs the captured publisher's title, category, format, license and redistribution metadata")
    allowances = dict(manifest["budget"])
    for key, value in (("preview_bytes", preview_bytes), ("expanded_bytes", expanded_bytes), ("scratch_bytes", scratch_bytes)):
        if value is not None:
            if type(value) is not int or value < allowances[key]:
                raise SafetyError("ZIM preview phase allowances must cover frozen acquisition declarations")
            allowances[key] = value
    workspace = recipe.get("workspace_bytes", 0)
    if (allowances["preview_bytes"] < limits["max_bytes"] or type(workspace) is not int
            or workspace <= 0 or workspace > allowances["scratch_bytes"]):
        raise SafetyError("ZIM preview must reserve its payload maximum and a positive finite metadata workspace")
    phase_peak = sum(allowances.values()) + manifest["metadata_allowance_bytes"]
    reserve = _read(path / "capture-report.json")["reserve_bytes"] if reserve_bytes is None else reserve_bytes
    if (type(reserve) is not int or reserve < 0
            or budget_bytes is not None and (type(budget_bytes) is not int or budget_bytes < phase_peak)):
        raise SafetyError("ZIM preview reserve/budget does not cover the declared phase peak")
    signature = _digest({"recipe": recipe, "assets": templates, "manifest_sha256": _digest(manifest),
                         "source_receipts": receipts, "phase_budget": allowances, "reserve_bytes": reserve})
    preview_dir = safe_path(path, "previews/" + identity)
    export_dir = preview_dir / "files"  # exporter appends its own LIBRARY root
    export_root = export_dir / "LIBRARY"
    preview_owner = {"owner": "owl-acquisition-preview", "schema_version": 1, "signature": signature,
                     "manifest_sha256": _digest(manifest), "preview_id": identity, "phase_budget": allowances,
                     "storage_peak_bytes": phase_peak, "reserve_bytes": reserve}
    owner = _owner(path, _digest(manifest))
    with guard_directory(path), file_lock(path / "capture.lock"):
        _space(path, phase_peak, reserve)
        marker = preview_dir / "owner.json"
        if preview_dir.exists() and not marker.exists():
            raise SafetyError("Unowned ZIM preview directory")
        _bounded_immutable(path, marker, preview_owner, peak=phase_peak, reserve=reserve)
        receipt_path = preview_dir / "preview-receipt.json"
        candidate_path = preview_dir / "candidate-fragment.json"
        if receipt_path.exists():
            record = _preview_receipt(path, receipt_path)
            if record.get("signature") != signature or record.get("candidate_sha256") != _digest(_read(candidate_path)):
                raise SafetyError("ZIM preview evidence changed")
            return {"operation": "preview", "status": "awaiting_review", "content_ready": False, "reused": True,
                    "receipt": str(receipt_path), "candidate_fragment": str(candidate_path), "blockers": record["blockers"]}
        other_work = sum(_usage(p) for p in (path / "previews").glob("*/work"))
        other_control = sum(_usage(p) for p in (path / "previews").glob("*/files/LIBRARY/.owl") if p != export_root / ".owl")
        if other_work + other_control + workspace > allowances["scratch_bytes"]:
            raise SafetyError("Combined ZIM preview workspaces exceed scratch_bytes")
        other_files = sum(_usage(p) for p in (path / "previews").glob("*/files") if p != export_dir)
        if other_files + limits["max_bytes"] > allowances["preview_bytes"]:
            raise SafetyError("Combined preview payload allowances exceed preview_bytes")
        before_write = _ZimWriteLedger(path, export_root, identity, peak=phase_peak,
                                      workspace=workspace, reserve=reserve)
        exported = export_zim(safe_path(path, receipt["relative_path"]), export_dir, source_asset=source_asset,
                              entries=entries, export_id=identity, progress=progress, _before_write=before_write, **limits)
        before_write.settle()
        expected_paths = selection.get("output_paths", {})
        if not isinstance(expected_paths, dict) or len(set(expected_paths.values())) != len(expected_paths):
            raise SafetyError("ZIM preview output paths must be unique")
        if recipe.get("output_asset_ids") and set(recipe["output_asset_ids"]) != set(expected_paths):
            raise SafetyError("ZIM preview declared outputs lack a complete path mapping")
        if expected_paths and set(expected_paths.values()) != {a["destination"] for a in exported["assets"]}:
            raise SafetyError("ZIM discovered dependencies differ from the frozen output selection")
        ids_by_path = {destination: aid for aid, destination in expected_paths.items()}
        candidate_assets, outputs, output_paths = [], [], {}
        for asset in exported["assets"]:
            aid = ids_by_path.get(asset["destination"], asset["id"])
            expected = by_id.get(aid, {})
            if any(expected.get(key) is not None and expected[key] != asset[key] for key in ("sha256", "size_bytes")):
                raise SafetyError("ZIM preview output differs from expected reviewed pins")
            target = safe_path(export_root, asset["destination"])
            outputs.append({"id": aid, "relative_path": target.relative_to(path).as_posix(),
                            "size_bytes": asset["size_bytes"], "sha256": asset["sha256"]})
            output_paths[aid] = asset["destination"]
            candidate_assets.append({**asset, "id": aid, "source_url": source["source_url"],
                "generation": {"recipe_id": identity},
                "acquisition_provenance": {"manifest_sha256": _digest(manifest), "preview_id": identity}})
        pending = deepcopy(recipe)
        pending["status"] = "pending"
        pending["source_asset_ids"] = [source_id]
        pending["output_asset_ids"] = sorted(output_paths)
        pending["selection"].update(source_asset_id=source_id, entries=exported["selected_entries"],
                                    output_paths=output_paths, max_item_bytes=limits["max_item_bytes"])
        warnings = list(exported.get("warnings", []))
        pending["blockers"] = list(dict.fromkeys([*recipe.get("blockers", []), *warnings]))
        pending["review"] = {"status": "pending", "evidence": ["Bounded static export requires text, illustration, dependency and notice review"]}
        for source_input in pending.get("build_inputs", []):
            if source_input["id"] == source_id:
                source_input.update(size_bytes=receipt["size_bytes"], sha256=receipt["sha256"])
        candidate = {"schema_version": 1, "assets": candidate_assets, "recipes": [pending], "resource_updates": [],
                     "acquisition_capture": {"capture_id": owner["capture_id"], "manifest_sha256": _digest(manifest)}}
        record = {"schema_version": 1, "status": "preview_awaiting_review", "content_ready": False,
                  "preview_id": identity, "signature": signature, "manifest_sha256": _digest(manifest),
                  "resource_id": recipe["resource_id"], "outputs": outputs, "expanded_sources": [], "companions": [],
                  "source_receipts": {r["source_id"]: _digest(r) for r in receipts}, "blockers": warnings,
                  "recipe_sha256": _recipe_digest(pending), "candidate_sha256": _digest(candidate)}
        load_capture_sources(path)
        _bounded_immutable(path, candidate_path, candidate, peak=phase_peak, reserve=reserve)
        _bounded_immutable(path, receipt_path, record, peak=phase_peak, reserve=reserve)
        _space(path, phase_peak, reserve)
        return {"operation": "preview", "status": "awaiting_review", "content_ready": False,
                "receipt": str(receipt_path), "candidate_fragment": str(candidate_path), "outputs": outputs,
                "blockers": warnings, "staging_root": str(path), "storage_peak_bytes": phase_peak}
