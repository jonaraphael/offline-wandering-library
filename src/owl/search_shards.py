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


SCHEMA = 1
MAX_PART = 3_000_000
REPO_LIMIT = 600_000_000
COUNT_PER_PART = 4096
MODEL_FILE = "model.js"
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
    value = bytearray(8192)
    for term in terms:
        key = hash_term(term)
        for bit in (key & 65535, key >> 16):
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


def part_path(digest, number):
    if not DIGEST.fullmatch(digest) or type(number) is not int or not 0 <= number < 100_000:
        raise ValueError("Invalid shard address")
    return f"sources/{digest}/{number:05}.js"


def packed_part(source, number, records, model):
    compact = []
    postings = defaultdict(list)
    embedded = 0
    for index, row in enumerate(records):
        concepts = " ".join(expansions(" ".join([row.title, row.heading, row.lead[:240]])))
        vector = model.encode(" ".join((row.title, row.heading, row.lead[:500], concepts))) if row.vector else ""
        embedded += bool(vector)
        compact.append([row.title, row.locator, row.lead[:280], vector, int(row.redirect)])
        weights = {}
        for field, weight in ((row.body, 1), (row.lead, 3), (concepts, 5), (row.heading, 8), (row.title, 9)):
            for word in terms(field):
                weights[word] = weight
        for word, weight in weights.items():
            postings[word].append(index * 16 + weight)
    message = encode({"records": compact, "postings": postings})
    packed = script("OWLShardPart", [source, number, base64.b64encode(compress(message, compresslevel=6, mtime=0)).decode("ascii")])
    if len(packed) > MAX_PART:
        raise ValueError("Index chunk exceeds its bounded script size")
    return packed, embedded, bloom(postings)


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
    if any(not DIGEST.fullmatch(digest) for digest in data["sources"]):
        raise ValueError("Invalid source digest in search shard manifest")
    return data


def selected_shards(assets, manifest):
    sources = manifest["sources"]
    return [(asset, sources[asset["sha256"]]) for asset in assets if asset.get("sha256") in sources]


def source_manifest(asset, shard, destination):
    return {"id": asset["id"], "sha256": asset["sha256"], "destination": destination,
            "title": asset["title"], "format": asset["format"], "parts": shard["parts"],
            "license": asset.get("license", ""), "attribution": asset.get("attribution", ""),
            "main": shard.get("main", ""), "records": shard["records"],
            "shelves": asset.get("shelves", []), "legacy": bool(asset.get("legacy"))}


def compose_shards(assets, budget, folder=SEARCH_ROOT):
    """Publish only whole source shards with a common runtime and pinned model."""
    manifest = load_manifest(folder)
    selected = selected_shards(assets, manifest)
    if not selected:
        return {}, []
    from .catalog import learning_shelves
    model = read_file(folder, MODEL_FILE, manifest["model"])
    license_text = read_file(folder, LICENSE_FILE, manifest["license"])
    runtime = Path(__file__).with_name("templates").joinpath("rank.js").read_bytes()
    outputs = {"SEARCH/" + MODEL_FILE: model, "SEARCH/" + LICENSE_FILE: license_text, RUNTIME_FILE: runtime}
    remaining = budget - sum(map(len, outputs.values())) - 64_000
    rows = []
    for asset, shard in sorted(selected, key=lambda pair: (not pair[0].get("critical"), pair[1]["records"], pair[0]["id"])):
        digest = asset["sha256"]
        row = source_manifest(asset, shard, asset["destination"])
        row["parts"] = [{"bloom": part["bloom"], "vectors": part["vectors"]} for part in shard["parts"]]
        row["shelves"] = sorted(learning_shelves(asset))
        chunks = {part_path(digest, index): pin for index, pin in enumerate(shard["parts"])}
        cost = len(encode(row)) + 1 + sum(pin["bytes"] for path, pin in chunks.items() if "SEARCH/" + path not in outputs)
        if cost > remaining:
            continue
        whole = sha256()
        for relative, pin in chunks.items():
            part = ShardPart(folder, relative, pin)
            whole.update(part.read())
            outputs["SEARCH/" + relative] = part
        if whole.hexdigest() != shard["sha256"]:
            raise ValueError(f"Search shard digest differs: {asset['id']}")
        remaining -= cost
        rows.append(row)
    if not rows or remaining < 0:
        return {}, []
    outputs[SELECTION_FILE] = script("OWLShardSelection", {"version": SCHEMA, "sources": rows})
    return outputs, [{"id": row["id"], "source_sha256": row["sha256"], "records": row["records"]}
                     for row in rows]
