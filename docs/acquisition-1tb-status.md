# 1 TB content-completion checkpoint

**Current selection and planning:** use [the topic-by-topic completion plan](full-1tb-coverage-plan.md)
and [generated selection](content-selection.md). They supersede the historical
byte-floor targets and conversion queues below. On 28 September, six finished
farming/trail manuals and their per-asset pseudoindexes were added to full-1tb;
[the brief review](../catalog/acquisition/practical-discovery-20260928.json) records
decisions and limits. Required topic tags establish presence, not sufficient depth.
No minimum GB quota is used by the active profiles.

Latest update — 27 September 2026: **PhET content is admitted for full-1tb**:
16 simulations, 38 identified screens, 76 desktop/phone checks and eight
additional construction checks. Its physical-device certification remains
pending. The 16/64/256/512 selections and original source pins are unchanged.
Production OWL still contains its completed 16 GB build.

Python queues continue acquisition and review without model calls. The 42-book
Survivor capture and 164 additional MIT package captures have finished. Nine whole-course source/preview candidates now contain 45,071,289,319 bytes
of unique media across the authorized acquisition batches; no course bytes
have been admitted to the library yet. The first 86 package
inventories propose 218.50 GB of distinct media, including 159.99 GB with no
recorded media/caption gaps. Required-reading and complete-output review still
gate those candidates. See [the runbook](acquisition-supervisor.md) for workers,
sampling limits and the original frozen queue.


The 1 TB preset is **not content-complete**. The current catalog audit accounts for
357,571,411,413 bytes of pinned knowledge content, leaving 392,428,588,587 bytes
below the unchanged 750 GB floor. Seventeen required collections remain
incomplete. These are catalog totals, not certification of a newly assembled
library or measurement of the pending candidates.

## Implemented machinery

- Frozen-manifest capture, explicit staging storage checks, quarantine,
  exact-size/publisher-checksum verification and observed whole-file SHA-256.
- Foreground resume and detached jobs that finish in `awaiting_review`.
- Local pinned-original reuse, bounded generated previews including ZIM,
  complete output receipts, and review bound to the exact proposed fragment.
- Separate build-only inputs, shared archive/cache accounting, bounded 7z
  extraction with allowlists and XML pins, and resumable generation.
- Active-selection work deduplication, source-exclusion propagation, content
  floor/ceiling checks, and separate physical-device status.
- Cached English book/course discovery and the full-profile effective 80 GB map
  allowance. Survivor targets use accepted measured works, not the old 130 GB
  assumption.

See [capture and admission commands](acquisition-capture.md),
[7z verification](acquisition-sevenzip.md) and the reproducible
`scripts/validate_acquisition.py` runner. Validation fails if its catalog,
profile, generated-file or source-code inputs change during the run.

The connected-drive continuation passed the full **890-test suite** (five
optional checks skipped), all five profile plans, generated-file freshness and
unchanged-input verification. All 11 validation checks passed. The initial
sandbox run could not bind 14 loopback HTTP fixtures; the rerun with local-server
permission passed. Older 722/812/844-test checkpoints are superseded by
`catalog/acquisition/validation-evidence.json`.

## Frozen initial batches

| Batch | Sources | Original bytes | Capture peak, including receipts |
| --- | ---: | ---: | ---: |
| New England detailed maps and USA overview | 1,448 | 72,124,080,891 | 72,164,924,091 |
| Shared Stack Overflow archives | 4 | 31,166,034,729 | 31,167,163,673 |
| Initial MIT course packages | 8 | 815,552,559 | 816,759,243 |
| Existing Appropedia, CD3WD, iFixit and Low-tech originals | 4 | 5,434,058,007 | 5,435,203,075 |

These are capture-only peaks. Extraction, output generation, review images,
course media and captions require their own measured bounds before that phase
runs. Source bytes do not establish useful additional content and are never
credited to the knowledge floor merely because they were downloaded. The direct
originals already belong to the baseline; their copies add no new knowledge.

The user authorized an explicitly complete trial on 23 September 2026. Actual
source-review jobs now run under `/Volumes/General Backup/OWL-acquisition`.
The trial preserves production OWL until the complete content and capacity gates
pass. It does not lower the 750–820 GB range or count captured source archives as
new knowledge.

Use `scripts/acquisition_trial_status.py --staging-root '/Volumes/General Backup/OWL-acquisition' --registry catalog/acquisition/1tb-trial-batches-expanded-courses-survivor-phet-v16.json`
for a bounded current report. This combined ledger includes all newly authorized
capture and review reservations; older running managers keep their original
immutable inputs. The combined report validates ownership,
filters, declared remaining peaks and the shared reserve against actual free
space. Source receipts and derivative bodies stay on the staging drive.

The eight initial MIT packages, four direct archives and 55-source programming
continuation were captured. The old mutable Python HTML source failed its exact
size pin; a separately captured official 3.14.7 release candidate preserves the
accepted edition until its replacement passes review. Maps, shared Stack
Overflow archives, five compact Gutenberg archives and 280 publisher-linked
course-media sources are being acquired. These are source captures, not content
admissions. No new collection is marked complete by this checkpoint.

## Remaining content work

- **Maps:** review actual PDF frames, scales, notices and dates. The frozen
  selection has 1,433 fine-scale sheets and 14 explicit coarse supplements.
  Fine-scale coastal gaps remain; mixed-scale footprints do not establish
  complete 1:24,000 land coverage.
- **Health:** the official free Hesperian digital Midwives edition now has a
  frozen authoritative table of contents: 132 book pages, 35 templates and 1,455
  images. Exact v3 capture enforces the publisher payload size/SHA-1 after the
  separately verified four-newline transport prefix. The earlier size mismatch
  remains quarantined. Complete ordinary rendering, clinical section coverage,
  attribution and permission-scope review remain pending. The digital edition
  is not claimed identical to the print PDF; no purchase is authorized.
- **Direct editions:** 8,554 exact candidates are frozen, including 82 original
  PDFs. Export and review full dependencies, original-book completeness,
  attribution and local links. Resolve recorded unsupported paths, replacement
  characters and iFixit language-tag conflicts. Keep additions beyond these
  baseline selections in a separate work manifest.
- **Survivor/books:** review scans, deduplicate works/editions across tiers and
  existing compact books, and close the topic matrix. The English expansion
  freezes 2,000 ranked book candidates, not accepted illustrated editions.
  The 42 practical books now have whole-file verification and all-page thumbnail
  evidence covering 15,254 pages. Three dense review images were regenerated
  within the original byte/pixel bounds; 28 works retain substantive review
  flags. These checks and a promising visual sample do not admit any books.
- **Courses/Khan/TED:** the frozen English core selects 31 course/topic trees,
  5,061 distinct video/exercise works and 24,157,449,786 candidate bytes. Explicit
  gaps include captions, duplicate-content renditions, required formats and
  permission scope. A 23-file format pilot has finished capture; the inspector now handles exact publisher SVG label wrappers as data without
  executing JavaScript. All 23 sources passed successor format inspection, including 40 publisher
  wrappers and 110 JSON documents. Ordinary rendering remains required. MIT's
  164 package inventories propose 374,590,151,250 bytes of distinct media before
  essential-material and output review. None of those metadata totals is an
  admitted content total.
- **Stack Overflow:** acquire the four inputs once, freeze extracted XML pins,
  render and review durable/legacy outputs with the declared selection rules.
- **Programming:** the complete Python package has a versioned local-link/index
  layout repair under whole-package offline browser review. SQLite has five
  verified link repairs, one explicitly deprecated historical reference, and
  an illustration/notice capture queued. Required dependencies remain gated.
- **PhET:** the full-1tb direct edition is content-ready. The changed pH source
  was quarantined, verified at its exact size, reviewed across both screensizes
  and admitted under a distinct identity. Physical-device certification is
  separately pending; this edition does not change the smaller presets.

After reviewed admission, reconcile measured useful content and continue
approved book/course discovery until whole-item admission lands within
750–820 GB. There is no final locked selection or complete output manifest yet.

## Small-preset baseline

The committed regression baseline now contains 551 selected assets /
9,869,555,191 bytes for 16 GB and 602 assets / 45,226,005,469 bytes for 64 GB.
This continuation preserves that baseline. Earlier task checkpoints listed
different EPUB/PDF selections; those historical counts are not the current
invariants. The connected OWL still contains its completed 16 GB build.

Production SSD assembly and paused-drive recovery have not started. Physical-device
certification remains separately pending.

## Timed continuation checkpoint

The active thread heartbeat checks every 30 minutes using
`scripts/check_acquisition_progress.py`. Python workers perform acquisition and
review between checks. The v16 combined preflight passed with 701,446,479,872
bytes free against 412,618,245,971 bytes reserved for all declared phase peaks
and shared reserve. This conservative mode grants no credit for already
retained files; each writer still checks its actual live usage. Older managers
keep their original immutable registries.

New running queues cover the exact health digital capture, the Khan/TED format
pilot, repaired Python/SQLite previews, three additional self-contained MIT
courses and three balanced physics/engineering courses. Job snapshots now
include active catalogs, recipes and referenced evidence rather than unrelated
candidate histories; the existing 64 MiB and explicit-input integrity guards
remain in force.

The v11 ledger also reserves complete original-plus-successor OCW preview sizes
on their actual source capture batches. This permits a source-SHA-bound offline
repair of eager YouTube/Sentry requests, with old preview evidence preserved.
A 43-source manual batch reuses exact local originals and notice companions;
duplicate publisher anchors and 33 individual source notice/header dependencies
remain explicit gates. The final 890-test run passed with five optional skips. All 11 checks passed,
including all five profile plans, generated-file freshness and unchanged inputs.
The portable result is catalog/acquisition/validation-evidence.json and the
local full report is .owl/acquisition/validation/run-awdovh9z/report.json.

28 September timed continuation: a 1,372-package exercise census was launched
from frozen publisher identities (558,261,197 source bytes; 589,160,345-byte
capture peak plus 100 MB review evidence). The resumable inspector verifies all
archive members and records every widget type, document key set, external
reference and source/output binding. It does not render, admit or count lessons
as useful content. Interrupted/cached reruns, evidence tampering, malformed
archives, duplicate JSON keys and non-finite values have focused tests.

The v14 ledger includes 33 exact manual notice/source candidates and three more
MIT candidates: Digital Communications I, Statistics for Applications, and
Programming for the Puzzled. Their 57 unique media files add 9,220,425,796 bytes
of candidates and their complete ordinary proposal is 9,406,876,559 bytes.
Statistics retains explicit missing-recording and assessment limitations.
Acquisition/review is pending; no additional content is admitted here. The
890-test validation checkpoint predates these latest scripts and requires
a final stable rerun after the ongoing health/manual renderer work.

The full exercise capture stopped safely after 11 sources: the frozen official
Apply: mutations package returned 404 despite publisher metadata saying it was
available. The failed source and required lesson remain explicit; no selection
was silently shortened. A new Python HEAD-only availability queue now probes
all 1,372 frozen identities with four workers and a half-second request interval.
It reuses the existing cached probe script and downloads no library bodies.
Use its result to freeze a versioned continuation and investigate missing works.

Midwives' bounded local template expansion passes 131/132 pages. An unmatched
literal closing brace pair in the family-planning source remains preserved and
blocks that page. The v15 ledger reserves a 4.28 MB official revision-render
diagnostic to establish publisher rendering; ordinary HTML conversion, image
closure and clinical-format review remain required.

The availability probe subsequently observed HTTP200, exact722,088-byte size
and matching MD5-labelled ETag for the failed exercise identity. One explicit
capture resume was authorized from this new evidence, preserving the original
404 and all source pins. Its timer-visible continuation is
`.owl/acquisition/kolibri-exercise-census-supervisor-v2`; the prior manager
stays unchanged. The retry decision/evidence lives in
`.owl/acquisition/kolibri-exercise-capture-retry-evidence-v1.json`. A further
permanent failure must not be blindly retried. The HEAD census continues.

The one evidence-backed retry also returned404; HEAD availability therefore
does not establish a downloadable body. Both failed attempts remain preserved.
A narrow opt-in missing-source continuation is being implemented so independent
404/410 failures can be recorded while other sources proceed; the final capture
will still fail incomplete and will not emit an admissible full candidate.

The next stable checkpoint passed904 tests (five optional skips) and all11
validation checks, including five profile plans/freshness/unchanged inputs:
`.owl/acquisition/validation/run-w_qcz2jx/report.json`. Subsequent source fixes
will require another stable validation. Python v4 now has1,142/1,142 full-page
browser checks and8/8 actual offline interactions; its1155-file preservation
audits passed. A reviewed profile-scoped admission proposal is being prepared.

The official Midwives render proves that the source brace pair is literal
visible text. Keep it unchanged; use that exact source-bound evidence when
allowing the parser case. All35 templates retain their pinned revisions.
The diagnostic completed successfully without admitting clinical content.

The v17 continuation preserves the exercise selection and11 verified receipts.
Its two recorded404 failures were imported into a source-bound immutable
exception without another GET; the new opt-in Python capture continues other
sources and still fails incomplete before emitting any candidate. A missing
source cannot enable the downstream full-census/review step. All1,372 HEAD
probes returned200, showing why HEAD status is insufficient body evidence.
The new job is `.owl/jobs/kolibri-exercise-census-v2-1tb`, monitored by
`.owl/acquisition/kolibri-exercise-census-supervisor-v3`. The v17 preflight
reserved412,758,245,971 bytes against688,497,311,744 actual free bytes; both
mounted volume UUIDs were reverified before starting it.

Thirty-three reviewed manual source/notice companions are admitted with whole
file pins and per-file license/edition evidence. Seven use the exact systemd
259.6 Git objects where259 differed. They are supporting files and add zero
knowledge-floor bytes. Both batches passed all five capacity plans and exact
16/64GB selection comparisons. Accepted fragments, receipts and stage evidence
are under `catalog/acquisition/manual-source-notices-*`. The reusable
`scripts/check_staged_admission.py` now performs these bounded admission checks.
Python's source ZIP is being corrected to build-only in an immutable v5 recipe;
v4 reading bytes passed1,142 page checks,8 interaction checks and sparse table/
SVG visual review, but v4 itself is not admitted.
