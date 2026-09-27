"""Ordinary HTML lessons referencing pinned media and captions directly.

The builder acquires media as ordinary catalog assets using its streaming
downloader. This adapter never reads a video into memory, duplicates it, fetches
a URL, installs a lesson runtime, or silently replaces an unsupported exercise.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from ..safety import atomic_write, safe_path
from .corpus import (CorpusError, check_source_identities, page, relative_link,
                     static_html, verify_sources)


VERSION = 1
MEDIA_TYPES = {"video/mp4", "video/webm", "video/ogg", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav"}
MAX_CAPTION_BYTES = 4 * 1024 * 1024


def lesson_gaps(selection: dict) -> list[str]:
    """Metadata-only audit, also used to refuse incomplete build recipes."""
    gaps, seen = [], set()
    lessons = selection.get("lessons", [])
    if not lessons:
        gaps.append("No frozen lesson/course selections")
    for lesson in lessons:
        lesson_id = lesson.get("id", "<missing>")
        if not isinstance(lesson_id, str) or not lesson_id or lesson_id in seen:
            gaps.append(f"Missing or duplicate lesson ID: {lesson_id}")
        seen.add(lesson_id)
        for key in ("title", "course_id", "source_url", "license", "attribution"):
            if not lesson.get(key):
                gaps.append(f"{lesson_id}: missing {key}")
        if urlsplit(lesson.get("source_url", "")).scheme != "https":
            gaps.append(f"{lesson_id}: source_url must identify an HTTPS publisher page")
        if lesson.get("language") != "en":
            gaps.append(f"{lesson_id}: English lesson language is not established")
        if lesson.get("kind", "article") not in {"article", "video", "audio"}:
            gaps.append(f"{lesson_id}: unsupported essential lesson format {lesson.get('kind')}")
        for gap in lesson.get("unsupported_essential", []):
            gaps.append(f"{lesson_id}: unsupported essential dependency {gap}")
        if not lesson.get("content_html"):
            gaps.append(f"{lesson_id}: missing lesson context/text")
        if lesson.get("kind") in {"video", "audio"} and not lesson.get("media"):
            gaps.append(f"{lesson_id}: missing original media")
        for media in lesson.get("media", []):
            if not media.get("asset_id") or media.get("mime_type") not in MEDIA_TYPES:
                gaps.append(f"{lesson_id}: unsupported or unpinned ordinary media")
            if not media.get("captions"):
                gaps.append(f"{lesson_id}: no pinned English captions/transcript")
            elif not any(caption.get("language") == "en" for caption in media["captions"]):
                gaps.append(f"{lesson_id}: missing English captions")
            for caption in media.get("captions", []):
                if not all(caption.get(key) for key in ("asset_id", "language", "label")):
                    gaps.append(f"{lesson_id}: incomplete caption metadata")
    return sorted(set(gaps))


def render(recipe: dict, sources: dict[str, Path], assets: dict[str, dict], output_dir: Path, *, output_writer=None) -> dict[str, Path]:
    selection = recipe.get("selection", {})
    if selection.get("reviewed") is not True:
        raise CorpusError("Lessons require recorded selection and completeness review")
    gaps = lesson_gaps(selection)
    if gaps:
        raise CorpusError("Lesson gaps: " + "; ".join(gaps[:12]))
    identities = verify_sources(recipe, sources, assets)
    dependencies = selection.get("dependencies", {})
    if any(value not in identities for value in dependencies.values()):
        raise CorpusError("All lesson illustrations must be pinned source_asset_ids")
    lessons = {lesson["id"]: lesson for lesson in selection["lessons"]}
    outputs = {asset_id: asset for asset_id, asset in assets.items() if asset.get("generation", {}).get("recipe_id") == recipe["id"]}
    by_lesson, destinations = {}, set()
    for asset in outputs.values():
        lesson_id = asset["generation"].get("lesson_id")
        destination = asset["destination"].casefold()
        if lesson_id not in lessons or lesson_id in by_lesson or destination in destinations:
            raise CorpusError("Outputs must declare each unique frozen lesson exactly once")
        by_lesson[lesson_id] = asset
        destinations.add(destination)
    if set(by_lesson) != set(lessons):
        raise CorpusError("Frozen lesson IDs and predeclared generated outputs do not match")
    result = {}
    for lesson_id in sorted(lessons):
        lesson, asset = lessons[lesson_id], by_lesson[lesson_id]
        body = f'<p>Course: {escape(lesson["course_id"])} · Lesson: {escape(lesson_id)}</p>'
        body += static_html(lesson["content_html"], asset, assets, dependencies)
        for media in lesson.get("media", []):
            media_id = media["asset_id"]
            if media_id not in identities:
                raise CorpusError(f"Media is not a pinned recipe source: {media_id}")
            tag = media["mime_type"].split("/")[0]
            body += f'<{tag} controls preload="metadata"><source src="{escape(relative_link(asset, assets[media_id]), quote=True)}" type="{escape(media["mime_type"], quote=True)}">'
            caption_texts = []
            for caption in media["captions"]:
                caption_id = caption["asset_id"]
                if caption_id not in identities:
                    raise CorpusError(f"Caption is not a pinned recipe source: {caption_id}")
                path = Path(sources[caption_id])
                if path.stat().st_size > MAX_CAPTION_BYTES:
                    raise CorpusError(f"Caption exceeds 4 MiB: {caption_id}")
                text = path.read_text(encoding="utf-8-sig")
                if not text.startswith("WEBVTT") or "-->" not in text:
                    raise CorpusError(f"Caption requires complete ordinary WebVTT cues: {caption_id}")
                caption_texts.append((caption, text))
                # Small text-only VTT tracks must be embedded: Chromium treats
                # separate file:// tracks as unique origins and rejects them.
                encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                body += f'<track kind="captions" src="data:text/vtt;base64,{encoded}" srclang="{escape(caption["language"], quote=True)}" label="{escape(caption["label"], quote=True)}"' + (' default' if caption["language"] == "en" else '') + '>'
            body += f'Your browser cannot play this media. <a href="{escape(relative_link(asset, assets[media_id]), quote=True)}">Open the original media file</a>.</{tag}>'
            for caption, text in caption_texts:
                # The complete cues remain readable even where file:// browser
                # restrictions prevent the native caption track from loading.
                body += f'<details><summary>{escape(caption["label"])} timed transcript</summary><p><a href="{escape(relative_link(asset, assets[caption["asset_id"]]), quote=True)}">Original WebVTT caption file</a></p><pre>{escape(text)}</pre></details>'
        body += f'<footer><p>{escape(lesson["attribution"])} · {escape(lesson["license"])}</p><a href="{escape(lesson["source_url"], quote=True)}" rel="noreferrer noopener">Original publisher lesson (requires internet)</a></footer>'
        path = safe_path(output_dir, asset["destination"])
        (output_writer or atomic_write)(path, page(lesson["title"], body, media=True))
        result[asset["id"]] = path
    check_source_identities(sources, identities)
    return result
