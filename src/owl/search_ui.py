"""Entry points for the local reader and its search redirect."""
from pathlib import Path


SEARCH_CSP = (
    "default-src 'none'; script-src 'self' file: blob: 'wasm-unsafe-eval'; style-src 'unsafe-inline'; "
    "img-src 'self' file: data: blob:; media-src blob:; font-src blob:; connect-src 'none'; object-src 'none'; "
    "frame-src 'self' file: blob:; "
    "base-uri 'none'; form-action 'none'"
)


def render_search_page() -> str:
    """Retain the old search address as a redirect to the reader."""
    return Path(__file__).with_name("templates").joinpath("search.html").read_text(encoding="utf-8")
