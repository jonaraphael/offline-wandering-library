"""Shared static document template and prioritized offline emergency routes."""

from functools import lru_cache
import html
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def layout():
    return json.loads((Path(__file__).with_name("templates") / "offline-layout.json").read_text(encoding="utf-8"))


def render(template, **values):
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda token: values.get(token[1], ""), layout()[template])


def emergency_routes(assets, href, archive_href):
    """Render the task directory and the article locators it links to."""
    by_id = {asset["id"]: asset for asset in assets}
    escape = html.escape
    rows, archive_rows = [], []
    for index, (task, candidates) in enumerate(layout()["tasks"], 1):
        for aid, *details in candidates:
            if aid not in by_id:
                continue
            asset = by_id[aid]
            fragment, hint = (details + ["", ""])[:2]
            entries = details[2] if len(details) > 2 else []
            destination = asset["destination"]
            path = escape(f"LIBRARY/{destination}")
            title = asset["title"]
            target = href(destination) + escape(fragment)
            if entries:
                anchor = f"emergency-{index}"
                target = href("INDEX/sections.html") + "#" + anchor
                archive_rows.append(render("archive_task", anchor=anchor,
                    task=escape(task), href=archive_href(destination), title=escape(title), path=path,
                    entries="".join(render("archive_task_entry", title=escape(name), path=escape(locator))
                                    for name, locator in entries)))
                title = title + ": " + " / ".join(name for name, _ in entries)
                hint = "opens in the Kiwix app"
            rows.append(render("task_link", task=escape(task), title=escape(title), icon=layout()["task_icons"][index - 1],
                               href=target, path=path, hint=f" · {escape(hint)}" if hint else ""))
            break
        else:
            rows.append(render("task_missing", task=escape(task)))
    return render("emergency", rows="".join(rows)), "".join(archive_rows)
