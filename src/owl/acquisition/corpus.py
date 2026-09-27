"""Bounded, offline Stack Exchange selection and ordinary HTML rendering.

The adapter consumes pinned, unpacked Posts/Comments/Users/PostLinks XML files.
Selection is reviewed metadata, never a command to fetch a dump.  A recipe uses
``selection.input_roles`` and ``selection.questions`` (id, bucket); generated
catalog assets carry ``generation.question_id`` and a matching ``legacy`` flag.
"""
from __future__ import annotations

from contextlib import contextmanager
from html import escape
from html.parser import HTMLParser
import heapq
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sqlite3
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

from ..export_direct import ATTRS, DROP_CONTENT, TAGS, VOID
from ..safety import atomic_write, reject_symlinks, safe_path, sha256_file


VERSION = 2
MAX_TEXT = 16 * 1024 * 1024
LEGACY_WARNING = "LEGACY — MAY APPLY ONLY TO OLD SYSTEMS"
DEFAULT_DURABLE_TAGS = frozenset("c c++ python java c# bash shell javascript html css posix unix linux sql sqlite git gcc algorithms data-structures unicode regex sockets multithreading memory-management make gdb compression serial-port filesystems".split())
DEFAULT_LEGACY_TAGS = frozenset("python-2.x python-2.7 java-6 java-7 java-8 windows-xp windows-7 bios mbr .net-2.0 .net-3.5 parallel-port fat16 fat32".split())
DEFAULT_EXCLUDED_TAGS = frozenset("amazon-web-services azure google-cloud-platform firebase stripe twilio wordpress flash flex silverlight blackberry symbian windows-phone jquery-plugins reactjs angular app-store google-play".split())
DEFAULT_VERSION_RULES = (
    {"name": "Python", "tags": ["python"], "pattern": r"\bpython\s+(\d+(?:\.\d+)*)", "legacy_major": [2]},
    {"name": "Java", "tags": ["java"], "pattern": r"\b(?:java|jdk|jre)\s+(?:1\.)?(\d+(?:\.\d+)*)", "legacy_major": [6, 7, 8]},
    {"name": "GCC", "tags": ["gcc"], "pattern": r"\bgcc\s+(\d+(?:\.\d+)*)", "legacy_major": [2, 3, 4]},
    {"name": ".NET", "tags": [".net", "c#"], "pattern": r"\.net\s+(\d+(?:\.\d+)*)", "legacy_major": [1, 2, 3]},
)


class CorpusError(ValueError):
    pass


def xml_rows(path: Path):
    """Yield one row at a time without retaining the dump's root children."""
    reject_symlinks(path)
    with path.open("rb") as handle:
        parser = ET.iterparse(handle, events=("start", "end"))
        _, root = next(parser)
        for event, node in parser:
            if event == "end" and node.tag == "row":
                row = dict(node.attrib)
                if sum(len(k) + len(v) for k, v in row.items()) > MAX_TEXT:
                    raise CorpusError("XML row exceeds the 16 MiB document limit")
                yield row
                node.clear()
                root.clear()


def classify_question(row: dict, rules: dict | None = None) -> str | None:
    """Explicit legacy rules win over durable rules. Dates never classify age."""
    bucket, _ = _classification(row, rules)
    return bucket if bucket in {"durable", "legacy"} else None


def _classification(row: dict, rules: dict | None = None):
    rules = rules or {}
    if row.get("PostTypeId") != "1" or int(row.get("Score", 0)) < 1 or int(row.get("AnswerCount", 0)) < 1:
        return None, ["Unanswered or question score below one"]
    question_id = int(row["Id"])
    tags = set(re.findall(r"<([^>]+)>", row.get("Tags", "")))
    if len(tags) > 64 or any(len(tag) > 128 for tag in tags):
        raise CorpusError("Question tag metadata exceeds bounded selection limits")
    denied = tags & set(rules.get("deny_tags", rules.get("excluded_tags", DEFAULT_EXCLUDED_TAGS)))
    if question_id in rules.get("excluded_ids", []) or denied:
        return None, ["Explicit exclusion" + (": " + ", ".join(sorted(denied)) if denied else "")]
    legacy_tags = tags & set(rules.get("legacy_tags", DEFAULT_LEGACY_TAGS))
    if question_id in rules.get("legacy_ids", []) or legacy_tags:
        return "legacy", ["Explicit legacy classification" + (": " + ", ".join(sorted(legacy_tags)) if legacy_tags else "")]
    title = row.get("Title", "")[:2048]
    version_reasons, ambiguous = [], False
    for rule in rules.get("version_rules", DEFAULT_VERSION_RULES):
        if not tags & set(rule["tags"]):
            continue
        versions = sorted(set(re.findall(rule["pattern"], title, re.I)))
        if any(not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)*", value) for value in versions):
            raise CorpusError("Version rule must capture exactly one numeric version")
        legacy = [value for value in versions if int(value.split(".")[0]) in rule["legacy_major"]]
        if legacy and len(legacy) != len(versions):
            ambiguous = True
            version_reasons.append(f"Mixed legacy/current {rule['name']} versions: {', '.join(versions)}")
        elif legacy:
            version_reasons.append(f"Explicit legacy {rule['name']} version: {', '.join(legacy)}")
    if re.search(r"\b(?:old|older|legacy|ancient)\b", title, re.I) and not version_reasons:
        ambiguous = True
        version_reasons.append("Old-version wording without an explicit reviewed version")
    allowed = tags & set(rules.get("allow_tags", rules.get("durable_tags", DEFAULT_DURABLE_TAGS)))
    in_scope = question_id in rules.get("durable_ids", []) or bool(allowed) or bool(version_reasons)
    if ambiguous and in_scope:
        return "review", version_reasons
    if version_reasons:
        return "legacy", version_reasons
    if in_scope:
        return "durable", ["Durable topic selection" + (": " + ", ".join(sorted(allowed)) if allowed else "")]
    return None, ["Outside declared topic selection"]


def discover_questions(posts: Path, *, rules: dict | None = None, limit: int = 1000) -> list[dict]:
    """Propose at most ``limit`` candidates by score then ID; no body retention."""
    return select_candidates(posts, rules=rules, limit=limit)["candidates"]


def select_candidates(posts: Path, *, rules: dict | None = None, limit: int = 1000,
                      cache_dir: Path | None = None, source_asset: dict | None = None) -> dict:
    """Stream local XML into bounded candidates plus an ambiguous-version queue.

    ``allow_tags``/``deny_tags``, ``legacy_tags`` and explicit ``*_ids`` are exact
    matches. Version rules contain name, tags, a regex capturing one numeric
    version, and legacy_major. Human review still precedes output pinning.
    A content-addressed local cache avoids XML parsing on unchanged reruns.
    """
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise CorpusError("Candidate limit must be between 1 and 100000")
    rules = rules or {}
    before = posts.stat()
    source_hash = sha256_file(posts)
    if source_asset is not None and (source_asset.get("sha256") != source_hash or source_asset.get("size_bytes") != before.st_size):
        raise CorpusError("Candidate input source size/SHA-256 mismatch")
    fingerprint = hashlib.sha256(json.dumps({"version": VERSION, "sha256": source_hash, "rules": rules, "limit": limit}, sort_keys=True).encode()).hexdigest()
    cache_file = safe_path(cache_dir, fingerprint + ".json") if cache_dir else None
    if cache_file and cache_file.is_file() and cache_file.stat().st_size <= 64 * 1024 * 1024:
        saved = json.loads(cache_file.read_text())
        if saved.get("fingerprint") == fingerprint:
            after = posts.stat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise CorpusError("Candidate source changed during cache verification")
            return dict(saved, cache_hit=True)
    heaps, scanned, excluded = {"candidates": [], "review_queue": []}, 0, 0
    for row in xml_rows(posts):
        if row.get("PostTypeId") != "1":
            continue
        scanned += 1
        bucket, reasons = _classification(row, rules)
        if bucket is None:
            excluded += 1
            continue
        item = (int(row["Score"]), -int(row["Id"]), {
            "id": int(row["Id"]), "title": row.get("Title", "")[:2048], "bucket": bucket,
            "score": int(row["Score"]), "tags": re.findall(r"<([^>]+)>", row.get("Tags", "")),
            "review_status": "needs-version-review" if bucket == "review" else "pending",
            "created": row.get("CreationDate", ""), "reasons": reasons,
        })
        heap = heaps["review_queue" if bucket == "review" else "candidates"]
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)
    after = posts.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise CorpusError("Candidate source changed during inspection")
    result = {key: [item[2] for item in sorted(heap, key=lambda item: item[:2], reverse=True)] for key, heap in heaps.items()}
    result.update(scanned_questions=scanned, excluded_questions=excluded, source_sha256=source_hash, fingerprint=fingerprint, cache_hit=False)
    if cache_file:
        payload = (json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode()
        if len(payload) > 64 * 1024 * 1024:
            raise CorpusError("Candidate metadata exceeds 64 MiB; reduce the candidate limit")
        atomic_write(cache_file, payload)
    return result


def verify_sources(recipe: dict, sources: dict[str, Path], assets: dict[str, dict]) -> dict:
    ids = recipe.get("source_asset_ids", [])
    if not ids or len(ids) != len(set(ids)):
        raise CorpusError("Recipe needs unique pinned source_asset_ids")
    identities = {}
    for asset_id in ids:
        if asset_id not in sources or asset_id not in assets:
            raise CorpusError(f"Missing pinned source: {asset_id}")
        path, asset = Path(sources[asset_id]), assets[asset_id]
        reject_symlinks(path)
        before = path.stat()
        pin = asset.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", pin) or before.st_size != asset.get("size_bytes") or sha256_file(path) != pin:
            raise CorpusError(f"Source size/SHA-256 mismatch: {asset_id}")
        identities[asset_id] = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    check_source_identities(sources, identities)
    return identities


def check_source_identities(sources, identities):
    for asset_id, identity in identities.items():
        reject_symlinks(Path(sources[asset_id]))
        info = Path(sources[asset_id]).stat()
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity:
            raise CorpusError(f"Source changed during generation: {asset_id}")


def relative_link(current: dict, target: dict) -> str:
    return quote(posixpath.relpath(target["destination"], posixpath.dirname(current["destination"])), safe="/.-_")


def substantive_comment(text: str) -> bool:
    """Retain correction/version warnings even when shorter than normal prose."""
    text = text.strip()
    if re.fullmatch(r"(?:thanks|thank you|\+1)[.!\s]*", text, re.I):
        return False
    warning = re.search(r"\b(?:warning|caution|unsafe|security|deprecated|obsolete|incorrect|bug|fails?|broken|instead|correction|do not|don't|not|only|requires?|since|removed)\b", text, re.I)
    return len(text) >= 40 and len(text.split()) >= 6 or bool(warning) and len(text) >= 12 and len(text.split()) >= 3


class StaticHTML(HTMLParser):
    """Keep semantic text/tables/math and require pinned image dependencies."""
    MATH = set("math mrow mi mn mo ms mtext mspace msup msub msubsup mfrac msqrt mroot mtable mtr mtd semantics annotation munderover mover munder".split())

    def __init__(self, current, assets, dependencies, question_links=None):
        super().__init__(convert_charrefs=True)
        self.current, self.assets, self.dependencies = current, assets, dependencies
        self.question_links = question_links or {}
        self.parts, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_CONTENT:
                self.skip.append(tag)
            return
        if tag in DROP_CONTENT:
            if tag not in {"embed"}:
                self.skip.append(tag)
            return
        if tag in {"audio", "video", "canvas", "form"}:
            raise CorpusError(f"Unsupported essential inline element: {tag}")
        if tag not in TAGS | self.MATH or tag in {"style", "link", "source"}:
            if tag == "style":
                self.skip.append(tag)
            return
        values = []
        for key, value in attrs:
            if value is None:
                continue
            if key in {"src", "srcset", "xlink:href", "background"} or key == "href" and tag != "a":
                if key == "srcset":
                    raise CorpusError("Responsive image variants require a reviewed ordinary image replacement")
                asset_id = self.dependencies.get(value)
                if not asset_id or asset_id not in self.assets:
                    raise CorpusError(f"Unpinned illustration dependency: {value[:200]}")
                value = relative_link(self.current, self.assets[asset_id])
            elif key == "href":
                parsed = urlsplit(value)
                if parsed.scheme not in {"", "https", "http"} or value.startswith("//"):
                    continue
                match = re.search(r"/(?:questions|q)/(\d+)", parsed.path)
                if match and int(match[1]) in self.question_links:
                    value = relative_link(self.current, self.question_links[int(match[1])])
                elif parsed.scheme:
                    values.append('rel="noreferrer noopener"')
                    values.append('title="Original source; requires internet"')
                elif not value.startswith("#"):
                    raise CorpusError(f"Unresolved local content link: {value[:200]}")
            elif key not in ATTRS | {"display", "mathvariant", "encoding"}:
                continue
            if key in {"fill", "stroke", "clip-path", "mask"} and "url(" in value.lower() and not re.fullmatch(r"url\(#[A-Za-z0-9_.:-]+\)", value):
                raise CorpusError("Unpinned external SVG dependency")
            key = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio",
                   "gradientunits": "gradientUnits", "gradienttransform": "gradientTransform",
                   "patternunits": "patternUnits", "patterntransform": "patternTransform"}.get(key, key)
            values.append(f'{key}="{escape(value, quote=True)}"')
        self.parts.append("<" + tag + (" " + " ".join(values) if values else "") + ">")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
        elif tag in TAGS | self.MATH and tag not in VOID and tag not in {"style", "link", "source"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(escape(value))


def static_html(body: str, current: dict, assets: dict, dependencies: dict, question_links=None) -> str:
    if len(body.encode("utf-8")) > MAX_TEXT:
        raise CorpusError("Document exceeds the 16 MiB HTML limit")
    parser = StaticHTML(current, assets, dependencies, question_links)
    parser.feed(body)
    parser.close()
    return "".join(parser.parts)


def page(title: str, content: str, *, legacy=False, media=False) -> bytes:
    csp = "default-src 'none'; script-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; img-src 'self' data:; style-src 'unsafe-inline';"
    if media:
        csp += " media-src 'self' data:;"
    warning = f'<aside role="note"><strong>{LEGACY_WARNING}</strong></aside>' if legacy else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}"><title>{escape(title)}</title>'
            '<style>body{max-width:72rem;margin:1.5rem auto;padding:0 1rem;font:18px/1.5 system-ui}img,video{max-width:100%;height:auto}pre{overflow:auto}table{border-collapse:collapse}td,th{border:1px solid;padding:.3rem}aside{border:2px solid;padding:1rem}footer{font-size:.85em}</style>'
            f'</head><body>{warning}<h1>{escape(title)}</h1>{content}</body></html>\n').encode("utf-8")


@contextmanager
def _database(output_dir: Path, workspace_bytes: int, signature: str):
    if type(workspace_bytes) is not int or workspace_bytes < 262144:
        raise CorpusError("Stack Exchange recipe.workspace_bytes must reserve at least 262144 bytes")
    output_dir.mkdir(parents=True, exist_ok=True)
    reject_symlinks(output_dir)
    directory = safe_path(output_dir, "corpus-work")
    marker = safe_path(output_dir, "corpus-work/identity.json")
    if directory.exists():
        if not marker.is_file() or marker.stat().st_size > 4096 or json.loads(marker.read_text()) != {"signature": signature, "version": VERSION}:
            raise CorpusError("Corpus checkpoint does not match the pinned recipe and sources")
    else:
        atomic_write(marker, (json.dumps({"signature": signature, "version": VERSION}) + "\n").encode())
    db = sqlite3.connect(str(safe_path(directory, "index.sqlite")))
    try:
        db.execute("PRAGMA page_size=4096")
        if db.execute("PRAGMA page_size").fetchone()[0] != 4096:
            raise CorpusError("Corpus checkpoint has an unexpected SQLite page size")
        db.execute("PRAGMA cache_size=-8192")
        db.execute("PRAGMA journal_mode=DELETE")
        # Reserve an equally large rollback journal plus its header/metadata.
        db.execute(f"PRAGMA max_page_count={(workspace_bytes - 65536) // 8192}")
        db.executescript("CREATE TABLE IF NOT EXISTS checkpoints(role TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS links(id INTEGER, target INTEGER, PRIMARY KEY(id,target)); CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, parent INTEGER, data TEXT); CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE IF NOT EXISTS needed_users(id INTEGER PRIMARY KEY); CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, post INTEGER, data TEXT); CREATE INDEX IF NOT EXISTS comments_post ON comments(post); CREATE INDEX IF NOT EXISTS posts_parent ON posts(parent);")
        yield db
    except sqlite3.DatabaseError as error:
        raise CorpusError(f"Corpus workspace failed within its {workspace_bytes}-byte allowance: {error}") from error
    finally:
        db.close()


def _ingest(db, role, path):
    """Commit a source checkpoint atomically; a failed source is replayed."""
    if db.execute("SELECT 1 FROM checkpoints WHERE role=?", (role,)).fetchone():
        return
    yield from xml_rows(path)
    db.execute("INSERT INTO checkpoints VALUES (?)", (role,))
    db.commit()


def render(recipe: dict, sources: dict[str, Path], assets: dict[str, dict], output_dir: Path, *, output_writer=None) -> dict[str, Path]:
    selection = recipe.get("selection", {})
    if selection.get("reviewed") is not True:
        raise CorpusError("Stack Exchange selection requires recorded review")
    identities = verify_sources(recipe, sources, assets)
    roles = selection.get("input_roles", {})
    if set(roles) != {"posts", "comments", "users", "links"} or any(value not in identities for value in roles.values()):
        raise CorpusError("Pinned posts, comments, users and links XML input_roles are required")
    dependencies = selection.get("dependencies", {})
    if any(value not in identities for value in dependencies.values()):
        raise CorpusError("Every illustration must be a pinned source_asset_id")
    questions = selection.get("questions", [])
    if not questions or len(questions) > 100000:
        raise CorpusError("A reviewed selection of 1–100000 question IDs is required")
    requested = {}
    for record in questions:
        question_id, bucket = record.get("id"), record.get("bucket")
        if type(question_id) is not int or question_id <= 0 or bucket not in {"durable", "legacy"} or question_id in requested:
            raise CorpusError("Question IDs must be unique positive integers with durable/legacy buckets")
        requested[question_id] = bucket
    signature = hashlib.sha256(json.dumps({"recipe": recipe, "sources": {key: assets[key]["sha256"] for key in identities}}, sort_keys=True).encode()).hexdigest()
    with _database(output_dir, recipe.get("workspace_bytes", 0), signature) as db:
        for row in _ingest(db, "links", sources[roles["links"]]):
            if row.get("LinkTypeId") == "3":
                # The publisher permits multiple canonical targets. Preserve all
                # edges; only an affected selected question requires review.
                db.execute("INSERT OR IGNORE INTO links VALUES (?,?)", (int(row["PostId"]), int(row["RelatedPostId"])))
        canonical, aliases = {}, {}
        for original, bucket in requested.items():
            current, seen = original, set()
            while True:
                if current in seen or len(seen) >= 64:
                    raise CorpusError(f"Cyclic or excessively deep canonical mapping for selected question {original} at {current}; review required")
                seen.add(current)
                targets = db.execute("SELECT target FROM links WHERE id=? ORDER BY target LIMIT 9", (current,)).fetchall()
                if not targets:
                    break
                if len(targets)>1:
                    excerpt=', '.join(str(row[0]) for row in targets[:8]) + (' …' if len(targets)>8 else '')
                    raise CorpusError(f"Selected question {original} reaches multiple canonical targets at {current}: {excerpt}; review required")
                current = targets[0][0]
            aliases[original] = current
            canonical[current] = "legacy" if bucket == "legacy" or canonical.get(current) == "legacy" else "durable"
        for row in _ingest(db, "posts", sources[roles["posts"]]):
            post_id, parent = int(row["Id"]), int(row.get("ParentId", 0))
            if post_id in canonical and row.get("PostTypeId") == "1" or parent in canonical and row.get("PostTypeId") == "2":
                db.execute("INSERT INTO posts VALUES (?,?,?)", (post_id, parent, json.dumps(row)))
                if row.get("OwnerUserId"):
                    db.execute("INSERT OR IGNORE INTO needed_users VALUES (?)", (int(row["OwnerUserId"]),))
        for row in _ingest(db, "comments", sources[roles["comments"]]):
            if db.execute("SELECT 1 FROM posts WHERE id=?", (int(row["PostId"]),)).fetchone():
                text = row.get("Text", "").strip()
                # Exact rule is deliberately conservative and reproducible.
                if substantive_comment(text):
                    db.execute("INSERT INTO comments VALUES (?,?,?)", (int(row["Id"]), int(row["PostId"]), json.dumps(row)))
                    if row.get("UserId"):
                        db.execute("INSERT OR IGNORE INTO needed_users VALUES (?)", (int(row["UserId"]),))
        for row in _ingest(db, "users", sources[roles["users"]]):
            if db.execute("SELECT 1 FROM needed_users WHERE id=?", (int(row["Id"]),)).fetchone():
                db.execute("INSERT INTO users VALUES (?,?)", (int(row["Id"]), row.get("DisplayName", "")))
        db.commit()
        outputs = {asset_id: asset for asset_id, asset in assets.items() if asset.get("generation", {}).get("recipe_id") == recipe["id"]}
        by_question = {}
        destinations = set()
        for asset in outputs.values():
            question_id = asset["generation"].get("question_id")
            destination = asset["destination"].casefold()
            if question_id not in canonical or question_id in by_question or destination in destinations:
                raise CorpusError("Generated outputs must declare each unique canonical question exactly once")
            if asset.get("legacy", False) is not (canonical[question_id] == "legacy"):
                raise CorpusError("Output legacy metadata does not match reviewed classification")
            by_question[question_id] = asset
            destinations.add(destination)
        if set(by_question) != set(canonical):
            raise CorpusError("Reviewed canonical questions and predeclared outputs do not match")
        question_links = dict(by_question)
        question_links.update({alias: by_question[target] for alias, target in aliases.items()})

        def author(row, comment=False):
            key = "UserId" if comment else "OwnerUserId"
            user = db.execute("SELECT name FROM users WHERE id=?", (int(row.get(key, 0)),)).fetchone()
            name = user[0] if user else row.get("UserDisplayName" if comment else "OwnerDisplayName")
            if not name:
                name = f"Stack Overflow user {row[key]}" if row.get(key) else "Deleted contributor (name absent from source)"
            license = row.get("ContentLicense")
            if not license:
                raise CorpusError(f"Missing per-post/comment license on {row['Id']}")
            return f'{escape(name)} · {escape(license)} · {escape(row.get("CreationDate", ""))}' + (f' · Updated {escape(row["LastEditDate"])}' if row.get("LastEditDate") else "")

        def content(row):
            post_id = int(row["Id"])
            result = static_html(row.get("Body", ""), asset, assets, dependencies, question_links)
            kind = "q" if row.get("PostTypeId") == "1" else "a"
            result += f'<footer>{author(row)} · <a href="https://stackoverflow.com/{kind}/{post_id}">Original post {post_id}</a></footer>'
            for item in db.execute("SELECT data FROM comments WHERE post=? ORDER BY id", (post_id,)):
                comment = json.loads(item[0])
                result += f'<blockquote><p>{escape(comment["Text"])}</p><footer>{author(comment, True)}</footer></blockquote>'
            return result

        result = {}
        for question_id in sorted(canonical):
            asset = by_question[question_id]
            item = db.execute("SELECT data FROM posts WHERE id=?", (question_id,)).fetchone()
            if item is None:
                raise CorpusError(f"Selected canonical question is absent: {question_id}")
            question = json.loads(item[0])
            if int(question.get("Score", 0)) < 1:
                raise CorpusError(f"Selected question has score below one: {question_id}")
            rules=selection.get('classification_rules',{})
            if not isinstance(rules,dict):raise CorpusError('Frozen classification_rules must be an object')
            actual_bucket,reasons=_classification(question,rules)
            if canonical[question_id]=='durable' and actual_bucket in {'legacy','review'}:
                raise CorpusError(f'Canonical question {question_id} requires reviewed reclassification from durable to '
                    f'{actual_bucket}: '+('; '.join(reasons))[:512])
            answer_rows = (json.loads(item[0]) for item in db.execute("SELECT data FROM posts WHERE parent=? ORDER BY id", (question_id,)))
            accepted, alternatives = None, []
            for answer in answer_rows:
                score, answer_id = int(answer.get("Score", 0)), int(answer["Id"])
                if answer_id == int(question.get("AcceptedAnswerId", 0)) and score >= 0:
                    accepted = answer
                elif score > 0:
                    alternatives.append(answer)
                    alternatives.sort(key=lambda item: (-int(item["Score"]), int(item["Id"])))
                    del alternatives[2:]
            answers = ([accepted] if accepted else []) + alternatives
            if not answers:
                raise CorpusError(f"Selected question lacks a qualifying answer: {question_id}")
            body = f'<p>Tags: {escape(question.get("Tags", ""))} · Score: {escape(question["Score"])} · Updated: {escape(question.get("LastEditDate", question.get("CreationDate", "")))}</p>'
            body += content(question)
            for answer in answers:
                body += f'<section><h2>{"Accepted answer" if answer is accepted else "Alternative answer"} (score {escape(answer["Score"])})</h2>{content(answer)}</section>'
            original_ids = sorted(alias for alias, target in aliases.items() if target == question_id and alias != question_id)
            if original_ids:
                body += '<p>Canonical question for duplicates: ' + ", ".join(f'<a href="https://stackoverflow.com/q/{alias}">{alias}</a>' for alias in original_ids) + '</p>'
            path = safe_path(output_dir, asset["destination"])
            (output_writer or atomic_write)(path, page(question.get("Title", asset["title"]), body, legacy=canonical[question_id] == "legacy"))
            result[asset["id"]] = path
        check_source_identities(sources, identities)
        return result
