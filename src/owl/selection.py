"""Compile a monotone capacity ladder and resolve default collection editions."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path

from .catalog import CatalogError

GB = 1_000_000_000
MIN_CAPACITY = 16 * GB
DEFAULT_LIMIT = 1000 * GB
MAX_CAPACITY = 2**53 - 1  # Exact bytes in both Python and JavaScript.
CAPACITY_GRID_GB = (16, 24, 32, 48, 64, 100, 128, 200, 256, 384, 500, 512, 750, 1000)
BUILTIN_CAPACITIES = {
    "flash-16gb": 16, "critical-64gb": 64, "compact-256gb": 256,
    "standard-512gb": 512, "full-1tb": 1000,
}
MINIMUM_MARGIN = 125_000_000
MARGIN_DIVISOR = 200
READER_BUDGET = GB
DISCOVERY_BUDGET = 16 * 1024 * 1024
METADATA_BUDGET = 16 * 1024 * 1024
READERS = "archive-readers"


def capacity_budget(capacity_bytes: int) -> dict[str, int]:
    if type(capacity_bytes) is not int or not MIN_CAPACITY <= capacity_bytes <= MAX_CAPACITY:
        raise CatalogError("Capacity must be a whole number of bytes from 16 GB to 9,007,199 GB")
    headroom = max(MINIMUM_MARGIN, capacity_bytes // MARGIN_DIVISOR)
    return {
        "capacity_bytes": capacity_bytes - headroom,
        "reserve_bytes": headroom,
        "discovery_budget_bytes": DISCOVERY_BUDGET,
        "readers_budget_bytes": READER_BUDGET,
    }


def usable_capacity(capacity_bytes: int) -> int:
    budget = capacity_budget(capacity_bytes)
    return (budget["capacity_bytes"] - budget["reserve_bytes"] -
            budget["discovery_budget_bytes"] - METADATA_BUDGET - budget["readers_budget_bytes"])


@dataclass(frozen=True)
class Edition:
    name: str
    size: int
    depth: tuple[tuple[str, int, int], ...]
    critical: bool


def _editions(assets, resources):
    by_id = {asset["id"]: asset for asset in assets}
    groups = {}
    levels = defaultdict(set)
    seen = set()
    for rid, resource in sorted(resources.items()):
        if rid == READERS or resource.get("opt_in"):
            continue
        if resource["replaces_asset_ids"]:
            raise CatalogError(f"{rid}: replacing files across collections cannot be a monotone default")
        editions = []
        members = set()
        for name, edition in {"published": resource, **resource["editions"]}.items():
            if edition["status"] != "ready":
                continue
            rows = [by_id[aid] for aid in edition["asset_ids"]]
            if not rows or any("selection" not in row for row in rows):
                raise CatalogError(f"{rid}: default files require planning metadata")
            depth = tuple(sorted({(row["selection"]["domain"], row["selection"]["level"],
                                   row["selection"]["rank"]) for row in rows}))
            size = sum(row["size_bytes"] for row in rows)
            if edition["target_bytes"] != size or any("generation" in row for row in rows):
                raise CatalogError(f"{rid}: default editions must be exact finished downloads")
            editions.append(Edition(name, size, depth, any(row["utility_tier"] == "CRITICAL" for row in rows)))
            members.update(edition["asset_ids"])
        if seen & members:
            raise CatalogError(f"{rid}: default collections must have unique files")
        seen.update(members)
        if editions:
            editions.sort(key=lambda item: (item.size, item.name))
            prior_depth = {}
            previous_size = 0
            for edition in editions:
                if edition.size <= previous_size:
                    raise CatalogError(f"{rid}: default editions must have increasing storage costs")
                previous_size = edition.size
                next_depth = _depth(edition)
                if any(next_depth.get(domain, -1) < level for domain, level in prior_depth.items()):
                    raise CatalogError(f"{rid}: a larger edition cannot lower domain depth")
                prior_depth = next_depth
                for domain, level in next_depth.items():
                    levels[domain].add(level)
            groups[rid] = editions
    return groups, levels


def _depth(edition):
    depth = {}
    for domain, level, _ in edition.depth:
        depth[domain] = max(level, depth.get(domain, -1))
    return depth


def compile_ladder(assets: list[dict], resources: dict[str, dict]) -> list[list]:
    """Produce [minimum usable bytes, resource id, edition] transitions.

    Fill the capacity bands in order. Larger editions use their incremental
    storage cost. The depth gate gives every field with a shallower offering
    a chance to establish coverage before any field advances two levels.
    """
    groups, levels = _editions(assets, resources)
    depth_maps = {edition: _depth(edition) for editions in groups.values() for edition in editions}
    requirements = {
        level: {domain: max(lower) for domain, available in levels.items()
                if (lower := [value for value in available if value < level])}
        for level in range(5)
    }

    def pack(limit, installed, depth, used, strategy, goal=None):
        installed, depth = installed.copy(), depth.copy()
        actions = []
        while True:
            options = []
            for rid, editions in groups.items():
                index = installed.get(rid, -1)
                if index + 1 >= len(editions) or (goal is not None and index >= goal.get(rid, -1)):
                    continue
                edition = editions[index + 1]
                cost = edition.size - (editions[index].size if index >= 0 else 0)
                offered = depth_maps[edition]
                level = max(offered.values())
                if cost <= limit - used and (edition.critical or all(
                    max(depth.get(domain, -1), offered.get(domain, -1)) >= minimum
                    for domain, minimum in requirements[level].items()
                )):
                    options.append((rid, edition, cost, level))
            if not options:
                break

            def priority(action):
                rid, edition, cost, level = action
                offered = depth_maps[edition]
                new = sum(domain not in depth for domain in offered)
                raises = sum(value > depth.get(domain, -1) for domain, value in offered.items())
                rank = min(rank for _, _, rank in edition.depth)
                foundation = (not edition.critical, level != 0)
                if strategy == "ascending":
                    return (*foundation, cost, -new, rank, rid)
                if strategy == "frontier":
                    return (*foundation, -raises, -level, -cost, rank, rid)
                if strategy == "small-frontier":
                    return (*foundation, -raises, -level, cost, rank, rid)
                return (*foundation, -new, -cost, rank, rid)

            rid, edition, cost, _ = min(options, key=priority)
            used += cost
            installed[rid] = installed.get(rid, -1) + 1
            for domain, level in depth_maps[edition].items():
                depth[domain] = max(level, depth.get(domain, -1))
            actions.append([used, rid, edition.name])
        return used, installed, depth, actions

    installed = {}
    depth = {}
    actions = []
    used = 0
    for capacity in CAPACITY_GRID_GB:
        limit = usable_capacity(capacity * GB)
        outcomes = [pack(limit, installed, depth, used, strategy)
                    for strategy in ("breadth", "frontier", "small-frontier")]
        # The variants trade breadth ordering for unlocking more expensive
        # depth steps. Keep the breadth order when it is already near full.
        chosen = next((outcome for outcome in outcomes if outcome[0] * 100 >= limit * 97),
                      max(outcomes, key=lambda outcome: outcome[0]))
        # Within that set, take smaller eligible steps first so intermediate
        # drives gain content before reaching the next indivisible archive.
        _, goal, _, _ = chosen
        used, installed, depth, band = pack(limit, installed, depth, used, "ascending", goal)
        actions.extend(band)
    if any(edition.critical and installed.get(rid, -1) < index
           for rid, editions in groups.items() for index, edition in enumerate(editions)):
        raise CatalogError("Capacity ladder omits a critical edition")
    return actions


def recommended_profile(profile: dict, capacity_bytes: int, ladder: list[list]) -> dict:
    usable = usable_capacity(min(capacity_bytes, DEFAULT_LIMIT))
    choices = {READERS: "published"}
    for threshold, rid, edition in ladder:
        if threshold > usable:
            break
        choices[rid] = edition
    return {
        **profile,
        **capacity_budget(capacity_bytes),
        "nominal_capacity_bytes": capacity_bytes,
        "default_resources": sorted(choices),
        "default_editions": {rid: edition for rid, edition in sorted(choices.items()) if edition != "published"},
    }


def fill(capacity_bytes: int, overrides: dict | None = None, *, assets=None, resources=None) -> dict:
    """Return the builder's resolved selection, with its recommendation budget."""
    from .catalog import load_catalog
    from .resources import load_resources, resolve_resources

    root = Path(__file__).resolve().parents[2]
    if assets is None:
        assets = load_catalog(root / "catalog/library.yaml")
    if resources is None:
        resources = load_resources(root / "catalog/resources.yaml", assets)
    profile = recommended_profile({"id": "capacity"}, capacity_bytes, compile_ladder(assets, resources))
    return {"profile": profile, **resolve_resources(assets, profile, resources, **(overrides or {}))}


def load_ladder(catalog: Path) -> list[list]:
    path = catalog.with_name("capacity-ladder.json")
    return json.loads(path.read_text(encoding="utf-8"))["transitions"]
