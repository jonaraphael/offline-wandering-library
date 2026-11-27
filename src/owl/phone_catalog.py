"""A searchable, phone-sized PDF start page for the documents actually on the drive."""
import json
import math
import os
import plistlib
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .offline_layout import layout
from .safety import atomic_write

FONT = "OWL-Vera"
BOLD = "OWL-Vera-Bold"
# A volume UUID, then any folders below the drive's top.
PHONE_PATH = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?:/(?!\.\.?(?:/|$))[^/]+)*")


def drive_path(target):
    """The library root as an iPhone names it: the drive's volume UUID, then any folders below the drive's top.

    None when the UUID is unknown. Only macOS reports it, through diskutil.
    """
    if sys.platform != "darwin":
        return None
    path = Path(target).resolve()
    mount = path
    while not os.path.ismount(mount):
        if mount.parent == mount:
            return None
        mount = mount.parent
    if mount.parent.as_posix() != "/Volumes":
        return None
    try:
        info = subprocess.run(["diskutil", "info", "-plist", str(mount)], capture_output=True, check=True, timeout=30)
        volume = plistlib.loads(info.stdout).get("VolumeUUID")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    if not volume:
        return None
    below = path.relative_to(mount).as_posix()
    return volume if below == "." else volume + "/" + below


# Beside the builders' private records: not in the checksum list, and not carried to a copy, whose UUID differs.
SAVED_DRIVE = ".owl/iphone-drive.json"


def phone_drive(root, saved=None):
    """Where an iPhone finds the folder holding LIBRARY, as saved beside the build records: {"path", "folder"} or None.

    A UUID read from the drive now wins. Otherwise a saved path is kept while the folder keeps its name, so a library
    copied to a differently named drive stops linking to the old one. A Windows drive root has no name to compare.
    """
    path = drive_path(root)
    folder = Path(root).resolve().name
    if path:
        return {"path": path, "folder": folder}
    if (isinstance(saved, dict) and isinstance(saved.get("path"), str) and PHONE_PATH.fullmatch(saved["path"])
            and (not folder or saved.get("folder") == folder)):
        return {"path": saved["path"], "folder": saved.get("folder")}
    return None


def saved_phone_drive(library):
    """The record a builder that could read the drive's UUID left in this library, or None."""
    try:
        return json.loads((Path(library) / SAVED_DRIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_phone_drive(library, record):
    """Keep a known location for the builders that cannot read the UUID: a browser, or Python off macOS."""
    if record and record != saved_phone_drive(library):
        path = Path(library) / SAVED_DRIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def files_link(spec, drive, path, opened=True):
    """A Files app link. Opened, it shows the PDF in place on an iPhone after one prompt; otherwise it shows a folder."""
    return "shareddocuments://" + quote(spec["files_root"] + drive + "/" + path, safe="/") + ("?open" if opened else "")


_PATH_TOKEN = re.compile(r"[MmLlHhVvCcAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _arc(x0, y0, rx, ry, turn, large, sweep, x, y):
    """Cubic curves for one SVG elliptical arc."""
    if not rx or not ry or (x0, y0) == (x, y):
        return [("L", x, y)]
    turn = math.radians(turn)
    cos, sin = math.cos(turn), math.sin(turn)
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1, y1 = cos * dx + sin * dy, cos * dy - sin * dx
    rx, ry = abs(rx), abs(ry)
    stretch = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if stretch > 1:
        rx, ry = rx * math.sqrt(stretch), ry * math.sqrt(stretch)
    below = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0, (rx * rx * ry * ry - below) / below)) * (-1 if large == sweep else 1)
    cxp, cyp = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx, cy = cos * cxp - sin * cyp + (x0 + x) / 2, sin * cxp + cos * cyp + (y0 + y) / 2
    start = math.atan2((y1 - cyp) / ry, (x1 - cxp) / rx)
    sweep_angle = math.atan2((-y1 - cyp) / ry, (-x1 - cxp) / rx) - start
    if sweep and sweep_angle < 0:
        sweep_angle += 2 * math.pi
    elif not sweep and sweep_angle > 0:
        sweep_angle -= 2 * math.pi
    count = max(1, math.ceil(abs(sweep_angle) / (math.pi / 2) - 1e-9))
    step = sweep_angle / count
    handle = 4 / 3 * math.tan(step / 4)

    def place(u, v):
        return cx + rx * u * cos - ry * v * sin, cy + rx * u * sin + ry * v * cos

    curves = []
    for index in range(count):
        a, b = start + index * step, start + (index + 1) * step
        curves.append(("C", *place(math.cos(a) - handle * math.sin(a), math.sin(a) + handle * math.cos(a)),
                       *place(math.cos(b) + handle * math.sin(b), math.sin(b) - handle * math.cos(b)),
                       *place(math.cos(b), math.sin(b))))
    return curves


def svg_segments(d):
    """Absolute move, line, curve and close segments of the SVG path commands the category icons use."""
    tokens = _PATH_TOKEN.findall(d)
    sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "A": 7, "Z": 0}
    segments, x, y, start, index, command = [], 0.0, 0.0, (0.0, 0.0), 0, ""
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
        kind, relative = command.upper(), command.islower()
        values = [float(value) for value in tokens[index:index + sizes[kind]]]
        index += sizes[kind]
        if kind == "Z":
            segments.append(("Z",))
            x, y = start
            continue
        if kind == "H":
            x = values[0] + (x if relative else 0)
        elif kind == "V":
            y = values[0] + (y if relative else 0)
        if kind in "HV":
            segments.append(("L", x, y))
            continue
        if relative:
            for position in range(0, len(values), 2) if kind != "A" else (5,):
                values[position] += x
                values[position + 1] += y
        if kind == "A":
            segments.extend(_arc(x, y, *values))
        else:
            segments.append((kind, *values))
        x, y = values[-2:]
        if kind == "M":
            start = (x, y)
            command = "l" if relative else "L"
    return segments


def _number(value):
    return f"{value:,}"


def _size(value):
    for unit, name in ((10 ** 9, "GB"), (10 ** 6, "MB"), (10 ** 3, "KB")):
        if value >= unit:
            tenths = (value * 10 + unit // 2) // unit
            return (str((value + unit // 2) // unit) if tenths >= 100 else f"{tenths // 10}.{tenths % 10}") + " " + name
    return ""


def phone_catalog(sections, drive=None, tasks=(), articles=()):
    """sections: categories with their rows. tasks: urgent tasks with every guide present. articles: WikiMed titles."""
    spec = layout()["phone_catalog"]
    width, height, margin = spec["page"]
    usable = width - 2 * margin
    for name, file in ((FONT, "Vera.ttf"), (BOLD, "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, file))
    buffer = BytesIO()
    doc = Canvas(buffer, pagesize=(width, height), invariant=True)
    doc.setTitle(spec["brand"])
    doc.setAuthor("Offline Wandering Library")
    y = 0

    def measure(value, size, bold=False):
        return pdfmetrics.stringWidth(value, BOLD if bold else FONT, size)

    def text(value, x, top, size, color="ink", bold=False, fit=None):
        # A long name shrinks instead of wrapping, so it stays one selectable run.
        measured = measure(value, size, bold)
        if fit and measured > fit:
            size = size * fit / measured
        doc.setFillColor(HexColor(spec.get(color, color)))
        doc.setFont(BOLD if bold else FONT, size)
        doc.drawString(x, height - top, value)

    def clip(value, size, limit, bold=False, more=False):
        if not more and measure(value, size, bold) <= limit:
            return value
        while value and measure(value + "…", size, bold) > limit:
            value = value[:-1]
        return value.rstrip() + "…"

    def wrap(value, size, limit, bold=False, most=0):
        result = []
        for word in value.split():
            if result and measure(result[-1] + " " + word, size, bold) <= limit:
                result[-1] += " " + word
            else:
                result.append(word)
        if most and len(result) > most:
            result = result[:most - 1] + [clip(result[most - 1], size, limit, bold, True)]
        return result

    def box(x, top, wide, high, color, radius=0):
        doc.setFillColor(HexColor(spec.get(color, color)))
        doc.roundRect(x, height - top - high, wide, high, radius, stroke=0, fill=1)

    def rule(top):
        doc.setStrokeColor(HexColor(spec["line"]))
        doc.setLineWidth(1)
        doc.line(margin, height - top, width - margin, height - top)

    def icon(d, x, top, size, color, stroke=2):
        scale = size / 24
        path = doc.beginPath()
        for kind, *values in svg_segments(d):
            points = [(x + values[i] * scale, height - top - values[i + 1] * scale) for i in range(0, len(values), 2)]
            if kind == "M":
                path.moveTo(*points[0])
            elif kind == "L":
                path.lineTo(*points[0])
            elif kind == "C":
                path.curveTo(*points[0], *points[1], *points[2])
            else:
                path.close()
        doc.setStrokeColor(HexColor(spec.get(color, color)))
        doc.setLineWidth(stroke * scale)
        doc.setLineCap(1)
        doc.setLineJoin(1)
        doc.drawPath(path, stroke=1, fill=0)

    def area(x, top, wide, high):
        return x, height - top - high, x + wide, height - top

    def jump(name, x, top, wide, high):
        doc.linkRect("", name, area(x, top, wide, high), thickness=0)

    def leave(url, x, top, wide, high):
        doc.linkURL(url, area(x, top, wide, high), kind="URI")

    def mark(name, title=None):
        doc.bookmarkPage(name)
        if title:
            doc.addOutlineEntry(title, name)

    def filled(template, value):
        return template.replace("{count}", str(value)).replace("{name}", str(value)).replace("{names}", str(value))

    def target(path, kind):
        """Where a title leads: the PDF itself, the folder of any other file, or Files when the drive is unknown."""
        if not drive:
            return spec["files_app"]
        if kind == "pdf":
            return files_link(spec, drive, path)
        return files_link(spec, drive, path.rsplit("/", 1)[0], False)

    def footer():
        text(str(doc.getPageNumber()), margin, height - 12, 9, "muted")
        doc.showPage()

    # The section being written, redrawn at the top of each page it continues onto.
    section = {}

    def start(title, back=None, blurb="", badge=None):
        section.update(title=title, back=back or ("home", spec["home"]), first=True)
        return heading(blurb, badge)

    def heading(blurb="", badge=None):
        name, label = section["back"]
        text(label, margin, 30, 12.5, "accent", fit=usable * 0.6)
        jump(name, 0, 4, width * 0.7, 40)
        if not section["first"]:
            title = clip(section["title"], 10.5, usable * 0.5)
            text(title, width - margin - measure(title, 10.5), 30, 10.5, "muted")
            return 50
        section["first"] = False
        indent = 0
        if badge:
            box(margin, 50, 40, 40, badge[0], 11)
            if badge[1]:
                icon(badge[1], margin + 9, 59, 22, "white")
            indent = 52
        top = 50
        for line in wrap(section["title"], 21, usable - indent, True, 3):
            top += 25
            text(line, margin + indent, top - 4, 21, "ink", True)
        for line in wrap(blurb, 11, usable - indent, most=3):
            top += 14
            text(line, margin + indent, top, 11, "muted")
        return max(top, 90 if badge else 0) + 16

    def need(high):
        nonlocal y
        if y + high > height - 28:
            footer()
            y = heading()

    def parts(path):
        """A file's folder and name; a multi-part book's path is its folder."""
        if path.endswith("/"):
            return path[:-1], ""
        folder, _, name = path.rpartition("/")
        return folder, name

    def trail_lines(path, limit, loud):
        """Where the file is. Loud, the filename stands alone above its folders, because following them is the only way
        to the file; otherwise one quiet line serves when a link fails."""
        folder, name = parts(path)
        folders = folder.replace("/", " › ")
        if loud or not name:
            return ([name] if name else []), wrap(folders, 9.5, limit)
        return [], wrap(folders + " › " + name, 9.5, limit)

    def trail(path, x, top, limit, loud):
        names, folders = trail_lines(path, limit, loud)
        for name in names:
            text(name, x, top, 11.5, fit=limit)
            top += 15
        for line in folders:
            text(line, x, top, 9.5, "muted")
            top += 12.5
        return top

    def trail_height(path, limit, loud):
        names, folders = trail_lines(path, limit, loud)
        return 15 * len(names) + 12.5 * len(folders)

    loud = not drive
    # A drive without a single urgent guide shows no urgent block, rather than eight empty tiles.
    tasks = list(tasks) if any(task["guides"] for task in tasks) else []
    count = sum(len(group["rows"]) for group in sections)
    topics = {}
    for group in sections:
        for row in group["rows"]:
            for topic in row.get("topics", []):
                topics.setdefault(topic, []).append(row)
    topic_names = sorted(topics, key=lambda name: (name.lower(), name))
    seen = set()
    articles = [row for row in articles if not (row["title"] in seen or seen.add(row["title"]))]
    articles.sort(key=lambda row: (row["title"].lower(), row["title"]))
    volumes = {row["title"]: row for row in articles}
    books = [row for group in sections for row in group["rows"] if row.get("chapters")]
    book_names = {id(row): f"book-{index}" for index, row in enumerate(books)}
    has_zim = any(row["format"] == "zim" for group in sections for row in group["rows"])

    def open_row(row, x, top, wide, high):
        if row.get("chapters"):
            jump(book_names[id(row)], x, top, wide, high)
        else:
            leave(target(row["path"], row["format"]), x, top, wide, high)

    # Home: search, the urgent tasks and the ways into the library, on one screen.
    mark("home", spec["title"])
    text(spec["brand"].upper(), margin, 30, 9.5, "muted", True)
    text(spec["title"], margin, 62, 26, "ink", True)
    box(margin, 78, usable, 58, "field", 14)
    box(margin + 11, 89, 36, 36, "white", 18)
    icon(spec["search_icon"], margin + 19, 97, 20, "accent", 2.4)
    text(spec["search"][0], margin + 58, 101, 14, "ink", True)
    for index, line in enumerate(wrap(spec["search"][1], 10.5, usable - 70, most=2)):
        text(line, margin + 58, 116 + 13 * index, 10.5, "muted")
    jump("help", margin, 78, usable, 58)
    y = 160
    if tasks:
        text(spec["urgent"].upper(), margin, y, 10, "urgent_color", True)
        y += 10
        tile, tall = (usable - 10) / 2, 52
        for index, task in enumerate(tasks):
            x, top = margin + (index % 2) * (tile + 10), y + (index // 2) * (tall + 8)
            guide = task["guides"][0] if task["guides"] else None
            box(x, top, tile, tall, "urgent_color" if guide else "field", 10)
            ink = "white" if guide else "muted"
            lines = wrap(task["task"], 12.5, tile - 20, True, 2)
            detail = spec["no_guide"]
            if guide:
                detail = guide["short"] + (" · " + filled(spec["page_number"], guide["page"]) if guide["page"] else "")
            first = top + (21 if len(lines) == 1 else 16)
            for line in lines:
                text(line, x + 10, first, 12.5, ink, True)
                first += 14
            text(clip(detail, 9.5, tile - 20), x + 10, top + tall - (11 if len(lines) == 1 else 7), 9.5, ink)
            if guide and drive:
                leave(target(guide["path"], guide["format"]), x, top, tile, tall)
            elif guide:
                jump(f"task-{index}", x, top, tile, tall)
        y += (len(tasks) + 1) // 2 * (tall + 8)
    text(spec["library"].upper(), margin, y + 18, 10, "muted", True)
    y += 26
    doors = [("browse", spec["browse"], count)] if sections else []
    if topic_names:
        doors.append(("topics", spec["topics"], len(topic_names)))
    if articles:
        doors.append(("articles", spec["articles"], len(articles)))
    doors.append(("help", spec["help"], 0))
    if not sections:
        text(spec["empty"], margin, y + 18, 12.5)
        y += 30
    for name, (title, detail), amount in doors:
        rule(y)
        text(title, margin, y + 19, 13.5, "ink", True)
        text(filled(detail, _number(amount)), margin, y + 34, 10.5, "muted")
        text("›", width - margin - 10, y + 28, 20, "muted")
        jump(name, margin, y, usable, 44)
        y += 44
    rule(y)
    for line in wrap(spec["hint_files" if loud else "hint_book"], 10, usable):
        y += 15
        text(line, margin, y + 4, 10, "muted")
    footer()

    # Browse: one row for each subject.
    if sections:
        mark("browse", spec["browse"][0])
        y = start(spec["browse"][0])
        for group in sections:
            need(54)
            rule(y)
            box(margin, y + 9, 36, 36, group["color"], 10)
            if group.get("icon"):
                icon(group["icon"], margin + 7, y + 16, 22, "white")
            text(group["name"], margin + 48, y + 24, 14, "ink", True)
            detail = _number(len(group["rows"])) + " " + group["unit"] + ("" if len(group["rows"]) == 1 else "s")
            text(clip(detail + " · " + group["blurb"], 10.5, usable - 70), margin + 48, y + 39, 10.5, "muted")
            text("›", width - margin - 10, y + 33, 20, "muted")
            jump("cat-" + group["id"], margin, y, usable, 54)
            y += 54
        rule(y)
        footer()

    # Urgent help: every guide for each task, with the words a person might search for.
    if tasks:
        mark("urgent", spec["urgent_title"])
        y = start(spec["urgent_title"], blurb=spec["urgent_blurb"])
        for index, task in enumerate(tasks):
            words = wrap(spec["search_words"] + ", ".join(task["keywords"]), 9.5, usable, most=2)
            need(40 + 12.5 * len(words) + 60)
            mark(f"task-{index}")
            rule(y)
            text(task["task"], margin, y + 22, 15, "ink", True)
            y += 26
            for line in words:
                y += 12.5
                text(line, margin, y, 9.5, "muted")
            y += 6
            if not task["guides"]:
                text(spec["no_guide"] + ".", margin, y + 14, 11.5, "muted")
                y += 20
            for guide in task["guides"]:
                is_zim = guide["format"] == "zim"
                title = wrap(guide["title"], 13, usable, most=2)
                detail = " · ".join(filter(None, [filled(spec["go_to_page"], guide["page"]) if guide["page"] else "",
                                                  guide["hint"]]))
                if is_zim:
                    detail = filled(spec["zim_lookup"], " / ".join(guide["articles"])) if guide["articles"] else spec["zim"]
                need(17 * len(title) + (14 if detail else 0) + trail_height(guide["path"], usable, loud) + 12)
                top = y
                for line in title:
                    y += 17
                    text(line, margin, y, 13, "accent")
                if detail:
                    y += 14
                    text(clip(detail, 10.5, usable), margin, y, 10.5, "ink")
                leave(target(guide["path"], guide["format"]), margin, top, usable, y - top + 5)
                y = trail(guide["path"], margin, y + 13.5, usable, loud) - 2
            for name in dict.fromkeys(task["lookups"]):
                if name not in volumes:
                    continue
                need(46)
                top = y
                text("WikiMed: " + name, margin, y + 17, 13, "accent", fit=usable)
                text(clip(filled(spec["volume"], volumes[name]["volume"]), 10.5, usable), margin, y + 31, 10.5, "ink")
                leave(target(volumes[name]["path"], "pdf"), margin, top, usable, 36)
                y += 40
            y += 8
        footer()

    # Topics: finer than the subjects, each leading straight to its books.
    if topic_names:
        mark("topics", spec["topics"][0])
        y = start(spec["topics"][0])
        for name in topic_names:
            rows = topics[name]
            shown = rows[:6]
            need(32 + 22 * len(shown) + (15 if len(rows) > len(shown) else 0))
            rule(y)
            text(name, margin, y + 20, 13.5, "ink", True, fit=usable)
            y += 26
            for row in shown:
                text(clip(row["title"], 12.5, usable - 8), margin + 8, y + 15, 12.5, "accent")
                open_row(row, margin, y, usable, 22)
                y += 22
            if len(rows) > len(shown):
                text(filled(spec["more"], len(rows) - len(shown)), margin + 8, y + 11, 10.5, "muted")
                y += 15
            y += 6
        footer()

    # Subjects: each book with what it covers, then the chapter lists of its multi-part books.
    for group in sections:
        mark("cat-" + group["id"], group["name"])
        y = start(group["name"], blurb=group["blurb"], badge=(group["color"], group.get("icon")))
        for index, row in enumerate(group["rows"]):
            chapters = row.get("chapters")
            title = wrap(row["title"], 15, usable - (18 if chapters else 0), True, 3)
            detail = clip(" · ".join(filter(None, [row["kind"], _size(row["bytes"]), row.get("publisher")])), 10.5, usable)
            summary = wrap(row.get("summary") or "", 11.5, usable, most=3)
            labels = wrap(spec["covers"] + " · ".join(row["labels"]), 10.5, usable, most=2) if row.get("labels") else []
            if row.get("terms"):
                labels += wrap(spec["inside"] + " · ".join(row["terms"]), 10.5, usable, most=2)
            note = [spec["zim"]] if row["format"] == "zim" else []
            high = (20 + 19 * len(title) + 15 + 15 * len(summary + note) + 13.5 * len(labels)
                    + trail_height(row["path"], usable, loud) + 12)
            need(high)
            if chapters:
                mark("row-" + book_names[id(row)])
            rule(y)
            top = y
            y += 4
            for line in title:
                y += 19
                text(line, margin, y, 15, "accent", True)
            if chapters:
                text("›", width - margin - 10, top + 25, 20, "muted")
            y += 15
            text(detail, margin, y, 10.5, "muted")
            open_row(row, margin, top, usable, y - top + 5)
            for line in summary + note:
                y += 15
                text(line, margin, y, 11.5)
            for line in labels:
                y += 13.5
                text(line, margin, y, 10.5, "muted")
            y = trail(row["path"], margin, y + 15, usable, loud) - 3
        footer()
        for row in group["rows"]:
            chapters = row.get("chapters")
            if not chapters:
                continue
            name = book_names[id(row)]
            mark(name)
            y = start(row["title"], ("row-" + name, filled(spec["back"], group["name"])),
                      " · ".join(filter(None, [row["kind"], row.get("publisher")])))
            y = trail(row["path"], margin, y - 2, usable, False) + 4
            for chapter in chapters:
                title = wrap(chapter["title"], 13.5, usable, most=3)
                inside = wrap(" · ".join(chapter["terms"]), 9.5, usable, most=2) if chapter.get("terms") else []
                high = 9 + 17 * len(title) + 12.5 * len(inside) + (14 if loud else 0) + 7
                need(high)
                rule(y)
                top = y
                y += 6
                for line in title:
                    y += 17
                    text(line, margin, y, 13.5, "accent")
                for line in inside:
                    y += 12.5
                    text(line, margin, y, 9.5, "muted")
                if loud:
                    y += 14
                    text(chapter["path"].rpartition("/")[2], margin, y, 10.5, fit=usable)
                leave(target(chapter["path"], chapter["format"]), margin, top, usable, high)
                y += 10
            footer()

    # Medical articles: every WikiMed title, so a search for a condition lands on the volume that holds it.
    if articles:
        mark("articles", spec["articles"][0])
        y = start(spec["articles"][0], blurb=spec["articles_blurb"])
        letters = list(dict.fromkeys(row["title"][:1].upper() for row in articles))
        cell = usable / 13
        for index, letter in enumerate(letters):
            x, top = margin + (index % 13) * cell, y + (index // 13) * 30
            text(letter, x + (cell - measure(letter, 14, True)) / 2, top + 20, 14, "accent", True)
            jump("letter-" + letter, x, top, cell, 30)
        y += ((len(letters) + 12) // 13) * 30 + 8
        current = ""
        for row in articles:
            letter = row["title"][:1].upper()
            if letter != current:
                current = letter
                need(34 + 20)
                mark("letter-" + letter)
                rule(y)
                text(letter, margin, y + 22, 15, "ink", True)
                y += 30
            need(20)
            title = clip(row["title"], 12, usable * 0.62)
            text(title, margin, y + 13, 12, "accent")
            volume = clip(row["volume"], 9.5, usable * 0.36)
            text(volume, width - margin - measure(volume, 9.5), y + 13, 9.5, "muted")
            leave(target(row["path"], "pdf"), margin, y, usable, 20)
            y += 20
        footer()

    # Help: the four things a reader needs to know, in order.
    mark("help", spec["help"][0])
    y = start(spec["help"][0])
    steps = [spec["steps"][0], spec["open_files" if loud else "open_book"], *spec["steps"][1:], *([spec["kiwix"]] if has_zim else [])]
    for number, (lead, body) in enumerate(steps, 1):
        lines = wrap(body, 12, usable - 34)
        need(34 + 16 * len(lines))
        rule(y)
        box(margin, y + 12, 22, 22, "field", 11)
        digit = str(number)
        text(digit, margin + 11 - measure(digit, 11, True) / 2, y + 27, 11, "ink", True)
        text(lead, margin + 34, y + 27, 13.5, "ink", True)
        y += 32
        for line in lines:
            y += 16
            text(line, margin + 34, y, 12)
        y += 12
    footer()
    doc.save()
    return buffer.getvalue()
