"""Plan deterministic, bounded, JavaScript-free topic and source-contents pages.

The caller verifies selected assets and calls atlas_model.validate_sources first.
This renderer neither downloads content nor writes files to the target.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import unicodedata
from urllib.parse import quote

from .catalog import learning_shelves
from .navigation import CSS, LETTERS, _href, _letter, _text
from .safety import SafetyError, safe_path, validate_relative

MAX_ENTRIES = 50
MAX_CHOICES = 15
MAX_PAGE_BYTES = 128 * 1024
PURPOSES = ("start-here", "practical", "explanation", "reference")
PURPOSE_LABELS = {"start-here": "Start here", "practical": "Practical guidance",
                  "explanation": "Foundations and explanations", "reference": "Additional references"}
ENTRANCES = {"subjects": "Browse subjects", "tasks": "Find practical guidance", "learn": "Learn"}


def _topic_path(identity):
    return f"INDEX/topics/{identity}.html"


def _book_path(identity):
    return f"INDEX/books/{identity}.html"


def _page_path(base, number):
    return base if number == 1 else f"{base[:-5]}/{number}.html"


def _link(path, label, current, fragment=None):
    href = _href(path, current)
    if fragment is not None:
        href += "#" + quote(str(fragment), safe="")
    return f'<a href="{href}">{_text(label)}</a>'


def _page(title, body, current):
    links = [("START_HERE.html", "Start here"), ("INDEX/topics.html", "Topic atlas"),
             ("INDEX/topic-a-z/A.html", "Topics A–Z"), ("INDEX/books.html", "Book contents"),
             ("INDEX/critical.html", "Critical content"), ("INDEX/textbooks.html", "Textbooks"),
             ("INDEX/illustrated-guides.html", "Illustrated guides"),
             ("INDEX/categories.html", "Categories"), ("SEARCH.html", "Search")]
    navigation = " ".join(_link(path, label, current) for path, label in links)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{_text(title)} · OWL topic atlas</title>
<style>{CSS}
.skip {{ display:inline-block; padding:.6rem; }} .entry {{ margin:1rem 0; border-bottom:1px solid #aab6c0; padding-bottom:.8rem; }}
.entry h3 {{ margin-bottom:.25rem; }} .entry p {{ margin:.35rem 0; }} li {{ padding:.25rem 0; }}
.choices a,.actions a {{ display:inline-block; padding:.35rem 0; }} .breadcrumb {{ font-size:.9rem; }}
</style></head><body><a class="skip" href="#content">Skip to content</a>
<nav aria-label="Library navigation">{navigation}</nav><main id="content">{body}</main>
<footer>Static offline navigation. Local links and PDF page fragments depend on your viewer; filenames and locations remain visible for manual access.</footer>
</body></html>'''


def _store(pages, path, text):
    validate_relative(path)
    if path in pages:
        raise SafetyError(f"Atlas output path collision: {path}")
    if len(text.encode("utf-8")) > MAX_PAGE_BYTES:
        raise SafetyError(f"Atlas page exceeds {MAX_PAGE_BYTES} bytes: {path}; shorten oversized metadata")
    pages[path] = text


def _series(pages, base, title, items, render, *, limit=MAX_ENTRIES):
    """Split by both entry count and actual rendered bytes; keep navigation bounded."""
    chunks = [items[i:i + limit] for i in range(0, len(items), limit)] or [[]]
    while True:
        placement = {item["key"]: _page_path(base, number)
                     for number, chunk in enumerate(chunks, 1) for item in chunk}
        rendered = []
        split = None
        for number, chunk in enumerate(chunks, 1):
            current = _page_path(base, number)
            controls = []
            if number > 1:
                controls.extend([_link(base, "First page", current),
                                 _link(_page_path(base, number - 1), "Previous page", current)])
            if number < len(chunks):
                controls.append(_link(_page_path(base, number + 1), "Next page", current))
            pager = (f'<nav aria-label="List pages">Page {number} of {len(chunks)}. ' +
                     " · ".join(controls) + "</nav>") if len(chunks) > 1 else ""
            html = _page(title, render(current, chunk, placement) + pager, current)
            if len(html.encode("utf-8")) > MAX_PAGE_BYTES:
                if len(chunk) <= 1:
                    raise SafetyError(f"Atlas page cannot fit its metadata within {MAX_PAGE_BYTES} bytes: {current}")
                split = number - 1
                break
            rendered.append((current, html))
        if split is None:
            for path, html in rendered:
                _store(pages, path, html)
            return placement
        middle = len(chunks[split]) // 2
        chunks[split:split + 1] = [chunks[split][:middle], chunks[split][middle:]]


def _reader(asset):
    return bool(asset.get("reader_required")) or asset.get("format", "").lower() in {"zim", "epub"}


def _labels(asset):
    labels = []
    if asset.get("resource_type"):
        labels.append(str(asset["resource_type"]).capitalize())
    if asset.get("illustrated"):
        labels.append("Illustrated document (whole work)")
    if asset.get("critical"):
        labels.append("Critical")
    labels.append("Reader required" if _reader(asset) else "Ordinary file")
    return " · ".join(labels)


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


def _resource(item, current, *, anchor=None, context=""):
    asset, section = item["asset"], item.get("section")
    title = section["title"] if section else asset["title"]
    fragment, location = _locator(section)
    href = _href(asset["destination"], current)
    # PDF fragments must retain their literal '='; arbitrary HTML IDs are encoded.
    if fragment is not None:
        href += "#" + (fragment if section["locator"]["type"] == "pdf-page" else quote(fragment, safe=""))
    identity = f' id="{_text(anchor)}"' if anchor else ""
    result = f'<section class="entry"{identity}><h3><a href="{href}">{_text(title)}</a></h3>'
    if context:
        result += context
    result += f'<p><strong>{_text(asset["title"])}</strong> · {_text(_labels(asset))}</p>'
    if item.get("description"):
        result += f'<p>{_text(item["description"])}</p>'
    result += f'<p>Location: {_text(location)}<br>File: <code>{_text(asset["destination"])}</code></p>'
    actions = []
    if fragment is not None:
        actions.append(f'<a href="{href}">Open this section</a>')
    actions.append(_link(asset["destination"], "Open complete document", current))
    result += '<p class="actions">' + " · ".join(actions) + "</p>"
    if section and section.get("illustrations"):
        result += '<ul aria-label="Verified section illustrations">'
        for figure in section["illustrations"]:
            words = ["Verified " + figure["kind"], figure["label"], figure.get("figure_id"), figure.get("caption")]
            result += "<li>" + _text(" · ".join(str(word) for word in words if word)) + "</li>"
        result += "</ul>"
    notices = [("Version / edition", asset.get("version")), ("Publisher / source", asset.get("publisher") or asset.get("source")),
               ("Audience", asset.get("audience")), ("License", asset.get("license")),
               ("Attribution", asset.get("attribution"))]
    result += '<p class="meta">' + "<br>".join(f"{label}: {_text(value)}" for label, value in notices if value) + "</p>"
    if section:
        result += f'<p class="meta">Source location provenance: {_text(section["provenance"])}.'
        if section.get("review"):
            review = section["review"]
            result += f' Reviewed by {_text(review["by"])} on {_text(review["date"])}.'
        result += "</p>"
    return result + "</section>"


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


def prepare_atlas(target: Path, assets: list[dict], navigation: dict) -> tuple[dict[str, str], dict]:
    """Render selected, verified sources using validated topic/section metadata.

    ``navigation['sections']`` must be the result of validate_sources, not an
    unchecked outline proposal. Imported contents are kept distinct from topic
    assignments. Missing semantic coverage is reported, never invented.
    """
    selected = {asset["id"]: asset for asset in assets}
    if len(selected) != len(assets):
        raise SafetyError("Duplicate selected atlas asset ID")
    for asset in assets:
        safe_path(target, asset["destination"])
        validate_relative(_book_path(asset["id"]))
    topics = navigation["topics"]
    for identity in topics:
        validate_relative(_topic_path(identity))
    children, ordered = _graph(topics)
    sort_topic = lambda identity: (topics[identity].get("order") is None,
                                  topics[identity].get("order") or 0, topics[identity]["title"].casefold(), identity)
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

    def topic_item(identity, current):
        topic, count = topics[identity], counts[identity]
        label = f'{count["asset_count"]} documents, {count["location_count"]} source locations'
        if count["reader_only"]:
            label += " · Reader required for all material"
        return (f'<li>{_link(_topic_path(identity), topic["title"], current)}<br>'
                f'<span class="meta">{_text(label)}</span><br>{_text(topic["description"])}</li>')

    pages = {}

    def choices(ids, current, label, extra_base, back):
        present = list(ids)
        text = '<ul class="choices">' + "".join(topic_item(identity, current) for identity in present[:MAX_CHOICES]) + "</ul>"
        if len(present) > MAX_CHOICES:
            if extra_base not in pages:
                records = [{"key": identity, "id": identity} for identity in present[MAX_CHOICES:]]
                def render(path, chunk, placement):
                    return (f'<h1>{_text(label)}</h1><p>{_link(back, "Back to overview", path)}</p>'
                            '<ul class="choices">' + "".join(topic_item(row["id"], path) for row in chunk) + "</ul>")
                _series(pages, extra_base, label, records, render, limit=MAX_CHOICES)
            text += "<p>" + _link(extra_base, f"More: {label.lower()} ({len(present) - MAX_CHOICES})", current) + "</p>"
        return text

    def breadcrumb(identity, current):
        chain, cursor = [], identity
        while True:
            parents = [parent for parent in topics[cursor]["parents"] if parent in visible]
            if not parents:
                break
            cursor = parents[0]
            chain.append(cursor)
        links = [_link("INDEX/topics.html", "Topic atlas", current)]
        links += [_link(_topic_path(parent), topics[parent]["title"], current) for parent in reversed(chain)]
        links += [_text(topics[identity]["title"])]
        return '<p class="breadcrumb" aria-label="Canonical topic breadcrumb">' + " / ".join(links) + "</p>"

    for identity in sorted(visible):
        topic = topics[identity]
        base = _topic_path(identity)
        narrow = sorted((child for child in children[identity] if child in visible), key=sort_topic)
        parents = [parent for parent in topic["parents"] if parent in visible]
        related = [other for other in topic["related"] if other in visible]
        records = list(local[identity].values())
        def render(current, chunk, placement, identity=identity, topic=topic, base=base,
                   narrow=narrow, parents=parents, related=related):
            body = breadcrumb(identity, current)
            if len(parents) > 1:
                body += '<h2>Other broader topics</h2>' + choices(parents[1:], current, "Other broader topics",
                    f"INDEX/topics/{identity}/parents.html", base)
            body += f'<h1>{_text(topic["title"])}</h1><p>{_text(topic["description"])}</p>'
            if counts[identity]["reader_only"]:
                body += '<p class="notice"><strong>Reader required for all material in this topic.</strong> Use a compatible archive or book reader.</p>'
            count = counts[identity]
            body += f'<p>{count["asset_count"]} documents, {count["location_count"]} source locations across this topic and its narrower topics. Shared routes are counted once.</p>'
            if narrow:
                body += '<h2>Narrower topics</h2>' + choices(narrow, current, "Narrower topics",
                    f"INDEX/topics/{identity}/children.html", base)
            for purpose in PURPOSES:
                if purpose == "reference" and related:
                    body += '<h2>Related topics and other routes</h2>' + choices(related, current, "Related topics",
                        f"INDEX/topics/{identity}/related.html", base)
                matching = [row for row in chunk if row["purpose"] == purpose]
                if matching:
                    body += f'<h2>{PURPOSE_LABELS[purpose]}</h2>' + "".join(_resource(row, current) for row in matching)
            return body
        _series(pages, base, topic["title"], records, render)

    current = "INDEX/topics.html"
    overview = '<h1>Topic atlas</h1><p>Browse the same topics through subjects, practical needs, or learning. Only material included in this build appears here.</p>'
    for group, label in ENTRANCES.items():
        identities = [identity for identity in navigation["entrances"].get(group, []) if identity in visible]
        overview += f'<section id="{group}"><h2>{label}</h2>'
        overview += (choices(identities, current, label, f"INDEX/topic-entrances/{group}.html", current)
                     if identities else '<p>No topics for this entrance have selected source material in this build.</p>')
        overview += "</section>"
    overview += '<p>Missing topic coverage is an editorial gap; a book can still be available through ' + _link("INDEX/books.html", "book contents", current) + ", the textbook shelf, or the category index.</p>"
    _store(pages, current, _page("Topic atlas", overview, current))

    labels = defaultdict(lambda: {"labels": set(), "topics": set()})
    for identity in sorted(visible):
        for label in [topics[identity]["title"], *topics[identity]["aliases"]]:
            normalized = " ".join(unicodedata.normalize("NFKC", label).casefold().split())
            labels[normalized]["labels"].add(label)
            labels[normalized]["topics"].add(identity)
    alphabet = defaultdict(list)
    for normalized, entry in sorted(labels.items()):
        label = min(entry["labels"], key=lambda value: (value.casefold(), value))
        alphabet[_letter(label)].append({"key": normalized, "label": label, "topics": sorted(entry["topics"], key=sort_topic)})
    for letter in LETTERS:
        base = f"INDEX/topic-a-z/{letter}.html"
        def render(current, chunk, placement, letter=letter):
            body = f'<h1>Topics A–Z: {_text(letter)}</h1><nav aria-label="Topic alphabet">'
            body += " ".join(_link(f"INDEX/topic-a-z/{part}.html", part, current) for part in LETTERS) + "</nav>"
            if not chunk:
                return body + '<p>No included topic labels begin with this letter.</p>'
            for entry in chunk:
                body += f'<section class="entry"><h2>{_text(entry["label"])}</h2>'
                if len(entry["topics"]) > 1:
                    body += '<p>This label has several meanings. Choose the topic you need:</p>'
                extra = "INDEX/topic-a-z/choices/" + hashlib.sha256(entry["key"].encode()).hexdigest()[:24] + ".html"
                body += choices(entry["topics"], current, entry["label"], extra, base) + "</section>"
            return body
        _series(pages, base, f"Topics A–Z: {letter}", alphabet[letter], render)

    book_ids = sorted(set(maps) | {identity for identity, asset in selected.items() if "textbooks" in learning_shelves(asset)},
                      key=lambda identity: (selected[identity]["title"].casefold(), identity))
    for identity in book_ids:
        asset = selected[identity]
        section_map = sections.get(identity, {})
        section_children = defaultdict(list)
        for section in section_map.values():
            section_children[section.get("parent")].append(section["id"])
        ordered_sections = []
        pending = list(reversed(section_children[None]))
        visited = set()
        while pending:
            sid = pending.pop()
            if sid in visited:
                raise SafetyError(f"Cycle or duplicate in source contents: {identity}")
            visited.add(sid)
            ordered_sections.append(section_map[sid])
            pending.extend(reversed(section_children[sid]))
        if len(visited) != len(section_map):
            raise SafetyError(f"Unreachable source contents: {identity}")
        records = [{"key": section["id"], "asset": asset, "section": section} for section in ordered_sections]
        def render(current, chunk, placement, asset=asset, section_map=section_map, records=records):
            body = f'<h1>{_text(asset["title"])}: source contents</h1>'
            body += '<p>These contents follow the source document. Imported publisher headings are not reviewed cross-library topic assignments.</p>'
            body += '<p>' + _link(asset["destination"], "Open complete document", current) + f' · <code>{_text(asset["destination"])}</code></p>'
            if not records:
                return body + '<p>No verified source contents are available for this document. Use the complete-document link and the original contents pages.</p>' + _resource({"asset": asset}, current)
            for item in chunk:
                section = item["section"]
                parent = section.get("parent")
                context = ("<p>Within: " + _link(placement[parent], section_map[parent]["title"], current,
                            "section-" + parent) + "</p>") if parent else ""
                body += _resource(item, current, anchor="section-" + section["id"], context=context)
            return body
        _series(pages, _book_path(identity), asset["title"] + ": source contents", records, render)
    book_items = [{"key": identity, "asset": selected[identity]} for identity in book_ids]
    def render_books(current, chunk, placement):
        body = '<h1>Book and source contents</h1><p>Explore a document’s own structure. Curated cross-library topics remain available in the topic atlas.</p>'
        if not chunk:
            return body + '<p>No selected textbook or validated source contents map is available in this build.</p>'
        for item in chunk:
            asset = item["asset"]
            body += '<section class="entry"><h2>' + _link(_book_path(asset["id"]), asset["title"], current) + '</h2>'
            body += f'<p>{_text(_labels(asset))}</p><p>Version: {_text(asset.get("version"))}<br>License: {_text(asset.get("license"))}'
            if asset.get("attribution"):
                body += '<br>Attribution: ' + _text(asset["attribution"])
            body += '</p></section>'
        return body
    _series(pages, "INDEX/books.html", "Book and source contents", book_items, render_books)

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
              "generated_file_count": len(pages), "html_bytes": sum(len(text.encode("utf-8")) for text in pages.values()),
              "coverage_note": "Available sources and reviewed assignments are distinct; missing topic mappings are editorial gaps, not absent files."}
    return dict(sorted(pages.items())), report
