# Unattended builds

`SELECT.html` generates background build commands. A Python worker downloads,
compiles discovery, generates navigation, verifies, and writes its completion report without
an agent supervising it. The launcher returns a saved job directory immediately.
Keep the computer awake and the drive connected.

The selector needs no index cache or search workspace. Python compiles the small
search catalog and atlas from approved metadata; original downloads and partials
remain on the destination drive.

```sh
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile flash-16gb --detach --job-dir .owl/jobs/flash
```

The job directory must be new. It contains the saved build recipe, source/input
snapshot, logs, and atomic status. A resumed job uses its saved implementation and
inputs; editing the working repository does not alter that recipe. Content is
downloaded or reused from verified local files. A detached worker survives closing
its launcher, but does not automatically restart after logout, reboot, forced
termination, or power loss.

```sh
python scripts/build_job.py status .owl/jobs/flash
python scripts/build_job.py logs .owl/jobs/flash --tail 40
python scripts/build_job.py cancel .owl/jobs/flash
python scripts/build_job.py resume .owl/jobs/flash
```

`owl-job` is the installed equivalent. Status is compact JSON independent of
verbose logs. The worker owns bounded transient retries.
Integrity errors, unsafe directories, missing sources, and insufficient space
stop with retained work and diagnostics. Cancellation is cooperative: wait for
terminal job status before ejecting. An active transfer or integrity check can delay the stop.

The agent workflow is: launch once and end the turn. Inspect status or a bounded
failure excerpt when requested or when completion/failure is delivered. There is
no need to feed unchanged progress into a model. Without `--detach`, the ordinary
build command runs in the foreground with Ctrl-C pause/resume behavior.

## Refresh discovery without rebuilding content

To make completed downloads browsable after a stopped batch, run
`python scripts/discovery.py assemble --output DRIVE --profile flash-16gb`.
It verifies available files and builds their search and atlas from per-asset Git
metadata. Missing or unfinished sources are reported and excluded. Rerun after
more downloads finish. This does not mark an interrupted full build as complete;
its saved job can still be resumed with the command above.

Use [the discovery CLI](search.md) to republish titles, aliases, topics, and reviewed
locations on a completed drive. It reads metadata and checks source presence and
size. It does not repeat the full source audit. There are no per-asset index
artifacts to cache or merge. `--cache-dir` still optionally caches original
downloads; `--work-dir` only serves acquisition recipes that require build inputs.

## Completion and diagnostics

The existing verifier checks every managed file. Automatic postflight adds
selection, coverage, measured-size and capacity checks without rehashing the whole
drive. A bounded Node smoke test exercises the generated search runtime and
sampled links when Node is available. Missing Node is explicitly recorded as
skipped, not passed; Node is present in CI but is not required to read a drive.

Only after these checks does `LIBRARY/.owl/state.json` become `complete: true`.
Its `result` contains measured totals and verification/smoke results. Job status
records success or a bounded error summary; full logs remain in the job directory.
`BUILD_INFO.json` alone is not the final completion marker.

Finish older active jobs with their original implementation or a preserved
recovery copy. Never edit checkpoint fingerprints to bypass incompatibility.
The original findings are in [the audit](agent-overhead-audit.md).
