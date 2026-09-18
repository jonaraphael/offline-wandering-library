"""Small, directly readable entry points and JavaScript-free catalog indexes."""

from __future__ import annotations

import html
import posixpath
import string
import unicodedata
from collections import defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .safety import atomic_write, safe_path

LETTERS = (*string.ascii_uppercase, "0-9", "other")
GENERATED_PATHS = (
    "START_HERE.html",
    "README.txt",
    "INVENTORY.html",
    "INDEX/categories.html",
    "INDEX/critical.html",
    *(f"INDEX/{letter}.html" for letter in LETTERS),
)

GROUPS = (
    ("first-aid", "First aid"),
    ("medical", "Medical"),
    ("water-sanitation", "Water and sanitation"),
    ("food", "Food safety and preservation"),
    ("agriculture", "Agriculture"),
    ("repair", "Mechanical repair"),
    ("electrical", "Electrical"),
    ("shelter", "Shelter"),
    ("navigation", "Navigation"),
    ("reference", "Essential reference"),
    ("books", "Books and textbooks"),
    ("maps", "Maps"),
    ("archives", "Wikipedia and large archives"),
    ("readers", "Software and archive readers"),
    ("other", "Other material"),
)
GROUP_LABELS = dict(GROUPS)
ALIASES = {
    "first-aid": "first-aid",
    "emergency-medicine": "medical",
    "medicine": "medical",
    "water": "water-sanitation",
    "sanitation": "water-sanitation",
    "water-and-sanitation": "water-sanitation",
    "food-safety": "food",
    "food-preservation": "food",
    "mechanical": "repair",
    "mechanical-repair": "repair",
    "engineering": "repair",
    "encyclopedia": "archives",
    "dictionary": "archives",
    "software": "readers",
    "reader": "readers",
    "textbooks": "books",
    "education": "books",
}

CSS = """
:root { color-scheme: light dark; font: 17px/1.55 system-ui, sans-serif; }
body { max-width: 68rem; margin: auto; padding: 1rem; background: #fff; color: #16212d; }
a { color: #125e96; overflow-wrap: anywhere; }
a:focus-visible { outline: 3px solid #d47d00; outline-offset: 3px; }
h1 { font-size: clamp(1.65rem, 5vw, 2.5rem); line-height: 1.2; }
h2 { margin-top: 1.6rem; line-height: 1.3; }
nav, .notice { padding: .8rem 1rem; background: #eef4f7; border-radius: .4rem; }
nav a { display: inline-block; padding: .3rem .55rem .3rem 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  list-style: none; padding: 0; gap: .7rem; }
.cards a { display: block; padding: .8rem; border: 1px solid #9babba; border-radius: .4rem; }
.assets { padding-left: 1.3rem; }
.assets li { padding: .55rem 0; }
.meta { font-size: .9rem; color: #43576a; }
.badge { font-size: .8rem; font-weight: 600; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { padding: .55rem; text-align: left; vertical-align: top; border-bottom: 1px solid #aab6c0; }
code { overflow-wrap: anywhere; }
footer { border-top: 1px solid #aab6c0; margin-top: 2rem; padding-top: .6rem; font-size: .85rem; }
@media (prefers-color-scheme: dark) {
  body { background: #111a23; color: #edf3f7; }
  a { color: #9ad1fc; } nav, .notice { background: #21303e; }
  .meta { color: #bed0df; }
}
"""


def _text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _href(destination: str, current: str) -> str:
    """Encode each relative link without letting a manifest create a URL scheme."""
    path = PurePosixPath(destination)
    if (
        not destination
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in destination.split("/"))
        or "\\" in destination
        or ":" in destination
    ):
        raise ValueError(f"Unsafe destination for navigation: {destination!r}")
    relative = posixpath.relpath(destination, posixpath.dirname(current) or ".")
    return quote(relative, safe="/")


def _group(asset: dict) -> str:
    destination = str(asset.get("destination", "")).upper().split("/")
    if destination[0] == "ZIM" or str(asset.get("format", "")).lower() == "zim":
        return "archives"
    if destination[0] == "SOFTWARE":
        return "readers"
    if destination[0] == "BOOKS":
        return "books"
    if destination[0] == "MAPS":
        return "maps"
    if destination[0] == "CRITICAL" and len(destination) > 1:
        category = destination[1].lower().replace("_", "-")
    else:
        category = str(asset.get("category", "other")).lower().replace("_", "-").replace(" ", "-")
    category = ALIASES.get(category, category)
    return category if category in GROUP_LABELS else "other"


def _letter(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title.strip())
    first = normalized[:1].upper()
    if first in string.ascii_uppercase and first:
        return first
    return "0-9" if first.isdigit() else "other"


def _requires_reader(asset: dict) -> bool:
    return bool(asset.get("reader_required")) or str(asset.get("format", "")).lower() in {"zim", "epub"}


def _page(title: str, body: str, current: str) -> str:
    home = _href("START_HERE.html", current)
    search = _href("SEARCH.html", current)
    categories = _href("INDEX/categories.html", current)
    critical = _href("INDEX/critical.html", current)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{_text(title)} · Offline Wandering Library</title><style>{CSS}</style></head>
<body><nav aria-label="Library navigation"><a href="{home}">Start here</a>
<a href="{search}">Search</a><a href="{categories}">Categories</a>
<a href="{critical}">Critical content</a></nav>
<main><h1>{_text(title)}</h1>{body}</main>
<footer>Offline Wandering Library · This page works without JavaScript or an internet connection.</footer>
</body></html>
"""


def _asset_list(assets: list[dict], current: str) -> str:
    if not assets:
        return "<p>No material in this section is included in this build. Check the inventory for what is available.</p>"
    items = []
    for asset in assets:
        title = _text(asset.get("title", asset["destination"]))
        link = _href(str(asset["destination"]), current)
        category = GROUP_LABELS[_group(asset)]
        publisher = asset.get("publisher") or asset.get("source") or ""
        metadata = " · ".join(str(value) for value in (category, publisher, asset.get("format", "").upper()) if value)
        if _group(asset) == "readers":
            badge = "Software package"
        elif str(asset.get("format", "")).lower() == "zim":
            badge = "Archive reader required"
        else:
            badge = "Compatible reader required" if _requires_reader(asset) else "Ordinary file"
        description = f"<br>{_text(asset['description'])}" if asset.get("description") else ""
        items.append(
            f'<li><a href="{link}">{title}</a> <span class="badge">({_text(badge)})</span>'
            f'<br><span class="meta">{_text(metadata)}</span>{description}</li>'
        )
    return '<ul class="assets">' + "\n".join(items) + "</ul>"


def _alphabet(current: str) -> str:
    links = " ".join(
        f'<a href="{_href(f"INDEX/{letter}.html", current)}">{_text(letter)}</a>' for letter in LETTERS
    )
    return f'<nav aria-label="Alphabetical title index">{links}</nav>'


def _size(value: object) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "Unknown"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{size:,} B"
        size /= 1024
    raise AssertionError("Unreachable")


def generate_navigation(target: Path, assets: list[dict], inventory: dict, search_report: dict) -> list[str]:
    """Write the fixed no-JavaScript navigation set, returning managed paths.

    Static indexes enumerate catalog assets. Entries inside specialized archives
    are accessible through their reader and, when extracted, the search index.
    """
    actual = {entry["destination"]: entry for entry in inventory.get("assets", [])}
    entries = [{**asset, **actual.get(asset["destination"], {})} for asset in assets]
    entries.sort(key=lambda asset: (str(asset.get("title", "")).casefold(), asset["destination"]))
    groups: dict[str, list[dict]] = defaultdict(list)
    letters: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        _href(str(entry["destination"]), "START_HERE.html")
        groups[_group(entry)].append(entry)
        letters[_letter(str(entry.get("title", entry["destination"])))].append(entry)

    pages: dict[str, str] = {}
    cards = "".join(
        f'<li><a href="INDEX/categories.html#{key}">{label} ({len(groups[key])})</a></li>'
        for key, label in GROUPS if key != "other" or groups[key]
    )
    pages["START_HERE.html"] = _page(
        "Offline Wandering Library",
        """<p>An offline knowledge library. Start with the topic you need, or search the library.</p>
<p class="notice"><strong>Open ordinary files directly.</strong> The critical library uses HTML, PDF,
and other ordinary files. Use your device’s file manager and a compatible browser or document viewer.
No account, server, or internet connection is needed to read these files.</p>
<p><a href="SEARCH.html"><strong>Search this library</strong></a> ·
<a href="INDEX/critical.html"><strong>Browse all critical content</strong></a></p>
"""
        + f'<ul class="cards">{cards}</ul>'
        + """<h2>When search does not work</h2>
<p><a href="INDEX/categories.html">Browse the category index</a> or use the alphabetical links below.
These ordinary pages need no JavaScript. If your phone previews HTML without opening links, open a
PDF or text file directly in the topic folders through the file manager.</p>"""
        + _alphabet("START_HERE.html")
        + """<h2>Large archives and reader software</h2>
<p>Files ending in <code>.zim</code>, including Wikipedia, need a compatible archive reader.
<a href="INDEX/categories.html#readers">Bundled reader software</a> is in <code>SOFTWARE/</code>.
Use the version for your operating system and processor; installation or permissions may be required.
Do not assume an iPhone can install a reader from this drive while offline. Use the directly readable
critical files on locked-down devices. EPUB support also depends on an available compatible viewer.</p>
<h2>What is on this drive</h2>
<p><a href="INVENTORY.html">Inventory, sources, licenses, and verification status</a> ·
<a href="SOURCE_NOTES.txt">Source limitations and license notes</a> ·
<a href="README.txt">Plain-text instructions</a> · <a href="VERIFY.py">Independent verifier</a> ·
<a href="BUILD_INFO.json">Build information</a> ·
<a href="SHA256SUMS.txt">SHA-256 checksums</a></p>
<p>The static indexes list library files; articles inside archives require their reader.
Coverage depends on the selected profile. Documents retain their original dates, authors, and limitations.</p>
""",
        "START_HERE.html",
    )

    current = "INDEX/categories.html"
    sections = "".join(
        f'<section id="{key}"><h2>{label}</h2>{_asset_list(groups[key], current)}</section>'
        for key, label in GROUPS
    )
    pages[current] = _page("Browse by category", "<p>Files included in this build.</p>" + sections, current)

    current = "INDEX/critical.html"
    critical = [entry for entry in entries if entry.get("critical")]
    pages[current] = _page(
        "Critical content",
        "<p>Priority resources stored as ordinary files. No specialized archive reader is needed; "
        "use your device’s compatible file viewer. This index lists the selected build’s resources.</p>"
        + _asset_list(critical, current),
        current,
    )
    for letter in LETTERS:
        current = f"INDEX/{letter}.html"
        pages[current] = _page(
            f"Titles: {letter}", _alphabet(current) + _asset_list(letters[letter], current), current
        )

    coverage = {entry["destination"]: entry for entry in search_report.get("assets", [])}
    rows = []
    for entry in entries:
        title = _text(entry.get("title", entry["destination"]))
        path = _href(entry["destination"], "INVENTORY.html")
        verification = entry.get("verification", "unknown")
        license_text = _text(entry.get("license", "Unspecified"))
        attribution = f"<br>{_text(entry['attribution'])}" if entry.get("attribution") else ""
        source = _text(entry.get("source_url", entry.get("source", "")))
        search_status = coverage.get(entry["destination"], {}).get("status", "not reported")
        rows.append(
            f'<tr><td><a href="{path}">{title}</a><br><code>{_text(entry["destination"])}</code></td>'
            f'<td>{_text(GROUP_LABELS[_group(entry)])}<br>{_text(entry.get("format", ""))}</td>'
            f'<td>{_text(_size(entry.get("size_bytes")))}</td>'
            f'<td>{_text(entry.get("version", ""))}<br><span class="meta">{source}</span></td>'
            f'<td>{license_text}{attribution}</td><td>{_text(verification)}</td>'
            f'<td>{_text(search_status)}</td></tr>'
        )
    pages["INVENTORY.html"] = _page(
        "Library inventory",
        f"<p>{len(entries)} catalog assets. See <a href=\"INVENTORY.json\">the machine-readable inventory</a> "
        "for exact byte sizes, SHA-256 hashes, and search coverage.</p>"
        "<p><strong>Pinned</strong> means a file matched the catalog’s source checksum. "
        "<strong>Observed</strong> means the build recorded a checksum after download; this detects later "
        "changes but does not independently authenticate the original source.</p>"
        "<p>Search coverage describes extracted text: <code>full_text</code>, <code>partial</code>, "
        "or <code>metadata_only</code>. Words in images may not be searchable. Details are recorded in "
        '<a href="SEARCH/coverage.json">the search coverage report</a>.</p>'
        '<div class="table-scroll"><table><thead><tr><th scope="col">Title / file</th>'
        '<th scope="col">Category / format</th><th scope="col">Size</th>'
        '<th scope="col">Version / source</th><th scope="col">License / attribution</th>'
        '<th scope="col">Verification</th><th scope="col">Search coverage</th></tr></thead><tbody>'
        + "\n".join(rows) + "</tbody></table></div>",
        "INVENTORY.html",
    )

    pages["README.txt"] = """OFFLINE WANDERING LIBRARY (OWL)

Open START_HERE.html for topic links, SEARCH.html for full-text search, or
INDEX/categories.html and INDEX/critical.html for navigation without JavaScript.
If HTML links do not work in your phone's preview, use its file manager to open
ordinary files directly in CRITICAL/, REFERENCE/, BOOKS/, and MAPS/.

CRITICAL contains ordinary files such as PDF, HTML, and text. A compatible
standard viewer is needed. No server, cloud account, or internet is required.
HTML behavior on removable drives varies between phones and browser apps.

SEARCH.html uses a precomputed index. Follow its file-picker instructions to
select the index from SEARCH/. Searches read portions of that file locally.
Search needs JavaScript and a browser supporting local File access. The static
indexes work without JavaScript and list the library's catalog assets.

ZIM archives need an archive reader. Bundled readers, when included in this
profile, are in SOFTWARE/ organized by platform. They may require installation,
permissions, compatible processor architecture, or system libraries. They are
never executed by the builder. An iPhone cannot generally install an arbitrary
reader from this SSD while offline. Use the directly readable files instead.
EPUB support also depends on your device's available compatible viewer.

INVENTORY.html and INVENTORY.json record the actual files, sources, licenses,
versions, and hashes. SOURCE_NOTES.txt records source limitations and license
notes. BUILD_INFO.json records the build and search coverage.
SHA256SUMS.txt covers managed files; it cannot prove authenticity if both the
files and this checksum list are altered. Keep an independent trusted copy.

To check this drive, use the repository's Python 3.11+ verification script:
    python scripts/verify.py /path/to/EMERGENCY_LIBRARY
Or use the independent copy included on this drive:
    python /path/to/EMERGENCY_LIBRARY/VERIFY.py /path/to/EMERGENCY_LIBRARY
It reports OK, MISSING, FAILED, and UNKNOWN. Verification reads every covered
file and can take hours on a large drive. UNKNOWN files are not in its manifest.

Build and verify two identical SSDs. Store the backup separately. Practice
opening critical files and search on your actual devices before an emergency.
Keep required USB adapters and, where necessary, an external power source with
the drives. Safely eject a drive before unplugging it.

Documents retain their original authors, publication dates, and limitations.
This library is a reference collection, not a substitute for professional help.
"""

    for relative in GENERATED_PATHS:
        destination = safe_path(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(destination, pages[relative].encode("utf-8"))
    return list(GENERATED_PATHS)
