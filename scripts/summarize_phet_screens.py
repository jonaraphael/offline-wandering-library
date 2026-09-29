#!/usr/bin/env python3
"""Bind complete named-screen browser evidence to immutable local PhET sources.

This reports structural and browser gates only. It never grants content admission
or physical-device certification; a substantive review and capture receipt remain
separate requirements.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if name in {"src", "href", "poster", "data"} and value and not value.startswith(("data:", "#", "javascript:")):
                self.references.append({"tag": tag, "attribute": name, "url": value})


def summarize(manifest_path, report_path, root, runner):
    manifest = json.loads(manifest_path.read_text())
    report = json.loads(report_path.read_text())
    if report.get("manifest_sha256") != pin(manifest_path)["sha256"]:
        raise ValueError("Browser report belongs to a different manifest")
    if report.get("runner_sha256") != pin(runner)["sha256"]:
        raise ValueError("Browser report belongs to a different runner")
    if report.get("mode") != "run" or not report.get("success") or not report.get("offline") or report.get("downloads") != 0:
        raise ValueError("A complete successful offline browser run is required")
    assets = {asset["id"]: asset for asset in manifest["assets"]}
    checks = {check["id"]: check for check in manifest["checks"]}
    viewports = {(v["width"], v["height"]) for v in manifest["viewports"]}
    expected = {(key, *viewport) for key in checks for viewport in viewports}
    observed = set()
    screens = {key: set() for key in assets}
    summaries = []
    for row in report["checks"]:
        key = (row["id"], row["viewport"]["width"], row["viewport"]["height"])
        if key in observed or key not in expected:
            raise ValueError("Duplicate or unexpected screen/viewport evidence")
        observed.add(key)
        check = checks[row["id"]]
        asset = assets[check["asset_id"]]
        if row["asset_id"] != asset["id"] or row["sha256"] != asset["sha256"] or not row["success"] or row["errors"]:
            raise ValueError("Failed check or changed source identity")
        for phase in ("entered", "after", "reset"):
            identity = row[phase]["selected"]
            layout = row[phase]["layout"]
            if identity["home"] or any(identity[k] != check["screen"][k] for k in ("index", "name")):
                raise ValueError("Named screen identity was not preserved")
            if layout["scroll_width"] > row["viewport"]["width"] + 1 or not layout["render_surfaces"]:
                raise ValueError("A screen phase lacks a fitted render surface")
        for prop in check["expected_changed_keys"]:
            states = [row[phase]["model"] for phase in ("entered", "after", "reset")]
            if any(prop not in state for state in states) or states[0][prop] == states[1][prop] or states[0][prop] != states[2][prop]:
                raise ValueError("Meaningful interaction/reset did not reproduce")
        runtime = {(s["index"], s["name"]) for s in row["entered"]["inventory"] if not s["home"]}
        configured = {(c["screen"]["index"], c["screen"]["name"]) for c in checks.values() if c["asset_id"] == asset["id"]}
        if runtime != configured:
            raise ValueError("Required screens differ from the runtime inventory")
        screens[asset["id"]] = runtime
        summaries.append({"id": row["id"], "asset_id": asset["id"], "viewport": row["viewport"], "screen": check["screen"],
                          "changed_and_restored": check["expected_changed_keys"], "blocked_remote_requests": row["blocked_remote_requests"]})
    if observed != expected:
        raise ValueError("Required screen/viewport evidence is missing")
    source_rows = []
    for asset in assets.values():
        source = (root / asset["destination"]).resolve()
        if not source.is_relative_to(root.resolve()):
            raise ValueError("Source escapes local root")
        actual = pin(source)
        if any(actual[k] != asset[k] for k in ("sha256", "size_bytes")):
            raise ValueError("Source bytes changed after browser review")
        content = source.read_text()
        versions = re.findall(r'''(?:window\.)?phet\.chipper\.version\s*=\s*['"]([^'"]+)''', content)
        refs = References()
        refs.feed(content)
        embedded_notices = all(x in content for x in ("creativecommons.org/licenses/by-nc/4.0", "University of Colorado", "Copyright"))
        optional = all(r["tag"] == "script" and r["url"].startswith("https://static.cloudflareinsights.com/beacon.min.js/") for r in refs.references)
        if versions != [asset["version"]] or not embedded_notices or not optional:
            raise ValueError("Source structure, version, notices, or dependency classification needs review")
        source_rows.append({"id": asset["id"], "source_url": asset["source_url"], "version": asset["version"],
                            "sha256": actual["sha256"], "size_bytes": actual["size_bytes"], "embedded_version": versions[0],
                            "original_notices_retained": True, "static_external_references": refs.references,
                            "static_external_reference_review": "Cloudflare analytics beacon only; blocked during all successful teaching-screen checks.",
                            "required_screens": [{"index": index, "name": name} for index, name in sorted(screens[asset["id"]])]})
    return {"schema_version": 1, "kind": "phet-required-screen-browser-and-structure-evidence", "content_ready": False,
            "content_review_required": True, "physical_device_certification": "pending", "offline": True,
            "gates": {"all_named_screens_in_both_viewports": True, "source_pins_rechecked_after_browser": True,
                      "embedded_runtime_versions_and_notices": True, "no_required_external_static_dependencies": True},
            "counts": {"simulations": len(assets), "teaching_screens": len(checks), "passing_checks": len(observed)},
            "evidence": [pin(manifest_path), pin(report_path), pin(runner)], "sources": source_rows, "checks": summaries,
            "limits": ["Browser emulation does not certify any physical device.", "Finite interactions do not exhaust all generated questions or possible simulation states.",
                       "No source pin is replaced and no catalog status is changed by this report."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("manifest", "report", "root", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--runner", type=Path, default=Path("scripts/check_phet_screens.cjs"))
    args = parser.parse_args()
    result = summarize(args.manifest, args.report, args.root, args.runner)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({**result["counts"], "output": str(args.output), "content_ready": False}))
