"""Bounded publisher-metadata adapters. Discovery never acquires library bodies."""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit, unquote

from .maps import MapError, NEW_ENGLAND, exclude_offshore_water, select_maps, select_mixed_maps, select_required_scale


class ProviderError(ValueError):
    pass


class _Links(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.links, self.current, self.parts = [], None, []
        self.feed(body.decode("utf-8"))
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current, self.parts = dict(attrs).get("href"), []

    def handle_data(self, text):
        if self.current is not None:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current, re.sub(r"\s+", " ", "".join(self.parts)).strip()))
            self.current, self.parts = None, []


def _url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ProviderError("Discovery sources must be ordinary HTTPS URLs")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _sources(recipe):
    for raw in recipe.get("metadata_sources", []):
        row = {"url": raw} if isinstance(raw, str) else dict(raw)
        row["url"] = _url(row["url"])
        yield row


def _fetch(source, fetcher, url=None):
    return fetcher.fetch(url or source["url"], kind=source.get("kind", "metadata"))


def _result(recipe, candidates, blockers=None, **extra):
    return {"recipe_id": recipe["id"], "candidates": candidates,
            "blockers": list(dict.fromkeys([*recipe.get("blockers", []), *(blockers or [])])),
            "evidence": [], **extra}


def discover_hesperian(recipe, fetcher):
    selection = recipe.get("selection", {})
    edition = selection.get("edition", "2026")
    expected = selection.get("expected_filename", f"en_midw_{edition}_bm.pdf")
    candidates = {}
    for source in _sources(recipe):
        body = _fetch(source, fetcher)
        for href, title in _Links(body).links:
            url = urljoin(source["url"], href)
            if urlsplit(url).path.rsplit("/", 1)[-1] == expected and f"_{edition}_" in url:
                candidates[url] = {"source_url": _url(url), "title": title or expected,
                                   "edition": edition, "body_verified": False,
                                   "discovered_on": source["url"]}
    blockers = ["Same-edition back matter must be acquired and verified at build time"]
    if not candidates:
        blockers.append("Publisher listing contains no exact same-edition back-matter link")
    return _result(recipe, sorted(candidates.values(), key=lambda row: row["source_url"]), blockers)


def _title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def select_survivor(candidates, selection):
    """Freeze reviewed titles only; discovery/keyword matches are never approval."""
    approved = {row["source_url"]: row for row in selection.get("approved_titles", [])}
    excluded_urls = set(selection.get("excluded_urls", []))
    exclude = [re.compile(pattern, re.I) for pattern in selection.get("exclude_title_patterns", [])]
    by_url, rejected = {}, []
    for row in candidates:
        url = _url(row["source_url"])
        if url in excluded_urls or any(pattern.search(row["title"]) for pattern in exclude):
            rejected.append({"source_url": url, "reason": "Explicit source/title exclusion"})
            continue
        current = by_url.setdefault(url, dict(row, source_url=url, topics=[]))
        current["topics"] = sorted(set(current["topics"]) | set(row.get("topics", [])))
    selected, pending, title_urls = [], [], {}
    for url, row in sorted(by_url.items()):
        title_urls.setdefault(_title_key(row["title"]), []).append(url)
        decision = approved.get(url)
        if decision and decision.get("reviewed") is True and decision.get("topics"):
            selected.append(dict(row, topics=sorted(set(decision["topics"])), reviewed=True,
                                 review_evidence=decision.get("evidence", [])))
        else:
            pending.append(dict(row, reviewed=False))
    required = set(selection.get("required_topics", []))
    covered = {topic for row in selected for topic in row["topics"]}
    missing = sorted(required - covered)
    duplicates = [urls for urls in title_urls.values() if len(urls) > 1]
    # Different URLs with the same title need an explicit edition decision.
    selected_urls = {row["source_url"] for row in selected}
    unresolved_duplicates = [urls for urls in duplicates if len(set(urls) & selected_urls) > 1 and
                             not all(approved[url].get("complementary_reason") for url in urls if url in selected_urls)]
    return {"selected": selected, "pending": pending, "rejected": rejected,
            "missing_topics": missing, "possible_duplicate_editions": duplicates,
            "unresolved_duplicate_editions": unresolved_duplicates,
            "complete": bool(required) and not missing and not unresolved_duplicates and
                        bool(selected) and all(row["review_evidence"] for row in selected)}


class _SurvivorTable(HTMLParser):
    """Bind PDF links to the publisher's Title cell, never its PDF/size label."""
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.headers, self.cells, self.cell, self.rows = [], None, None, []
        self.feed(body.decode('utf-8')); self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.headers = []
        if tag == 'tr': self.cells = []
        if tag in {'td', 'th'} and self.cells is not None:
            self.cell = {'tag':tag, 'text':[], 'links':[]}
        if tag == 'a' and self.cell is not None and dict(attrs).get('href'):
            self.cell['links'].append(dict(attrs)['href'])

    def handle_data(self, text):
        if self.cell is not None: self.cell['text'].append(text)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.cell['text'] = re.sub(r'\s+', ' ', ''.join(self.cell['text'])).strip()
            self.cells.append(self.cell); self.cell = None
        if tag == 'tr' and self.cells is not None:
            if self.cells and all(c['tag']=='th' for c in self.cells):
                self.headers = [c['text'].casefold() for c in self.cells]
            elif 'title' in self.headers and len(self.cells)==len(self.headers):
                fields = dict(zip(self.headers, self.cells))
                title = fields['title']['text']
                if title:
                    for cell in self.cells:
                        for href in cell['links']:
                            if urlsplit(href).path.lower().endswith('.pdf'):
                                self.rows.append({'href':href, 'publisher_title':title,
                                    'title':re.sub(r'\s+', ' ', title.replace('_',' ')).strip(),
                                    'title_source':'publisher-table-title',
                                    'publisher_size_label':fields.get('size',{}).get('text'),
                                    'publisher_date_added':fields.get('dateadded',{}).get('text')})
            self.cells = None


def survivor_records(body):
    rows = _SurvivorTable(body).rows
    known = {r['href'] for r in rows}
    for href, title in _Links(body).links:
        if href in known or not urlsplit(href).path.lower().endswith('.pdf'):
            continue
        # Older category pages can expose a genuine title directly in a link.
        # Metadata-only labels cannot establish title/edition identity; preserve
        # an explicit filename-derived candidate for later source review.
        inferred = not title or re.fullmatch(r'(?:PDF\s*)?(?:[\d.,]+\s*[kmg]?b)?', title, re.I)
        rows.append({'href':href, 'title':unquote(urlsplit(href).path.rsplit('/',1)[-1]).removesuffix('.pdf').replace('_',' ') if inferred else title,
            'title_source':'filename-pending-review' if inferred else 'publisher-link-title'})
    return rows


def discover_survivor(recipe, fetcher):
    candidates = []
    for source in _sources(recipe):
        for row in survivor_records(_fetch(source, fetcher)):
            url = urljoin(source["url"], row['href'])
            if not urlsplit(url).path.lower().endswith(".pdf"):
                continue
            if urlsplit(url).hostname not in {"survivorlibrary.com", "www.survivorlibrary.com"}:
                continue
            candidates.append({**{k:v for k,v in row.items() if k!='href'}, "source_url": _url(url),
                               "topics": source.get("topics", []), "body_verified": False,
                               "discovered_on": source["url"]})
    discovered = {row["source_url"] for row in candidates}
    for known in recipe.get("selection", {}).get("approved_titles", []):
        if known["source_url"] not in discovered:
            candidates.append({"source_url": _url(known["source_url"]), "title": known["title"],
                               "topics": known["topics"], "body_verified": False,
                               "previous_review_evidence": known.get("evidence", []),
                               "discovered_on": "previous accepted catalog pin"})
    report = select_survivor(candidates, recipe.get("selection", {}))
    blockers = []
    if report["missing_topics"]:
        blockers.append("No reviewed title for: " + ", ".join(report["missing_topics"]))
    if report["unresolved_duplicate_editions"]:
        blockers.append("Selected duplicate editions need a complementary-content decision")
    return _result(recipe, candidates, blockers, selection_report=report)


def _map_row(item, source):
    box = item.get("boundingBox", item.get("bbox"))
    if isinstance(box, dict):
        box = [box.get(k) for k in ("minX", "minY", "maxX", "maxY")]
    title_scale = re.search(r"1\s*:\s*([\d,]+)\s*[- ]?scale", item.get("title", ""), re.I)
    scale = item.get("scale", int(title_scale[1].replace(",", "")) if title_scale else source.get("scale"))
    if isinstance(scale, str):
        match = re.fullmatch(r"(?:1\s*:\s*)?([\d,]+)", scale)
        scale = int(match[1].replace(",", "")) if match else None
    size = item.get("sizeInBytes", item.get("size_bytes"))
    if isinstance(size, str) and size.isdigit():
        size = int(size)
    url = item.get("downloadURL", item.get("source_url"))
    edition = item.get("publicationDate", item.get("dateCreated", item.get("edition")))
    identity = item.get("mapId", item.get("sheet_id"))
    if identity is None and isinstance(box, list) and len(box) == 4 and all(type(n) in {int, float} for n in box):
        identity = "bbox:" + ",".join(format(n, ".8g") for n in box)
    return {"sheet_id": identity, "title": item.get("title", identity), "scale": scale,
            "size_bytes": size, "edition": edition, "bbox": box,
            "source_url": _url(url) if url else None, "body_verified": False,
            "publisher_id": item.get("sourceId"), "discovered_on": source["url"]}


def _query(url, **updates):
    parsed = urlsplit(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update({key: str(value) for key, value in updates.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(sorted(params.items())), ""))


def discover_maps(recipe, fetcher):
    candidates, blockers, geometries = [], [], {}
    water_features, water_evidence = [], []
    inventory_complete = True
    selection = recipe.get("selection", {})
    overview_candidates = selection.get("overview_candidates", [])
    if not isinstance(overview_candidates, list):
        raise ProviderError("Pending overview candidates must be a list")
    seen_overviews = set()
    for row in overview_candidates:
        if (not isinstance(row, dict) or not row.get("id") or not row.get("source_url")
                or type(row.get("size_bytes")) is not int or row["size_bytes"] <= 0
                or type(row.get("scale")) is not int or row["scale"] <= 0
                or not row.get("version_date") or not row.get("candidate_manifest")
                or row.get("sha256") is not None or row.get("pin_status") != "pending"):
            raise ProviderError("Overview candidate needs exact metadata and an explicitly pending content pin")
        _url(row["source_url"])
        if row["source_url"] in seen_overviews or row["source_url"] in {r.get("source_url") for r in selection.get("overview", [])}:
            raise ProviderError("Duplicate pending/pinned overview source")
        seen_overviews.add(row["source_url"])
    overview_candidate_bytes = sum(row["size_bytes"] for row in overview_candidates)
    states = tuple(selection.get("states", NEW_ENGLAND))
    for source in _sources(recipe):
        if source.get("role") == "offshore_water":
            document = json.loads(_fetch(source, fetcher))
            features = document.get("features", [])
            if not features or document.get("exceededTransferLimit"):
                raise ProviderError("Missing/truncated authoritative offshore-water metadata")
            water_features.extend(features)
            continue
        if source.get("role") == "boundaries":
            document = json.loads(_fetch(source, fetcher))
            features = document.get("features", [])
            if not features or document.get("exceededTransferLimit"):
                raise ProviderError("Missing/truncated authoritative state-boundary metadata")
            for feature in features:
                properties = feature.get("properties", feature.get("attributes", {}))
                state = properties.get(source.get("state_property", "STUSPS"))
                if state in states:
                    if state in geometries:
                        raise ProviderError("Duplicate state boundary")
                    geometries[state] = feature.get("geometry")
            continue
        offset, total, seen_pages = 0, None, set()
        for _ in range(selection.get("max_pages", 30)):
            url = _query(source["url"], offset=offset, max=100)
            data = _fetch(source, fetcher, url)
            digest = sha256(data).hexdigest()
            if digest in seen_pages:
                raise ProviderError("USGS pagination repeated a page")
            seen_pages.add(digest)
            document = json.loads(data)
            items, reported = document.get("items"), document.get("total")
            if not isinstance(items, list) or type(reported) is not int or reported < 0:
                raise ProviderError("USGS product metadata structure changed")
            if total is not None and total != reported:
                raise ProviderError("USGS inventory changed during pagination")
            total = reported
            for item in items:
                if source.get("expected_extent") and item.get("extent") != source["expected_extent"]:
                    raise ProviderError("USGS returned products outside the frozen extent filter")
                if source.get("pdf_only"):
                    formats = {value.strip() for value in item.get("format", "").split(",")}
                    if (not formats & {"GeoPDF", "GeospatialPDF", "Geospatial PDF"} or
                            not urlsplit(item.get("downloadURL", "")).path.lower().endswith(".pdf")):
                        raise ProviderError("USGS returned a non-PDF primary map product")
                candidates.append(_map_row(item, source))
            offset += len(items)
            if offset >= total:
                break
            if not items:
                raise ProviderError("USGS returned an empty page before completing the inventory")
        else:
            blockers.append("USGS inventory exceeds metadata pagination budget")
            inventory_complete = False
    complete = [row for row in candidates if all(row.get(key) is not None for key in
                ("sheet_id", "scale", "size_bytes", "edition", "bbox", "source_url"))]
    if len(complete) != len(candidates):
        blockers.append("Some USGS products lack sheet/scale/edition/size/footprint metadata")
    if water_features:
        geometries, water_evidence = exclude_offshore_water(geometries, water_features)
    plans = {}
    selector = select_mixed_maps if selection.get("mixed_scale_gap_supplements") else select_maps
    for name, allowance in selection.get("allowances", {}).items():
        try:
            # A chosen national overview consumes its own space while remaining
            # outside the pinned/complete selection until its content is verified.
            if selection.get("required_scale"):
                plans[name] = select_required_scale(complete, geometries, allowance - overview_candidate_bytes,
                    scale=selection["required_scale"], gap_scales=selection.get("gap_supplement_scales", []),
                    overview=selection.get("overview", []), states=states)
            else:
                plans[name] = selector(complete, geometries, allowance - overview_candidate_bytes,
                                       overview=selection.get("overview", []), states=states)
        except MapError as error:
            plans[name] = {"selected": [], "complete": False, "blockers": [str(error)]}
        if overview_candidates:
            plans[name].update(budget_bytes=allowance, sheet_budget_bytes=allowance - overview_candidate_bytes,
                               overview_candidate_bytes=overview_candidate_bytes,
                               candidate_total_bytes=plans[name].get("size_bytes", 0) + overview_candidate_bytes,
                               complete=False, selected=[])
            plans[name]["blockers"] = [reason for reason in plans[name]["blockers"]
                                       if reason != "USA overview has not been selected and pinned"]
            plans[name]["blockers"].append("USA overview identity selected; whole-file SHA-256 and PDF review remain pending")
        if not inventory_complete or len(complete) != len(candidates):
            plans[name]["complete"] = False
            plans[name]["selected"] = []
            plans[name]["proposed_sheets"] = []
            plans[name]["geographic_complete"] = False
            plans[name]["blockers"].append("Incomplete product inventory cannot prove the finest complete edition set")
    return _result(recipe, candidates, blockers, plans=plans, boundary_states=sorted(geometries),
                   inventory_complete=inventory_complete, offshore_water_exclusions=water_evidence,
                   overview_candidates=overview_candidates)


def discover_lessons(recipe, fetcher):
    """Consume explicitly declared JSON lesson manifests; never guess a channel."""
    candidates, blockers = [], []
    selection = recipe.get("selection", {})
    allowed_topics = set(selection.get("course_ids", []))
    allowed_formats = set(selection.get("formats", ["html", "pdf", "mp4", "webm", "mp3", "vtt"]))
    for source in _sources(recipe):
        if source.get("role") != "lesson_manifest":
            continue
        document = json.loads(_fetch(source, fetcher))
        if not document.get("revision") or not isinstance(document.get("lessons"), list):
            raise ProviderError("Lesson metadata requires a revision and explicit lessons list")
        seen = set()
        for row in document["lessons"]:
            if not all(row.get(key) for key in ("id", "title", "course_id", "license", "files")):
                raise ProviderError("Incomplete lesson identity/course/license/files metadata")
            if row["id"] in seen:
                raise ProviderError("Duplicate lesson ID")
            seen.add(row["id"])
            if row.get("language") != selection.get("language", "en"):
                continue
            if allowed_topics and row["course_id"] not in allowed_topics:
                continue
            files = []
            for item in row["files"]:
                if item.get("format") not in allowed_formats:
                    blockers.append(f"Unsupported ordinary-file lesson dependency: {row['id']}")
                    files = []
                    break
                if (not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                        or type(item.get("size_bytes")) is not int or item["size_bytes"] < 1):
                    raise ProviderError("Lesson dependency lacks complete pin metadata")
                files.append(dict(item, source_url=_url(item["source_url"])))
            if files:
                candidates.append(dict(row, files=files, revision=document["revision"], body_verified=False))
    if not candidates:
        blockers.append("No verified ordinary-file lesson inventory; channel/course IDs must be discovered")
    if not allowed_topics and recipe["resource_id"] == "khan-core-stem":
        blockers.append("Exact STEM course IDs have not been frozen; candidates are discovery only")
    return _result(recipe, candidates, blockers)


def discover_direct(recipe, fetcher):
    # Pinned archive entry lists can only be resolved after the archive is present
    # at build time. Discovery deliberately does not download a ZIM or pretend a
    # current website URL is an entry in its older pinned edition.
    selection = recipe.get("selection", {})
    entries = selection.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(item, str) or not item for item in entries):
        raise ProviderError("Direct selection entries must be explicit archive identifiers")
    candidates = [{"entry": entry, "source_asset_ids": recipe.get("source_asset_ids", []),
                   "body_verified": False} for entry in sorted(set(entries))]
    blockers = ["Pinned archive entry/dependency resolution and visual review occur at build time"]
    if not entries:
        blockers.append("Reviewed entry manifest has not been selected")
    return _result(recipe, candidates, blockers)


def discover(recipe: dict, fetcher) -> dict:
    """Dispatch provider metadata only; no adapter calls a library-body URL."""
    adapter = recipe.get("adapter")
    if adapter in {"gutenberg_expansion", "ocw_expansion"}:
        from .expansions import discover as discover_expansion
        return discover_expansion(recipe, fetcher)
    dispatch = {"hesperian": discover_hesperian, "survivor": discover_survivor,
                "usgs_maps": discover_maps, "lessons": discover_lessons,
                "zim_direct": discover_direct}
    if adapter in dispatch:
        return dispatch[adapter](recipe, fetcher)
    if adapter in {"html_snapshot", "manual_html", "phet_review"}:
        return _result(recipe, [], ["Local pinned sources and reviewed build-time outputs are required"])
    raise ProviderError(f"Unsupported metadata adapter: {adapter}")
