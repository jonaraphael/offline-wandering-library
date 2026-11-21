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


def emergency_directory(assets, href):
    by_id = {asset["id"]: asset for asset in assets}
    escape = html.escape
    rows = []
    for task, candidates in layout()["tasks"]:
        for aid, *details in candidates:
            if aid not in by_id:
                continue
            asset = by_id[aid]
            fragment, hint = (details + ["", ""])[:2]
            destination = asset["destination"]
            rows.append(render("task_link", task=escape(task), title=escape(asset["title"]),
                               href=href(destination) + escape(fragment),
                               path=escape(f"LIBRARY/{destination}"),
                               hint=f" · {escape(hint)}" if hint else ""))
            break
        else:
            rows.append(render("task_missing", task=escape(task)))
    return render("emergency", rows="".join(rows))
