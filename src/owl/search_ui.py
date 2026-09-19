"""Render the same automatic offline search interface on both entry pages."""
from __future__ import annotations

from html import escape
from pathlib import Path


SEARCH_CSP = (
    "default-src 'none'; script-src 'self' file:; style-src 'unsafe-inline'; "
    "img-src 'self' file: data:; connect-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)
_START = "<!-- OWL_SEARCH_WIDGET_START -->"
_END = "<!-- OWL_SEARCH_WIDGET_END -->"


def render_search_page() -> str:
    """Return LIBRARY/SEARCH.html, including its shared widget."""
    template = Path(__file__).with_name("templates").joinpath("search.html").read_text(encoding="utf-8")
    return template.replace("__OWL_SEARCH_CSP__", escape(SEARCH_CSP, quote=True)).replace("__OWL_LIBRARY_PREFIX__", "")


def render_search_widget(library_prefix: str = "") -> str:
    """Render local links from either outer START_HERE or inner SEARCH.html."""
    if library_prefix not in {"", "LIBRARY/"}:
        raise ValueError("Search library prefix must be empty or LIBRARY/")
    page = Path(__file__).with_name("templates").joinpath("search.html").read_text(encoding="utf-8")
    if page.count(_START) != 1 or page.count(_END) != 1:
        raise ValueError("Search template must contain exactly one shared widget")
    _, remainder = page.split(_START, 1)
    widget, _ = remainder.split(_END, 1)
    if not widget.strip():
        raise ValueError("Search widget is empty")
    return widget.strip().replace("__OWL_LIBRARY_PREFIX__", library_prefix)
