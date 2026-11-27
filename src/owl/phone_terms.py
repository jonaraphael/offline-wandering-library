"""Pick the words that set each indexed book apart, for the iPhone start page.

Preview on an iPhone searches only the start page's own text. Listing a book's
distinctive words beside its title lets that search find the book by what is
inside it. The words come from the search shards, so no source file is read.
"""
from __future__ import annotations

from base64 import b64decode
from collections import Counter, defaultdict
from functools import lru_cache
from gzip import decompress
import json
import math
from pathlib import Path
import re

from .search_shards import ROOT, SEARCH_ROOT, load_manifest, part_location, payload, shard_chunks, stem, words

TERMS_FILE = ROOT / "catalog/phone-terms.json"
PER_SOURCE = 16
# Page furniture and, for the few books not in English, function words. Neither says what a book is about.
SKIPPED = frozenset("""appendix august bulletin card chapter contents copyright december edition february figure glossary
    inches index intro introduction january july june march module november october office page participant preface
    press refs section september table university volume workbook worksheet
    antes cada como cuadro cuando debe desde donde durante entre esta estas este estos figura otra otras otro otros
    para pero puede pueden sobre tabla tiene tienen toda todas todo todos
    avec cette dans elle elles leur leurs nous pour sont vous""".split())


def _sources(manifest, folder):
    """Per source: record count, records per stemmed word, strongest field per word, and words as printed."""
    for digest, shard in manifest["sources"].items():
        if shard["format"] == "zim":
            continue
        counts, weights, printed, total = Counter(), {}, Counter(), 0
        for pool, number, pin in shard_chunks(manifest, digest, shard):
            raw = (folder / part_location(pool, number, pin)).read_bytes()
            blob = payload(raw, "OWLShardBlob") if pin.get("path") else payload(raw, "OWLShardPart")[2]
            part = json.loads(decompress(b64decode(blob)))
            total += len(part["records"])
            for word, rows in part["postings"].items():
                counts[word] += len(rows)
                weights[word] = max(weights.get(word, 0), max(row % 16 for row in rows))
            for record in part["records"]:
                for field in (record[0], record[2], record[7] if len(record) > 7 else ""):
                    if isinstance(field, str):
                        printed.update(word.lower() for word in re.findall(r"[A-Za-z][A-Za-z'-]+", field))
        yield digest, total, counts, weights, printed


def compile_terms(folder=SEARCH_ROOT, limit=PER_SOURCE) -> dict[str, list[str]]:
    """Source SHA-256 to its distinctive words, most telling first."""
    sources = list(_sources(load_manifest(folder), Path(folder)))
    holders, printed_in, forms = Counter(), Counter(), defaultdict(Counter)
    for _, _, counts, _, printed in sources:
        holders.update(counts.keys())
        stems = set()
        for word, seen in printed.items():
            for piece in words(word):
                forms[stem(piece)][piece] += seen
                stems.add(stem(piece))
        printed_in.update(stems)
    result = {}
    for digest, total, counts, weights, _ in sources:
        scored = []
        for word, records in counts.items():
            # A word printed in a single book is as likely a broken hyphenation or a name as a subject.
            if (len(word) < 4 or not word.isalpha() or printed_in[word] < 2 or holders[word] < 2
                    or holders[word] > len(sources) * 0.3):
                continue
            heading = weights[word] >= 8
            if records < (2 if heading else 3):
                continue
            rarity = math.log(len(sources) / holders[word]) ** 1.5
            # Rounded so the order does not depend on a platform's last floating-point digit.
            scored.append((-round(records / max(total, 1) * rarity * (2.5 if heading else 1), 9), word))
        chosen = []
        for _, word in sorted(scored):
            form = min(forms[word].items(), key=lambda row: (-row[1], row[0]))[0]
            if form not in SKIPPED and form not in chosen:
                chosen.append(form)
            if len(chosen) == limit:
                break
        if chosen:
            result[digest] = chosen
    return dict(sorted(result.items()))


def encode_terms(terms) -> bytes:
    """One source to a line, so a rebuilt index changes only the lines of the books that changed."""
    rows = ",\n".join(json.dumps(digest) + ":" + json.dumps(chosen, ensure_ascii=False, separators=(",", ":"))
                      for digest, chosen in terms.items())
    return ('{"schema_version":1,"terms":{\n' + rows + "\n}}\n").encode("utf-8")


@lru_cache(maxsize=1)
def load_terms() -> dict[str, list[str]]:
    """The committed word lists; empty when the file is absent, as in an installed package."""
    if not TERMS_FILE.is_file():
        return {}
    data = json.loads(TERMS_FILE.read_bytes())
    if data.get("schema_version") != 1 or not isinstance(data.get("terms"), dict):
        raise ValueError("Unsupported phone terms file")
    return data["terms"]
