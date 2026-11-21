"""Compile a monotone capacity ladder and resolve default collection editions."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path

from .catalog import CatalogError, is_document, read_yaml

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


PUBLISHED = "published"
FIELD_PRIORITIES = (
    ("health", "water-sanitation", "food-preservation", "agriculture", "shelter"),
    ("hand-tools", "repair"),
    ("navigation",),
    ("general-reference",),
    ("school-math", "school-science"),
    ("languages",),
    ("culture", "advanced-study", "computing"),
)
FIELD_PRIORITY = {field: priority for priority, fields in enumerate(FIELD_PRIORITIES) for field in fields}
PROTECTED_FIELDS = frozenset(FIELD_PRIORITIES[0])


def is_knowledge(asset):
    return is_document(asset) and not asset["destination"].startswith("SOFTWARE/")


def attributed_bytes(asset):
    """Allocate each knowledge byte once, using recorded editorial weights."""
    if not is_knowledge(asset):
        return {}
    selection = asset["selection"]
    weights = selection.get("domain_weights")
    if weights is None:
        return {selection["domain"]: asset["size_bytes"]}
    total = sum(weights.values())
    remaining = asset["size_bytes"]
    bytes_by_domain = {}
    for domain, weight in sorted(weights.items()):
        value = asset["size_bytes"] * weight // total
        bytes_by_domain[domain] = value
        remaining -= value
    for domain in list(bytes_by_domain)[:remaining]:
        bytes_by_domain[domain] += 1
    return bytes_by_domain


class DomainRetention:
    """Compare a selection to the 1 TB default with the same byte attribution."""

    def __init__(self, assets):
        self.full = Counter()
        self.candidates = defaultdict(list)
        for asset in assets:
            for domain, size in attributed_bytes(asset).items():
                self.full[domain] += size
                self.candidates[domain].append(asset)
        self.total = self.full.total()
        for items in self.candidates.values():
            items.sort(key=lambda asset: (asset["selection"]["level"], asset["selection"]["rank"], asset["id"]))

    def gaps(self, assets, capacity):
        domains = Counter()
        ids = set()
        for asset in assets:
            ids.add(asset["id"])
            domains.update(attributed_bytes(asset))
        yield from self.gaps_from_totals(domains, ids, capacity)

    def gaps_from_totals(self, domains, ids, capacity):
        total = domains.total()
        for domain, reference in sorted(self.full.items()):
            shortfall = (reference * total + 3 * self.total - 1) // (3 * self.total) - domains[domain]
            if reference >= GB and shortfall > 0:
                next_asset = next(asset for asset in self.candidates[domain] if asset["id"] not in ids)
                yield domain, shortfall, next_asset, 10 * next_asset["size_bytes"] > capacity


def _first_fitting_capacity(size):
    """Find a capacity where the files fit through the next margin increment."""
    lo, hi = MIN_CAPACITY, DEFAULT_LIMIT
    if size > usable_capacity(hi):
        raise CatalogError("Capacity order exceeds the 1 TB usable budget")
    while lo < hi:
        middle = (lo + hi) // 2
        if size <= min(usable_capacity(middle), usable_capacity(middle + 1)):
            hi = middle
        else:
            lo = middle + 1
    return lo


def _totals(assets):
    tiers, fields = Counter(), Counter()
    for asset in assets.values():
        if is_knowledge(asset):
            tiers[asset["utility_tier"]] += asset["size_bytes"]
            fields.update(attributed_bytes(asset))
    return tiers, fields


def _validate_transition(capacity, before, after, previous_fields, fields):
    removed = before.keys() - after.keys()
    if any(PROTECTED_FIELDS & attributed_bytes(before[aid]).keys() for aid in removed):
        raise CatalogError(f"{capacity / GB:g} GB: capacity order removes a protected asset")
    drops = [field for field, size in previous_fields.items() if fields[field] < size]
    if not drops:
        return
    large_entries = [
        FIELD_PRIORITY[after[aid]["selection"]["domain"]]
        for aid in after.keys() - before.keys() if 10 * after[aid]["size_bytes"] >= capacity
    ]
    highest_priority = min(large_entries, default=len(FIELD_PRIORITIES))
    if any(FIELD_PRIORITY[field] <= highest_priority for field in drops):
        raise CatalogError(f"{capacity / GB:g} GB: field losses without a higher-priority archive: {drops}")


def compile_ladder(assets: list[dict], resources: dict[str, dict], order_path: Path | None = None) -> dict:
    """Compile a reviewed collection order using exact catalog bytes."""
    if order_path is None:
        order_path = Path(__file__).resolve().parents[2] / "catalog/capacity-order.yaml"
    order = read_yaml(order_path).get("steps")
    if not isinstance(order, list) or not order:
        raise CatalogError("Capacity order must have a nonempty steps list")
    for step in order:
        if not isinstance(step, dict) or "add" not in step or step.keys() - {"add", "remove"}:
            raise CatalogError("Capacity order steps require add and may specify remove")
        for ids in step.values():
            if (not isinstance(ids, list) or any(not isinstance(rid, str) for rid in ids)
                    or len(ids) != len(set(ids))):
                raise CatalogError("Capacity order steps require lists of unique collection IDs")
    by_id = {row["id"]: row for row in assets}
    members = {}
    for identity in {rid for step in order for rid in step["add"]}:
        resource = resources.get(identity)
        if (not resource or resource.get("opt_in") or identity == READERS
                or resource["status"] != "ready" or resource["replaces_asset_ids"]):
            raise CatalogError(f"{identity}: capacity order requires a ready default collection")
        rows = {aid: by_id[aid] for aid in resource["asset_ids"]}
        if (resource["target_bytes"] != sum(row["size_bytes"] for row in rows.values())
                or any("generation" in row or "selection" not in row for row in rows.values())):
            raise CatalogError(f"{identity}: capacity order requires exact downloads")
        members[identity] = rows

    def selected_assets(ids):
        rows = {aid: row for rid in ids for aid, row in members[rid].items()}
        if len(rows) != sum(len(members[rid]) for rid in ids):
            raise CatalogError("Capacity order includes overlapping collections")
        return rows

    mandatory = {row["id"] for row in assets if row["utility_tier"] == "CRITICAL"}
    for resource in resources.values():
        if resource.get("default_sampler"):
            mandatory.update(resource["asset_ids"])
    # A collection is persistent from its last entry. Previous appearances
    # remain in the filler table until an eligible archive replaces them.
    last_removal = {rid: index for index, step in enumerate(order) for rid in step.get("remove", [])}
    active = set()
    selected = {}
    fields = Counter()
    history = []
    capacities = []
    transitions = []
    filler_steps = []
    placements = sorted(last_removal)
    for index, step in enumerate(order):
        added, removed = set(step["add"]), set(step.get("remove", []))
        if not added or added & active or not removed <= active:
            raise CatalogError(f"Invalid capacity order step {index + 1}")
        active = (active - removed) | added
        current = selected_assets(active)
        size = sum(row["size_bytes"] for row in current.values())
        earliest = _first_fitting_capacity(size)
        capacity = max(earliest, capacities[-1] + 1 if capacities else MIN_CAPACITY)
        if index == 0 and capacity != MIN_CAPACITY:
            raise CatalogError("The initial capacity order must fit at 16 GB")
        if capacity > DEFAULT_LIMIT:
            raise CatalogError("Capacity order reaches past the 1 TB default")
        tiers, next_fields = _totals(current)
        if not mandatory <= current.keys():
            raise CatalogError(f"{capacity / GB:g} GB: capacity order omits required files")
        _validate_transition(capacity, selected, current, fields, next_fields)
        fields, selected = next_fields, current
        capacities.append(capacity)
        history.append(tiers)
        transitions.extend([capacity, rid, PUBLISHED] for rid in sorted(added)
                           if last_removal.get(rid, -1) < index)
        current_fillers = [i for i, rid in enumerate(placements) if rid in active
                           and last_removal[rid] > index]
        if not filler_steps or filler_steps[-1][1] != current_fillers:
            filler_steps.append([capacity, current_fillers])

    full = history[-1]
    for capacity, tiers in zip(capacities, history, strict=True):
        if tiers["USEFUL"] * full["NONESSENTIAL"] < tiers["NONESSENTIAL"] * full["USEFUL"]:
            raise CatalogError(f"{capacity / GB:g} GB: capacity order reverses tier retention")
    return {
        "schema_version": 2,
        "transitions": transitions,
        "filler_placements": [[rid, PUBLISHED] for rid in placements],
        "fillers": filler_steps,
    }


def ladder_choices(capacity_bytes: int, ladder: dict) -> tuple[dict, dict]:
    capacity = min(capacity_bytes, DEFAULT_LIMIT)
    core = {}
    for threshold, resource, edition in ladder["transitions"]:
        if threshold > capacity:
            break
        core[resource] = edition
    fillers = ladder["fillers"]
    index = bisect_right(fillers, capacity, key=lambda row: row[0]) - 1
    return core, dict(ladder["filler_placements"][i] for i in fillers[index][1])


def recommended_profile(profile: dict, capacity_bytes: int, ladder: dict) -> dict:
    budget = capacity_budget(capacity_bytes)
    core, fillers = ladder_choices(capacity_bytes, ladder)
    choices = {READERS: PUBLISHED, **core, **fillers}
    return {
        **profile,
        **budget,
        "nominal_capacity_bytes": capacity_bytes,
        "default_resources": sorted(choices),
        "default_editions": {rid: edition for rid, edition in sorted(choices.items()) if edition != PUBLISHED},
    }


def fill(capacity_bytes: int, overrides: dict | None = None, *, assets=None, resources=None) -> dict:
    """Return the builder's resolved selection, with its recommendation budget."""
    from .catalog import load_catalog
    from .resources import load_resources, resolve_resources

    root = Path(__file__).resolve().parents[2]
    catalog = root / "catalog/library.yaml"
    use_generated = assets is None and resources is None
    if assets is None:
        assets = load_catalog(catalog)
    if resources is None:
        resources = load_resources(root / "catalog/resources.yaml", assets)
    ladder = load_ladder(catalog) if use_generated else compile_ladder(assets, resources)
    profile = recommended_profile({"id": "capacity"}, capacity_bytes, ladder)
    return {"profile": profile, **resolve_resources(assets, profile, resources, **(overrides or {}))}


def load_ladder(catalog: Path) -> dict:
    path = catalog.with_name("capacity-ladder.json")
    ladder = json.loads(path.read_text(encoding="utf-8"))
    if ladder["schema_version"] != 2:
        raise CatalogError("Regenerate the capacity ladder with scripts/build_capacity_ladder.py")
    return ladder
