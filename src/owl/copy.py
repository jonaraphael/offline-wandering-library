"""Deploy an already built library without downloads, extraction, or unrelated-file deletion."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys

from .build import _json, _owned_directory, _root, _state, check_space
from .catalog import fingerprint
from .runtime import file_lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, safe_path, sha256_file, validate_relative
from .transfer import resume_copy


def _check_names(names) -> None:
    """Reject file/directory prefix conflicts and case aliases on every platform."""
    prefixes = {}
    for relative in names:
        validate_relative(relative)
        parts = relative.split("/")
        if parts[0].casefold() == ".owl":
            raise SafetyError("The checksum manifest must not include private .owl files")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            kind = "file" if index == len(parts) else "directory"
            previous = prefixes.get(prefix.casefold())
            if previous and (previous != (prefix, kind) or kind == "file"):
                raise SafetyError(f"Conflicting or duplicate checksum path: {relative}")
            prefixes[prefix.casefold()] = (prefix, kind)


def _existing_names(root: Path, names) -> None:
    """Do not alias a differently cased existing file/directory on an exFAT target."""
    directories = {}
    for relative in names:
        parent = root
        for component in relative.split("/"):
            if parent.exists():
                if not parent.is_dir():
                    raise SafetyError(f"Destination parent is not a directory: {parent}")
                if parent not in directories:
                    directories[parent] = {}
                    for child in parent.iterdir():
                        directories[parent].setdefault(child.name.casefold(), []).append(child.name)
                matches = directories[parent].get(component.casefold(), [])
                if any(name != component for name in matches):
                    raise SafetyError(f"Destination has a case-conflicting path: {parent / component}")
            parent = parent / component


@contextmanager
def _source_lock(source: Path):
    private = safe_path(source, ".owl")
    if not private.exists():
        # A checksum-verified library copied without its private build state is valid.
        yield
        return
    marker = safe_path(source, ".owl/owner.json")
    if (not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) !=
            {"owner": "offline-wandering-library", "schema_version": 1}):
        raise SafetyError("Source .owl directory is not owned by OWL")
    with file_lock(safe_path(source, ".owl/build.lock")):
        if _state(safe_path(source, ".owl/state.json")).get("complete") is not True:
            raise SafetyError("Source library build is incomplete")
        yield


def _source_manifest(source: Path) -> tuple[dict, dict, list[str]]:
    manifest = safe_path(source, "SHA256SUMS.txt")
    data = manifest.read_bytes()
    entries = {}
    names = []
    for line in data.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise SafetyError("Malformed source SHA256SUMS.txt")
        checksum, relative = match.groups()
        if relative.casefold() == "sha256sums.txt":
            raise SafetyError("Checksum manifest cannot include itself")
        names.append(relative)
        entries[relative] = {"sha256": checksum}
    if not entries:
        raise SafetyError("Source checksum manifest is empty")
    _check_names([*names, "SHA256SUMS.txt"])
    for relative, entry in entries.items():
        path = safe_path(source, relative)
        if not path.is_file():
            raise SafetyError(f"Source file missing or not regular: {relative}")
        entry["size_bytes"] = path.stat().st_size
    for required in ("BUILD_INFO.json", "INVENTORY.json"):
        if required not in entries:
            raise SafetyError(f"Source checksum manifest does not cover {required}")

    def checked_json(relative):
        raw = safe_path(source, relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entries[relative]["sha256"]:
            raise SafetyError(f"Source checksum mismatch: {relative}")
        return json.loads(raw)

    info = checked_json("BUILD_INFO.json")
    if not isinstance(info, dict) or info.get("schema_version") != 1 or info.get("complete") is not True:
        raise SafetyError("Source BUILD_INFO.json does not identify a completed OWL build")
    inventory = checked_json("INVENTORY.json")
    if not isinstance(inventory, dict) or inventory.get("schema_version") != 1 or not isinstance(inventory.get("assets"), list):
        raise SafetyError("Invalid source INVENTORY.json")
    asset_state = {}
    destinations = set()
    for asset in inventory["assets"]:
        if not isinstance(asset, dict):
            raise SafetyError("Invalid source inventory asset")
        identity, relative = asset.get("id"), asset.get("destination")
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9_-]+", identity)
                or identity in asset_state or not isinstance(relative, str) or relative in destinations):
            raise SafetyError("Invalid or duplicate source inventory asset")
        expected = entries.get(relative)
        if (expected is None or asset.get("sha256") != expected["sha256"] or
                type(asset.get("size_bytes")) is not int or asset["size_bytes"] != expected["size_bytes"]):
            raise SafetyError(f"Source inventory disagrees with checksum manifest: {identity}")
        original = {**asset, "sha256": None} if asset.get("verification") == "observed" else asset
        asset_state[identity] = {"sha256": expected["sha256"], "fingerprint": fingerprint(original)}
        destinations.add(relative)
    # The public, checksum-covered report carries dynamic output ownership even
    # when a library was copied without its private .owl directory. Never infer
    # ownership from a filename prefix or copy unchecked source-state claims.
    from .atlas_build import REPORT, _previous, _reported_paths
    atlas_paths = _reported_paths(checked_json(REPORT), entries) if REPORT in entries else []
    source_state_path = safe_path(source, ".owl/state.json")
    if source_state_path.exists():
        previous_atlas = _previous(_state(source_state_path))
        copied_previous = set(previous_atlas) & set(entries)
        if copied_previous - set(atlas_paths):
            raise SafetyError("Source atlas ownership is missing from its checksum-covered output report")
    # The manifest itself is pinned to the exact bytes read under the source lock.
    entries["SHA256SUMS.txt"] = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    return entries, asset_state, atlas_paths


def copy_drive(source: Path, target: Path, *, progress=print) -> dict:
    """Copy checksum-listed files, preserving unrelated files and resumable owned parts.

    Each reused file is hashed in both libraries. New transfers verify their
    source prefix and completed destination bytes before atomic promotion. This
    avoids a redundant final pass over the entire destination dataset.
    """
    source, target = _root(source), _root(target)
    source_parts = tuple(part.casefold() for part in source.parts)
    target_parts = tuple(part.casefold() for part in target.parts)
    if (source_parts[:len(target_parts)] == target_parts or
            target_parts[:len(source_parts)] == source_parts or
            (source.exists() and target.exists() and source.samefile(target))):
        raise SafetyError("Source and target libraries must be separate, non-overlapping directories")
    if not source.is_dir():
        raise SafetyError(f"Source library is not a directory: {source}")
    if target.exists() and not target.is_dir():
        raise SafetyError(f"Target is not a directory: {target}")
    with guard_directory(source), _source_lock(source), ExitStack() as guards:
        entries, asset_state, atlas_paths = _source_manifest(source)
        # SHA256SUMS is deliberately promoted after every file it describes.
        names = [*sorted(name for name in entries if name != "SHA256SUMS.txt"), "SHA256SUMS.txt"]
        _existing_names(target, [*names, ".owl/owner.json", ".owl/state.json", ".owl/build.lock", ".owl/copies"])
        for relative in names:
            path = safe_path(target, relative)
            if path.exists() and not path.is_file():
                raise SafetyError(f"Destination is not a regular file: {relative}")
        target.mkdir(parents=True, exist_ok=True)
        guards.enter_context(guard_directory(target))
        _owned_directory(safe_path(target, ".owl"))
        with file_lock(safe_path(target, ".owl/build.lock")):
            state_path = safe_path(target, ".owl/state.json")
            state = _state(state_path)
            from .atlas_build import _previous
            previous_atlas = _previous(state)
            owned = set(state["managed"])
            prior_parts = state.get("copy_parts", {})
            if not isinstance(prior_parts, dict):
                raise SafetyError("Invalid destination copy-part state")
            reusable, parts = {}, {}
            required_bytes = 0
            for relative in names:
                entry = entries[relative]
                destination = safe_path(target, relative)
                reusable[relative] = (destination.is_file() and destination.stat().st_size == entry["size_bytes"]
                                      and sha256_file(destination) == entry["sha256"])
                if destination.exists() and not reusable[relative] and relative not in owned:
                    raise SafetyError(f"Refusing to overwrite unverified, unowned destination: {relative}")
                key = hashlib.sha256((relative + "\0" + entry["sha256"]).encode()).hexdigest()
                part_name = ".owl/copies/" + key + ".part"
                part = safe_path(target, part_name)
                record = {"destination": relative, **entry}
                if part.exists() and (not part.is_file() or prior_parts.get(part_name) != record):
                    raise SafetyError(f"Unowned or conflicting copy partial: {part_name}")
                credit = min(part.stat().st_size, entry["size_bytes"]) if part.exists() else 0
                if not reusable[relative]:
                    required_bytes += entry["size_bytes"] - credit
                parts[relative] = (part_name, record)
            state["complete"] = False
            state["phase"] = "copy"
            state.pop("active_asset", None)
            state.pop("active_path", None)
            state["managed"] = sorted(owned | set(names))
            if previous_atlas or atlas_paths:
                state["atlas_managed"] = sorted(set(previous_atlas) | set(atlas_paths))
            state["copy_parts"] = {**prior_parts, **{name: record for name, record in parts.values()}}
            pending_state = _json(state)
            final_state = _json({**state, "complete": True, "phase": "complete",
                                 "assets": {**state["assets"], **asset_state}})
            # Both persisted and atomic temporary state may coexist. Keep a small
            # floor for filesystem metadata, without assuming every catalog is tiny.
            required_bytes += max(1024 * 1024, len(pending_state) + len(final_state) + 1024)
            progress(f"OWL local copy: {source} -> {target}")
            progress(f"Verified reusable files: {sum(reusable.values())}/{len(names)}; "
                     f"additional free space required: {required_bytes:,} bytes")
            check_space(target, required_bytes)
            atomic_write(state_path, pending_state)
            safe_path(target, ".owl/copies").mkdir(exist_ok=True)
            copied = reused = 0
            for relative in names:
                entry = entries[relative]
                source_file, destination = safe_path(source, relative), safe_path(target, relative)
                state["active_path"] = relative
                atomic_write(state_path, _json(state))
                if reusable[relative]:
                    # Even a reused destination must not conceal a corrupt source library.
                    if source_file.stat().st_size != entry["size_bytes"] or sha256_file(source_file) != entry["sha256"]:
                        raise SafetyError(f"Source checksum mismatch: {relative}")
                    progress(f"REUSE {relative}")
                    reused += 1
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    part_name, _ = parts[relative]
                    digest = resume_copy(source_file, destination, size=entry["size_bytes"],
                                         checksum=entry["sha256"], part=safe_path(target, part_name), progress=progress)
                    if digest != entry["sha256"]:
                        raise SafetyError(f"Destination checksum mismatch: {relative}")
                    copied += 1
            state["assets"].update(asset_state)
            state["complete"] = True
            state["phase"] = "complete"
            state.pop("active_path", None)
            atomic_write(state_path, _json(state))
            progress("COPY COMPLETE: all managed destination files verified")
            return {"copied": copied, "reused": reused, "verified": len(names), "complete": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="completed local OWL library")
    parser.add_argument("target", type=Path, help="separate destination directory, for example on a USB SSD")
    args = parser.parse_args(argv)
    try:
        with interrupt_signals():
            copy_drive(args.source, args.target)
        return 0
    except KeyboardInterrupt:
        print("Copy interrupted; rerun the same command to reuse verified files and resume owned partials.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
