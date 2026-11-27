"""A searchable, phone-sized PDF index of the documents actually on the drive."""
import json
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

FONT = "OWL-Vera"
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


def phone_drive(root, saved=None):
    """Where an iPhone finds the folder holding LIBRARY, as saved in BUILD_INFO.json: {"path", "folder"} or None.

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
    """The phone_drive record in a library's previous BUILD_INFO.json, or None."""
    try:
        info = json.loads((Path(library) / "BUILD_INFO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info.get("iphone_drive") if isinstance(info, dict) else None


def files_link(spec, drive, path):
    """A Files app link that opens the PDF in place on an iPhone; Preview asks once before leaving."""
    return "shareddocuments://" + quote(spec["files_root"] + drive + "/" + path, safe="/") + "?open"


def phone_catalog(groups, drive=None):
    spec = layout()["phone_catalog"]
    width, height, margin = spec["page"]
    usable = width - 2 * margin
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, "Vera.ttf"))
    buffer = BytesIO()
    doc = Canvas(buffer, pagesize=(width, height), invariant=True)
    doc.setTitle(spec["title"])
    doc.setAuthor("Offline Wandering Library")

    def text(value, y, size, color="ink"):
        # Keep a basename in one selectable text run even on a narrow page.
        measured = pdfmetrics.stringWidth(value, FONT, size)
        fitted = min(size, size * usable / measured) if measured else size
        doc.setFillColor(HexColor(spec[color]))
        doc.setFont(FONT, fitted)
        doc.drawString(margin, height - y, value)

    def lines(value, size):
        result = []
        for word in value.split():
            if result and pdfmetrics.stringWidth(result[-1] + " " + word, FONT, size) <= usable:
                result[-1] += " " + word
            else:
                result.append(word)
        return result

    def rule(y):
        doc.setStrokeColor(HexColor(spec["line"]))
        doc.line(margin, height - y, width - margin, height - y)

    def footer():
        text(str(doc.getPageNumber()), height - 16, 10, "muted")
        doc.showPage()

    doc.bookmarkPage("contents")
    text(spec["brand"], 36, 11, "muted")
    text(spec["title"], 78, 29)
    y = 110
    for paragraph in spec["intro"] + [spec["open_book" if drive else "open_files"]]:
        for line in lines(paragraph, 13):
            text(line, y, 13)
            y += 18
        y += 6
    for identity, name, rows in groups:
        rule(y)
        text(f"{name}  ({len(rows)})", y + 23, 16, "accent")
        doc.linkRect("", identity, (margin, height - y - 36, width - margin, height - y), thickness=0)
        y += 36
    if not groups:
        text(spec["empty"], y + 20, 14)
    footer()

    def section(name):
        text(spec["contents"], 33, 12, "accent")
        doc.linkRect("", "contents", (margin, height - 47, width - margin, height - 12), thickness=0)
        text(name, 76, 23)
        return 100

    for identity, name, rows in groups:
        doc.bookmarkPage(identity)
        doc.addOutlineEntry(name, identity)
        y = section(name)
        for row in rows:
            title = lines(row["title"], 16)
            folder, basename = row["path"].rsplit("/", 1)
            folders = lines(folder.replace("/", " › "), 11)
            row_height = 20 * len(title) + 14 * len(folders) + 42
            if y + row_height > height - 32 and y > 100:
                footer()
                y = section(name)
            rule(y)
            y += 22
            is_pdf = row["format"] == "pdf"
            top = y - 22
            for line in title:
                text(line, y, 16, "accent" if is_pdf else "ink")
                y += 20
            if is_pdf:
                area = (margin, height - y + 10, width - margin, height - top)
                # Without the drive's volume UUID, the title opens Files at its last folder.
                target = files_link(spec, drive, row["path"]) if drive else spec["files_app"]
                doc.linkURL(target, area, kind="URI")
            text(basename, y, 13)
            y += 17
            for line in folders:
                text(line, y, 11, "muted")
                y += 14
            y += 3
        footer()
    doc.save()
    return buffer.getvalue()
