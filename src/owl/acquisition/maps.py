"""Metadata-only map selection with explicit coverage and capacity failures.

Coverage is proved against caller-supplied state polygons, not guessed from state
names or product counts. Footprints are WGS84 rectangles from publisher metadata.
No map body is downloaded, rasterized or synthesized here.
"""
from __future__ import annotations

import math
import warnings


NEW_ENGLAND = ("CT", "MA", "ME", "NH", "RI", "VT")
ALLOWANCES = {"compact-256gb": 10_000_000_000, "standard-512gb": 30_000_000_000,
              "full-1tb": 30_000_000_000}
# Never discard a positive-area coastal/island gap as floating-point tolerance.
EPS = 0


class MapError(ValueError):
    pass


def _bbox(value):
    if isinstance(value, dict):
        value = [value.get(key) for key in ("minX", "minY", "maxX", "maxY")]
    if (not isinstance(value, (list, tuple)) or len(value) != 4 or
            any(type(n) not in {int, float} or not math.isfinite(n) for n in value)):
        raise MapError("Map footprint needs four finite coordinates")
    west, south, east, north = value
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        raise MapError("Invalid or antimeridian-crossing map footprint")
    return tuple(float(n) for n in value)


def _merge(intervals):
    result = []
    for left, right in sorted(intervals):
        if right - left <= EPS:
            continue
        if result and left <= result[-1][1] + EPS:
            result[-1][1] = max(result[-1][1], right)
        else:
            result.append([left, right])
    return result


def _subtract(wanted, covered):
    result = []
    for left, right in wanted:
        cursor = left
        for a, b in covered:
            if b <= cursor or a >= right:
                continue
            if a > cursor + EPS:
                result.append([cursor, min(a, right)])
            cursor = max(cursor, b)
            if cursor >= right:
                break
        if cursor < right - EPS:
            result.append([cursor, right])
    return result


def _polygons(geometry):
    if not isinstance(geometry, dict):
        raise MapError("Coverage requires authoritative Polygon/MultiPolygon geometry")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else None
    if not isinstance(polygons, list) or not polygons:
        raise MapError("Coverage requires nonempty Polygon/MultiPolygon geometry")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise MapError("Empty polygon")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise MapError("Polygon rings must be explicitly closed")
            for point in ring:
                if (not isinstance(point, (list, tuple)) or len(point) < 2 or
                        any(type(n) not in {int, float} or not math.isfinite(n) for n in point[:2]) or
                        not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise MapError("Invalid polygon coordinate")
    return polygons


def _ring_slice(ring, y):
    intersections = []
    for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:]):
        if min(y1, y2) <= y < max(y1, y2):
            intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    intersections.sort()
    if len(intersections) % 2:
        raise MapError("Invalid polygon intersection")
    return [[intersections[i], intersections[i + 1]] for i in range(0, len(intersections), 2)]


def coverage_holes(geometry: dict, footprints: list, *, max_strips: int = 100_000) -> list[dict]:
    """Find every uncovered positive-area strip, including polygon holes/islands.

Sweep at polygon vertices, sheet edges and polygon/sheet-edge intersections.
Between these events all boundaries are linear, so a midpoint tests the entire
strip's topology; this is not a coarse sampling grid that can overlook a gap.
The report's x bounds are its middle slice, not a claimed rectangular hole.
"""
    polygons, rectangles = _polygons(geometry), [_bbox(box) for box in footprints]
    rings = [ring for polygon in polygons for ring in polygon]
    # Detailed real state coastlines have thousands of vertices. Use a robust
    # geometry library for these; the bounded reference sweep below keeps tiny
    # fixtures and installations without the optional dependency usable.
    if sum(len(ring) for ring in rings) > 250 or len(rectangles) > 250:
        try:
            from shapely.geometry import box, shape
            from shapely.ops import unary_union
        except ImportError as error:
            raise MapError("Detailed map coverage requires the optional Shapely dependency") from error
        target = shape(geometry)
        if not target.is_valid:
            raise MapError("Invalid authoritative boundary geometry")
        # GEOS operations can leave a NumPy floating-point warning flag on
        # otherwise valid results. Inspect the resulting geometry explicitly;
        # never accept a NaN/invalid difference or a GEOS exception.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            missing = target.difference(unary_union([box(*bounds) for bounds in rectangles]))
        if not missing.is_valid or not math.isfinite(missing.area):
            raise MapError("Geometry difference is invalid; coverage is unverified")
        pieces = list(missing.geoms) if hasattr(missing, "geoms") else [missing]
        return [{"bbox": list(piece.bounds), "area_square_degrees": piece.area}
                for piece in sorted(pieces, key=lambda item: item.bounds) if not piece.is_empty and piece.area > EPS]
    ys = {point[1] for ring in rings for point in ring}
    xs = {x for west, _, east, _ in rectangles for x in (west, east)}
    min_y, max_y = min(ys), max(ys)
    ys.update(y for _, south, _, north in rectangles for y in (south, north) if min_y < y < max_y)
    for ring in rings:
        for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:]):
            if x1 != x2 and y1 != y2:
                for x in xs:
                    if min(x1, x2) < x < max(x1, x2):
                        ys.add(y1 + (x - x1) * (y2 - y1) / (x2 - x1))
    if len(ys) > max_strips:
        raise MapError("Coverage geometry exceeds sweep budget")
    ys = sorted(ys)
    holes = []
    for south, north in zip(ys, ys[1:]):
        if north - south <= EPS:
            continue
        y = (south + north) / 2
        wanted = []
        for polygon in polygons:
            exterior = _ring_slice(polygon[0], y)
            interior = _merge([span for ring in polygon[1:] for span in _ring_slice(ring, y)])
            wanted.extend(_subtract(exterior, interior))
        covered = _merge([[west, east] for west, low, east, high in rectangles if low <= y < high])
        for west, east in _subtract(_merge(wanted), covered):
            holes.append({"south": south, "north": north, "midpoint_west": west,
                          "midpoint_east": east, "area_square_degrees": (east - west) * (north - south)})
    return holes


def _intersects(geometry, footprint):
    """Positive-area intersection, so offshore/neighboring filler is excluded."""
    polygons = _polygons(geometry)
    points = [point for polygon in polygons for ring in polygon for point in ring]
    west, south, east, north = _bbox(footprint)
    if (max(p[0] for p in points) <= west or min(p[0] for p in points) >= east or
            max(p[1] for p in points) <= south or min(p[1] for p in points) >= north):
        return False
    if len(points) > 250:
        try:
            from shapely.geometry import box, shape
        except ImportError as error:
            raise MapError("Detailed map coverage requires the optional Shapely dependency") from error
        target = shape(geometry)
        if not target.is_valid:
            raise MapError("Invalid authoritative boundary geometry")
        return target.intersection(box(west, south, east, north)).area > EPS
    ys = {south, north}
    for polygon in polygons:
        for ring in polygon:
            ys.update(p[1] for p in ring if south < p[1] < north)
            for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:]):
                if x1 != x2:
                    for x in (west, east):
                        if min(x1, x2) < x < max(x1, x2):
                            y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
                            if south < y < north:
                                ys.add(y)
    ys = sorted(ys)
    for bottom, top in zip(ys, ys[1:]):
        y = (bottom + top) / 2
        for polygon in polygons:
            spans = _subtract(_ring_slice(polygon[0], y), _merge([
                span for ring in polygon[1:] for span in _ring_slice(ring, y)]))
            if any(min(right, east) - max(left, west) > EPS for left, right in spans):
                return True
    return False


def _intersector(geometry):
    polygons = _polygons(geometry)
    if sum(len(ring) for polygon in polygons for ring in polygon) <= 250:
        return lambda footprint: _intersects(geometry, footprint)
    try:
        from shapely.geometry import box, shape
        from shapely.prepared import prep
    except ImportError as error:
        raise MapError("Detailed map coverage requires the optional Shapely dependency") from error
    target = shape(geometry)
    if not target.is_valid or not math.isfinite(target.area):
        raise MapError("Invalid authoritative boundary geometry")
    prepared = prep(target)

    def intersects(footprint):
        rectangle = box(*_bbox(footprint))
        # Interior-interior relation avoids constructing thousands of clipped
        # coastlines and excludes sheets which merely touch the state boundary.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return bool(prepared.intersects(rectangle) and target.relate_pattern(rectangle, "T********"))
    return intersects


def select_maps(candidates: list[dict], regions: dict, budget_bytes: int, *,
                overview: list[dict] | None = None, states=NEW_ENGLAND) -> dict:
    """Choose the finest *complete* same-scale set fitting its full allowance.

Latest edition wins for each (scale, stable sheet ID). No selection is returned
as complete when metadata, state geometry, overview or geographic coverage is
missing. Incomplete fine maps never hide gaps behind a count/byte target.
"""
    if type(budget_bytes) is not int or budget_bytes < 1:
        raise MapError("Map allowance must be a positive integer")
    missing = sorted(set(states) - regions.keys())
    if missing:
        return {"selected": [], "complete": False, "blockers": ["Missing state boundaries: " + ", ".join(missing)],
                "holes": {}, "budget_bytes": budget_bytes}
    intersections = [_intersector(regions[state]) for state in states]
    latest = {}
    for row in candidates:
        if (not row.get("sheet_id") or type(row.get("scale")) is not int or row["scale"] < 1 or
                type(row.get("size_bytes")) is not int or row["size_bytes"] < 1 or
                not row.get("edition") or not row.get("source_url")):
            raise MapError("Map candidate lacks stable sheet/scale/edition/bytes/source metadata")
        _bbox(row.get("bbox"))
        key = (row["scale"], row["sheet_id"])
        if key not in latest or (str(row["edition"]), row["source_url"]) > (str(latest[key]["edition"]), latest[key]["source_url"]):
            latest[key] = row
    latest = {key: row for key, row in latest.items() if any(intersects(row["bbox"]) for intersects in intersections)}
    overview = overview or []
    overview_bytes = 0
    for row in overview:
        if type(row.get("size_bytes")) is not int or row["size_bytes"] < 1 or not row.get("source_url"):
            raise MapError("Overview lacks exact source/size metadata")
        overview_bytes += row["size_bytes"]
    attempts = []
    for scale in sorted({key[0] for key in latest}):
        sheets = sorted((row for (denominator, _), row in latest.items() if denominator == scale),
                        key=lambda row: row["sheet_id"])
        footprints = [row["bbox"] for row in sheets]
        holes = {state: coverage_holes(regions[state], footprints) for state in states}
        holes = {state: gaps for state, gaps in holes.items() if gaps}
        total = overview_bytes + sum(row["size_bytes"] for row in sheets)
        attempts.append({"scale": scale, "size_bytes": total, "holes": holes,
                         "fits": total <= budget_bytes})
        if not holes and total <= budget_bytes and overview:
            return {"selected": [*overview, *sheets], "complete": True, "blockers": [], "holes": {},
                    "scale": scale, "size_bytes": total, "budget_bytes": budget_bytes, "attempts": attempts}
    blockers = []
    if not overview:
        blockers.append("USA overview has not been selected and pinned")
    if not attempts:
        blockers.append("No fully described map sheets")
    elif not any(not trial["holes"] for trial in attempts):
        blockers.append("Every available scale has uncovered New England areas")
    elif not any(not trial["holes"] and trial["fits"] for trial in attempts):
        blockers.append("Complete geographic coverage exceeds allowance at every available scale")
    return {"selected": [], "complete": False, "blockers": blockers, "budget_bytes": budget_bytes,
            "holes": attempts[0]["holes"] if attempts else {}, "attempts": attempts}


def exclude_offshore_water(regions: dict, features: list[dict]) -> tuple[dict, list[dict]]:
    """Subtract explicitly evidenced ocean polygons, retaining islands and holes.

    Census state outlines include territorial water. Only publisher polygons
    classified as ocean/sea (H2053), with zero land, may be excluded here. This
    never buffers, simplifies, or tolerates a geographic hole.
    """
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
    except ImportError as error:
        raise MapError("Water exclusions require the optional Shapely dependency") from error
    waters, evidence = [], []
    for feature in features:
        props = feature.get("properties", {})
        if (props.get("MTFCC") != "H2053" or type(props.get("AREALAND")) is not int or props["AREALAND"] != 0 or
                type(props.get("AREAWATER")) is not int or props["AREAWATER"] <= 0 or
                not props.get("NAME")):
            raise MapError("Water exclusion is not an authoritative zero-land ocean polygon")
        _polygons(feature.get("geometry"))
        water = shape(feature["geometry"])
        if not water.is_valid or not math.isfinite(water.area):
            raise MapError("Invalid ocean exclusion geometry")
        waters.append(water)
        evidence.append(dict(props))
    if not waters:
        raise MapError("Empty offshore-water exclusion metadata")
    mask = unary_union(waters)
    result = {}
    for state, geometry in regions.items():
        _polygons(geometry)
        target = shape(geometry)
        if not target.is_valid:
            raise MapError("Invalid authoritative boundary geometry")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            land = target.difference(mask)
        if land.is_empty or not land.is_valid or not math.isfinite(land.area):
            raise MapError("Water exclusion removed/invalidated the state target")
        # JSON-normalize tuples so the same polygon validator handles this result.
        import json
        result[state] = json.loads(json.dumps(mapping(land)))
    return result, evidence


def select_required_scale(candidates: list[dict], regions: dict, budget_bytes: int, *,
                          scale: int, gap_scales=(), overview=None, states=NEW_ENGLAND) -> dict:
    """Freeze every relevant latest sheet at an explicitly required scale.

    Budget pressure never removes a required-scale sheet. Explicitly permitted
    coarser supplements can close footprint gaps while the fine-scale gaps remain
    visible and prevent complete status.
    """
    if type(scale) is not int or scale < 1:
        raise MapError("Required map scale must be a positive integer")
    validated = select_maps(candidates, regions, budget_bytes, overview=overview, states=states)
    if set(states) - regions.keys():
        return validated
    intersects = [_intersector(regions[state]) for state in states]
    latest = {}
    for row in candidates:
        if row["scale"] != scale:
            continue
        key = row["sheet_id"]
        if key not in latest or (str(row["edition"]), row["source_url"]) > (str(latest[key]["edition"]), latest[key]["source_url"]):
            latest[key] = row
    sheets = sorted((row for row in latest.values() if any(test(row["bbox"]) for test in intersects)),
                    key=lambda row: row["sheet_id"])
    fine_holes = {state: coverage_holes(regions[state], [row["bbox"] for row in sheets]) for state in states}
    fine_holes = {state: gaps for state, gaps in fine_holes.items() if gaps}
    supplements = []
    if gap_scales:
        if any(type(value) is not int or value <= scale for value in gap_scales):
            raise MapError("Gap supplement scales must be explicitly coarser than required scale")
        try:
            from shapely.geometry import box, shape
            from shapely.ops import unary_union
        except ImportError as error:
            raise MapError("Gap supplements require the optional Shapely dependency") from error
        latest_supplements = {}
        for row in candidates:
            if row["scale"] not in gap_scales:
                continue
            key = (row["scale"], row["sheet_id"])
            if key not in latest_supplements or (str(row["edition"]), row["source_url"]) > (str(latest_supplements[key]["edition"]), latest_supplements[key]["source_url"]):
                latest_supplements[key] = row
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            target = unary_union([shape(regions[state]) for state in states])
            gaps = target.difference(unary_union([box(*row["bbox"]) for row in sheets]))
            for _, row in sorted(latest_supplements.items()):
                rectangle = box(*row["bbox"])
                if gaps.relate_pattern(rectangle, "T********"):
                    supplements.append(row)
                    gaps = gaps.difference(rectangle)
                if not gaps.is_valid or not math.isfinite(gaps.area):
                    raise MapError("Required-scale gap geometry is invalid")
    proposal = [*sheets, *supplements]
    holes = {state: coverage_holes(regions[state], [row["bbox"] for row in proposal]) for state in states}
    holes = {state: gaps for state, gaps in holes.items() if gaps}
    total = sum(row["size_bytes"] for row in [*(overview or []), *proposal])
    geographic_complete = bool(sheets) and not holes
    blockers = []
    if fine_holes:
        blockers.append("Required scale has uncovered geographic areas")
    if holes:
        blockers.append("Explicit gap supplements do not complete geographic coverage")
    if total > budget_bytes:
        blockers.append("Complete required-scale sheet list exceeds allowance; no sheets were omitted")
    if not overview:
        blockers.append("USA overview has not been selected and pinned")
    complete = geographic_complete and not fine_holes and total <= budget_bytes and bool(overview)
    return {"selected": [*(overview or []), *proposal] if complete else [], "proposed_sheets": proposal,
            "geographic_complete": geographic_complete, "complete": complete, "blockers": blockers,
            "holes": holes, "required_scale_holes": fine_holes, "required_scale_complete": not fine_holes,
            "base_scale": scale, "scales": sorted({row["scale"] for row in proposal}), "size_bytes": total,
            "budget_bytes": budget_bytes, "attempts": [{"base_scale": scale, "size_bytes": total,
                "base_sheet_count": len(sheets), "supplement_count": len(supplements), "holes": holes,
                "fits": total <= budget_bytes}]}


def select_mixed_maps(candidates: list[dict], regions: dict, budget_bytes: int, *,
                      overview: list[dict] | None = None, states=NEW_ENGLAND) -> dict:
    """Complete a base scale with finer sheets at exact gaps, without truncation.

    The finest complete base-scale proposal that fits wins. All latest sheets
    at that base scale are kept; only finer sheets intersecting its actual gaps
    supplement it. Every uncovered area and the scale mixture remain explicit.
    A proposal is not an accepted content pin or a review approval.
    """
    try:
        from shapely.geometry import box, shape
        from shapely.ops import unary_union
    except ImportError as error:
        raise MapError("Mixed-scale map selection requires the optional Shapely dependency") from error
    # Reuse candidate/geometry/allowance validation before constructing differences.
    base = select_maps(candidates, regions, budget_bytes, overview=overview, states=states)
    if sorted(set(states) - regions.keys()):
        return base
    targets = [shape(regions[state]) for state in states]
    target = unary_union(targets)
    latest = {}
    for row in candidates:
        key = (row["scale"], row["sheet_id"])
        if key not in latest or (str(row["edition"]), row["source_url"]) > (str(latest[key]["edition"]), latest[key]["source_url"]):
            latest[key] = row
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rows = sorted((row for row in latest.values() if target.relate_pattern(box(*row["bbox"]), "T********")),
                      key=lambda row: (row["scale"], row["sheet_id"], row["source_url"]))
    attempts = []
    for scale in sorted({row["scale"] for row in rows}):
        sheets = [row for row in rows if row["scale"] == scale]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            gaps = target.difference(unary_union([box(*row["bbox"]) for row in sheets]))
        additions = []
        for row in rows:
            if row["scale"] >= scale or gaps.is_empty:
                continue
            rectangle = box(*row["bbox"])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                intersects = gaps.relate_pattern(rectangle, "T********")
                if intersects:
                    additions.append(row)
                    gaps = gaps.difference(rectangle)
            if not gaps.is_valid or not math.isfinite(gaps.area):
                raise MapError("Mixed-scale geometry difference is invalid")
        proposal = [*sheets, *additions]
        holes = {state: coverage_holes(regions[state], [row["bbox"] for row in proposal]) for state in states}
        holes = {state: gaps for state, gaps in holes.items() if gaps}
        total = sum(row["size_bytes"] for row in [*(overview or []), *proposal])
        attempts.append({"base_scale": scale, "size_bytes": total, "base_sheet_count": len(sheets),
                         "supplement_count": len(additions), "holes": holes, "fits": total <= budget_bytes})
        if not holes and total <= budget_bytes:
            blockers = [] if overview else ["USA overview has not been selected and pinned"]
            return {"selected": [*(overview or []), *proposal] if overview else [],
                    "proposed_sheets": proposal, "geographic_complete": True, "complete": bool(overview),
                    "blockers": blockers, "holes": {}, "base_scale": scale, "size_bytes": total,
                    "scales": sorted({row["scale"] for row in proposal}), "budget_bytes": budget_bytes,
                    "attempts": attempts}
    return {"selected": [], "proposed_sheets": [], "geographic_complete": False, "complete": False,
            "blockers": ["No complete mixed-scale coverage fits allowance"], "attempts": attempts,
            "budget_bytes": budget_bytes}
