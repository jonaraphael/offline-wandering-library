"""Build and compose source-pinned search shards as bounded local scripts."""
from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from gzip import compress
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from .search_model import semantic_text


SCHEMA = 1
MAX_PART = 3_000_000
REPO_LIMIT = 900_000_000
COUNT_PER_PART = 4096
MODEL_FILE = "model.js"
MODEL_PART = "model/{:02}.js"
RUNTIME_FILE = "SEARCH/rank.js"
SELECTION_FILE = "SEARCH/shards.js"
LICENSE_FILE = "model-license.txt"
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ROOT = Path(__file__).resolve().parents[2]
SEARCH_ROOT = ROOT / "catalog/search"
STOP = frozenset("a an and are as at be by do does for from how i in is it of on or the to use what when where with you your".split())
# Each reviewed group follows one concept. Only a matching phrase adds its
# alternate terms and questions, so common words do not amplify unrelated hits.
CONCEPTS = (
    ("bleeding", "bleed", "bleeding control", "hemorrhage", "haemorrhage", "stop bleeding", "direct pressure"),
    ("cardiopulmonary resuscitation", "cpr", "chest compressions", "rescue breathing", "restart breathing"),
    ("diarrhea", "diarrhoea", "loose stools", "oral rehydration"),
    ("broken bone", "bone fracture", "fracture", "splint"),
    ("snake bite", "snakebite", "snake envenomation"),
    ("tooth ache", "toothache", "dental pain"),
    ("childbirth", "deliver a baby", "child delivery", "labor and delivery", "labour and delivery"),
    ("water purification", "purify water", "drinking water treatment", "make water safe to drink", "disinfect water"),
    ("latrine", "pit toilet", "pit privy", "build a latrine"),
    ("axe", "ax", "hatchet"),
    ("potato", "potatoes"),
    ("canning", "water bath canning", "preserve food in jars"),
    ("solar panel", "photovoltaic", "pv module"),
    ("using a compass", "magnetic compass", "orienteering", "take a bearing"),
    ("asthma attack", "bronchospasm", "rescue inhaler"),
    ("hypothermia", "dangerously cold body temperature", "warming a cold person"),
    ("frostbite", "frozen skin", "cold injury"),
    ("welding", "arc weld", "joining metal"),
    ("evaporation", "water turns to vapor", "water turns to vapour"),
    ("ventilation", "fresh air circulation", "air exchange"),
    ("bookkeeping", "double entry accounting", "track income and expenses"),
    ("bicycle flat tire", "bicycle puncture", "patch inner tube", "bike flat tyre"),
    ("soldering", "solder joint", "join electronic components"),
    ("voltage", "potential difference", "electric potential"),
    ("composting", "turn food scraps into soil", "compost pile"),
    ("photosynthesis", "how plants make sugar", "plants convert light energy"),
    ("pythagorean theorem", "right triangle sides", "find a hypotenuse"),
    ("quadratic equation", "quadratic formula", "solve a second degree equation"),
)


def encode(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")


def script(callback, payload):
    return b"globalThis." + callback.encode("ascii") + b"(" + encode(payload) + b");\n"


def payload(data, callback):
    prefix = b"globalThis." + callback.encode("ascii") + b"("
    if not data.startswith(prefix) or not data.endswith(b");\n"):
        raise ValueError(f"Unexpected search script wrapper: {callback}")
    return json.loads(data[len(prefix):-3])


def words(text):
    if text.isascii():
        return re.findall(r"[a-z0-9]+", text.lower())
    value = unicodedata.normalize("NFKD", text.lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", value, re.UNICODE)


@lru_cache(maxsize=131_072)
def stem(term):
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if len(term) > 5 and term.endswith("oes"):
        return term[:-2]
    for suffix in ("ing", "ed", "es", "s"):
        if len(term) > len(suffix) + 3 and term.endswith(suffix) and not term.endswith(("ss", "us")):
            term = term[:-len(suffix)]
            if suffix in ("ing", "ed") and term[-2:] in {"bb", "dd", "gg", "mm", "nn", "pp", "rr", "tt"}:
                term = term[:-1]
            break
    if len(term) > 4 and term.endswith("e"):
        term = term[:-1]
    return term


def terms(text):
    return {stem(word) for word in words(text) if word not in STOP and 1 < len(word) <= 50}


CONCEPT_GROUP = {phrase: index for index, group in enumerate(CONCEPTS) for phrase in group}
CONCEPT_PATTERN = re.compile(r"(?<!\S)(?:" + "|".join(
    re.escape(phrase) for phrase in sorted(CONCEPT_GROUP, key=len, reverse=True)) + r")(?!\S)")


def expansions(text):
    normalized = " ".join(words(text))
    matched = {CONCEPT_GROUP[match.group()] for match in CONCEPT_PATTERN.finditer(normalized)}
    for index in sorted(matched):
        yield " ".join(CONCEPTS[index])


def hash_term(word):
    # Hash UTF-16 code units to match String.charCodeAt in the browser.
    value = 2166136261
    data = word.encode("utf-16-le")
    for index in range(0, len(data), 2):
        value = ((value ^ (data[index] | data[index + 1] << 8)) * 16777619) & 0xffffffff
    return value


def bloom(terms):
    terms = list(terms)
    size = min(8192, max(32, 1 << (max(1, len(terms)) - 1).bit_length()))
    value = bytearray(size)
    mask = size * 8 - 1
    for term in terms:
        key = hash_term(term)
        for bit in (key & mask, (key >> 16) & mask):
            value[bit >> 3] |= 1 << (bit & 7)
    return base64.b64encode(value).decode("ascii")


@dataclass(frozen=True)
class Record:
    title: str
    locator: str | int
    heading: str = ""
    lead: str = ""
    body: str = ""
    vector: bool = True
    redirect: bool = False
    show_lead: bool = True
    accepted_answer: bool = False


def part_path(digest, number):
    if not DIGEST.fullmatch(digest) or type(number) is not int or not 0 <= number < 100_000:
        raise ValueError("Invalid shard address")
    return f"sources/{digest}/{number:05}.js"


def part_location(pool, number, pin):
    path = pin.get("path")
    if path is None:
        return part_path(pool, number)
    if not DIGEST.fullmatch(pin["sha256"]) or path != f"chunks/{pin['sha256']}.js":
        raise ValueError("Invalid content-addressed shard path")
    return path


def packed_part(source, number, records, model, *, title_paths=False, content_addressed=False):
    compact = []
    postings = defaultdict(list)
    route_terms = set()
    embedded = 0
    passages = 0
    for index, row in enumerate(records):
        title_terms = terms(row.title)
        title_only = title_paths and not (row.heading or row.lead or row.body)
        concepts = " ".join(expansions(" ".join((row.title, row.heading, row.lead[:240]))))
        title = row.title
        if title_paths and isinstance(row.locator, str):
            if title == row.locator.rsplit("/", 1)[-1].replace("_", " "):
                title = None
        weights = {}
        for field, weight in ((row.body, 1), (row.lead, 3), (concepts, 5), (row.heading, 8)):
            for word in terms(field):
                weights[word] = weight
        if title_only:
            route_terms.update(title_terms)
            for word in title_terms:
                weights.pop(word, None)
        else:
            weights.update(dict.fromkeys(title_terms, 9))
        for word, weight in weights.items():
            postings[word].append(index * 16 + weight)
        excerpt = (row.lead or row.body)[:160] if row.show_lead else ""
        keywords = sorted(word for word, weight in weights.items() if weight < 9)
        vector = model.encode(semantic_text(row.title, excerpt, keywords)) if row.vector and (row.lead or row.body) else ""
        embedded += bool(vector)
        passages += bool(row.body and vector)
        compact.append([title, row.locator, excerpt, vector, int(row.redirect), int(title_only)])
        passage_heading = row.heading if title_paths and row.body else ""
        if row.accepted_answer or passage_heading:
            compact[-1].append(int(row.accepted_answer))
        if passage_heading:
            compact[-1].append(passage_heading)
    route_terms.update(postings)
    message = encode({"records": compact, "postings": postings})
    encoded = base64.b64encode(compress(message, compresslevel=6, mtime=0)).decode("ascii")
    packed = script("OWLShardBlob", encoded) if content_addressed else script("OWLShardPart", [source, number, encoded])
    if len(packed) > MAX_PART:
        raise ValueError("Index chunk exceeds its bounded script size")
    return packed, embedded, bloom(route_terms), passages


def info(data):
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


def read_file(folder, path, pin, limit=MAX_PART):
    if type(pin["bytes"]) is not int or not 0 < pin["bytes"] <= limit or not DIGEST.fullmatch(pin["sha256"]):
        raise ValueError(f"Invalid search script pin: {path}")
    with (folder / path).open("rb") as file:
        data = file.read(pin["bytes"] + 1)
    if info(data) != {key: pin[key] for key in ("bytes", "sha256")}:
        raise ValueError(f"Search shard integrity differs: {path}")
    return data


@dataclass(frozen=True)
class ShardPart:
    directory: Path
    path: str
    pin: dict

    def read(self):
        return read_file(self.directory, self.path, self.pin)


def output_bytes(value):
    if isinstance(value, ShardPart):
        return value.read()
    return value.encode("utf-8") if isinstance(value, str) else value


def output_size(value):
    return value.pin["bytes"] if isinstance(value, ShardPart) else len(output_bytes(value))


def output_info(value):
    if isinstance(value, ShardPart):
        return {"size_bytes": value.pin["bytes"], "sha256": value.pin["sha256"]}
    encoded = output_bytes(value)
    return {"size_bytes": len(encoded), "sha256": sha256(encoded).hexdigest()}


def load_manifest(folder=SEARCH_ROOT):
    path = folder / "manifest.json"
    if not path.is_file():
        return {"version": SCHEMA, "sources": {}}
    data = json.loads(path.read_bytes())
    if data.get("version") != SCHEMA or not isinstance(data.get("sources"), dict):
        raise ValueError("Unsupported search shard schema")
    shared = data.get("shared", {})
    if not isinstance(shared, dict) or any(not DIGEST.fullmatch(digest) for digest in (*data["sources"], *shared)):
        raise ValueError("Invalid source digest in search shard manifest")
    return data


def load_routes(folder=SEARCH_ROOT):
    path = folder / "routes.json"
    return json.loads(path.read_bytes()) if path.is_file() else {}


def model_files(manifest):
    """List the shared model header, license and bounded weight scripts."""
    yield MODEL_FILE, manifest["model"]
    yield LICENSE_FILE, manifest["license"]
    for number, pin in enumerate(manifest.get("model_parts", ())):
        yield MODEL_PART.format(number), pin


def selected_shards(assets, manifest):
    sources = manifest["sources"]
    return [(asset, sources[asset["sha256"]]) for asset in assets if asset.get("sha256") in sources]


def shard_chunks(manifest, digest, shard):
    """Resolve shared directory chunks and source-specific chunks in digest order."""
    for pool in shard.get("shared", ()):
        for number, pin in enumerate(manifest["shared"][pool]["parts"]):
            yield pool, number, pin
    for number, pin in enumerate(shard.get("parts", ())):
        yield digest, number, pin


def source_manifest(asset, shard, destination):
    return {"id": asset["id"], "sha256": asset["sha256"], "destination": destination,
            "title": asset["title"], "format": asset["format"],
            "category": asset.get("category", ""), "critical": bool(asset.get("critical")),
            "discussion": "/stack_exchange/" in asset.get("source_url", ""),
            "license": asset.get("license", ""), "attribution": asset.get("attribution", ""),
            "restricted": asset.get("redistributable") is False, "entrypoints": shard.get("entrypoints", []),
            "main": shard.get("main", ""), "records": shard["records"],
            **({"title_overrides": shard["title_overrides"]} if "title_overrides" in shard else {}),
            "shelves": asset.get("shelves", []), "legacy": bool(asset.get("legacy"))}


def load_impact(folder=SEARCH_ROOT):
    path = folder / "impact/manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_bytes())
    if data.get("version") != 1 or any(not re.fullmatch(r"[a-f0-9]{2}\.js", name) for name in data["files"]):
        raise ValueError("Invalid search impact index")
    return data


def load_transformer(folder=SEARCH_ROOT):
    path = folder / "transformer/manifest.json"
    if not path.is_file():
        return {}
    files = json.loads(path.read_bytes())
    if any(not re.fullmatch(r"[a-zA-Z0-9.-]+\.(?:js|txt)", name) for name in files):
        raise ValueError("Invalid local transformer asset name")
    return files


def compile_search_plan(assets, manifest, routes, impact=None, transformer=None):
    """Compile source order, destinations, physical files and ranker inputs once."""
    from .catalog import learning_shelves

    candidates = selected_shards(assets, manifest)
    ordered = sorted(candidates, key=lambda pair: (not pair[0].get("critical"), pair[1]["records"], pair[0]["id"]))
    chunks = {}
    sources = []
    impact = impact or {}
    ids = impact.get("ids", {})
    for asset, shard in ordered:
        digest = asset["sha256"]
        row = source_manifest(asset, shard, asset["destination"])
        row["shelves"] = sorted(learning_shelves(asset))
        paths = []
        for pool, number, pin in shard_chunks(manifest, digest, shard):
            path = part_location(pool, number, pin)
            paths.append(path)
            if path in chunks:
                continue
            rank = {key: pin[key] for key in ("bloom", "vectors", "passages", "lead_vectors", "semantic_vectors")
                    if key in pin}
            if pin["sha256"] in routes:
                rank.update(route=routes[pin["sha256"]], bytes=pin["bytes"])
            rank["bytes"] = pin["bytes"]
            if pin["sha256"] in ids:
                rank["impact"] = ids[pin["sha256"]]
            if "path" in pin:
                rank.update(path=path)
            else:
                rank.update(pool=pool, number=number)
            chunks[path] = {"pin": {key: pin[key] for key in ("bytes", "sha256")}, "rank": rank}
        sources.append({"row": row, "parts": paths, "sha256": shard["sha256"]})
    model = list(model_files(manifest)) if candidates else []
    return {"version": SCHEMA, "sources": sources, "chunks": chunks, "model": model,
            "model_parts": len(manifest.get("model_parts", ())), "reserve": 64_000,
            "impact": impact.get("files", {}), "transformer": transformer or {}}


def compose_shards(assets, budget, folder=SEARCH_ROOT):
    """Publish only whole source shards with a common runtime and pinned model."""
    manifest = load_manifest(folder)
    plan = compile_search_plan(assets, manifest, load_routes(folder), load_impact(folder), load_transformer(folder))
    if not plan["sources"]:
        return {}, []
    runtime = Path(__file__).with_name("templates").joinpath("rank.js").read_bytes()
    model = plan["model"]
    remaining = budget - len(runtime) - sum(pin["bytes"] for _, pin in model) - plan["reserve"]
    if remaining < 0:
        return {}, []
    outputs = {"SEARCH/" + path: ShardPart(folder, path, pin) for path, pin in model}
    outputs[RUNTIME_FILE] = runtime
    rows = []
    for source in plan["sources"]:
        paths = source["parts"]
        chunks = plan["chunks"]
        row = {**source["row"], "parts": [chunks[path]["rank"] for path in paths]}
        cost = len(encode(row)) + 1 + sum(chunks[path]["pin"]["bytes"] for path in set(paths)
                                          if "SEARCH/" + path not in outputs)
        if cost > remaining:
            continue
        whole = sha256()
        for path in paths:
            part = ShardPart(folder, path, chunks[path]["pin"])
            whole.update(part.read())
            outputs["SEARCH/" + path] = part
        if whole.hexdigest() != source["sha256"]:
            raise ValueError(f"Search shard digest differs: {row['id']}")
        remaining -= cost
        rows.append(row)
    if not rows:
        return {}, []
    for path, pin in model:
        read_file(folder, path, pin)
    selection = {"version": plan["version"], "sources": rows, "model_parts": plan["model_parts"]}
    impact = plan["impact"]
    routed = any("impact" in part for row in rows for part in row["parts"])
    if impact and routed and sum(pin["bytes"] + 20 for pin in impact.values()) <= remaining:
        for name, pin in impact.items():
            path = "impact/" + name
            outputs["SEARCH/" + path] = ShardPart(folder, path, pin)
            read_file(folder, path, pin)
        selection["impact"] = {name: pin["bytes"] for name, pin in impact.items()}
    if "impact" in selection:
        remaining -= sum(pin["bytes"] + 20 for pin in impact.values())
    transformer = plan["transformer"]
    rerank = Path(__file__).with_name("templates").joinpath("rerank.js").read_bytes()
    if transformer and sum(pin["bytes"] for pin in transformer.values()) + len(rerank) + 20 <= remaining:
        for name, pin in transformer.items():
            path = "transformer/" + name
            outputs["SEARCH/" + path] = ShardPart(folder, path, pin)
            read_file(folder, path, pin)
        outputs["SEARCH/rerank.js"] = rerank
        selection["reranker"] = True
    outputs[SELECTION_FILE] = script("OWLShardSelection", selection)
    return outputs, [{"id": row["id"], "source_sha256": row["sha256"], "records": row["records"]}
                     for row in rows]
