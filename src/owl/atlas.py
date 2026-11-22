"""Validate topic coverage and supply subject labels to the drive reader."""
from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path

from .catalog import learning_shelves
from .safety import SafetyError, safe_path, validate_relative

PURPOSES = ("start-here", "practical", "explanation", "reference")
ENTRANCES = ("subjects", "tasks", "learn")


def _reader(asset):
    return bool(asset.get("reader_required")) or asset.get("format") in {"zim", "epub"}


def _locator(section):
    if section is None:
        return None, "Complete document"
    locator = section["locator"]
    kind = locator["type"]
    if kind == "pdf-page":
        label = f'Physical PDF page {locator["page"]}'
        if locator.get("end_page") is not None:
            label += f'–{locator["end_page"]}'
        if locator.get("printed_label"):
            label += f'; printed label: {locator["printed_label"]}'
        return "page=" + str(locator["page"]), label
    if kind == "html-anchor":
        return locator["id"], "HTML heading / element ID: " + locator["id"]
    if kind == "text-lines":
        label = f'Line {locator["start"]}'
        if locator.get("end") is not None:
            label += f'–{locator["end"]}'
        return None, label + " (locate in the complete file)"
    if kind in {"epub-entry", "zim-entry"}:
        return None, ("EPUB chapter: " if kind == "epub-entry" else "Archive article: ") + locator["path"]
    if kind == "image":
        return None, "Complete image"
    if kind == "media-time":
        label = f'Time {locator["seconds"]} seconds'
        if locator.get("end_seconds") is not None:
            label += f'–{locator["end_seconds"]} seconds'
        return None, label + " (navigate in your media player)"
    raise SafetyError(f"Unknown validated atlas locator type: {kind}")


def _location_key(asset_id, section):
    if section is None:
        return asset_id, "whole-document"
    locator = dict(section["locator"])
    locator.pop("printed_label", None)
    return asset_id, json.dumps(locator, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _graph(topics):
    children = {identity: [] for identity in topics}
    degree = {}
    for identity, topic in topics.items():
        degree[identity] = len(topic["parents"])
        for parent in topic["parents"]:
            if parent not in topics:
                raise SafetyError(f"Unknown atlas parent: {parent}")
            children[parent].append(identity)
    ready = deque(sorted(identity for identity, count in degree.items() if not count))
    ordered = []
    while ready:
        identity = ready.popleft()
        ordered.append(identity)
        for child in sorted(children[identity]):
            degree[child] -= 1
            if not degree[child]:
                ready.append(child)
    if len(ordered) != len(topics):
        raise SafetyError("Atlas topic hierarchy contains a cycle")
    return children, ordered


def reader_topics(navigation):
    """Index assigned subjects and their parents for category chips and topic views."""
    topics = navigation["topics"]
    by_asset = defaultdict(set)
    for assignment in navigation["assignments"]:
        pending = [assignment["topic_id"]]
        seen = by_asset[assignment["asset_id"]]
        while pending:
            identity = pending.pop()
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(topics[identity]["parents"])
    return {asset: [[identity, topics[identity]["title"]] for identity in sorted(ids)]
            for asset, ids in sorted(by_asset.items())}


def prepare_atlas(target: Path, assets: list[dict], navigation: dict) -> tuple[dict[str, str], dict]:
    """Report coverage of the reviewed topics and source sections."""
    selected = {asset["id"]: asset for asset in assets}
    if len(selected) != len(assets):
        raise SafetyError("Duplicate selected atlas asset ID")
    for asset in assets:
        safe_path(target, asset["destination"])
        validate_relative(f"INDEX/books/{asset['id']}.html")
    topics = navigation["topics"]
    for identity in topics:
        validate_relative(f"INDEX/topics/{identity}.html")
    children, ordered = _graph(topics)
    maps = {identity: mapping for identity, mapping in navigation.get("sections", {}).items() if identity in selected}
    sections = {}
    for identity, mapping in maps.items():
        if mapping["source_sha256"] != selected[identity]["sha256"]:
            raise SafetyError(f"Stale reviewed atlas source map: {identity}")
        sections[identity] = {section["id"]: section for section in mapping["sections"]}
    local = defaultdict(dict)
    assignments = sorted(navigation["assignments"], key=lambda row: (
        PURPOSES.index(row["purpose"]), row.get("order") is None, row.get("order") or 0,
        row["asset_id"], row.get("section_id") or ""))
    for assignment in assignments:
        identity = assignment["asset_id"]
        if identity not in selected:
            continue
        topic_id = assignment["topic_id"]
        if topic_id not in topics:
            raise SafetyError(f"Unknown assigned topic: {topic_id}")
        section = None
        if assignment.get("section_id"):
            section = sections.get(identity, {}).get(assignment["section_id"])
            if section is None:
                raise SafetyError(f"Missing validated section: {identity}/{assignment['section_id']}")
        key = _location_key(identity, section)
        local[topic_id].setdefault(key, {**assignment, "asset": selected[identity], "section": section, "key": key})
    reachable = {identity: set(local[identity]) for identity in topics}
    for identity in reversed(ordered):
        for parent in topics[identity]["parents"]:
            reachable[parent].update(reachable[identity])
    visible = {identity for identity in topics if reachable[identity]}
    counts = {}
    for identity in visible:
        asset_ids = {key[0] for key in reachable[identity]}
        direct = {key for key in asset_ids if not _reader(selected[key])}
        counts[identity] = {"asset_count": len(asset_ids), "location_count": len(reachable[identity]),
                            "direct_asset_count": len(direct), "reader_asset_count": len(asset_ids - direct),
                            "reader_only": not direct}

    group_reach = {}
    for group in ENTRANCES:
        found = set(navigation["entrances"].get(group, []))
        pending = list(found)
        while pending:
            identity = pending.pop()
            for child in children.get(identity, []):
                if child not in found:
                    found.add(child)
                    pending.append(child)
        group_reach[group] = found
    asset_topics = defaultdict(set)
    for identity in visible:
        for asset_id, _location in local[identity]:
            asset_topics[asset_id].add(identity)
    mapped = set(asset_topics)
    textbooks = {identity for identity, asset in selected.items() if asset.get("required") and "textbooks" in learning_shelves(asset)}
    routes = {identity: {"subjects": bool(asset_topics[identity] & group_reach["subjects"]),
                         "learn": bool(asset_topics[identity] & group_reach["learn"]),
                         "topic_ids": sorted(asset_topics[identity])} for identity in sorted(textbooks)}
    report = {"schema_version": 1, "included_topic_ids": sorted(visible), "omitted_topic_ids": sorted(set(topics) - visible),
              "selected_asset_count": len(selected), "mapped_asset_ids": sorted(mapped),
              "unmapped_assets": sorted(set(selected) - mapped),
              "unmapped_critical": sorted(identity for identity, asset in selected.items() if asset.get("critical") and identity not in mapped),
              "unmapped_required_textbooks": sorted(textbooks - mapped), "textbook_route_coverage": routes,
              "missing_textbook_subject_routes": sorted(identity for identity in textbooks if not routes[identity]["subjects"]),
              "missing_textbook_learning_routes": sorted(identity for identity in textbooks if not routes[identity]["learn"]),
              "topics": {identity: counts[identity] for identity in sorted(counts)},
              "included_section_count": sum(len(mapping) for mapping in sections.values()),
              "source_maps": {identity: {"source_sha256": maps[identity]["source_sha256"],
                  "section_count": len(sections[identity]),
                  "provenance": sorted({section["provenance"] for section in sections[identity].values()})} for identity in sorted(maps)},
              "unresolved_location_proposals": navigation.get("unresolved_location_proposals", []),
              "input_hashes": dict(sorted(navigation.get("input_hashes", {}).items())),
              "reader_topics": {identity: labels for identity, labels in reader_topics(navigation).items()
                                if identity in selected}, "generated_file_count": 0, "html_bytes": 0,
              "coverage_note": "Available sources and reviewed assignments are distinct; missing topic mappings are editorial gaps, not absent files."}
    return {}, report
