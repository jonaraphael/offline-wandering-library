"""Metadata-only expansion discovery; candidates never constitute admission.

Rank complete-work identities before resource acquisition. A CSV or download
page establishes neither complete dependencies nor a reviewed edition.
"""
from __future__ import annotations

import csv
from collections import deque
import hashlib
from html.parser import HTMLParser
import io
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from .metadata import CATALOG_LIMITS
from .model import AcquisitionError

GUTENBERG_CATALOG = next(iter(CATALOG_LIMITS))
SUBJECTS = (
    ("literature", ("fiction", "poetry", "drama", "literature", "stories")),
    ("history", ("history", "civilization", "archaeology")),
    ("biography", ("biography", "autobiography", "diaries", "memoirs")),
    ("philosophy", ("philosophy", "ethics", "logic")),
    ("language-learning", ("language", "grammar", "dictionaries", "linguistics")),
    ("nonfiction", ("science", "engineering", "technology", "agriculture", "natural history", "mathematics", "education", "geography")),
)


def work_key(title, authors):
    """A conservative comparison key, still requiring edition review."""
    def norm(value):
        return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).split())
    return norm(title) + " | " + norm(authors)


def gutenberg_candidates(data, *, existing_ids=(), existing_work_keys=(), limit=2000):
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise AcquisitionError("Book discovery limit must be 1–10000")
    if len(data) > CATALOG_LIMITS[GUTENBERG_CATALOG]:
        raise AcquisitionError("Gutenberg CSV exceeds its metadata allowance")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    required = {"Text#", "Type", "Issued", "Title", "Language", "Authors", "Subjects"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise AcquisitionError("Gutenberg CSV lacks required stable book metadata")
    seen, excluded_ids, excluded_works = set(), set(map(str, existing_ids)), set(existing_work_keys)
    candidates = []
    for count, row in enumerate(reader, 1):
        if count > 150000:
            raise AcquisitionError("Gutenberg catalog row bound exceeded")
        if any(not isinstance(row.get(field), str) for field in required):
            raise AcquisitionError("Gutenberg CSV contains an incomplete metadata row")
        identity = row["Text#"]
        if not identity.isdecimal() or identity in seen:
            raise AcquisitionError("Invalid or duplicate Gutenberg book identity")
        seen.add(identity)
        if row["Type"] != "Text" or row["Language"].strip().lower() != "en":
            continue
        key = work_key(row["Title"], row["Authors"])
        if identity in excluded_ids or key in excluded_works:
            continue
        subjects = row["Subjects"].casefold()
        coverage = [name for name, terms in SUBJECTS if any(term in subjects for term in terms)]
        if not coverage:
            continue
        candidates.append({"id": "gutenberg-" + identity, "book_id": int(identity),
            "resource_id": "books-culture-expansion", "title": row["Title"], "authors": row["Authors"],
            "language": "en", "catalog_issued": row["Issued"], "work_key": key,
            "subjects": row["Subjects"], "coverage": coverage,
            "edition_review": "pending", "source_files": [], "content_ready": False})
    # Interleave subjects so a bounded batch is not dominated by one shelf.
    shelves = {name: deque() for name, _ in SUBJECTS}
    for item in sorted(candidates, key=lambda item: item["book_id"]):
        shelves[item["coverage"][0]].append(item)
    selected, chosen = [], set()
    while len(selected) < limit and any(shelves.values()):
        for name in shelves:
            if shelves[name] and len(selected) < limit:
                item = shelves[name].popleft()
                if item["work_key"] not in chosen:
                    chosen.add(item["work_key"])
                    selected.append({**item, "rank": len(selected) + 1})
    return selected


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.href, self.label = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, text):
        if self.href:
            self.label.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(" ".join(self.label).split())))
            self.href = None


def ocw_candidates(course, data):
    url = course["download_url"]
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "ocw.mit.edu" or not re.fullmatch(r"/courses/[a-z0-9-]+/download/", parts.path):
        raise AcquisitionError("OCW discovery requires the official course download page")
    if len(data) > 8 * 1024**2:
        raise AcquisitionError("OCW metadata exceeds page allowance")
    parser = _Links()
    parser.feed(data.decode("utf-8"))
    sources, seen = [], set()
    for href, title in parser.links:
        source = urljoin(url, href)
        parsed = urlsplit(source)
        suffix = parsed.path.rsplit(".", 1)[-1].lower()
        if suffix not in {"zip", "mp4", "webm", "mp3", "vtt", "srt"} or source in seen:
            continue
        original_source = source
        if parsed.scheme == "http" and parsed.netloc in {"archive.org", "www.archive.org"}:
            source = parsed._replace(scheme="https").geturl()
            parsed = urlsplit(source)
        if parsed.scheme != "https" or parsed.netloc not in {"ocw.mit.edu", "archive.org", "www.archive.org"}:
            raise AcquisitionError("Unexpected OCW download host requires explicit review")
        if source in seen:
            continue
        seen.add(source)
        sources.append({"id": "ocw_" + hashlib.sha256(source.encode()).hexdigest()[:20],
            "source_url": source, "publisher_link": original_source, "title": title, "format": suffix,
            "role": ("course_package" if "download course" in title.casefold() else "course_dependency") if suffix == "zip"
                else "caption" if suffix in {"vtt", "srt"} else "media",
            "size_bytes": None, "sha256": None})
    return {**course, "resource_id": "complete-courses-expansion", "language": "en",
        "source_files": sorted(sources, key=lambda item: (item["role"], item["source_url"])),
        "metadata_sha256": hashlib.sha256(data).hexdigest(), "content_ready": False,
        "blockers": ["Exact file sizes and source capture required", "Full media and caption inventory required; download pages can paginate media",
            "Course package, exercise, notice and local-link review required", "Essential external readings must be reviewed before admission"]}


def discover(recipe, fetcher):
    selection = recipe["selection"]
    if recipe["adapter"] == "gutenberg_expansion":
        data = fetcher.fetch(GUTENBERG_CATALOG, kind="csv", max_bytes=CATALOG_LIMITS[GUTENBERG_CATALOG])
        return {"candidates": gutenberg_candidates(data, existing_ids=selection.get("existing_book_ids", []),
            existing_work_keys=selection.get("existing_work_keys", []), limit=selection.get("candidate_limit", 2000)),
            "metadata_sha256": hashlib.sha256(data).hexdigest(), "body_downloads": 0,
            "blockers": ["Compact archive book/work inventory must be complete before candidate admission",
                "Per-book supported catalog file inventory, edition comparison and complete illustrated edition review required"]}
    courses = selection.get("courses", [])
    if (not isinstance(courses, list) or any(not isinstance(c, dict) or
            not {"id", "rank", "download_url"} <= c.keys() or not isinstance(c["id"], str) or
            type(c["rank"]) is not int or c["rank"] < 1 for c in courses)):
        raise AcquisitionError("OCW courses require stable IDs, positive ranks and download URLs")
    if len(courses) > 100 or len({c["id"] for c in courses}) != len(courses):
        raise AcquisitionError("OCW batch needs at most 100 unique course IDs")
    results = []
    for course in sorted(courses, key=lambda item: (item["rank"], item["id"])):
        try:
            results.append(ocw_candidates(course, fetcher.fetch(course["download_url"], kind="html")))
        except (ValueError, OSError) as error:
            results.append({**course, "content_ready": False, "blockers": [str(error)[:500]]})
    return {"candidates": results, "body_downloads": 0,
            "blockers": ["Candidate metadata is not a reviewed or size-measured course edition"]}
