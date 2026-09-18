"""Named content collections and explicit, inspectable build selection.

The registry describes intended collections separately from pinned asset files.
An incomplete collection remains incomplete even when some of its files are
available. Download policy and capacity enforcement belong to the builder.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlsplit

from .catalog import CatalogError, DIRECT, read_yaml


RESOURCE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
STATUSES = {"ready", "partial", "unresolved"}
READERS = "archive-readers"
EDITIONS = {"published", "direct", "compact"}


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CatalogError(f"{name} must be an integer >= {minimum}")
    return value


def _strings(value: object, name: str, *, unique: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise CatalogError(f"{name} must be a list of nonempty strings")
    if unique and len(value) != len(set(value)):
        raise CatalogError(f"{name} contains duplicate entries")
    return value


def _asset_map(assets: list[dict]) -> dict[str, dict]:
    result = {}
    for asset in assets:
        identity = asset.get("id")
        if not isinstance(identity, str) or not identity or identity in result:
            raise CatalogError(f"Invalid or duplicate catalog asset id: {identity!r}")
        result[identity] = asset
    return result


def load_resources(path: Path, assets: list[dict]) -> dict[str, dict]:
    """Validate a YAML resource registry against the pinned asset catalog."""
    document = read_yaml(path)
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int or
            document["schema_version"] != 1 or
            not isinstance(document.get("resources"), list)):
        raise CatalogError("Resource registry requires schema_version: 1 and resources list")
    asset_map = _asset_map(assets)
    result, numbers = {}, set()
    required = {"id", "title", "target_bytes", "status", "asset_ids"}
    for raw in document["resources"]:
        if not isinstance(raw, dict) or required - raw.keys():
            raise CatalogError("Every resource requires id, title, target_bytes, status, and asset_ids")
        row = dict(raw)
        identity = row["id"]
        if not isinstance(identity, str) or not RESOURCE_ID.fullmatch(identity) or identity in result:
            raise CatalogError(f"Invalid or duplicate resource id: {identity!r}")
        if not isinstance(row["title"], str) or not row["title"].strip():
            raise CatalogError(f"{identity}: title must be nonempty text")
        number = row.setdefault("number", None)
        if number is not None:
            _integer(number, f"{identity}.number", 1)
            if number in numbers:
                raise CatalogError(f"Duplicate resource number: {number}")
            numbers.add(number)
        _integer(row["target_bytes"], f"{identity}.target_bytes")
        if not isinstance(row["status"], str) or row["status"] not in STATUSES:
            raise CatalogError(f"{identity}: status must be ready, partial, or unresolved")
        reason = row.get("reason", "")
        if not isinstance(reason, str) or (row["status"] != "ready" and not reason.strip()):
            raise CatalogError(f"{identity}: incomplete resources require a nonempty reason")
        row["reason"] = reason
        members = _strings(row["asset_ids"], f"{identity}.asset_ids", unique=True)
        replacements = _strings(row.setdefault("replaces_asset_ids", []),
                                f"{identity}.replaces_asset_ids", unique=True)
        missing = (set(members) | set(replacements)) - asset_map.keys()
        if missing:
            raise CatalogError(f"{identity}: unknown asset ids: {', '.join(sorted(missing))}")
        if set(members) & set(replacements):
            raise CatalogError(f"{identity}: a resource cannot replace its own member assets")
        if row["status"] == "ready":
            if not members:
                raise CatalogError(f"{identity}: a ready resource needs at least one source asset")
            if any(asset_map[member].get("status", "resolved") != "resolved" for member in members):
                raise CatalogError(f"{identity}: a ready resource contains unresolved source assets")
        editions = row.setdefault("editions", {})
        if not isinstance(editions, dict) or set(editions) - {"direct", "compact"}:
            raise CatalogError(f"{identity}: editions may define only direct and compact")
        critical = {member for member in members if asset_map[member].get("critical")}
        for name, edition in editions.items():
            label = f"{identity} edition {name}"
            if (not isinstance(edition, dict) or
                    set(edition) != {"asset_ids", "target_bytes", "status", "reason"}):
                raise CatalogError(f"{label}: requires asset_ids, target_bytes, status, and reason")
            group = _strings(edition["asset_ids"], f"{label}.asset_ids", unique=True)
            _integer(edition["target_bytes"], f"{label}.target_bytes")
            if not isinstance(edition["status"], str) or edition["status"] not in STATUSES:
                raise CatalogError(f"{label}: invalid status")
            if (not isinstance(edition["reason"], str) or
                    (edition["status"] != "ready" and not edition["reason"].strip())):
                raise CatalogError(f"{label}: incomplete editions require a nonempty reason")
            if not group:
                raise CatalogError(f"{label}: an edition needs pinned source assets")
            if set(group) - asset_map.keys():
                raise CatalogError(f"{label}: unknown asset ids")
            for member in group:
                asset = asset_map[member]
                if (asset.get("status", "resolved") != "resolved" or
                        not isinstance(asset.get("sha256"), str) or
                        not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
                    raise CatalogError(f"{label}: every source must be resolved and SHA-256 pinned")
                if name == "direct" and (str(asset.get("format", "")).lower() not in DIRECT or
                        asset.get("reader_required") or
                        str(asset.get("destination", "")).split("/")[0] in {"ZIM", "SOFTWARE"}):
                    raise CatalogError(f"{label}: direct editions require ordinary readable source formats")
            if name == "compact" and not any(str(asset_map[m].get("format", "")).lower() == "zim" for m in group):
                raise CatalogError(f"{label}: compact editions require a pinned ZIM archive")
            if critical - set(group):
                raise CatalogError(f"{label}: editions must preserve critical directly readable source assets")
        for field in ("preferred_formats", "include", "exclude", "source_pages"):
            if field in row:
                _strings(row[field], f"{identity}.{field}")
        for url in row.get("source_pages", []):
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise CatalogError(f"{identity}: source_pages must contain HTTPS source pages")
        credit = row.get("replacement_credit")
        if credit is not None:
            if not isinstance(credit, dict) or set(credit) != {"resource_id", "target_bytes"}:
                raise CatalogError(f"{identity}: replacement_credit requires resource_id and target_bytes")
            if not isinstance(credit["resource_id"], str) or not RESOURCE_ID.fullmatch(credit["resource_id"]):
                raise CatalogError(f"{identity}: invalid replacement_credit.resource_id")
            if not replacements:
                raise CatalogError(f"{identity}: replacement_credit needs replaces_asset_ids")
            _integer(credit["target_bytes"], f"{identity}.replacement_credit.target_bytes")
        result[identity] = row
    for identity, row in result.items():
        credit = row.get("replacement_credit")
        if credit:
            other = credit["resource_id"]
            if other not in result or other == identity:
                raise CatalogError(f"{identity}: replacement credit must reference another known resource")
            if not set(row["replaces_asset_ids"]) & set(result[other]["asset_ids"]):
                raise CatalogError(f"{identity}: replacement credit does not replace an asset in {other}")
    return result


def _selections(values: Iterable[str | int] | str, resources: dict[str, dict], name: str) -> list[str]:
    """Accept repeated CLI values, comma-separated IDs, and listed numbers."""
    if isinstance(values, str):
        values = [values]
    by_number = {str(row["number"]): identity for identity, row in resources.items()
                 if row.get("number") is not None}
    selected = set()
    for value in values:
        if type(value) is int:
            value = str(value)
        if not isinstance(value, str):
            raise CatalogError(f"{name}: select resource ids or listed numbers")
        for token in value.split(","):
            token = token.strip()
            if not token:
                raise CatalogError(f"{name}: empty resource selection")
            identity = by_number.get(str(int(token))) if token.isascii() and token.isdigit() else token
            if identity not in resources:
                raise CatalogError(f"{name}: unknown resource {token!r}; list resources to see available ids and numbers")
            selected.add(identity)
    return [identity for identity in resources if identity in selected]


def resource_asset_ids(resource: dict) -> set[str]:
    """All registered editions belong to the resource for explicit exclusions."""
    return set(resource["asset_ids"]).union(*(set(e["asset_ids"]) for e in resource.get("editions", {}).values()))


def _edition_selections(values: Iterable[str] | str, resources: dict[str, dict]) -> dict[str, str]:
    if isinstance(values, str):
        values = [values]
    chosen = {}
    for value in values:
        if not isinstance(value, str):
            raise CatalogError("edition: use RESOURCE=direct|compact|published")
        for token in value.split(","):
            if token.count("=") != 1:
                raise CatalogError("edition: use RESOURCE=direct|compact|published")
            resource, edition = (part.strip() for part in token.split("="))
            identity = _selections([resource], resources, "edition")[0]
            if edition not in EDITIONS:
                raise CatalogError(f"{identity}: unknown edition {edition!r}")
            if identity in chosen and chosen[identity] != edition:
                raise CatalogError(f"{identity}: conflicting edition selections")
            if edition != "published" and edition not in resources[identity].get("editions", {}):
                raise CatalogError(f"{identity}: {edition} edition is unavailable; no pinned edition is registered")
            chosen[identity] = edition
    return {identity: chosen[identity] for identity in resources if identity in chosen}


def resolve_resources(assets: list[dict], profile: dict, resources: dict[str, dict], *,
                      include: Iterable[str | int] | str = (),
                      exclude: Iterable[str | int] | str = (),
                      editions: Iterable[str] | str = ()) -> dict:
    """Resolve defaults plus explicit changes without claiming missing content.

    Targets are budgets, not download instructions. Exact known files can raise
    an effective budget, never lower it. Resource aliases share one file copy.
    The caller must refuse incomplete resources unless explicitly authorized.

    Editions replace a selected resource's members, status, reason and target.
    Profile member exclusions apply to whichever edition contains those IDs;
    profile target overrides apply only to the default ``published`` edition.
    A choice never implicitly selects its resource or removes critical files.
    """
    asset_map = _asset_map(assets)
    defaults = _strings(profile.get("default_resources", []), "default_resources", unique=True)
    unknown = set(defaults) - resources.keys()
    if unknown:
        raise CatalogError(f"Unknown default resources: {', '.join(sorted(unknown))}")
    explicit_include = _selections(include, resources, "include")
    explicit_exclude = _selections(exclude, resources, "exclude")
    explicit_editions = _edition_selections(editions, resources)
    configured = profile.get("default_editions", {})
    if (not isinstance(configured, dict) or set(configured) - set(defaults) or
            any(not isinstance(value, str) for value in configured.values())):
        raise CatalogError("default_editions must map default resources to registered editions")
    default_editions = _edition_selections(
        [f"{identity}={edition}" for identity, edition in configured.items()], resources)
    collisions = set(explicit_include) & set(explicit_exclude)
    if collisions:
        raise CatalogError(f"Resources both included and excluded: {', '.join(sorted(collisions))}")
    selected = (set(defaults) | set(explicit_include)) - set(explicit_exclude)
    effective_editions = {identity: edition for identity, edition in
                          {**default_editions, **explicit_editions}.items() if identity in selected}
    for identity in explicit_editions:
        if identity not in selected:
            raise CatalogError(f"{identity}: an edition requires a selected resource; use --include and remove any exclusion")
    overrides = profile.get("resource_overrides", {})
    if not isinstance(overrides, dict) or set(overrides) - resources.keys():
        raise CatalogError("resource_overrides must name known resource ids")
    for identity, override in overrides.items():
        if not isinstance(override, dict) or set(override) - {"target_bytes", "exclude_asset_ids"}:
            raise CatalogError(f"{identity}: override supports target_bytes and exclude_asset_ids")
        if "target_bytes" in override:
            _integer(override["target_bytes"], f"{identity} override target_bytes")
        excluded = _strings(override.get("exclude_asset_ids", []), f"{identity} override exclude_asset_ids", unique=True)
        if set(excluded) - resource_asset_ids(resources[identity]):
            raise CatalogError(f"{identity}: override excludes an asset outside this resource")
    if "readers_budget_bytes" in profile:
        _integer(profile["readers_budget_bytes"], "readers_budget_bytes")

    def edition_data(identity: str) -> dict:
        name = effective_editions.get(identity, "published")
        return resources[identity] if name == "published" else resources[identity]["editions"][name]

    def members(identity: str) -> list[str]:
        removed = set(overrides.get(identity, {}).get("exclude_asset_ids", []))
        return [member for member in edition_data(identity)["asset_ids"] if member not in removed]

    raw_members = {identity: members(identity) for identity in selected}
    raw_asset_ids = {member for group in raw_members.values() for member in group}
    replacements = {}
    credits = {identity: 0 for identity in selected}
    for identity in resources:
        if identity not in selected:
            continue
        row = resources[identity]
        replaced = set(row.get("replaces_asset_ids", [])) & raw_asset_ids
        for member in replaced:
            if member in replacements:
                raise CatalogError(f"{identity} and {replacements[member]} both replace asset {member}")
            replacements[member] = identity
        credit = row.get("replacement_credit")
        if credit and credit["resource_id"] in selected and replaced & set(raw_members[credit["resource_id"]]):
            credits[credit["resource_id"]] += credit["target_bytes"]
    memberships = {identity: [member for member in group if member not in replacements]
                   for identity, group in raw_members.items()}
    selected_assets = {member for group in memberships.values() for member in group}
    needs_readers = any(asset_map[member].get("status", "resolved") == "resolved" and
                        str(asset_map[member].get("format", "")).lower() == "zim"
                        for member in selected_assets)
    auto_included = []
    if needs_readers:
        if READERS in explicit_exclude:
            raise CatalogError("Selected ZIM archives need archive-readers; remove its exclusion or exclude the ZIM resources")
        if READERS not in resources:
            raise CatalogError("Selected ZIM archives need the archive-readers resource, but it is missing from the registry")
        if READERS not in selected:
            selected.add(READERS)
            memberships[READERS] = members(READERS)
            credits[READERS] = 0
            auto_included.append(READERS)
        if not any(asset_map[member].get("status", "resolved") == "resolved" and
                   str(asset_map[member].get("destination", "")).startswith("SOFTWARE/")
                   for member in memberships[READERS]):
            raise CatalogError("Selected ZIM archives need a resolved bundled reader in archive-readers; its selected sources are missing")
    selected_ids = [identity for identity in resources if identity in selected]
    rows, owners = [], {}
    for identity in selected_ids:
        resource = resources[identity]
        edition = effective_editions.get(identity, "published")
        mapping = edition_data(identity)
        group = memberships[identity]
        resolved = [member for member in group if asset_map[member].get("status", "resolved") == "resolved"]
        unresolved = [member for member in group if member not in resolved]
        known = sum(asset_map[member]["size_bytes"] for member in resolved)
        planning_target = (overrides.get(identity, {}).get("target_bytes", resource["target_bytes"])
                           if edition == "published" else mapping["target_bytes"])
        credit = credits[identity]
        if credit > planning_target:
            raise CatalogError(f"{identity}: replacement credit exceeds its selected planning target")
        adjusted_target = planning_target - credit
        status, reason = mapping["status"], mapping.get("reason", "")
        if not group:
            status = "unresolved"
            reason = "; ".join(filter(None, [reason, "No selected source assets remain after overrides or replacements"]))
        elif unresolved and status == "ready":
            status = "partial" if resolved else "unresolved"
            reason = "Selected source assets are unresolved: " + ", ".join(unresolved)
        rows.append({"id": identity, "number": resource.get("number"), "title": resource["title"],
                     "edition": edition,
                     "status": status, "reason": reason, "target_bytes": resource["target_bytes"],
                     "planning_target_bytes": planning_target, "credit_bytes": credit,
                     "adjusted_target_bytes": adjusted_target,
                     "effective_target_bytes": max(adjusted_target, known),
                     "known_bytes": known, "asset_ids": list(group),
                     "resolved_asset_ids": resolved, "unresolved_asset_ids": unresolved})
        for member in group:
            owners.setdefault(member, []).append(identity)
    copies = []
    for asset in assets:
        if asset["id"] in owners:
            memberships_list = list(asset.get("profiles", []))
            if profile["id"] not in memberships_list:
                memberships_list.append(profile["id"])
            copies.append({**asset, "profiles": memberships_list, "resource_ids": owners[asset["id"]]})
    declared = sum(row["adjusted_target_bytes"] for row in rows if row["id"] != READERS)
    content = sum(row["effective_target_bytes"] for row in rows if row["id"] != READERS)
    reader_row = next((row for row in rows if row["id"] == READERS), None)
    reader_budget = max(profile.get("readers_budget_bytes", 0), reader_row["effective_target_bytes"]) if reader_row else 0
    return {"assets": copies, "selected_ids": selected_ids, "excluded_ids": explicit_exclude,
            "explicit_include": explicit_include, "explicit_exclude": explicit_exclude,
            "explicit_editions": explicit_editions,
            "default_editions": {identity: edition for identity, edition in default_editions.items()
                                 if identity in selected},
            "effective_editions": effective_editions,
            "auto_included_ids": auto_included, "customized": bool(explicit_include or explicit_exclude or explicit_editions),
            "resource_rows": rows, "incomplete_resources": [row for row in rows if row["status"] != "ready"],
            "declared_content_target_bytes": declared, "content_target_bytes": content,
            "readers_budget_bytes": reader_budget, "planned_total_bytes": content + reader_budget,
            "resolved_asset_bytes": sum(asset["size_bytes"] for asset in copies if asset.get("status", "resolved") == "resolved"),
            "unresolved_asset_ids": [asset["id"] for asset in copies if asset.get("status", "resolved") != "resolved"],
            "replaced_asset_ids": sorted(replacements)}
