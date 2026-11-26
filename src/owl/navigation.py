"""Generate the drive reader from verified inventory data."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from html import escape
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import quote

from .catalog import is_document, read_yaml
from .layout import checksum_name, managed_path, reader_destination
from .offline_layout import TEMPLATES, emergency_routes, layout, render
from .resources import resource_asset_ids
from .safety import atomic_write
from .search_ui import SEARCH_CSP, render_search_page
from .wikimed_phone import DESTINATION as PHONE_DESTINATION


def _package_json(name):
    return json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))


_CATEGORY_DATA = _package_json("categories.json")
CATEGORIES = [*_CATEGORY_DATA["categories"], _CATEGORY_DATA["other"]]
_VERTICALS = _package_json("topic_verticals.json")["verticals"]
_COPY = _package_json("collection_copy.json")["collections"]
_READER_CSS = (TEMPLATES / "site.css").read_text(encoding="utf-8")
_DEVICES = ("iphone", "android", "windows", "mac", "linux")
_FORMATS = {"pdf": "PDF", "html": "Web page", "htm": "Web page", "epub": "EPUB book",
            "zim": "Encyclopedia", "txt": "Text", "zip": "ZIP"}
GENERATED_PATHS = ("START_HERE.html", "README.txt", "INVENTORY.html", "BUILD_REPORT.html")
READER_GENERATION = re.compile(r"INDEX/[0-9a-f]{12}/")
SHARED_SEARCH = re.compile(r"SEARCH/shared/[0-9a-f]{64}\.js\Z")
ZIM_RUNTIME = ("fzstd.js", "zim.js", "zim-drive.js", "zim-article.js")
# These archive versions need Kiwix to show their content.
_KIWIX_KINDS = {"ZIM/phet_en_all_2026-08.zim": "Simulations",
                "ZIM/oer4schools_en_all_2025-10.zim": "Teacher training"}
SEARCH_SCRIPTS = ("manifest.js", "rank.js", "shards.js", "rerank.js")
SEARCH_SUPPORT = re.compile(r"SEARCH/(?:model\.js|(?:model|impact|transformer)/[a-zA-Z0-9.-]+\.js)\Z")
FIRST_RESPONSE = {"cert", "medical_bec"}

_CHAPTER = re.compile(r"^(?P<book>.+?)(?: — |: )(?P<chapter>.+)$")
_FRONT = re.compile(r"^(?:front|intro|preface|foreword|contents|cover|title|about)", re.I)


def book_chapters(assets: list[dict]) -> dict[str, dict]:
    """Find books published as one file per chapter.

    Files in one folder whose titles share a stem before " — " or ": " form a
    book when at least three are cataloged. Returns the book title, chapter
    label and reading order for each member, keyed by asset id.
    """
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for asset in assets:
        match = _CHAPTER.match(str(asset.get("title", "")))
        if not match or not is_document(asset) or "/" not in asset["destination"]:
            continue
        stem = re.sub(r"\s+\d+$", "", match["book"])
        number = re.search(r"(\d+)$", match["book"]) if stem != match["book"] else re.match(r"(\d+)", match["chapter"])
        title = stem + "s" if stem != match["book"] else stem
        groups[(asset["destination"].rsplit("/", 1)[0], title)].append((asset, match["chapter"], number))
    books = {}
    for (_, title), members in groups.items():
        if len(members) < 3:
            continue
        def position(member):
            asset, chapter, number = member
            rank = 0 if _FRONT.match(chapter) and not number else 1 if number else 2
            return rank, int(number[1]) if number else 0, chapter.casefold(), asset["id"]
        for order, (asset, chapter, _) in enumerate(sorted(members, key=position)):
            books[asset["id"]] = {"title": title, "chapter": chapter, "order": order}
    return books


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
    relative = posixpath.relpath(checksum_name(destination),
                                posixpath.dirname(checksum_name(current)) or ".")
    return quote(relative, safe="/")


def collection_category(collection: dict) -> str:
    """The same first recognized topic and editorial override used by Manage."""
    theme = _COPY.get(collection["id"], {}).get("theme")
    if theme:
        return theme
    return next((vertical["id"] for domain in collection.get("knowledge_domains", ())
                 for vertical in _VERTICALS if domain in vertical["domains"]), "other")


@lru_cache(maxsize=1)
def _canonical_collections():
    registry = Path(__file__).resolve().parents[2] / "catalog/resources.yaml"
    if not registry.is_file():
        return ()
    return read_yaml(registry)["resources"]


def navigation_assets(assets, collections=None, topics=None) -> dict:
    """Compute each file's category and grouping once, before rendering."""
    collections = _canonical_collections() if collections is None else collections
    order = {"CRITICAL": 0, "USEFUL": 1, "NONESSENTIAL": 2}
    owners = {}
    for collection in sorted(collections, key=lambda row: (
            order.get(row.get("utility_tier"), 3), row.get("number") or 1000, row["id"])):
        category = collection_category(collection)
        importance = order.get(collection.get("utility_tier"), 3)
        for identity in resource_asset_ids(collection):
            owners.setdefault(identity, (category, collection["id"], importance))
    books = book_chapters(assets)
    result = {}
    for asset in assets:
        identity = asset["id"]
        software = asset["destination"].startswith("SOFTWARE/") or asset.get("resource_type") == "software"
        category, owner, importance = ("other", "", 3) if software else owners.get(identity, ("other", "", 3))
        course = owner in {"khan-academy", "crash-course"} or asset.get("resource_type") == "course"
        kind = "Course" if course else None
        result[identity] = {"document": is_document(asset) and not software, "category": category,
                            "importance": importance,
                            "first_aid": (asset.get("category") == "first_aid" or identity in FIRST_RESPONSE or
                                          asset.get("title", "").lower().endswith(" first aid")),
                            "book": books.get(identity), "topics": (topics or {}).get(identity, []), "kind": kind,
                            "publisher": asset.get("publisher"), "attribution": asset.get("attribution")}
        if asset["destination"] in _KIWIX_KINDS:
            result[identity]["kiwixKind"] = _KIWIX_KINDS[asset["destination"]]
    return result


def reader_payload(assets, *, collections=None, topics=None) -> dict:
    """Ship the same templates and preclassified rows to both builders."""
    return {
        "categories": CATEGORIES, "layout": layout(), "css": _READER_CSS,
        "reader": (TEMPLATES / "reader.html").read_text(encoding="utf-8"),
        "document": (TEMPLATES / "reader-document.html").read_text(encoding="utf-8"),
        "runtime": (TEMPLATES / "reader.js").read_text(encoding="utf-8"),
        "zim": {name: (TEMPLATES / name).read_text(encoding="utf-8") for name in ZIM_RUNTIME},
        "bootstrap": (TEMPLATES / "search.js").read_text(encoding="utf-8"),
        "readme": (TEMPLATES / "reader-readme.txt").read_text(encoding="utf-8"),
        "redirect": render_search_page(), "csp": SEARCH_CSP,
        "assets": navigation_assets(assets, collections, topics),
    }


def _text(value):
    return escape(str(value) if value is not None else "").replace("&#x27;", "&#39;")


def _script(name, *values):
    args = ",".join(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for value in values)
    return f"globalThis.{name}({args});\n"


def _order(row):
    return row["title"].lower(), row["id"]


def _row(asset, data):
    destination = reader_destination(asset)
    path = checksum_name(destination)
    row = {"id": asset["id"], "title": asset["title"], "path": path,
           "href": _href(destination, "START_HERE.html"),
           "kind": data.get("kind") or _FORMATS.get(asset["format"], asset["format"].upper()),
           "format": asset["format"], "bytes": asset.get("size_bytes", asset.get("bytes", 0))}
    if len(asset.get("parts") or ()) > 1:
        row["parts"] = len(asset["parts"])
    if data.get("kiwixKind"):
        row["kiwixKind"] = data["kiwixKind"]
    return row


def _grouped(rows, metadata, category):
    books = defaultdict(list)
    output = []
    for row in rows:
        data = metadata.get(row["id"], {})
        book = data.get("book")
        row["topics"] = data.get("topics", [])
        if book and row["format"] != "zim":
            books[(row["path"].rsplit("/", 1)[0], book["title"])].append(row)
        else:
            output.append(row)
    for (folder, title), members in books.items():
        if len(members) < 3:
            output.extend(members)
            continue
        members.sort(key=lambda row: metadata[row["id"]]["book"]["order"])
        chapters = [{**row, "title": metadata[row["id"]]["book"]["chapter"], "source": title} for row in members]
        topics = sorted({tuple(topic) for row in members for topic in row["topics"]})
        output.append({"id": "book-" + members[0]["id"], "title": title, "path": folder + "/",
                       "kind": f"Book, {len(members)} chapters", "bytes": sum(row["bytes"] for row in members),
                       "publisher": metadata[members[0]["id"]].get("publisher") or "", "chapters": chapters,
                       "topics": topics})
    def importance(row):
        members = row.get("chapters", [row])
        return min(metadata.get(member["id"], {}).get("importance", 3) for member in members)

    def first_response(row):
        if category != "health":
            return 2
        if row["id"] in FIRST_RESPONSE:
            return 0
        return 1 if row.get("chapters") and row["title"] == "Where There Is No Doctor" else 2

    return sorted(output, key=lambda row: (first_response(row), importance(row), *_order(row)))


def _reader_files(assets, inventory, scripts, shared):
    report = inventory.get("navigation") or {}
    config = reader_payload(assets, topics=report.get("reader_topics"))
    markup = config["layout"]
    meta = config["assets"]
    files = [_row(asset, meta[asset["id"]]) for asset in assets]
    documents = [row for row in files if meta[row["id"]]["document"]]
    readers = [{"label": label, "path": row["path"], "href": row["href"]}
               for folder, label, _ in markup["readers"] for row in sorted(files, key=_order)
               if row["path"].startswith("LIBRARY/" + folder)]
    phone = []
    for volume in inventory.get("phone_volumes", []):
        path = PHONE_DESTINATION + volume["file"]
        phone.append({"id": "wikimed-phone-" + volume["file"], "title": "WikiMed: " + volume["title"],
                      "path": checksum_name(path), "href": _href(path, "START_HERE.html"),
                      "kind": "PDF", "format": "pdf", "bytes": volume.get("bytes", 0)})
    tasks = emergency_routes(documents)
    missing = sorted([{"id": row.get("id") or "", "title": row.get("title") or row.get("id") or "",
                       "reason": row.get("reason") or row.get("unresolved_reason") or ""}
                      for row in inventory.get("unresolved", [])], key=_order)
    actual = inventory.get("assets") or assets
    home = {"version": 1, "tasks": tasks, "readers": readers, "devices": markup["devices"], "phone": phone,
            "stats": {"count": len(actual), "bytes": sum(row.get("size_bytes", row.get("bytes", 0)) for row in actual),
                      "missing": len(missing)}, "searchCount": len(documents), "categories": []}
    parts = {asset["id"]: asset.get("parts") for asset in actual}
    home["archives"] = [{**row, "files": [{"path": part["path"], "bytes": part["bytes"]}
                           for part in parts.get(row["id"]) or [{"path": row["path"], "bytes": row["bytes"]}]]}
                        for row in documents if row["format"] == "zim"]
    pages = {"INDEX/reader.js": config["runtime"], "README.txt": config["readme"],
             **{f"INDEX/{name}": text for name, text in config["zim"].items()}}

    # The static page is all a phone's file preview shows: no scripts, and often no working links.
    def link(href, text):
        return render(markup["static_link"], href=_text(href), text=_text(text))

    def trail(path):
        *folders, name = [part for part in path.split("/") if part]
        return render(markup["static_trail"], folders=_text("".join(folder + " › " for folder in folders)), name=_text(name))

    def amount(value, unit):
        return f"{value:,} {unit}" + ("" if value == 1 else "s")

    def static_row(title, detail, path="", chapters=""):
        return render(markup["static_row"], title=title, detail=_text(detail), trail=trail(path) if path else "",
                      chapters=chapters)

    def urgent(row):
        if "path" not in row:
            return static_row(_text(row["task"]), "No guide on this drive.")
        page = re.search(r"#page=(\d+)$", row["href"])
        detail = " · ".join(filter(None, [row["title"], "page " + page[1] if page else "", row.get("hint") or "",
                                          ("Look up " + " / ".join(row["articles"]) + " in Kiwix") if row["articles"] else ""]))
        return static_row(_text(row["task"]) if row["format"] == "zim" else link(row["href"], row["task"]), detail, row["path"])

    static = [render(markup["static_urgent"], rows="".join(urgent(row) for row in tasks))]
    tiles, shelves = [], []
    for category in config["categories"]:
        identity = category["id"]
        members = [row for row in documents if meta[row["id"]]["category"] == identity]
        if identity == "health":
            members.extend(phone)
        grouped = _grouped(members, meta, identity)
        home["categories"].append({**category, "count": len(grouped)})
        pages[f"INDEX/c-{identity}.js"] = _script("OWLReaderData", identity, grouped)
        if not grouped:
            continue
        count = amount(len(grouped), category["unit"])
        if category.get("icon"):
            tiles.append(render(markup["static_tile"], id=identity, icon=_text(category["icon"]),
                                name=_text(category["name"]), count=count))
        rows = []
        for row in grouped:
            chapters = render(markup["static_chapters"], items="".join(
                render(markup["static_chapter"], title=link(chapter["href"], chapter["title"]),
                       name=_text(chapter["path"].rsplit("/", 1)[-1])) for chapter in row["chapters"])) if row.get("chapters") else ""
            title = _text(row["title"]) if row.get("chapters") or row.get("format") == "zim" else link(row["href"], row["title"])
            rows.append(static_row(title, "" if row["kind"] == "PDF" else row["kind"], row["path"], chapters))
        shelves.append(render(markup["static_section"], id=identity, name=_text(category["name"]), count=count,
                              blurb=_text(category["blurb"]), rows="".join(rows)))
    if tiles:
        static.append(render(markup["static_tiles"], tiles="".join(tiles)))
    static.extend(shelves)
    if any(row["format"] == "zim" for row in documents):
        devices = []
        for device in _DEVICES:
            instructions = markup["devices"][device]
            folder = "MACOS" if device == "mac" else device.upper()
            install = instructions["install"]
            if device != "iphone" and not any(row["path"].startswith(f"LIBRARY/SOFTWARE/{folder}/") for row in readers):
                install = "Install Kiwix while you have internet."
            devices.append(render(markup["static_device"], id=device, name=_text(instructions["label"]),
                                  install=_text(install), open=_text(instructions["open"]), pick=_text(instructions["pick"])))
        software = render(markup["static_software"], rows="".join(
            static_row(link(row["href"], row["label"]), "", row["path"]) for row in readers)) if readers else ""
        static.append(render(markup["static_archives"], devices="".join(devices), software=software))
    if inventory.get("content_complete") is False:
        static.append('<p class="note">This library is incomplete. See the <a href="LIBRARY/BUILD_REPORT.html">build report</a>.</p>')
    home["search"] = "manifest.js" in scripts
    home["searchPriority"] = {identity: (2 if row["first_aid"] else 1) for identity, row in meta.items()
                              if row["first_aid"] or row["importance"] == 0}
    if inventory.get("syncedAt"):
        home["syncedAt"] = inventory["syncedAt"]
    pages["INDEX/home.js"] = _script("OWLReaderData", "home", home)

    def document(title, body):
        return render(config["document"], title=_text(title), body=body, css=config["css"], home="../START_HERE.html")

    inventory_rows = []
    actual_by_id = {asset["id"]: asset for asset in actual}
    for row in sorted((_row(asset, {}) for asset in actual), key=_order):
        asset = actual_by_id[row["id"]]
        label = _text(row["title"])
        path = row["path"]
        detail = " · ".join(_text(asset.get(key)) for key in ("license", "attribution") if asset.get(key))
        if row.get("parts", 1) > 1:
            detail = " · ".join(filter(None, [detail, f"{row['parts']} parts. Keep them together and open the first."]))
        inventory_rows.append(render(markup["inventory_row"], path=_text(path),
                                     link=render(markup["location_link"], href=_text(row["href"].removeprefix("LIBRARY/")), text=label),
                                     detail="<small>" + detail + "</small>" if detail else ""))
    pages["INVENTORY.html"] = document("Every file, with its location",
        "<p>See <a href=\"INVENTORY.json\">file details, sources and checksums</a>.</p><ul>" + "".join(inventory_rows) + "</ul>")
    omission = ("<h2>Could not be downloaded</h2><ul>" + "".join(render(markup["report_row"],
        title=_text(row["title"]), detail=" · " + _text(row["reason"]) if row["reason"] else "") for row in missing) + "</ul>"
        if missing else "<p>Every requested file available to this build is listed in the inventory.</p>")
    pages["BUILD_REPORT.html"] = document("Build report", omission + '<p><a href="INVENTORY.html">Every file, with its location</a></p>')
    colors = ":root{" + "".join(f"--c-{cat['id']}:{cat['light']};" for cat in CATEGORIES if cat["id"] not in {"trades", "school"}) + "}\n"
    colors += "@media(prefers-color-scheme:dark){:root{" + "".join(f"--c-{cat['id']}:{cat['dark']};" for cat in CATEGORIES) + "}}"
    generation = {path.removeprefix("INDEX/"): pages.pop(path) for path in list(pages) if path.startswith("INDEX/")}
    generation.update(scripts)
    generation["search.js"] = config["bootstrap"]
    generation["search-paths.js"] = _script("OWLSearchPaths", shared)
    hashes = [[path, sha256(text.encode()).hexdigest()] for path, text in sorted(generation.items())]
    digest = sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest()[:12]
    base = f"INDEX/{digest}"
    pages.update({f"{base}/{path}": text for path, text in generation.items()})
    pages["START_HERE.html"] = render(config["reader"], css=config["css"], colors=colors,
                                     static="\n".join(static), policy=_text(config["csp"]), generation=base)
    return pages


def generate_navigation(target: Path, assets: list[dict], inventory: dict, search_report: dict, *,
                        write: bool = True, search_outputs=None):
    """Return library-relative reader files, or publish them to the drive."""
    from .search_shards import output_bytes

    search_files = search_report.get("file_integrity") or {}
    scripts, shared, objects = {}, {}, {}
    for path, pin in search_files.items():
        name = path.removeprefix("SEARCH/")
        if name not in SEARCH_SCRIPTS and not SEARCH_SUPPORT.fullmatch(path):
            continue
        if search_outputs is not None:
            raw = output_bytes(search_outputs[path])
        else:
            with managed_path(target, path).open("rb") as source:
                raw = source.read(pin["size_bytes"] + 1)
        if len(raw) != pin["size_bytes"] or sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError(f"Search file changed before reader publication: {path}")
        if name in SEARCH_SCRIPTS:
            scripts[name] = raw.decode("utf-8")
        else:
            alias = f"SEARCH/shared/{pin['sha256']}.js"
            shared[path] = alias
            objects[alias] = raw.decode("utf-8")
    pages = {**objects, **_reader_files([asset for asset in assets if is_document(asset)], inventory, scripts, shared)}
    if not write:
        return pages
    for relative, content in pages.items():
        destination = managed_path(target, relative)
        atomic_write(destination, content.encode("utf-8"))
    return list(pages)
