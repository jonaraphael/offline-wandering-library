"""Bounded official OCW discovery and package capture proposals, never admission.

The public catalog's lecture-video filter is a discovery aid, not a completeness
claim. Complete media/caption inventories are obtained from the captured packages
with ``inspect_ocw_packages.py``; download pages can paginate their media lists.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

from ..safety import SafetyError, atomic_write, reject_symlinks
from ..archive import MAX_EXPLICIT_PACKAGE_BYTES
from .capture import normalize_manifest
from .expansions import ocw_candidates

INDEX = "https://api.learn.mit.edu/api/v1/learning_resources/"
SITEMAP = "https://ocw.mit.edu/sitemap.xml"
MAX_COURSES = 100
MAX_INDEX_ROWS = 500
SUBJECTS = {
    "mathematics": {"18"},
    "computing": {"6"},
    "engineering": {"1", "2", "3", "10", "16", "22", "ESD", "IDS"},
    "physical-sciences": {"5", "8", "12"},
    "life-sciences": {"7", "9", "20", "HST"},
    "humanities-social-sciences": {"4", "11", "14", "17", "21", "21A", "21G", "21H", "21L", "21M", "21W", "24", "STS", "WGS"},
}
REVIEW_REQUIREMENTS = [
    "Package capture is a build input; ZIP bytes are not additional useful knowledge.",
    "Reconcile every packaged video, English caption, exercise and supplied solution with the full course inventory.",
    "Essential external readings and dependencies must be available and reviewed before admission.",
    "Retain one appropriate publisher media rendition, normally 720p; no upscaling or duplicate representations.",
    "Review English language, notices, local links, legibility and disconnected playback; measure ordinary outputs.",
]


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def course_id(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/courses/([a-z0-9][a-z0-9.-]*)/", parts.path)
    if parts.scheme != "https" or parts.netloc != "ocw.mit.edu" or parts.query or parts.fragment or not match:
        raise SafetyError("Expected canonical official OCW course URL")
    if ".." in match[1]:
        raise SafetyError("Invalid course slug")
    return match[1]


def metadata(fetcher, url, kind):
    body = fetcher.fetch(url, kind=kind)
    # Exclude transport timestamps/cache-hit flags so online and offline replay
    # of the same metadata bytes yield identical frozen proposals.
    return body, {"url": url, "kind": kind, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def load_index(fetcher):
    body, evidence = metadata(fetcher, SITEMAP, "publisher-course-index")
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise SafetyError("Course sitemap must not contain entity declarations")
    root = ElementTree.fromstring(body)
    if root.tag.rsplit("}", 1)[-1] != "sitemapindex":
        raise SafetyError("Expected the official OCW sitemap index")
    sites = set()
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and "/courses/" in node.text:
            if not node.text.endswith("/sitemap.xml"):
                raise SafetyError("Unexpected course sitemap identity")
            sites.add(course_id(node.text.removesuffix("sitemap.xml")))
    if not 1 <= len(sites) <= 10000:
        raise SafetyError("Official course sitemap exceeds its course bound")
    rows, evidence_rows, expected = [], [evidence], None
    for offset in range(0, MAX_INDEX_ROWS, 100):
        url = INDEX + f"?platform=ocw&course_feature=Lecture%20Videos&limit=100&offset={offset}"
        data, evidence = metadata(fetcher, url, "publisher-lecture-course-index")
        page = json.loads(data)
        count, items = page.get("count"), page.get("results")
        if type(count) is not int or not 0 < count <= MAX_INDEX_ROWS or not isinstance(items, list):
            raise SafetyError("Official lecture-course index exceeds its row bound")
        if expected is not None and count != expected:
            raise SafetyError("Publisher index count changed during pagination")
        expected = count
        if len(items) != min(100, count - offset):
            raise SafetyError("Publisher index pagination is incomplete")
        rows.extend(items); evidence_rows.append(evidence)
        if len(rows) == count:
            if page.get("next"):
                raise SafetyError("Publisher index has unexpected trailing pages")
            break
        if not page.get("next"):
            raise SafetyError("Publisher index ends before its declared count")
    if len({r.get("id") for r in rows}) != len(rows):
        raise SafetyError("Publisher course index repeats an identity")
    for row in rows:
        if row.get("platform", {}).get("code") != "ocw" or row.get("resource_type") != "course":
            raise SafetyError("Publisher filter returned a non-OCW course")
        if course_id(row["url"]) not in sites:
            raise SafetyError("Publisher course is absent from the official OCW sitemap")
    return rows, evidence_rows


def number_keys(row):
    numbers = row.get("course", {}).get("course_numbers", [])
    # Cross-listings also identify the same work. SC/J suffixes do not create a
    # new knowledge work when a normal edition is already selected.
    return {re.sub(r"(?:SC|J)$", "", n["value"].upper()) for n in numbers if n.get("value")}


def title_key(title):
    return " ".join(re.sub(r"[^\w]+", " ", title.casefold()).split())


def rank_courses(rows, *, excluded_ids=(), limit=100, start=0):
    if type(limit) is not int or not 1 <= limit <= MAX_COURSES or type(start) is not int or not 0 <= start < MAX_INDEX_ROWS:
        raise SafetyError("Select 1–100 courses and a bounded rank offset")
    excluded_ids = set(excluded_ids)
    old = [row for row in rows if course_id(row["url"]) in excluded_ids]
    seen_numbers = set().union(*(number_keys(r) for r in old)) if old else set()
    seen_titles = {title_key(r["title"]) for r in old}
    candidates = []
    for row in rows:
        cid = course_id(row["url"])
        if cid in excluded_ids or not row.get("published") or "Lecture Videos" not in row.get("course_feature", []):
            continue
        languages = row.get("languages")
        if languages and any(str(x).casefold() not in {"en", "english"} for x in languages):
            continue
        departments = {r["department_id"] for r in row.get("departments", [])}
        subject = next((s for s, ids in SUBJECTS.items() if departments & ids), None)
        if subject is None:
            continue
        features = row.get("course_feature", [])
        score = sum(weight for feature, weight in (("Lecture Notes", 8), ("Problem Sets", 8),
            ("Problem Set Solutions", 4), ("Exam Solutions", 4), ("Open Textbooks", 4)) if feature in features)
        year = max((r.get("year") or 0 for r in row.get("runs", [])), default=0)
        candidates.append(((-score, -year, cid), subject, row))
    shelves = {subject: deque() for subject in SUBJECTS}
    for priority, subject, row in sorted(candidates, key=lambda item: item[0]):
        numbers, title = number_keys(row), title_key(row["title"])
        if numbers & seen_numbers or title in seen_titles:
            continue
        seen_numbers.update(numbers); seen_titles.add(title)
        shelves[subject].append({"id": course_id(row["url"]), "title": row["title"],
            "subject": subject, "course_url": row["url"], "catalog_id": row["id"],
            "work_numbers": sorted(numbers), "year": -priority[1], "priority_score": -priority[0],
            "publisher_features": sorted(row["course_feature"]), "language_review": "pending",
            "content_ready": False, "expected_useful_bytes": None})
    ranked = []
    while any(shelves.values()):
        for shelf in shelves.values():
            if shelf:
                ranked.append({**shelf.popleft(), "rank": len(ranked) + 1})
    return ranked[start:start + limit], len(ranked)


def excluded_courses(manifests):
    ids, urls = set(), set()
    for path in manifests:
        reject_symlinks(path)
        if path.stat().st_size > 16 * 1024**2:
            raise SafetyError("Excluded manifest exceeds16MiB")
        document = json.loads(path.read_text())
        for source in document.get("sources", []):
            url = source.get("source_url", "")
            urls.add(url)
            if source.get("course_id"):
                ids.add(source["course_id"])
            match = re.fullmatch(r"https://ocw\.mit\.edu/courses/([a-z0-9-]+)/[^/]+\.zip", url)
            if match:
                ids.add(match[1])
    return ids, urls


def freeze_packages(candidates, fetcher, probe, *, excluded_urls=(), max_source_bytes=20_000_000_000, progress=None):
    if len(candidates) > MAX_COURSES or type(max_source_bytes) is not int or not 0 < max_source_bytes <= 100_000_000_000:
        raise SafetyError("Package proposal exceeds bounded course/storage selection")
    sources, results, used = [], [], 0
    seen_urls = set(excluded_urls)
    for candidate in candidates:
        result = {**candidate, "blockers": list(REVIEW_REQUIREMENTS), "capture_source_id": None}
        try:
            url = candidate["course_url"]
            cid = course_id(url)
            raw, root_evidence = metadata(fetcher, url + "data.json", "publisher-course-metadata")
            course = json.loads(raw)
            if course.get("site_url_path", "").strip("/") != "courses/" + cid or not course.get("site_uid"):
                raise SafetyError("Course metadata does not match the ranked course identity")
            if title_key(course.get("course_title", "")) != title_key(candidate["title"]):
                raise SafetyError("Publisher index and course title differ; review before capture")
            if course.get("hide_download"):
                raise SafetyError("Publisher hides this course download")
            raw, download_evidence = metadata(fetcher, url + "download/", "publisher-course-download-page")
            parsed = ocw_candidates({"download_url": url + "download/"}, raw)
            packages = [s for s in parsed["source_files"] if s["role"] == "course_package"]
            if len(packages) != 1 or not packages[0]["source_url"].startswith(url):
                raise SafetyError("Course must link exactly one official complete course ZIP")
            package = packages[0]
            if package["source_url"] in seen_urls:
                raise SafetyError("Course package overlaps an existing frozen source")
            pin = probe.probe({"id": package["id"], "url": package["source_url"]})
            if not pin.get("size_bytes"):
                raise SafetyError("; ".join(pin["blockers"]) or "Exact package byte size is unavailable")
            # A package may lack a publisher SHA-256. The capture runner then
            # verifies its exact size and records the observed whole-file hash.
            allowed = "Publisher metadata supplies no whole-file SHA-256; ETag/MD5/SHA-1 are not pins"
            if any(b != allowed for b in pin.get("blockers", [])):
                raise SafetyError("; ".join(pin["blockers"]))
            size = pin["size_bytes"]
            if size > MAX_EXPLICIT_PACKAGE_BYTES:
                raise SafetyError("Course ZIP exceeds the existing512MiB bounded package inspector; a separately reviewed large-package workflow is required")
            if used + size > max_source_bytes:
                raise SafetyError("Package exceeds remaining explicit source-byte budget")
            head = pin["evidence"][0]
            head_record = {k: v for k, v in head.items() if k not in {"cached"}}
            source = {"id": package["id"], "course_id": cid, "work_id": "ocw:" + course["site_uid"],
                "resource_ids": ["complete-courses-expansion"], "source_url": package["source_url"],
                "version": cid + "-metadata-" + root_evidence["sha256"][:16],
                "size_bytes": size, "sha256": pin.get("sha256"), "publisher_checksums": {},
                "metadata_evidence": [root_evidence, download_evidence, {"kind": "HEAD", "url": package["source_url"],
                    "sha256": hashlib.sha256(canonical(head_record)).hexdigest(), "body_read": False, "record": head_record}]}
            sources.append(source); seen_urls.add(source["source_url"]); used += size
            result.update(capture_source_id=source["id"], package_source_bytes=size, work_id=source["work_id"],
                media_inventory="pending captured-package inspection; download-page media is incomplete evidence")
        except (OSError, ValueError, KeyError, TypeError) as error:
            result["blockers"].insert(0, str(error)[:500])
        results.append(result)
        if progress:
            progress(len(results), len(candidates), len(sources), used)
    manifest = None
    if sources:
        identity = "ocw-expansion-packages-" + hashlib.sha256(canonical(sources)).hexdigest()[:16]
        manifest = normalize_manifest({"schema_version": 1, "kind": "acquisition", "id": identity,
            "profile": "full-1tb", "content_ready": False, "sources": sources,
            "budget": {"download_bytes": used, "cache_bytes": 0, "expanded_bytes": 0, "preview_bytes": 0, "scratch_bytes": 0},
            "review_requirements": REVIEW_REQUIREMENTS})
    return results, manifest


def immutable_json(path, value):
    reject_symlinks(path)
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if len(data) > 16 * 1024**2:
        raise SafetyError("Frozen OCW proposal exceeds16MiB")
    if path.exists() and path.read_bytes() != data:
        raise SafetyError("Frozen OCW proposal differs; use a new output directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, data)
