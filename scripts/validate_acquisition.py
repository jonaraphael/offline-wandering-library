#!/usr/bin/env python3
"""Repeatable acquisition verification with full local evidence and tiny stdout.

Default: acquisition tests, catalog validation, five no-download plans, fixed
small-preset invariants, English resource defaults, and generated-file freshness.
--full replaces the focused test pass with the complete unittest suite.
Planning simulates ample disk space: nominal profile capacity is checked without
requiring a terabyte of free space on the development computer.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROFILES = ("flash-16gb", "critical-64gb", "compact-256gb", "standard-512gb", "full-1tb")
SMALL_PRESETS = {"flash-16gb": {"assets": 551, "content_bytes": 9_869_555_191},
                 "critical-64gb": {"assets": 602, "content_bytes": 45_226_005_469}}
LANGUAGE_OPT_INS = {"gutenberg-multilingual", "wikipedia-es", "wikipedia-fr", "wikipedia-zh",
                    "wikipedia-ar", "wikipedia-pt", "wikipedia-it"}
SIMULATED_FREE_BYTES = 10_000_000_000_000
EVIDENCE_SCOPE = ("Local regression and no-download nominal-capacity planning; not a production build, "
                  "drive recovery or physical-device certification.")
MAX_PORTABLE_EVIDENCE_BYTES = 64 * 1024


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _input_hashes(sources):
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sources}
    # Aggregate trees keep portable evidence small while detecting code changes,
    # including newly added/deleted files, during a long regression run.
    for name in ("src", "scripts", "tests"):
        digest = hashlib.sha256()
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".js", ".cjs", ".html", ".css"}:
                digest.update(str(path.relative_to(ROOT)).encode() + b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
        hashes[name + "/**"] = digest.hexdigest()
    return hashes


def _check_inputs(initial, current):
    changed = sorted(key for key in initial.keys() | current.keys()
                     if initial.get(key) != current.get(key))
    return {"name": "inputs-unchanged", "passed": not changed,
            "changed_inputs": changed,
            **({"error": "Validation inputs changed during the run; repeat on stable inputs"}
               if changed else {})}


def _command(name, arguments, destination, timeout):
    start = time.monotonic()
    log = destination / (name + ".log")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    command = [sys.executable, *arguments]
    try:
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.run(command, cwd=ROOT, env=environment, stdout=output,
                                     stderr=subprocess.STDOUT, timeout=timeout, check=False)
        passed, code, error = process.returncode == 0, process.returncode, None
    except (OSError, subprocess.TimeoutExpired) as failure:
        passed, code, error = False, None, str(failure)
    result = {"name": name, "passed": passed, "command": command, "exit_code": code,
              "seconds": round(time.monotonic() - start, 3), "log": str(log)}
    with log.open("rb") as handle:
        handle.seek(max(0, log.stat().st_size - 2400))
        tail = handle.read().decode("utf-8", errors="replace")
    matches = re.findall(r"Ran (\d+) tests? in ([\d.]+)s", tail)
    if matches:
        result["tests_run"] = int(matches[-1][0])
    if not passed:
        # Full output stays on disk. Only the final diagnostic appears in JSON.
        result["failure_excerpt"] = tail
        if error:
            result["error"] = error
    return result


def _plans(destination):
    from owl.build import build
    from owl.catalog import load_catalog, load_profiles, resolve_content

    profiles = load_profiles(ROOT / "profiles")
    assets = load_catalog(ROOT / "catalog/library.yaml", profiles)
    results, summaries = [], []
    with tempfile.TemporaryDirectory(prefix="owl-acquisition-validation-") as directory:
        temporary = Path(directory).resolve()
        for name in PROFILES:
            target = temporary / name
            log = destination / ("plan-" + name + ".log")
            started = time.monotonic()
            row = {"name": "plan-" + name, "passed": False, "log": str(log)}
            try:
                # A plan regression must fail loudly if it tries any acquisition,
                # DNS/network activity, or writes the proposed library target.
                with ExitStack() as stack, log.open("w", encoding="utf-8") as output:
                    for function in ("owl.build.download", "owl.download.urlopen", "socket.create_connection"):
                        stack.enter_context(patch(function, side_effect=AssertionError("Validation plans must not download/use the network")))
                    stack.enter_context(patch("owl.build.shutil.disk_usage", return_value=
                                              shutil._ntuple_diskusage(SIMULATED_FREE_BYTES, 0, SIMULATED_FREE_BYTES)))
                    plan = build(target, catalog=ROOT / "catalog/library.yaml", profiles_dir=ROOT / "profiles",
                                 profile_name=name, resources_catalog=ROOT / "catalog/resources.yaml",
                                 plan_only=True, progress=lambda message: output.write(str(message) + "\n"))
                if target.exists():
                    raise AssertionError("Plan created its library target")
                if not plan["in_place_target_budget_fits"]:
                    raise AssertionError("Profile peak exceeds nominal capacity")
                selected, unresolved, selection = resolve_content(assets, profiles[name],
                    resources_path=ROOT / "catalog/resources.yaml")
                summary = {"profile": name, "assets": len(selected), "content_bytes": plan["content_bytes"],
                           "peak_bytes": plan["in_place_peak_budget_bytes"], "capacity_bytes": plan["capacity_bytes"],
                           "incomplete_resources": [r["id"] for r in selection["incomplete_resources"]] if selection else [],
                           "unresolved_assets": [a["id"] for a in unresolved], "target_created": target.exists()}
                if name in SMALL_PRESETS:
                    observed = {key: summary[key] for key in SMALL_PRESETS[name]}
                    if observed != SMALL_PRESETS[name]:
                        raise AssertionError(f"Fixed preset changed: expected {SMALL_PRESETS[name]}, observed {observed}")
                    if unresolved or selection:
                        raise AssertionError("Fixed small preset unexpectedly changed to resource selection")
                defaults = set(profiles[name].get("default_resources", []))
                if defaults & LANGUAGE_OPT_INS:
                    raise AssertionError("A non-English resource was silently defaulted: " + ", ".join(sorted(defaults & LANGUAGE_OPT_INS)))
                row.update(passed=True, summary=summary, plan=plan)
                summaries.append(summary)
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
                with log.open("a", encoding="utf-8") as output:
                    output.write(row["traceback"])
            row["seconds"] = round(time.monotonic() - started, 3)
            results.append(row)
    # English defaults must not remove the user's explicit language opt-in.
    try:
        _, _, selection = resolve_content(assets, profiles["full-1tb"],
            resources_path=ROOT / "catalog/resources.yaml", include=["wikipedia-es"])
        if "wikipedia-es" not in selection["selected_ids"]:
            raise AssertionError("Explicit Spanish Wikipedia opt-in is unavailable")
        results.append({"name": "explicit-language-opt-in", "passed": True})
    except Exception as error:
        results.append({"name": "explicit-language-opt-in", "passed": False, "error": str(error)})
    return results, summaries


def _summary(report, path):
    failures = [row for row in report["checks"] if not row["passed"]]
    result = {"passed": not failures, "checks": len(report["checks"]), "failed": len(failures),
              "tests": sum(row.get("tests_run", 0) for row in report["checks"]),
              "seconds": report["seconds"], "report": str(path),
              "profiles": [{"id": row["profile"], "assets": row["assets"],
                            "bytes": row["content_bytes"], "incomplete": len(row["incomplete_resources"])}
                           for row in report.get("profiles", [])],
              "failures": [{"check": row["name"], "error": row.get("error", row.get("failure_excerpt", "Check failed"))[-180:]}
                           for row in failures[:5]]}
    text = json.dumps(result, sort_keys=True, ensure_ascii=True)
    if len(text.encode()) > 2048:
        result["failures"] = [{"check": row["name"]} for row in failures[:5]]
        text = json.dumps(result, sort_keys=True, ensure_ascii=True)
    if len(text.encode()) > 2048:
        result.pop("profiles", None)
        text = json.dumps(result, sort_keys=True, ensure_ascii=True)
    return text


def _portable_evidence(report, raw_report):
    """Export only portable facts; command lines, paths and diagnostics stay local."""
    fields = ("schema_version", "completed_at", "downloads", "fixed_small_preset_expectations",
              "freshness_checked", "full_tests", "input_sha256", "simulated_free_bytes_for_plans")
    result = {key: report[key] for key in fields}
    checks = []
    for row in report["checks"]:
        check = {"name": row["name"], "passed": row.get("passed") is True}
        if "tests_run" in row:
            check["tests_run"] = row["tests_run"]
        if not check["passed"]:
            # No error excerpts: exception messages may contain private paths,
            # test fixture bodies or tokens. Detailed evidence remains local.
            check["failure_kind"] = "nonzero_exit" if row.get("exit_code") is not None else "check_error"
            if row.get("exit_code") is not None:
                check["exit_code"] = row["exit_code"]
        checks.append(check)
    required = {"catalog", "inputs-unchanged", "full-tests" if report["full_tests"] else "acquisition-tests",
                "explicit-language-opt-in", *("plan-" + name for name in PROFILES)}
    if report["freshness_checked"]:
        required.update({"selector-freshness", "content-docs-freshness"})
    if not required <= {row["name"] for row in checks}:
        checks.append({"name": "validation-incomplete", "passed": False, "failure_kind": "missing_checks"})
    result["checks"] = checks
    result["passed"] = report.get("passed") is True and bool(checks) and all(row["passed"] for row in checks)
    profiles = []
    for row in report.get("profiles", []):
        profile = {key: row[key] for key in ("profile", "assets", "content_bytes", "peak_bytes",
                   "capacity_bytes", "target_created")}
        for key in ("incomplete_resources", "unresolved_assets"):
            values = row.get(key, [])
            profile[key] = values[:128]
            if len(values) > 128:
                profile[key + "_total"] = len(values)
                profile[key + "_truncated"] = True
        profiles.append(profile)
    result["profiles"] = profiles
    result["scope"] = EVIDENCE_SCOPE
    result["reproduce"] = ("python scripts/validate_acquisition.py" + (" --full" if report["full_tests"] else "") +
        (" --skip-freshness" if not report["freshness_checked"] else "") +
        " --export-evidence catalog/acquisition/validation-evidence.json")
    digest = hashlib.sha256()
    with raw_report.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    result["raw_report"] = {"sha256": digest.hexdigest(), "size_bytes": raw_report.stat().st_size}
    return result


def _export_evidence(report, raw_report, destination):
    from owl.safety import atomic_write, reject_symlinks

    destination = destination.expanduser().absolute()
    reject_symlinks(destination)
    evidence = _portable_evidence(report, raw_report)
    payload = (json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    if len(payload) > MAX_PORTABLE_EVIDENCE_BYTES:
        raise ValueError("Portable validation evidence exceeds the 64 KiB bound; detailed report remains local")
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(destination, payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Run the complete unittest suite instead of only acquisition tests")
    parser.add_argument("--skip-freshness", action="store_true", help="Skip generated-file checks while editing; final validation should omit this")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".owl/acquisition/validation",
                        help="Parent directory for a unique detailed report and command logs")
    parser.add_argument("--timeout", type=int, default=600, help="Maximum seconds per subprocess (default:600)")
    parser.add_argument("--export-evidence", type=Path,
                        help="Write a bounded portable evidence JSON without local paths, commands or log bodies")
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    from owl.safety import reject_symlinks
    destination = args.output_dir.expanduser().absolute()
    reject_symlinks(destination)
    destination.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="run-", dir=destination)).resolve()
    started = time.monotonic()
    report = {"schema_version": 1, "started_at": _now(), "full_tests": args.full,
              "freshness_checked": not args.skip_freshness, "downloads": 0,
              "simulated_free_bytes_for_plans": SIMULATED_FREE_BYTES,
              "fixed_small_preset_expectations": SMALL_PRESETS, "checks": [], "profiles": []}
    sources = [ROOT / "catalog/library.yaml", ROOT / "catalog/resources.yaml", ROOT / "catalog/acquisition/recipes.yaml",
               ROOT / "SELECT.html", ROOT / "docs/content-selection.md",
               *(ROOT / "profiles" / (name + ".yaml") for name in PROFILES)]
    report["input_sha256"] = _input_hashes(sources)
    jobs = [("catalog", ["scripts/validate_catalog.py"]),
            ("full-tests" if args.full else "acquisition-tests",
             ["-m", "unittest", "discover", "-s", "tests", "-v", "-p", "test_*.py" if args.full else "test_acquisition*.py"])]
    if not args.skip_freshness:
        jobs.extend([("selector-freshness", ["scripts/build_selector.py", "--check"]),
                     ("content-docs-freshness", ["scripts/build_content_docs.py", "--check"])])
    for name, arguments in jobs:
        report["checks"].append(_command(name, arguments, destination, args.timeout))
    try:
        checks, report["profiles"] = _plans(destination)
        report["checks"].extend(checks)
    except Exception as error:
        report["checks"].append({"name": "profile-plans", "passed": False, "error": str(error),
                                 "traceback": traceback.format_exc()})
    try:
        report["final_input_sha256"] = _input_hashes(sources)
        report["checks"].append(_check_inputs(report["input_sha256"], report["final_input_sha256"]))
    except OSError as error:
        report["checks"].append({"name": "inputs-unchanged", "passed": False, "error": str(error)})
    report.update(completed_at=_now(), seconds=round(time.monotonic() - started, 3),
                  passed=all(row["passed"] for row in report["checks"]))
    path = destination / "report.json"
    _dump(path, report)
    if args.export_evidence:
        try:
            _export_evidence(report, path, args.export_evidence)
        except (OSError, ValueError) as error:
            report["checks"].append({"name":"export-evidence", "passed":False, "error":str(error)})
            report["passed"] = False
            _dump(path, report)
    print(_summary(report, path))
    return int(any(not row["passed"] for row in report["checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
