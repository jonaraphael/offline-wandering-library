"""Shared reader markup and ordered offline emergency routes."""
from functools import lru_cache
import json
from pathlib import Path
import re


TEMPLATES = Path(__file__).with_name("templates")


@lru_cache(maxsize=1)
def layout():
    return json.loads((TEMPLATES / "offline-layout.json").read_text(encoding="utf-8"))


def render(template, **values):
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda token: values.get(token[1], ""), template)


def emergency_routes(rows):
    """Use the first present file for each task, retaining precise locations."""
    by_id = {row["id"]: row for row in rows}
    tasks = []
    for title, candidates in layout()["tasks"]:
        for identity, *details in candidates:
            if identity not in by_id:
                continue
            fragment, hint, articles = details + ["", "", []][len(details):]
            row = by_id[identity]
            tasks.append({**row, "task": title, "href": row["href"] + fragment, "hint": hint,
                          "articles": [name for name, _ in articles],
                          "articlePaths": [path for _, path in articles]})
            break
        else:
            tasks.append({"task": title})
    return tasks
