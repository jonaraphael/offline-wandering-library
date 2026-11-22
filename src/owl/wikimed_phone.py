"""Pinned ordinary-file derivatives of the WikiMed source edition."""
from hashlib import sha256
import json
from pathlib import Path
import re

from .safety import SafetyError

ROOT = Path(__file__).resolve().parents[2] / "catalog/wikimed-phone"
DESTINATION = "CRITICAL/MEDICAL/WIKIMED-PHONE/"
BUDGET = 4_000_000


def manifest():
    path = ROOT / "manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_bytes())
    if sum(row["bytes"] for row in data["volumes"]) > BUDGET:
        raise SafetyError("WikiMed phone layer exceeds its generation budget")
    files = set()
    for row in data["volumes"]:
        file = row["file"]
        if file in files or not re.fullmatch(r"wikimed-[a-z-]+\.pdf", file):
            raise SafetyError("Invalid WikiMed phone volume name")
        files.add(file)
    return data


def volumes(rows, pin):
    return pin.get("volumes", []) if any(
        row["id"] == pin.get("source_id") and row["sha256"] == pin.get("source_sha256")
        for row in rows) else []


def verified_volume(row):
    data = (ROOT / row["file"]).read_bytes()
    if len(data) != row["bytes"] or sha256(data).hexdigest() != row["sha256"]:
        raise SafetyError("WikiMed phone volume differs from pin: " + row["file"])
    return data
