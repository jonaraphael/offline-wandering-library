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
    """Return the standalone search page, including its shared widget."""
    template = Path(__file__).with_name("templates").joinpath("search.html").read_text(encoding="utf-8")
    return template.replace("__OWL_SEARCH_CSP__", escape(SEARCH_CSP, quote=True))


def render_search_widget() -> str:
    """Return the root-relative widget and runtime reference for START_HERE."""
    page = render_search_page()
    if page.count(_START) != 1 or page.count(_END) != 1:
        raise ValueError("Search template must contain exactly one shared widget")
    _, remainder = page.split(_START, 1)
    widget, _ = remainder.split(_END, 1)
    if not widget.strip():
        raise ValueError("Search widget is empty")
    return widget.strip()
