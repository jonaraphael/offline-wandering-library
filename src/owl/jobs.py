"""Detached, resumable build jobs with bounded diagnostics and owned cancellation.

Jobs survive their launching terminal, not a reboot. Resume uses the captured
source and input recipe; create a new job to adopt code or catalog changes.
"""
from __future__ import annotations

import argparse
import _thread
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.metadata
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import runpy
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .runtime import file_lock, interrupt_signals
from .safety import SafetyError, atomic_write, guard_directory, reject_symlinks, safe_path, sha256_file

SCHEMA = 1
HEARTBEAT_SECONDS = 2.0
LOG_BYTES = 2 * 1024 * 1024
TAIL_BYTES = 8192
REPO_ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {"complete", "failed", "cancelled", "awaiting_review"}
INPUT_OPTIONS = {"--catalog", "--profiles-dir", "--resources-catalog", "--extra-catalog", "--navigation-dir", "--local-manifest"}
OUTPUT_OPTIONS = {"--cache-dir", "--work-dir"}
TRIAL_SCRIPTS = {
    'trial_supervisor.py': {'run'},
    'prepare_review_packets.py': None,
    'inspect_map_capture.py': None, 'inspect_ocw_packages.py': None,
    'prepare_ocw_preview.py': None, 'inspect_zim_candidates.py': None,
    'prepare_ocw_followup.py': None,
    'inspect_survivor_capture.py': None,
    'check_manual_package.py': None,
    'prepare_sqlite_package.py': None,
    'prepare_ocw_complete_preview.py': None,
    'review_ocw_course.py': None,
    'inspect_kolibri_capture.py': None,
    'inspect_kolibri_census.py': None,
    'probe_source_batches.py': None,
    'prepare_stackoverflow.py': {'inspect'},
    'trial_direct_previews.py': {'run'},
    'acquire_content.py': {'preview', 'inspect-local', 'audit', 'report'},
    'audit_manual_dependencies.py': None,
    'inspect_midwives_response.py': None,
    'inspect_midwives_digital.py': None,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise SafetyError(f"Refusing symlink job/input directory: {path}")
    path = path.parent.resolve() / path.name
    reject_symlinks(path)
    return path


def _read(path: Path, *, max_bytes=4 * 1024 * 1024):
    reject_symlinks(path)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise SafetyError(f"Invalid job metadata: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _owned(job_dir: Path) -> tuple[Path, dict]:
    job_dir = _path(job_dir)
    owner = _read(job_dir / "owner.json")
    if owner.get("owner") != "offline-wandering-library-job" or owner.get("schema_version") != SCHEMA:
        raise SafetyError(f"Unrecognized job directory: {job_dir}")
    return job_dir, owner


def _dependencies() -> dict:
    packages = {}
    for name in ("PyYAML", "pypdf", "cryptography", "libzim", "PyMuPDF"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": list(sys.version_info[:3]), "packages": packages}


def _snapshot(job_dir: Path, argv: list[str], *, scripts=False) -> dict:
    snapshot = job_dir / "snapshot"
    manifest = {}
    total = 0

    def copy(source: Path, destination: Path):
        nonlocal total
        reject_symlinks(source)
        if source.is_dir():
            for child in sorted(source.iterdir()):
                if child.name != "__pycache__" and child.suffix not in {".pyc", ".pyo"}:
                    copy(child, destination / child.name)
        elif source.is_file():
            total += source.stat().st_size
            if total > 64 * 1024 * 1024 or len(manifest) >= 10000:
                raise SafetyError("Job source/input snapshot exceeds 64 MiB or 10,000 files")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            manifest[destination.relative_to(snapshot).as_posix()] = sha256_file(destination)
        else:
            raise SafetyError(f"Job input is not a regular file/directory: {source}")

    for relative in ("src/owl", "profiles", "assets", "docs/sources.md") + (("scripts",) if scripts else ()):
        source = REPO_ROOT / relative
        if source.exists():
            copy(source, snapshot / relative)
    # Freeze runtime catalogs and their referenced acquisition evidence. Other
    # candidate histories are independent controls, supplied explicitly by their
    # jobs; growing discovery history must not fill every worker's snapshot.
    catalog = REPO_ROOT / "catalog"
    if catalog.exists():
        reject_symlinks(catalog)
        for source in sorted(catalog.iterdir()):
            if source.name != "acquisition":
                copy(source, snapshot / "catalog" / source.name)
        default_recipes = catalog / "acquisition/recipes.yaml"
        if default_recipes.exists():
            copy(default_recipes, snapshot / "catalog/acquisition/recipes.yaml")
        pending = [name for name in manifest if name.startswith("catalog/")]
        scanned = set()
        while pending:
            name = pending.pop()
            if name in scanned or Path(name).suffix not in {".json", ".yaml", ".yml"}:
                continue
            scanned.add(name)
            import yaml
            document = snapshot / name
            body = document.read_text(encoding="utf-8")
            values = [json.loads(body) if document.suffix == ".json" else yaml.safe_load(body)]
            visited = 0
            while values:
                value = values.pop()
                visited += 1
                if visited > 1000000:
                    raise SafetyError("Catalog snapshot dependency traversal exceeds1,000,000 nodes")
                if isinstance(value, dict):
                    values.extend(value.values())
                elif isinstance(value, list):
                    values.extend(value)
                elif isinstance(value, str) and value.startswith("catalog/acquisition/"):
                    source = safe_path(REPO_ROOT, value)
                    if source.is_file() and value not in manifest:
                        copy(source, snapshot / value)
                        pending.append(value)
    captured = []
    index = 0
    target_seen = False
    target = None
    while index < len(argv):
        token = argv[index]
        option, separator, inline = token.partition("=")
        if option in INPUT_OPTIONS | OUTPUT_OPTIONS:
            if not separator:
                index += 1
                if index >= len(argv):
                    raise ValueError(f"Missing value for {option}")
            value = inline if separator else argv[index]
            source = _path(Path(value))
            if option in INPUT_OPTIONS:
                destination = (snapshot / "catalog/library.yaml" if option == "--catalog" and
                    source == (REPO_ROOT / "catalog/library.yaml").resolve() else
                    snapshot / "inputs" / str(index) / source.name)
                copy(source, destination)
                if source.is_file() and option == "--catalog":
                    sibling = source.with_name("resources.yaml")
                    if sibling.is_file():
                        copy(sibling, destination.with_name("resources.yaml"))
                value = str(destination)
            else:
                value = str(source)
            captured.extend([option, value])
        else:
            # Build CLI's target is the sole positional value. Known options
            # with scalar values must not have their values mistaken for it.
            if token in {"--profile", "--include", "--exclude", "--edition"}:
                captured.append(token)
                index += 1
                if index >= len(argv):
                    raise ValueError(f"Missing value for {token}")
                captured.append(argv[index])
            elif not token.startswith("-") and not target_seen:
                target = str(_path(Path(token)))
                captured.append(target)
                target_seen = True
            else:
                captured.append(token)
        index += 1
    if not target_seen:
        raise ValueError("A build job requires a target directory")
    if any(token.partition("=")[0] in {"--detach", "--job-dir", "--plan", "--list-resources"} for token in argv):
        raise ValueError("Job build arguments must request a foreground build, without --detach, --job-dir, --plan or --list-resources")
    return {"build_argv": captured, "original_argv": argv, "dependencies": _dependencies(),
            "snapshot_files": manifest, "source_bytes": total, "working_directory": str(Path.cwd()), "target": target}


def _policy(max_attempts=3, retry_delay=30.0, retry_deadline=3600.0):
    if (type(max_attempts) is not int or not 1 <= max_attempts <= 20 or
            not 0 <= retry_delay <= 3600 or not 0 < retry_deadline <= 86400):
        raise ValueError("Retry policy requires 1–20 attempts, 0–3600 second delay, and a 0–86400 second deadline")
    return {"max_attempts": max_attempts, "retry_delay": float(retry_delay), "retry_deadline": float(retry_deadline)}


def _active(job_dir: Path) -> bool:
    try:
        with file_lock(job_dir / "worker.lock"):
            return False
    except SafetyError as error:
        # Check the path separately so unsafe file errors are never a liveness proof.
        reject_symlinks(job_dir / "worker.lock")
        if "Another OWL process" not in str(error):
            raise
        return True


def _launch(job_dir: Path, owner: dict, recipe: dict) -> dict:
    run_id = uuid.uuid4().hex
    status = {"schema_version": SCHEMA, "job_id": owner["job_id"], "run_id": run_id,
              "state": "starting", "phase": "starting", "attempt": 0,
              "started_at": _now(), "heartbeat_at": _now(), "message": "Launching captured build recipe"}
    atomic_write(job_dir / "status.json", _json(status))
    snapshot_source = str(job_dir / "snapshot/src")
    bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1)); from owl.jobs import _worker; raise SystemExit(_worker(*sys.argv[1:]))"
    command = [sys.executable, "-I", "-u", "-c", bootstrap, snapshot_source, str(job_dir), run_id]
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
               "stderr": subprocess.DEVNULL, "close_fds": True, "cwd": str(job_dir / "snapshot")}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    except OSError as error:
        status.update(state="failed", phase="launch", error=str(error)[:500], finished_at=_now())
        atomic_write(job_dir / "status.json", _json(status))
        raise
    # Reap our own child while this launcher stays alive; the daemon does not
    # keep a terminal/parent alive and holds no stdin/stdout pipe open.
    threading.Thread(target=process.wait, daemon=True).start()
    # The worker owns status after spawn. Never overwrite it with launcher data.
    return {**status, "pid": process.pid, "job_dir": str(job_dir)}


def start_job(build_argv: list[str], *, job_dir: Path, max_attempts=3,
              retry_delay=30.0, retry_deadline=3600.0) -> dict:
    policy = _policy(max_attempts, retry_delay, retry_deadline)
    job_dir = _path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(job_dir / "control.lock"):
        if any(path.name != "control.lock" for path in job_dir.iterdir()):
            raise SafetyError(f"Job directory is not empty; use resume for an existing job: {job_dir}")
        owner = {"owner": "offline-wandering-library-job", "schema_version": SCHEMA, "job_id": uuid.uuid4().hex}
        atomic_write(job_dir / "owner.json", _json(owner))
        recipe = {"schema_version": SCHEMA, **_snapshot(job_dir, list(build_argv)), "retry_policy": policy}
        atomic_write(job_dir / "recipe.json", _json(recipe))
        return _launch(job_dir, owner, recipe)


def start_acquisition_job(manifest, staging, *, job_dir: Path, budget_bytes=None,
                          reserve_bytes=1024 * 1024 * 1024, allow_local=False, production_root=None, local_manifest=None,
                          resource_ids=(), profile=None, max_attempts=3, retry_delay=30.0,
                          retry_deadline=3600.0, continue_missing_sources=False) -> dict:
    """Snapshot and launch a source-review build; terminal success is not library readiness."""
    from .acquisition.capture import capture
    manifest, staging, job_dir = _path(Path(manifest)), _path(Path(staging)), _path(Path(job_dir))
    if job_dir == staging or job_dir.is_relative_to(staging) or staging.is_relative_to(job_dir):
        raise SafetyError("Acquisition job and capture directories must be separate owned trees")
    kwargs = {"budget_bytes": budget_bytes, "reserve_bytes": reserve_bytes, "allow_local": bool(allow_local),
              "production_root": str(_path(Path(production_root))) if production_root is not None else None,
              "resource_ids": list(resource_ids), "profile": profile,
              "continue_missing_sources": bool(continue_missing_sources)}
    capture(manifest, staging, plan_only=True, local_manifest=local_manifest, **kwargs)
    policy = _policy(max_attempts, retry_delay, retry_deadline)
    job_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(job_dir / "control.lock"):
        if any(path.name != "control.lock" for path in job_dir.iterdir()):
            raise SafetyError(f"Job directory is not empty; use resume for an existing job: {job_dir}")
        owner = {"owner": "offline-wandering-library-job", "schema_version": SCHEMA, "job_id": uuid.uuid4().hex}
        atomic_write(job_dir / "owner.json", _json(owner))
        # Reuse the same bounded source/input snapshotter as normal builds.
        snapshot_args = [str(staging), "--catalog", str(manifest)]
        if local_manifest is not None:
            snapshot_args.extend(["--local-manifest", str(_path(Path(local_manifest)))])
        snapshot = _snapshot(job_dir, snapshot_args)
        if local_manifest is not None:
            kwargs["local_manifest"] = snapshot["build_argv"][snapshot["build_argv"].index("--local-manifest") + 1]
        captured_manifest = snapshot["build_argv"][snapshot["build_argv"].index("--catalog") + 1]
        recipe = {"schema_version": SCHEMA, **snapshot, "kind": "acquisition", "retry_policy": policy,
                  "acquisition": {"manifest": captured_manifest, "kwargs": kwargs}}
        atomic_write(job_dir / "recipe.json", _json(recipe))
        return _launch(job_dir, owner, recipe)


def status_job(job_dir: Path) -> dict:
    job_dir, _ = _owned(job_dir)
    status = _read(job_dir / "status.json")
    status = dict(status)
    status["worker_active"] = _active(job_dir)
    if status["state"] not in TERMINAL and not status["worker_active"]:
        started = datetime.fromisoformat(status["started_at"]).timestamp()
        if time.time() - started > 30:
            status["state"] = "interrupted"
            status["message"] = "Worker exited without a terminal record; resume the saved job"
    return status


def start_trial_step(script, argv, *, job_dir, target, inputs=(), working_directory=None):
    """Run one frozen, allowlisted review step using the existing job runner.

    No shell, automatic content approval, production build, or model API is
    available here. Mutable control inputs are independently pinned before and
    after execution; reports/outputs must not also be declared as inputs.
    """
    if script not in TRIAL_SCRIPTS or not isinstance(argv, list) or any(not isinstance(a, str) for a in argv):
        raise SafetyError('Unsupported trial script or arguments')
    allowed = TRIAL_SCRIPTS[script]
    if allowed is not None and (not argv or argv[0] not in allowed):
        raise SafetyError('Trial script action is outside the reviewed workflow')
    job_dir, target = _path(Path(job_dir)), _path(Path(target))
    pins, total = {}, 0
    for value in inputs:
        path = _path(Path(value))
        if not path.is_file(): raise SafetyError('Trial control input must be a regular file')
        total += path.stat().st_size
        if total > 64 * 1024 * 1024 or len(pins) >= 1000:
            raise SafetyError('Trial control inputs exceed64MiB/1000files')
        pins[str(path)] = sha256_file(path)
    job_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(job_dir/'control.lock'):
        if any(p.name != 'control.lock' for p in job_dir.iterdir()):
            raise SafetyError('Trial job already exists; resume its exact saved recipe')
        owner = {'owner':'offline-wandering-library-job','schema_version':SCHEMA,'job_id':uuid.uuid4().hex}
        atomic_write(job_dir/'owner.json', _json(owner))
        snapshot = _snapshot(job_dir, [str(target)], scripts=True)
        recipe = {'schema_version':SCHEMA, **snapshot, 'kind':'trial_step', 'retry_policy':_policy(),
            'trial_step':{'script':script,'argv':argv,'inputs':pins,'cwd':str(_path(Path(working_directory or REPO_ROOT)))}}
        atomic_write(job_dir/'recipe.json', _json(recipe))
        return _launch(job_dir, owner, recipe)


def _run_trial_step(job_dir, recipe):
    step = recipe['trial_step']
    script = step['script']; allowed = TRIAL_SCRIPTS.get(script)
    if script not in TRIAL_SCRIPTS or allowed is not None and (not step['argv'] or step['argv'][0] not in allowed):
        raise SafetyError('Unsupported captured trial action')
    def check():
        for name, digest in step['inputs'].items():
            path = Path(name); reject_symlinks(path)
            if sha256_file(path) != digest: raise SafetyError('Trial control input changed: '+name)
    check()
    path = job_dir/'snapshot/scripts'/script
    if 'scripts/'+script not in recipe['snapshot_files']:
        raise SafetyError('Trial script is outside the verified snapshot')
    old_argv, old_cwd = sys.argv, Path.cwd()
    try:
        os.chdir(step['cwd']); sys.argv = [str(path), *step['argv']]
        try: runpy.run_path(str(path), run_name='__main__')
        except SystemExit as error:
            if error.code not in (None, 0): raise RuntimeError('Trial script exited with status '+str(error.code)) from error
    finally:
        sys.argv = old_argv; os.chdir(old_cwd)
    check()
    return {'operation':'trial_step','script':script,'content_ready':False,
        'status':'awaiting_review','control_inputs':step['inputs']}


def cancel_job(job_dir: Path) -> dict:
    job_dir, owner = _owned(job_dir)
    with file_lock(job_dir / "control.lock"):
        status = status_job(job_dir)
        if status["state"] in TERMINAL or status["state"] == "interrupted":
            return status
        atomic_write(job_dir / "cancel.json", _json({"job_id": owner["job_id"], "run_id": status["run_id"]}))
        return {"state": "cancellation_requested", "run_id": status["run_id"],
                "message": "Worker will stop cooperatively at the next interruptible boundary"}


def resume_job(job_dir: Path) -> dict:
    job_dir, owner = _owned(job_dir)
    with file_lock(job_dir / "control.lock"):
        status = status_job(job_dir)
        if status["worker_active"] or status["state"] not in TERMINAL | {"interrupted"}:
            raise SafetyError("Job is already active or starting")
        if status["state"] in {"complete", "awaiting_review"}:
            raise SafetyError("Job already completed its operation; review its result or create a new job")
        recipe = _read(job_dir / "recipe.json")
        _verify_recipe(job_dir, recipe)
        return _launch(job_dir, owner, recipe)


def logs_job(job_dir: Path, *, tail_bytes=TAIL_BYTES, tail_lines=40) -> str:
    job_dir, _ = _owned(job_dir)
    if type(tail_bytes) is not int or not 1 <= tail_bytes <= TAIL_BYTES:
        raise ValueError(f"Log tail must be between 1 and {TAIL_BYTES} bytes")
    if type(tail_lines) is not int or not 1 <= tail_lines <= 200:
        raise ValueError("Log tail must be between 1 and 200 lines")
    path = job_dir / "build.log"
    reject_symlinks(path)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - tail_bytes))
        # A seek may cut the first UTF-8 character; ignoring that fragment keeps
        # the returned UTF-8 bytes within the requested byte bound too.
        content = handle.read(tail_bytes).decode("utf-8", errors="ignore")
        return "".join(content.splitlines(keepends=True)[-tail_lines:])


def _verify_recipe(job_dir: Path, recipe: dict):
    if recipe.get("schema_version") != SCHEMA or recipe["dependencies"] != _dependencies():
        raise SafetyError("Captured job Python/dependencies changed; restore them or create a new job")
    snapshot = job_dir / "snapshot"
    for relative, digest in recipe["snapshot_files"].items():
        path = snapshot / relative
        if path.is_absolute() and not path.is_relative_to(snapshot) or ".." in Path(relative).parts:
            raise SafetyError("Invalid captured source path")
        if sha256_file(path) != digest:
            raise SafetyError(f"Captured job source/input changed: {relative}; create a new job")


class _Log(io.TextIOBase):
    def __init__(self, job_dir):
        self.job_dir = job_dir
        self.handler = RotatingFileHandler(job_dir / "build.log", maxBytes=LOG_BYTES, backupCount=2, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    def write(self, text):
        for name in ("build.log", "build.log.1", "build.log.2"):
            path = self.job_dir / name
            reject_symlinks(path)
            if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise SafetyError(f"Unsafe job log: {path}")
        for offset in range(0, len(text), 2000):
            chunk = text[offset:offset + 2000].rstrip("\n")
            if chunk:
                self.handler.handle(logging.LogRecord("owl-job", logging.INFO, "", 0, chunk, (), None))
        return len(text)

    def flush(self):
        if hasattr(self, "handler"):
            self.handler.flush()

    def close(self):
        self.handler.close()
        super().close()


class _Progress:
    def __init__(self, job_dir, state, stream):
        self.job_dir, self.state, self.stream = job_dir, state, stream
        self.lock = threading.Lock()

    def __call__(self, message):
        self.stream.write(str(message) + "\n")
        with self.lock:
            self.state["message"] = str(message)[:300]

    def event(self, **fields):
        allowed = {"phase", "active_asset", "total_assets", "completed_assets", "passages",
                   "completed_units", "checkpoint_at", "scratch_bytes", "output_bytes", "warning_count",
                   "cache_hits", "cache_misses"}
        with self.lock:
            for key, value in fields.items():
                if key in allowed and value is None:
                    self.state.pop(key, None)
                elif key in allowed and isinstance(value, (str, int, float, bool)):
                    self.state[key] = value[:160] if isinstance(value, str) else value

    def save(self, **fields):
        with self.lock:
            self.state.update(fields, heartbeat_at=_now())
            for key in ("message", "error"):
                if key in self.state:
                    self.state[key] = str(self.state[key])[:250]
            data = _json(self.state)
            if len(data) > 2048:
                # Non-ASCII diagnostics may occupy four bytes per character.
                for key in ("message", "error", "active_asset", "checkpoint_at"):
                    if key in self.state:
                        self.state[key] = str(self.state[key])[:40]
                data = _json(self.state)
            atomic_write(self.job_dir / "status.json", data)


def _worker(job_dir: str, run_id: str) -> int:
    """Record setup failures too, while never overwriting another live worker."""
    try:
        return _run_worker(job_dir, run_id)
    except BaseException as error:
        try:
            directory, _ = _owned(Path(job_dir))
            state = _read(directory / "status.json")
            if state["run_id"] == run_id and not _active(directory):
                state.update(state="failed", phase="startup", exit_code=1, finished_at=_now(),
                             error_type=type(error).__name__, error=str(error)[:250])
                atomic_write(directory / "status.json", _json(state))
        except (OSError, ValueError, RuntimeError):
            pass  # An unsafe/unavailable job directory must not be recreated.
        return 1


def _run_worker(job_dir: str, run_id: str) -> int:
    job_dir, owner = _owned(Path(job_dir))
    with guard_directory(job_dir), file_lock(job_dir / "worker.lock"):
        state = _read(job_dir / "status.json")
        if state["run_id"] != run_id:
            return 1
        # Logs and cancellation are owned regular files; never follow replacement links.
        for name in ("build.log", "build.log.1", "build.log.2", "cancel.json"):
            reject_symlinks(job_dir / name)
        stream = _Log(job_dir)
        progress = _Progress(job_dir, state, stream)
        stopped = threading.Event()
        cancelled = threading.Event()

        def heartbeat():
            while not stopped.wait(HEARTBEAT_SECONDS):
                try:
                    request = job_dir / "cancel.json"
                    if state.get("state") in TERMINAL:
                        return
                    if request.exists() and _read(request) == {"job_id": owner["job_id"], "run_id": run_id}:
                        if not cancelled.is_set():
                            cancelled.set()
                            progress.save(state="cancelling", message="Cancellation requested; waiting for safe interruption")
                            _thread.interrupt_main()
                    else:
                        progress.save()
                except (OSError, ValueError) as error:
                    stream.write(f"Job heartbeat failed: {error}")
                    _thread.interrupt_main()
                    return

        monitor = threading.Thread(target=heartbeat, daemon=True)
        try:
            with redirect_stdout(stream), redirect_stderr(stream), interrupt_signals():
                recipe = _read(job_dir / "recipe.json")
                _verify_recipe(job_dir, recipe)
                policy = recipe["retry_policy"]
                progress.save(state="running", pid=os.getpid())
                monitor.start()
                from .build import main as build_main
                from .download import TransientDownloadError
                retry_started = None
                for attempt in range(1, policy["max_attempts"] + 1):
                    progress.save(state="running", attempt=attempt)
                    try:
                        if recipe.get("kind", "build") == "acquisition":
                            from .acquisition.capture import IncompleteCaptureError, capture
                            configuration = recipe["acquisition"]
                            manifest = Path(configuration["manifest"])
                            snapshot_root = job_dir / "snapshot"
                            if (not manifest.is_relative_to(snapshot_root)
                                    or manifest.relative_to(snapshot_root).as_posix() not in recipe["snapshot_files"]):
                                raise SafetyError("Acquisition manifest is outside its verified job snapshot")
                            try:
                                operation_result = capture(manifest, Path(recipe["target"]),
                                                           progress=progress, **configuration["kwargs"])
                            except IncompleteCaptureError as error:
                                atomic_write(job_dir / "result.json", _json(error.report))
                                progress.save(result_file="result.json")
                                raise
                            if operation_result.get("status") != "awaiting_review" or operation_result.get("content_ready") is not False:
                                raise RuntimeError("Acquisition returned without a pending review result")
                            terminal = "awaiting_review"
                        elif recipe.get('kind') == 'trial_step':
                            operation_result = _run_trial_step(job_dir, recipe)
                            terminal = 'awaiting_review'
                        elif recipe.get("kind", "build") == "build":
                            result = build_main(recipe["build_argv"], raise_errors=True, progress=progress)
                            if result != 0:
                                raise RuntimeError(f"Build exited with status {result}")
                            build_state_path = Path(recipe["target"]) / "LIBRARY/.owl/state.json"
                            build_state = _read(build_state_path, max_bytes=64 * 1024 * 1024)
                            if (not build_state.get("complete") or build_state.get("phase") != "complete" or
                                    build_state.get("result", {}).get("status") != "passed"):
                                raise RuntimeError("Build returned without completed verification and passed postflight")
                            operation_result, terminal = build_state["result"], "complete"
                        else:
                            raise SafetyError("Unknown captured job kind")
                        atomic_write(job_dir / "result.json", _json(operation_result))
                        progress.save(result_file="result.json")
                        for key in ("retry_seconds", "error", "error_type"):
                            with progress.lock:
                                state.pop(key, None)
                        progress.save(state=terminal, phase=terminal, exit_code=0, finished_at=_now())
                        return 0
                    except TransientDownloadError as error:
                        if retry_started is None:
                            retry_started = time.monotonic()
                        delay = min(policy["retry_delay"] * 2 ** (attempt - 1), 300)
                        if attempt == policy["max_attempts"] or time.monotonic() - retry_started + delay > policy["retry_deadline"]:
                            raise
                        progress(str(error))
                        progress.save(state="retry_wait", retry_seconds=delay, error_type=type(error).__name__, error=str(error)[:500])
                        if cancelled.wait(delay):
                            raise KeyboardInterrupt
        except KeyboardInterrupt:
            progress.save(state="cancelled", exit_code=130, finished_at=_now(), message="Stopped safely; resume this saved job")
            return 130
        except BaseException as error:
            stream.write(f"{type(error).__name__}: {error}")
            progress.save(state="failed", exit_code=1, finished_at=_now(), error_type=type(error).__name__, error=str(error)[:500])
            return 1
        finally:
            stopped.set()
            if monitor.is_alive():
                monitor.join(timeout=3)
            stream.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="Capture and launch a build without keeping the terminal open")
    start.add_argument("job_dir", type=Path)
    start.add_argument("--max-attempts", type=int, default=3)
    start.add_argument("--retry-delay", type=float, default=30)
    start.add_argument("--retry-deadline", type=float, default=3600)
    for name in ("status", "logs", "cancel", "resume"):
        command = subparsers.add_parser(name)
        command.add_argument("job_dir", type=Path)
        if name == "logs":
            command.add_argument("--tail", type=int, default=40, help="last 1–200 lines within an 8 KiB byte limit")
    values = list(sys.argv[1:] if argv is None else argv)
    build_argv = []
    if "--" in values:
        split = values.index("--")
        values, build_argv = values[:split], values[split + 1:]
    args = parser.parse_args(values)
    try:
        if args.command == "start":
            result = start_job(build_argv, job_dir=args.job_dir, max_attempts=args.max_attempts,
                               retry_delay=args.retry_delay, retry_deadline=args.retry_deadline)
        elif args.command == "logs":
            print(logs_job(args.job_dir, tail_lines=args.tail), end="")
            return 0
        else:
            result = {"status": status_job, "cancel": cancel_job, "resume": resume_job}[args.command](args.job_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
