# Unattended builds and reusable indexes

`SELECT.html` generates background build commands. A Python worker downloads,
indexes, generates navigation, verifies, and writes its completion report without
an agent supervising it. The launcher returns a saved job directory immediately.
Keep the computer awake and the drive connected.

The selector explicitly enables reusable per-asset indexes in `.owl/index-cache`
and generated indexing scratch in `.owl/index-work`, relative to the repository.
Both locations are editable. Its cache allowance starts at the profile's search
budget (2,000,000,000 bytes for 16 GB). Original PDFs, ZIMs, reader packages, other
source assets, and download partials remain exclusively on the external drive.
The selector never adds `--cache-dir`, which would store another copy of originals.
Repo-local generated indexes are Git-ignored and persist for future local builds;
they are not uploaded or included in a clone.

```sh
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile flash-16gb --index-cache-dir .owl/index-cache \
    --index-cache-budget-bytes 2000000000 --work-dir .owl/index-work \
    --detach --job-dir .owl/jobs/flash
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
verbose logs and the indexing database. The worker owns bounded transient retries.
Integrity errors, unsafe directories, missing sources, and insufficient space
stop with retained work and diagnostics. Cancellation is cooperative: wait for
terminal job status before ejecting. A slow extraction unit can delay the stop.

The agent workflow is: launch once and end the turn. Inspect status or a bounded
failure excerpt when requested or when completion/failure is delivered. There is
no need to feed unchanged progress into a model. Without `--detach`, the ordinary
build command runs in the foreground with Ctrl-C pause/resume behavior.

## Reuse indexes across drives and selections

An explicit shared cache retains immutable per-asset indexes. Warm builds merge
selected compressed records and sorted postings into the normal browser search
format. Adding one source builds its missing index; removing one does not require
parsing other sources.

```sh
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile flash-16gb --detach --job-dir .owl/jobs/flash-cached \
    --index-cache-dir /path/to/SHARED_INDEX_CACHE \
    --index-cache-budget-bytes 2000000000
```

The cache allowance covers total retained cache storage, including other
selections. It defaults to the profile's search allowance when a cache is
requested. No cache is implicitly created on the computer. Old artifacts are
retained; if the allowance is exhausted, choose a larger allowance or another
cache location. Extraction scratch and final output retain separate budgets.

Put a shared cache outside the destination library. An internal cache must be
under `LIBRARY/.owl/`, and its whole allowance is added to profile capacity.
The 16 GB profile cannot assume space for its original peak workspace plus a
retained cache. `--plan` checks allocations without creating files or downloading.

This cache differs from `--cache-dir` (downloaded originals) and `--work-dir`
(resumable extraction scratch). Source checksums and semantic recipe versions
determine reuse; logging, checkpoint timing and SQLite tuning do not. Relevant
source/extractor/tokenizer changes invalidate the affected work. Metadata-only
changes reuse a compatible shard's stored passages and rebuild that asset's
records/postings without parsing the source again.

Cache manifests record hashes, sizes, recipe identities and coverage. Small
manifests can be reviewed/versioned; binary payloads stay outside normal Git.
This implementation does not upload artifacts. Index records contain source text,
so `redistributable: false` assets must not be automatically published.

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
