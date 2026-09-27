# 1 TB content-completion checkpoint

Latest update — 27 September 2026: the Python supervisor is running the frozen
23-step queue. It resumed map and course-media captures and the Python manual
preview after 812 regression tests (five skipped), all five profile plans and
freshness checks passed. Five existing source captures were reused immediately.
No candidate was admitted and production OWL was not cleared. The queue makes no
model calls and finishes awaiting review; see [the runbook](acquisition-supervisor.md)
and `.owl/acquisition/supervisor-1tb-20260927/summary.json` for current state.
Sparse AI review packets now use reproducible samples and explicit completeness
limits. The 750–820GB finish line and outstanding content/device gates remain.


The 1 TB preset is **not content-complete**. The current catalog audit accounts for
357,571,411,413 bytes of pinned knowledge content, leaving 392,428,588,587 bytes
below the unchanged 750 GB floor. Eighteen required collections remain
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

The last pre-trial full validation ran **722 tests**: 62 failing assertions remain in two atlas
navigation tests following the concurrent PDF migration (61 relate to retained
Book Dash EPUB companions). Catalog validation, generated-file freshness, all
five current profile plans and the unchanged-input check passed. The five
optional geometry tests skipped by the default environment passed in a separate
18-test run with Shapely. Six real 7z checks also passed. The full-suite failure
is preserved in `catalog/acquisition/validation-evidence.json`.

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

Use `scripts/acquisition_trial_status.py --staging-root '/Volumes/General Backup/OWL-acquisition'`
for a bounded current report; `catalog/acquisition/1tb-trial-batches.json` records
all running capture and review phases. The combined report validates ownership,
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
- **Health:** the missing 2026 midwives back matter and discovered older whole
  PDFs return 404. An official complete 2026 PDF purchase is identified, but
  its file and pin remain unavailable. The user declined purchase: continue
  looking for a free complete official edition, or remove this requirement only
  after verifying that included assets cover its pregnancy, birth and newborn
  content. Do not infer equivalence from titles or splice editions.
- **Direct editions:** 8,554 exact candidates are frozen, including 82 original
  PDFs. Export and review full dependencies, original-book completeness,
  attribution and local links. Resolve recorded unsupported paths, replacement
  characters and iFixit language-tag conflicts. Keep additions beyond these
  baseline selections in a separate work manifest.
- **Survivor/books:** review scans, deduplicate works/editions across tiers and
  existing compact books, and close the topic matrix. The English expansion
  freezes 2,000 ranked book candidates, not accepted illustrated editions.
- **Courses/Khan/TED:** freeze complete English lesson sequences and dependency
  inventories, including every essential exercise, supplied solution, media
  rendition and caption. Eight initial MIT package identities do not prove a
  complete course-media inventory or enough expansion content.
- **Stack Overflow:** acquire the four inputs once, freeze extracted XML pins,
  render and review durable/legacy outputs with the declared selection rules.
- **Programming/PhET:** complete required dependency classifications and screen
  coverage reviews. The PhET screen manifest names 14 unchecked screens; eight
  other simulations still need a pinned complete screen inventory. Prior sample
  runs do not record explicit screen identity. Device certification remains
  separately pending.

After reviewed admission, reconcile measured useful content and continue
approved book/course discovery until whole-item admission lands within
750–820 GB. There is no final locked selection or complete output manifest yet.

## Shared-workspace baseline issue

The concurrent task **Build and test 16GB SELECT** changed small-preset EPUB/PDF
selections. This acquisition work preserves those edits while the user resolves
which baseline should be fixed. The regression runner currently checks that
task's new expectations; passing it does not prove preservation of the original
baseline requested by this plan.

| Preset | Original fixed assets / bytes | Concurrent PDF baseline assets / bytes |
| --- | ---: | ---: |
| 16 GB | 436 / 9,696,060,616 | 535 / 9,804,297,565 |
| 64 GB | 450 / 40,272,521,791 | 549 / 40,380,758,740 |

Production SSD assembly and paused-drive recovery have not started. Physical-device
certification remains separately pending.
