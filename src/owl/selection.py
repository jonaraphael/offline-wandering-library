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
READER_BUDGET = 500_000_000
DISCOVERY_BUDGET = 16 * 1024 * 1024
MAX_DISCOVERY_BUDGET = 900_000_000
DISCOVERY_DIVISOR = 100
METADATA_BUDGET = 16 * 1024 * 1024
BASE_LADDER_SEARCH_BUDGET = 500_000_000
READERS = "archive-readers"
EXPANSION_FILL_PERCENT = 90
REGIONAL_PACKS = ("regional-maps", "topo-usgs-northeast", "topo-usgs-mid-atlantic",
                  "topo-usgs-appalachian", "topo-canada-nearby")
LANGUAGE_PACKS = ("wikipedia-es", "wikipedia-fr", "wikipedia-zh", "wikipedia-ar",
                  "wikipedia-pt", "wikipedia-it")


def capacity_budget(capacity_bytes: int) -> dict[str, int]:
    if type(capacity_bytes) is not int or not MIN_CAPACITY <= capacity_bytes <= MAX_CAPACITY:
        raise CatalogError("Capacity must be a whole number of bytes from 16 GB to 9,007,199 GB")
    headroom = max(MINIMUM_MARGIN, capacity_bytes // MARGIN_DIVISOR)
    discovery = min(
        MAX_DISCOVERY_BUDGET,
        BASE_LADDER_SEARCH_BUDGET + headroom - MINIMUM_MARGIN,
        max(DISCOVERY_BUDGET, min(capacity_bytes, DEFAULT_LIMIT) // DISCOVERY_DIVISOR),
    )
    extra_search = max(0, discovery - BASE_LADDER_SEARCH_BUDGET)
    return {
        "capacity_bytes": capacity_bytes - headroom,
        "reserve_bytes": headroom - extra_search,
        "discovery_budget_bytes": discovery,
        "readers_budget_bytes": READER_BUDGET,
    }


def usable_capacity(capacity_bytes: int) -> int:
    budget = capacity_budget(capacity_bytes)
    search_reserve = max(BASE_LADDER_SEARCH_BUDGET, budget["discovery_budget_bytes"])
    return (budget["capacity_bytes"] - budget["reserve_bytes"] -
            READER_BUDGET - search_reserve - DISCOVERY_BUDGET - METADATA_BUDGET)


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
PROTECTED_FIELDS = frozenset((*FIELD_PRIORITIES[0], "navigation"))


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


def _validate_transition(capacity, before, after, previous_fields, fields, edition_replacements, peaks, core):
    lost_core = sorted({aid for ids in core.values() for aid in ids} - after.keys())
    if lost_core:
        raise CatalogError(f"{capacity / GB:g} GB: capacity order omits core assets: {lost_core}")
    below_floor = [field for field, peak in peaks.items() if 2 * fields[field] < peak]
    if below_floor:
        raise CatalogError(f"{capacity / GB:g} GB: field drops below half its earlier peak: {below_floor}")
    removed = before.keys() - after.keys()
    if any(fields[field] < previous_fields[field] for field in PROTECTED_FIELDS):
        raise CatalogError(f"{capacity / GB:g} GB: capacity order reduces a protected field")
    removed -= edition_replacements
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


def _expansion(assets, resources, choices, selected):
    """Price additional pinned collections in the reviewed pack order."""
    by_id = {asset["id"]: asset for asset in assets}
    seen = set(selected) | set(resources[READERS]["asset_ids"])
    # Other editions of a default collection remain available through the editor.
    alternatives = {aid for rid in choices for edition in resources[rid].get("editions", {}).values()
                    for aid in edition["asset_ids"]}
    remainder = sorted(resources.keys() - choices.keys() - {READERS, *REGIONAL_PACKS, *LANGUAGE_PACKS},
                       key=lambda rid: (resources[rid].get("utility_tier") != "USEFUL",
                                        resources[rid]["target_bytes"], rid))
    total = sum(by_id[aid]["size_bytes"] for aid in seen)
    for rid in (*REGIONAL_PACKS, *LANGUAGE_PACKS, *remainder):
        resource = resources.get(rid)
        if not resource or resource["status"] != "ready" or resource["replaces_asset_ids"]:
            continue
        ids = set(resource["asset_ids"])
        if not ids - seen or ids & alternatives or any(
                by_id[aid]["status"] != "resolved" or by_id[aid].get("generation") for aid in ids):
            continue
        total += sum(by_id[aid]["size_bytes"] for aid in ids - seen)
        seen.update(ids)
        threshold = (100 * total + EXPANSION_FILL_PERCENT - 1) // EXPANSION_FILL_PERCENT
        yield [max(DEFAULT_LIMIT + 1, threshold), rid]


def compile_ladder(assets: list[dict], resources: dict[str, dict], order_path: Path | None = None) -> dict:
    """Compile ordered collection additions, edition upgrades and removals."""
    if order_path is None:
        order_path = Path(__file__).resolve().parents[2] / "catalog/capacity-order.yaml"
    policy = read_yaml(order_path)
    order = policy.get("steps")
    if not isinstance(order, list) or not order:
        raise CatalogError("Capacity order must have a nonempty steps list")
    for step in order:
        if not isinstance(step, dict) or "add" not in step or step.keys() - {"add", "remove"}:
            raise CatalogError("Capacity order steps require add and may specify remove")
        for ids in step.values():
            if (not isinstance(ids, list) or any(not isinstance(rid, str) for rid in ids)
                    or len(ids) != len(set(ids))):
                raise CatalogError("Capacity order steps require lists of unique collection IDs")
    additions = []
    for step in order:
        choices = {}
        for choice in step["add"]:
            rid, separator, name = choice.partition("=")
            if rid in choices:
                raise CatalogError(f"{rid}: capacity order adds two editions in one step")
            choices[rid] = name if separator else PUBLISHED
        additions.append(choices)

    by_id = {row["id"]: row for row in assets}
    core = policy.get("core")
    if not isinstance(core, dict) or core.keys() != FIELD_PRIORITY.keys():
        raise CatalogError("Capacity order requires a core for every planning field")
    for field, ids in core.items():
        if (not isinstance(ids, list) or not ids or any(
                not isinstance(aid, str) or aid not in by_id or
                by_id[aid]["selection"]["level"] > 1 or not attributed_bytes(by_id[aid]).get(field)
                for aid in ids) or len(ids) != len(set(ids))):
            raise CatalogError(f"{field}: capacity core requires distinct level 0 or 1 references")
    members = {}
    for identity, name in {pair for choices in additions for pair in choices.items()}:
        resource = resources.get(identity)
        if (not resource or resource.get("opt_in") or identity == READERS
                or resource["replaces_asset_ids"]):
            raise CatalogError(f"{identity}: capacity order requires a ready default collection")
        edition = resource if name == PUBLISHED else resource.get("editions", {}).get(name)
        if not edition or edition["status"] != "ready":
            raise CatalogError(f"{identity}={name}: capacity order requires a ready edition")
        rows = {aid: by_id[aid] for aid in edition["asset_ids"]}
        if (edition["target_bytes"] != sum(row["size_bytes"] for row in rows.values())
                or any("generation" in row or "selection" not in row for row in rows.values())):
            raise CatalogError(f"{identity}={name}: capacity order requires exact downloads")
        members[identity, name] = rows

    def selected_assets(choices):
        collections = [members[pair] for pair in choices.items()]
        rows = {aid: row for collection in collections for aid, row in collection.items()}
        if len(rows) != sum(map(len, collections)):
            raise CatalogError("Capacity order includes overlapping collections")
        return rows

    mandatory = {row["id"] for row in assets if row["utility_tier"] == "CRITICAL"}
    for resource in resources.values():
        if resource.get("default_sampler"):
            mandatory.update(resource["asset_ids"])
    # A collection is persistent from its last entry. Previous appearances
    # remain in the filler table until an eligible archive replaces them.
    last_removal = {rid: index for index, step in enumerate(order) for rid in step.get("remove", [])}
    active = {}
    selected = {}
    fields = Counter()
    peaks = Counter()
    history = []
    capacities = []
    transitions = []
    filler_steps = []
    placements = sorted(last_removal)
    for index, (step, added) in enumerate(zip(order, additions, strict=True)):
        removed = set(step.get("remove", []))
        if not added or not removed <= active.keys() or removed & added.keys():
            raise CatalogError(f"Invalid capacity order step {index + 1}")
        if any(resources[rid].get("editions") for rid in removed):
            raise CatalogError(f"Capacity order step {index + 1} removes an edition group")
        edition_replacements = set()
        for rid in added.keys() & active.keys():
            before = members[rid, active[rid]]
            after = members[rid, added[rid]]
            _, previous_shares = _totals(before)
            _, shares = _totals(after)
            if shares.total() <= previous_shares.total() or previous_shares - shares:
                raise CatalogError(f"{rid}={added[rid]}: edition upgrade must increase knowledge bytes "
                                   "and retain every field's attributed bytes")
            edition_replacements.update(before.keys() - after.keys())
        for rid in removed:
            del active[rid]
        active.update(added)
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
        _validate_transition(capacity, selected, current, fields, next_fields, edition_replacements, peaks, core)
        peaks |= next_fields
        fields, selected = next_fields, current
        capacities.append(capacity)
        history.append(tiers)
        transitions.extend([capacity, rid, added[rid]] for rid in sorted(added)
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
        "field_core": core,
        "expansion": list(_expansion(assets, resources, active, selected)),
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
    for threshold, resource in ladder.get("expansion", ()):
        if threshold > capacity_bytes:
            break
        core[resource] = PUBLISHED
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
