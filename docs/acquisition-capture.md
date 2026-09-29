# Source-review acquisition

Acquisition builds write quarantined sources to an explicitly supplied staging
directory. They finish in `awaiting_review`, with `content_ready: false`.
They do not assemble or certify a production library. Use a separate volume;
prefer at least 2 TB, and check actual free space for each batch.

The reusable entry point is `scripts/acquire_content.py`. JSON summaries are
bounded to approximately 2 KiB; complete records remain under the local cache
and owned staging directory. `--resource` and `--profile` constrain a frozen
batch. Changing its selection requires a new staging directory.

```sh
python scripts/acquire_content.py build \
  --candidate-manifest catalog/acquisition/stackoverflow-capture.json \
  --staging-root /Volumes/STAGING/OWL-acquisition/stackoverflow-2024 \
  --production-root /Volumes/OWL --profile full-1tb --plan

python scripts/acquire_content.py build \
  --candidate-manifest catalog/acquisition/stackoverflow-capture.json \
  --staging-root /Volumes/STAGING/OWL-acquisition/stackoverflow-2024 \
  --production-root /Volumes/OWL --profile full-1tb \
  --detach --job-dir .owl/jobs/stackoverflow-capture
```

Replace the example staging path with the chosen mounted volume. A plan makes
no body requests and creates no staging directory. Actual capture reuses the
normal downloader, validates exact sizes and available publisher checksums,
and records whole-file SHA-256 observations plus source and metadata identity.
An observed hash remains a candidate until its review is admitted.

Already verified originals can be copied through the same capture workflow with
`--local-manifest .owl/acquisition/zim-inventory/direct-local-sources.json` and
`catalog/acquisition/direct-local-acquisition.json`. The local manifest maps
frozen source IDs to existing absolute file paths. It stays local, is snapshotted
for detached jobs, and does not replace the official source identity. Every copy
must match the frozen size and whole-file SHA-256. The production source remains
read-only; copies and generated previews belong on the chosen staging volume.

For interrupted foreground capture, repeat the identical command. Detached
jobs use the existing `scripts/build_job.py` status/resume/cancel interface.
Snapshots preserve code and candidate inputs; a completed acquisition job is
awaiting review, never a completed library.

For an exact-size batch with unavailable publisher objects, explicitly add
`--continue-missing-sources` to attempt independent remaining sources. Only HTTP
404 and 410 responses are checkpointed and skipped, without retrying them or
their mirrors. The default still stops at the first failed source. Size changes,
checksum mismatches, changed receipts, and other failures still stop capture.
Each missing source has a bounded identity-bound record under `exceptions/`;
resume with the same option reuses those records without requesting those URLs
again. Existing originals, receipts, and partial downloads keep their usual
verification and resume checks. After the remaining sources have been attempted,
the command exits unsuccessfully, the detached job is `failed`, and
`capture-report.json` reports `incomplete` with `content_ready: false` and a
bounded exception summary. Full exception details stay on disk. No candidate
fragment is created, and preview/review still require every requested receipt.
The option is preserved in a new detached job's snapshot; existing frozen job
snapshots are never edited to add it.

Older jobs have no missing-source checkpoints. When both a prior failure and a
failed explicit resume have already been preserved, use
`owl.acquisition.capture.import_missing_source_failure(failed_job_dir,
evidence_path, source_id=...)` to validate the frozen job manifest, exact source
identity, and matching terminal HTTP failures without any request. Its default
is a dry run; `plan_only=False` writes the exception under the capture lock,
with hashes of the preserved evidence and job records. The helper requires two
distinct failed runs, rejects HEAD observations as failure proof, and leaves
the old job snapshot unchanged. A new continuation job can then skip that
already-confirmed failure on its first run.

Capture budgets separately declare downloads, expansion, previews, scratch,
and retained caches, with a receipt allowance. A capture-only batch can declare
zero extraction and preview bytes. After examining an acquired archive's
directory, supply measured extraction limits and an explicit bounded preview
phase budget. No nominal volume size substitutes for a free-space check.

ZIM previews use the existing direct exporter and freeze exact archive entry
paths, output limits and scratch limits. They discover output pins from actual
exports. Export warnings remain review blockers; a completed preview is still
pending. Use the candidate entry inventory in
`catalog/acquisition/direct-local-candidates.json` to prepare a reviewed selection,
not as evidence that all articles have passed review.

```sh
python scripts/acquire_content.py preview \
  --staging-root /Volumes/STAGING/OWL-acquisition/BATCH \
  --recipe /path/to/candidate-recipe.json --assets /path/to/candidate-assets.json \
  --expanded-bytes EXACT_EXPANSION_BOUND --preview-bytes OUTPUT_BOUND \
  --scratch-bytes SCRATCH_BOUND --budget-bytes TOTAL_PHASE_BOUND

python scripts/acquire_content.py review \
  --staging-root /Volumes/STAGING/OWL-acquisition/BATCH \
  --fragment /path/to/reviewed-fragment.json \
  --evidence 'path/to/hash-bound-structural-and-visual-review.json'

python scripts/acquire_content.py stage \
  --fragment /path/to/reviewed-fragment.json \
  --review-receipt /path/to/review-receipt.json --output /path/to/candidate-catalog
```

Review evidence must cover the complete declared collection scope, documents,
illustrations, tables, equations, notices, essential dependencies and local
links. Candidate receipts and sample-only reviews cannot set a collection to
ready. Captured fragments carry provenance; staging requires an approved
receipt bound to that exact fragment and its output pins. Staging creates a
validated candidate catalog rather than overwriting the active catalog.

Generation recipes may declare pinned `build_inputs` and allowlisted
`build_input_extractions`. Shared Stack Overflow archives are acquired once;
extracted XML has its own size and SHA-256 pins. These sources, expanded XML
and temporary databases stay in owned work/cache locations. They do not enter
the final inventory, search, checksums or knowledge-content total. Retained
source/license companions remain explicit ordinary catalog dependencies.

Resource `status` describes content readiness. `device_validation` separately
records physical certification; browser viewport checks do not certify a phone.

The 1 TB map planning override is 101 GB before the world-map replacement
credit of 21 GB, leaving an effective 80 GB topographic allowance. Other map
allowances and the fixed 16/64 GB selections remain unchanged. Survivor targets
now follow accepted measured works. Expansion candidates contribute zero bytes
until accepted; the 750–820 GB knowledge-content requirement is unchanged.

```sh
python scripts/acquire_content.py discover --profile full-1tb \
  --resource books-culture-expansion,complete-courses-expansion --offline
python scripts/acquire_content.py audit --profile full-1tb
python scripts/validate_acquisition.py --full
```

Validation records hashes before and after the run. A concurrent catalog or
profile change makes the result fail, even when individual checks passed.

Discovery uses Gutenberg's supported publisher CSV and official MIT download
metadata. Course download pages can paginate media; their initial lists do not
prove a complete media/caption inventory. Compact-book ID inventories and
edition comparisons are required before admitting expansion works.
