"""Compile a monotone capacity ladder and resolve default collection editions."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from .catalog import CatalogError, is_document

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


# Fill plans are compiled for quarter-GB intervals. Storage is rounded up only
# during the subset search. Catalog bytes decide the final fit and retention.
STEP = GB // 4
QUANTUM = 5_000_000
LARGE_ARCHIVE = 64 * GB
PUBLISHED = "published"
PRACTICAL_DOMAINS = frozenset({
    "health", "water-sanitation", "food-preservation", "agriculture", "shelter",
    "navigation", "repair", "hand-tools", "school-math", "school-science",
})


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


@dataclass(frozen=True)
class Edition:
    resource: str
    name: str
    size: int
    knowledge: int
    tier: str
    depth: tuple[int, int]
    practical: bool


def _editions(assets, resources):
    by_id = {asset["id"]: asset for asset in assets}
    groups = {}
    seen = set()
    for rid, resource in sorted(resources.items()):
        if rid == READERS or resource.get("opt_in"):
            continue
        if resource["replaces_asset_ids"]:
            raise CatalogError(f"{rid}: default collections cannot replace files across collections")
        editions = []
        members = set()
        prior_levels = {}
        for name, edition in sorted({PUBLISHED: resource, **resource["editions"]}.items(),
                                    key=lambda item: item[1]["target_bytes"]):
            if edition["status"] != "ready":
                continue
            rows = [by_id[aid] for aid in edition["asset_ids"]]
            if not rows or any("selection" not in row for row in rows):
                raise CatalogError(f"{rid}: default files require planning metadata")
            size = sum(row["size_bytes"] for row in rows)
            if (edition["target_bytes"] != size or any("generation" in row for row in rows)
                    or editions and editions[-1].size >= size):
                raise CatalogError(f"{rid}: default editions must be exact downloads of increasing size")
            tier = resource["utility_tier"]
            levels = {}
            for row in rows:
                data = row["selection"]
                for domain in attributed_bytes(row):
                    levels[domain] = max(data["level"], levels.get(domain, -1))
                if row["utility_tier"] != tier:
                    raise CatalogError(f"{rid}: default collections require a single tier")
            if any(levels.get(domain, -1) < level for domain, level in prior_levels.items()):
                raise CatalogError(f"{rid}: a larger edition cannot lower domain depth")
            prior_levels = levels
            depth = max(row["selection"]["level"] for row in rows)
            rank = min(row["selection"]["rank"] for row in rows if row["selection"]["level"] == depth)
            editions.append(Edition(rid, name, size, sum(row["size_bytes"] for row in rows if is_knowledge(row)),
                                    tier, (depth, rank),
                                    sum(row["size_bytes"] for row in rows
                                        if row["selection"]["domain"] in PRACTICAL_DOMAINS) * 2 >= size))
            members.update(edition["asset_ids"])
        if seen & members:
            raise CatalogError(f"{rid}: default collections must have unique files")
        seen.update(members)
        if editions:
            if len(editions) > 1 and editions[0].tier == "CRITICAL":
                raise CatalogError(f"{rid}: critical defaults cannot have alternate editions")
            groups[rid] = editions
    if any(row["utility_tier"] == "CRITICAL" and row["id"] not in seen for row in assets):
        raise CatalogError("The default collections omit critical assets")
    return groups


def _bytes(editions):
    return sum(item.size for item in editions)


class Subsets:
    """Index fitting subsets of one tier and reconstruct a chosen byte sum."""

    def __init__(self, items):
        self.items = [(item, (item.size + QUANTUM - 1) // QUANTUM) for item in items]
        self.rounding_loss = sum(cost * QUANTUM - item.knowledge for item, cost in self.items)
        self.suffix = [1] * (len(self.items) + 1)
        for index in reversed(range(len(self.items))):
            tail = self.suffix[index + 1]
            self.suffix[index] = tail | (tail << self.items[index][1])

    @staticmethod
    def closest(bits, limit):
        if limit < 0:
            return -1
        if bits.bit_length() <= limit + 1:
            return bits.bit_length() - 1
        return (bits & ((1 << (limit + 1)) - 1)).bit_length() - 1

    def recover(self, units):
        result = []
        for index, (item, cost) in enumerate(self.items):
            if units >= cost and (self.suffix[index + 1] >> (units - cost)) & 1:
                result.append(item)
                units -= cost
        return result


def _priority(item):
    return (*item.depth, item.size, item.resource)


def _full_plan(largest, samplers):
    """Keep practical collections and use remaining space for enrichment."""
    core = [item for item in largest if item.tier != "NONESSENTIAL" or item.resource in samplers]
    spare = usable_capacity(DEFAULT_LIMIT) - _bytes(core)
    if spare < 0:
        raise CatalogError("The full library's practical collections exceed its capacity")
    enrichment = Subsets(sorted((item for item in largest if item.tier == "NONESSENTIAL"
                                 and item.resource not in samplers),
                                key=lambda item: (not item.practical, *_priority(item))))
    return core + enrichment.recover(enrichment.closest(enrichment.suffix[0], spare // QUANTUM))


def _fill_for(core, fillers, limit, minimum, full_useful, full_nonessential):
    core_size = _bytes(core)
    if core_size > limit:
        return None
    by_tier = defaultdict(int)
    for item in core:
        by_tier[item.tier] += item.knowledge
    useful, nonessential = fillers
    budget = (limit - core_size) // QUANTUM
    # Start with the highest useful subtotal. Allow only enough nonessential
    # content to fit and to keep its full-plan retention below useful retention.
    reachable = useful.suffix[0]
    units = useful.closest(reachable, budget)
    target = max(minimum, limit * 985 // 1000)
    best = None
    best_bytes = minimum - 1
    base = sum(by_tier.values())
    while units >= 0 and base + units * QUANTUM + (
            nonessential.suffix[0].bit_length() - 1) * QUANTUM >= best_bytes:
        useful_floor = by_tier["USEFUL"] + max(0, units * QUANTUM - useful.rounding_loss)
        other_budget = (useful_floor * full_nonessential // full_useful - by_tier["NONESSENTIAL"]) // QUANTUM
        other = nonessential.closest(nonessential.suffix[0], min(budget - units, other_budget))
        if other >= 0 and base + (units + other) * QUANTUM > best_bytes:
            pack = [*useful.recover(units), *nonessential.recover(other)]
            retained = base + sum(item.knowledge for item in pack)
            if retained > best_bytes:
                best, best_bytes = pack, retained
                if retained >= target:
                    break
        units = useful.closest(reachable, units - 1)
    return best


def compile_ladder(assets: list[dict], resources: dict[str, dict]) -> dict:
    """Compile persistent collection upgrades and replaceable filler plans."""
    groups = _editions(assets, resources)
    largest = [editions[-1] for editions in groups.values()]
    samplers = {rid for rid, row in resources.items() if row.get("default_sampler")}
    full = _full_plan(largest, samplers)
    full_set = set(full)
    full_useful = sum(item.knowledge for item in full if item.tier == "USEFUL")
    full_nonessential = sum(item.knowledge for item in full if item.tier == "NONESSENTIAL")
    if not full_useful or not full_nonessential:
        raise CatalogError("The full library requires both USEFUL and NONESSENTIAL content")

    core = {item.resource: item for item in sorted(full, key=_priority)
            if item.tier == "CRITICAL" or item.tier == "USEFUL" and item.depth[0] == 0
            or item.resource in samplers}
    upgrades = [item for editions in groups.values() if len(editions) > 1 and editions[0].tier == "USEFUL"
                for item in editions
                if item != core.get(item.resource)]
    big = [item for item in full if item.tier == "USEFUL" and item.size >= LARGE_ARCHIVE
           and len(groups[item.resource]) == 1]
    remaining = [item for item in full if item.tier == "USEFUL" and item.resource not in core
                 and len(groups[item.resource]) == 1 and item not in big]
    pending = [*upgrades, *sorted(big, key=lambda item: item.size), *sorted(remaining, key=_priority)]
    cursor = 0
    checkpoints = [gb * GB for gb in CAPACITY_GRID_GB]
    transitions = [[MIN_CAPACITY, item.resource, item.name] for item in core.values()]
    filler_steps = []
    by_id = {asset["id"]: asset for asset in assets}

    def edition_assets(item):
        resource = resources[item.resource]
        edition = resource if item.name == PUBLISHED else resource["editions"][item.name]
        return [by_id[aid] for aid in edition["asset_ids"]]

    members = {item: edition_assets(item) for editions in groups.values() for item in editions}
    member_ids = {item: {row["id"] for row in rows} for item, rows in members.items()}
    shares = {}
    for item, rows in members.items():
        shares[item] = Counter()
        for row in rows:
            shares[item].update(attributed_bytes(row))
    balance = DomainRetention(row for item in full for row in members[item])

    @lru_cache(maxsize=48)
    def subset_index(available):
        options = [groups[rid][0] for rid in available]
        ordered = sorted(options, key=lambda item: (item not in full_set, *_priority(item)))
        return tuple(Subsets([item for item in ordered if item.tier == tier])
                     for tier in ("USEFUL", "NONESSENTIAL"))

    def pack(capacity, fixed, *, through=None):
        limit = usable_capacity(capacity)
        if through is None:
            through = min(DEFAULT_LIMIT, capacity + STEP - 1)
        elif capacity < through:
            # The two matched margins grow at the same byte boundary.
            # Only the first increment can dip below the left endpoint.
            limit = min(limit, usable_capacity(capacity + 1))
        minimum = (9 * through + 9) // 10
        if capacity in checkpoints:
            minimum = max(minimum, (97 * limit + 99) // 100)
        if _bytes(fixed.values()) > limit:
            return None
        available = frozenset(groups.keys() - fixed.keys())
        return _fill_for(fixed.values(), subset_index(available), limit, minimum, full_useful, full_nonessential)

    def plan(capacity, core, *, balanced=False, through=None):
        fixed_domains = Counter()
        fixed_ids = set()
        if balanced or capacity in checkpoints:
            for item in core.values():
                fixed_domains.update(shares[item])
                fixed_ids.update(member_ids[item])
        if balanced:
            spare = usable_capacity(capacity) - _bytes(core.values())
            if spare < 0:
                return None
            potential = fixed_domains.copy()
            for rid, editions in groups.items():
                item = editions[0]
                if rid not in core and item.size <= spare:
                    potential.update(shares[item])
            for domain, reference in balance.full.items():
                if (reference >= GB and 30 * balance.total * potential[domain] < 9 * capacity * reference
                        and not any(10 * row["size_bytes"] > capacity and row["id"] not in fixed_ids
                                    for row in balance.candidates[domain])):
                    return None
        filler = pack(capacity, core, through=through)
        if filler is None or (not balanced and capacity not in checkpoints):
            return filler

        def deficits(items):
            domains, ids = fixed_domains.copy(), fixed_ids.copy()
            for item in items:
                if item.resource not in core:
                    domains.update(shares[item])
                    ids.update(member_ids[item])
            return {d: missing for d, missing, _, exempt in balance.gaps_from_totals(domains, ids, capacity)
                    if not exempt}

        gaps = deficits([*core.values(), *filler])
        if not gaps:
            return filler
        # At the grid, try forcing a few collections with coverage that the
        # two-tier subset search missed. Keep several alternatives because a
        # collection can close one gap and make a second field harder to fill.
        frontier = [(core, gaps)]
        visited = set()
        for _ in range(12):
            candidates = []
            for fixed, missing in frontier:
                options = [editions[0] for rid, editions in groups.items() if rid not in fixed
                           and shares[editions[0]].keys() & missing.keys()]
                for item in options:
                    proposed = {**fixed, item.resource: item}
                    key = frozenset(proposed)
                    if key in visited:
                        continue
                    visited.add(key)
                    result = pack(capacity, proposed, through=through)
                    if result is None:
                        continue
                    gaps = deficits([*proposed.values(), *result])
                    if not gaps:
                        return [row for rid, row in proposed.items() if rid not in core] + result
                    candidates.append((proposed, gaps))
            if not candidates:
                return None
            candidates.sort(key=lambda row: (sum(row[1][d] / balance.full[d] for d in row[1]), len(row[1]),
                                              _bytes(row[0].values()), tuple(sorted(row[0]))))
            frontier = candidates[:6]
        return None

    @lru_cache
    def fits_checkpoint(capacity, items):
        return plan(capacity, {item.resource: item for item in items}) is not None

    def record_filler(capacity, filler):
        current = sorted([item.resource, item.name] for item in filler)
        if not filler_steps or filler_steps[-1][1] != current:
            filler_steps.append([capacity, current])

    def first_upgrade_capacity(capacity, proposed, balanced_filler=None):
        # The prior interval has a valid plan; find the first byte in it where
        # the newer edition can already fit and meet fill until the next step.
        start = max(capacity - STEP + 1, transitions[-1][0] + 1)
        end = capacity
        while start < end:
            middle = (start + end) // 2
            if balanced_filler is None:
                fits = pack(middle, proposed, through=capacity - 1) is not None
            else:
                # Test the chosen domain-balanced pack while refining its
                # byte threshold. Its domain and tier ratios stay the same.
                items = [*proposed.values(), *balanced_filler]
                fits = (_bytes(items) <= min(usable_capacity(middle), usable_capacity(middle + 1))
                        and 10 * sum(item.knowledge for item in items) >= 9 * (capacity - 1))
            if not fits:
                start = middle + 1
            else:
                end = middle
        return start

    for capacity in range(MIN_CAPACITY, DEFAULT_LIMIT, STEP):
        filler = None
        while cursor < len(pending):
            resource = pending[cursor].resource
            alternatives = [item for item in groups[resource] if item.size >= pending[cursor].size]
            following = checkpoints[bisect_right(checkpoints, capacity)]
            for item in reversed(alternatives):
                proposed = {**core, resource: item}
                final_edition = len(groups[resource]) > 1 and item == groups[resource][-1]
                advance = plan(capacity, proposed, balanced=final_edition)
                if advance is None:
                    continue
                if following != DEFAULT_LIMIT and not any(
                    fits_checkpoint(following, tuple({**proposed, resource: later}.values()))
                    for later in alternatives if later.size >= item.size
                ):
                    continue
                threshold = capacity
                if resource in core and capacity > MIN_CAPACITY:
                    threshold = min(capacity, first_upgrade_capacity(
                        capacity, proposed, advance if final_edition else None))
                    if threshold < capacity:
                        early_filler = advance if final_edition else pack(threshold, proposed, through=capacity - 1)
                        record_filler(threshold, early_filler)
                filler, core = advance, proposed
                transitions.append([threshold, resource, item.name])
                cursor = pending.index(item, cursor) + 1
                break
            else:
                break
        if filler is None:
            filler = plan(capacity, core)
        if filler is None:
            raise CatalogError(f"No tier-prioritized fill at {capacity / GB:g} GB")
        record_filler(capacity, filler)
    if not set(core.values()) <= full_set:
        raise CatalogError("The full recommendation must preserve all persistent collections")
    filler_steps.append([DEFAULT_LIMIT, sorted([item.resource, item.name] for item in full
                                               if item.resource not in core)])
    placements = sorted({tuple(item) for _, pack in filler_steps for item in pack})
    position = {item: index for index, item in enumerate(placements)}
    return {
        "schema_version": 2,
        "transitions": transitions,
        "filler_placements": [list(item) for item in placements],
        "fillers": [[capacity, [position[tuple(item)] for item in plan]] for capacity, plan in filler_steps],
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
