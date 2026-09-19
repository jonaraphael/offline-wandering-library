"""One visible entry page beside a single folder of library content.

Catalog destinations and private managed-file records are relative to LIBRARY.
Checksum entries are relative to the outer drive directory.
"""
from pathlib import Path

from .safety import SafetyError, safe_path, validate_relative

LIBRARY_DIR = "LIBRARY"
START_PAGE = "START_HERE.html"


def content_root(root: Path) -> Path:
    return safe_path(root, LIBRARY_DIR)


def managed_path(library: Path, relative: str) -> Path:
    if relative == START_PAGE:
        return safe_path(library.parent, START_PAGE)
    return safe_path(library, relative)


def checksum_name(relative: str) -> str:
    validate_relative(relative)
    result = relative if relative == START_PAGE else f"{LIBRARY_DIR}/{relative}"
    validate_relative(result)
    return result


def logical_name(relative: str) -> str:
    validate_relative(relative)
    if relative == START_PAGE:
        return relative
    prefix = LIBRARY_DIR + "/"
    if not relative.startswith(prefix) or not relative[len(prefix):]:
        raise SafetyError(f"File is outside the OWL library layout: {relative}")
    logical = relative[len(prefix):]
    if logical.casefold() == START_PAGE.casefold():
        raise SafetyError("The start page belongs beside LIBRARY, not inside it")
    return logical
