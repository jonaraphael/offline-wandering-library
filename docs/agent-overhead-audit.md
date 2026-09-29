# Unattended builds and reusable asset indexes

> Historical note: full-text indexing constraints below describe the previous
> implementation. New builds use [lightweight discovery](search.md), without
> source-text extraction or index caches. Acquisition and integrity checks remain.

Implementation follow-up: the detached runner, automatic postflight, semantic
fingerprints and local per-asset cache/compiler are now available. See
[unattended-builds.md](unattended-builds.md) for the implemented commands. The
findings and proposed interfaces below preserve the original audit context.

Audit date: 2026-09-19. This is an implementation proposal based on the current
working tree and local 16 GB build records. No runtime code, running process,
checkpoint, catalog, or drive was changed by this audit.

The build should require zero model calls while healthy. Downloading, extracting,
indexing, checking capacity, verifying, and reporting are deterministic work.
Agents should handle bounded failure diagnostics or editorial decisions.

## Findings, in priority order

| Priority | Finding and evidence | Recommended change |
| --- | --- | --- |
| 1 | The local `RUN_STATE.md:8` prescribes 50-second agent polling. Its lines 18 and 40 assign routine completion checks and size arithmetic to the agent. | A detached Python job owns execution through postflight, writes compact status, and emits one completion or actionable failure event. End the agent turn after launch. |
| 1 | `search.py:390–419` hashes the entire selection, all metadata, whole `search.py` and `catalog.py`, Python patch version, and all extractor dependencies. A mismatch clears the whole extraction job at `search.py:868–877`. | Separate semantic extraction/index versions from operational settings. Cache immutable per-asset artifacts and retain completed assets across selection changes. |
| 1 | `search.py:315–326` binds the workspace to the target pathname; `search.py:1009–1011` reclaims extraction files after serialization. There is no portable per-asset artifact cache. | Use a shared, explicitly located cache addressed by content and recipe hashes. Compile only the selected assets into each drive's search package. |
| 2 | Build state records only the search phase (`build.py:470–475`). Detailed progress is in logs and the active SQLite database. The sampled current log already contained 2,393 lines, including 436 each of CHECK, REUSE, and INDEX VERIFY. | Write a separate atomic `status.json`; expose bounded status and error commands that never read the corpus or query the busy extraction database. Keep full logs on disk. |
| 2 | The builder already checks capacity and runs the verifier (`build.py:554–566`), but local handoff instructions request another verifier, plan run, smoke harness, and report. | Incorporate the missing smoke/summary checks once in automatic postflight. Persist measured sizes and verification results. Avoid routine duplicate whole-drive verification. |
| 2 | Generalizable checks live in ignored `.owl/flash-16gb-build/size-audit.py` and `search-smoke.cjs`, coupled to this profile and a local selector report. | Promote parameterized checks into tracked tools, deriving expectations from the locked selection. Python can invoke Node for the actual browser search runtime. |
| 2 | The CLI exits after exhausted downloader retries (`build.py:642–644`); the documented recovery is manual rerun. | Persist typed failure causes and a bounded transient retry policy. Stop on integrity, missing-source, space, or configuration failures with an actionable summary. |
| 3 | Extraction runs inline inside pypdf/libzim (`search.py:241`, `:281`), so a slow unit delays both progress and checkpoints. | Isolate expensive asset extraction in supervised processes with configurable limits and an independent heartbeat. Exhausted limits must fail explicitly rather than silently omit content. |
| 3 | Source acquisition and refresh still contain repeated mechanical work in prose; the catalog and generated selector are large contexts. | Add compact catalog queries and reproducible source adapters that enumerate, download, hash, and report in code. Keep source selection and substantive review separate. |

The indexing path already uses ordinary Python, SQLite, pypdf and libzim; the
problem is the surrounding workflow and coarse reuse boundaries, not model-based
text extraction.

Two restarts demonstrate the cost. Local `REPORT.md:25–27` records a cache-size
change after about 88,000 passages and a checkpoint-timer fix after 96,598 passages;
each invalidated extraction. Those figures describe overlapping work on separate
attempts, not distinct documents. The cache is now 256 MiB in code, while
`docs/search.md` still says 16 MiB. The recorded five-second process sample was
dominated by SQLite reads/fsync; it is evidence of an I/O bottleneck in that sample,
not a full performance benchmark.

## Where per-asset indexes should live

Yes: prepare an asset once and reuse its index in any matching selection. Commit
small manifests, recipes, schemas, and checksums to this repository. Store large
payloads in an ignored local cache; publish eligible payloads to artifact storage
when appropriate. Normal builds should fetch only their selected payloads.

The catalog already supplies strong identities: all 2,222 resolved records have
SHA-256 pins. The flash selection has 436 assets totaling 9,696,060,616 source bytes.

There are two practical constraints:

- Index records contain extracted source text (`search.py:952`). The catalog marks
  309 flash assets, and 343 resolved assets overall, `redistributable: false`.
  Respect those flags when deciding which artifacts may be published. A source
  checksum or compressed representation does not change the catalog restriction.
- Large binary history is a poor fit for normal Git. GitHub blocks files above
  100 MiB and recommends releases for distributing large binaries. Releases have
  per-file and asset-count limits, so large corpora need chunking or an appropriate
  object store. Git LFS is an alternative with storage/bandwidth implications;
  it is not required for a manifest-driven downloader.

GitHub references: [large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github),
[release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
[LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs).

## Cache and compilation contract

Use one coherent pipeline with distinct identities for distinct work:

1. **Extract an asset.** Key normalized passages, source-local page/entry identities,
   and coverage by source SHA-256, format/encoding, extraction schema, and the
   relevant extractor implementation/environment. Keep operational tuning outside
   this identity. Pin and record the actual environment; changing an irrelevant
   dependency should not invalidate every format. Compatibility must be tested.
2. **Prepare an asset index.** Store compressed records, locally numbered sorted
   postings, token-length totals, document flags, coverage and bounded warnings.
   Key it by the extraction identity, tokenizer/index schema, and effective search
   metadata. Titles, destinations, tags, licenses, attribution and shelf flags
   matter; download mirrors generally do not. Separating extraction from these
   overlays allows metadata edits to reuse expensive document parsing.
3. **Compile the selected indexes.** Assign deterministic global document IDs,
   relocate record offsets, and stream-merge sorted terms/postings. Recompute
   global term document frequencies and average document length. Emit the existing
   OWLIDX3 browser package, preserving its ranking and bounded query behavior.
4. **Verify and publish atomically.** Reject incomplete, corrupt, or incompatible
   artifacts; retain the last valid generation until replacement succeeds. Cache
   misses run the same Python producer locally without requiring an agent.

Do not merely cache extracted text and rebuild the entire postings B-tree every
time: the recorded SQLite bottleneck would remain. Cache compact sorted postings
as well, so repeated builds primarily do sequential reads/merges. Do not
concatenate complete standalone indexes: the current format embeds global IDs,
offsets and ranking statistics (`search.py:656–733`). A correct compiler can keep
the browser runtime unchanged.

Each manifest should record source digest, recipe/schema identities, artifact
digest and exact size, passage/token counts, coverage, provenance, and any eligible
download locations. Verify payload hashes on use; use ownership markers, locks,
partial files and atomic promotion as the existing code does.

Account for cache storage explicitly. The flash plan already reserves roughly
15.71 GB including workspace and free-space reserve; retaining another set of
artifacts on that drive cannot be assumed to fit. A user-selected shared cache
may live elsewhere. In-place mode needs measured phase budgets, including
downloaded shards, extraction, merge output, browser chunks, and retained old
generations. Completed shard sizes improve planning, but merged size and scratch
still need deterministic calculation or measurement.

## The unattended job contract

The following commands are proposed interfaces, not currently implemented:

```text
owl-build TARGET --profile flash-16gb --detach
owl-build status JOB_ID --json
owl-build logs JOB_ID --tail 40
owl-build cancel JOB_ID
```

The launcher returns a job ID and log path, then the agent turn ends. A detached
worker owns download → extraction/cache → compilation → navigation → verification
→ smoke checks → final report. Use an OS service where persistence across login
or reboot is required; a detached subprocess alone does not provide that.

Save the resolved command/selection, implementation and dependency identity, and
durable state. Expose phase, active asset, completed/total assets, passages, cache
hits/misses, last durable checkpoint, last heartbeat, retry deadline, measured
bytes, warnings, exit status, and error class in a small JSON object. A heartbeat
must distinguish an alive worker from actual extraction progress. Agent-facing
status should stay around 2 KiB, with failure excerpts capped around 8 KiB; large
diagnostics remain files referenced by path.

Retries belong to the worker and must have a deadline/backoff. Genuine failures
retain checkpoints and produce one diagnostic bundle. Avoid turning every slow
PDF page or unchanged progress interval into a model invocation. A code-driven
completion/error signal can notify once; frequent agent heartbeat automations
would recreate the token overhead.

Use the existing verification pass as a completion requirement, and add the
missing runtime/selection checks to postflight. The saved final report should
include source/managed/search bytes, capacity/reserve results, coverage summaries,
verification counts, smoke results, elapsed time, and cache reuse counts. Routine
success must not require another agent to calculate those values or write prose.

## Implementation sequence and acceptance checks

First implement the detached runner, compact status, and automatic postflight.
This removes healthy-build token consumption without waiting for the index format
work. Next split semantic identities and add local per-asset artifacts plus the
streaming compiler. Add optional published artifacts and changed-asset CI after
the local cache contract is stable. Source adapters and catalog query commands are
useful follow-on work.

Do not patch the current running job's fingerprint to pretend compatibility.
Existing checkpoints save only an aggregate fingerprint, not the semantic recipe
needed to establish equivalence. Preserve the running job; a later migration must
prove compatibility or retain its exact implementation/environment.

Acceptance requires:

- A healthy hours-long build completes after the launching agent turn ends, with
  no polling/model calls, and produces its own final report.
- Closing the launcher does not kill the worker. Cancellation, process crashes,
  retry exhaustion and resume preserve correct state and ownership checks.
- A second target with the same selection uses cached assets; adding one source
  extracts only that source, and removing one extracts none.
- Changes to logs, cache limits, checkpoint timers, or download mirrors preserve
  extraction reuse. Source bytes or extraction semantics invalidate the affected
  assets; search metadata changes update postings/records without stale links,
  attribution or shelf flags.
- Corrupt/incomplete shards fail verification. Shared concurrent builds cannot
  consume half-written artifacts or overwrite one another's work.
- Compiled results, scores, filters, links and coverage match a clean build for
  representative selections, including metadata-only documents and empty text.
- Capacity checks include retained cache/old generations and both cold/warm build
  peaks. No smaller output or runtime claim is made before measurement.
- Public artifact publication excludes assets disallowed by catalog policy.

## Audit validation

Five focused existing tests passed: completed-index reuse, input/metadata/dependency
invalidation, changed-corpus checkpoint cleanup, raw-checkpoint resume, and the
slow-commit timer regression. An isolated temporary-file probe confirmed that
both a comment-only source edit and retrieval-only metadata change alter today's
fingerprint. The probe did not modify repository source files.

The production build was not restarted or reverified for this audit. Local build
notes describe prior observations; they are not a completion certificate. No
actual model-token accounting or full-corpus speedup measurement was available.
