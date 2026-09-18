# Validation evidence

The initial implementation was exercised on macOS/Apple Silicon with Python
3.12, Node.js 20, and the versions in `requirements-tested.txt`. The source audit
was performed on 2026-09-18 UTC. This document records evidence, not a claim that
all target hardware or the largest profiles have been tested.

- The automated suite covers catalog validation, decimal capacity/headroom,
  traversal/symlink/reparse-point rejection, streaming checksums, interrupted
  transfers, real loopback HTTP Range responses, ignored ranges, changed entity
  validators, hash failures, cache reuse, incomplete builds, repeated builds,
  static links, extraction and the JavaScript search engine.
- Real PDF, EPUB and tiny generated ZIM fixtures test the extraction paths.
  Node executes the exact script embedded in `SEARCH.html`, including ranking,
  snippets, Unicode, multi-block common-word postings and damaged index handling.
- The three-file demo was built through the CLI and independently verified.
- A live HTTPS build downloaded the pinned EPA water-disinfection PDF and
  successfully created and verified its navigation, full-text index and metadata.
- All 20 initial critical PDFs were downloaded from their catalog sources for
  the source audit, then hash-checked and assembled through the builder. Their
  152,460,333 source bytes produced 2,745 passages and a 14,127,290-byte search
  index. Seven assets reported some pages without extractable text. Such pages
  may be blank or image-based; OWL reports partial coverage rather than assuming
  OCR. No critical asset was entirely metadata-only.
- The four reader distributions were downloaded, sized and SHA-256-hashed;
  upstream MD5 sidecars were additionally compared. No downloaded reader was
  executed. Large ZIM sizes and SHA-256 pins were checked against upstream
  Metalink files; the large archives were not downloaded for this validation.

No physical exFAT SSD, iPhone/Pixel file picker, Raspberry Pi reader, or complete
512 GB/1 TB build was exercised. The available automated browser rejects local
`file://` navigation, so an actual local-browser UI smoke test could not be run.
No browser-policy workaround was attempted. Search-engine tests do not establish
external-drive browser permissions or phone storage-provider compatibility.

The workflow in `.github/workflows/test.yml` exercises Windows/macOS/Linux Python
3.11/3.13 tests and a separate Linux ZIM job. All seven jobs passed for baseline
commit `3e209dbc2c2b28c26b338cc9b165f6495931103c` in
[the hosted run](https://github.com/jonaraphael/offline-wandering-library/actions/runs/35298253778).
Before relying on a drive, run the verifier and the device checks in
`docs/usage.md`, offline, on each intended device. Keep a separately stored
verified backup.

## Textbooks and illustrated guides

The expanded collection was exercised on the same macOS/Python/Node environment:

- All 70 automated tests passed, including real-catalog policy checks, collection
  filters applied before top-result selection, bounded flag reads, and visible
  attribution in the search result renderer.
- All five new OpenStax PDFs were fully downloaded from their publisher and
  independently checked against their catalog sizes and SHA-256 pins. Their
  licensing notices and representative illustrated pages were inspected.
- The actual `critical-64gb` recipe built all 25 PDFs from verified local cache
  and existing content, retaining the original source URLs in the inventory.
  Its **1,574,545,596 bytes** of source documents produced **9,505 passages** and
  a **51,723,366-byte** OWLIDX2 index. Seven required textbooks and thirteen
  illustrated works were present. Twelve PDFs reported some pages with no
  extractable text; none was entirely metadata-only. Illustrations remain in
  the original PDFs independently of text-index coverage.
- The build's verification and a separate isolated invocation of its copied
  `VERIFY.py` both reported **68 OK, 0 MISSING, 0 FAILED, 0 UNKNOWN**. All **1,164**
  local links in the generated landing, inventory, and static index pages
  resolved to existing paths.
- Node ran the actual search-page engine against that index using file-backed
  random reads, without loading the entire file. Filtered queries for
  `stoichiometry`, `fractions`, `shelter`, and `circuits` returned the appropriate
  textbooks or illustrated guides and preserved OpenStax attribution. Together
  these queries read 109,547 bytes, with no single read exceeding 15,708 bytes.
  These measurements describe these queries, not an upper bound for common
  words or a larger corpus.
- The expanded four-file, 3,977-byte original demo built through the CLI and
  independently verified all 47 managed outputs. This fixture includes a tiny
  illustrated teaching document so CI exercises both dedicated learning shelves.

These checks do not replace the hardware, browser permission, and full-archive
performance checks listed above.

## Enumerated resource selections

The acquisition-list update was checked with **107 passing automated tests**.
New coverage includes all 46 numbered resources and three support collections,
actual profile defaults, decimal planning budgets, numeric/ID selectors,
include/exclude conflicts, map replacement credits, automatic reader dependencies,
partial-content refusal, explicit partial builds, locked-catalog reproduction,
malformed lock rejection, preserved excluded files, and the new reading shelves.

Actual production plans resolve to **209,139,967,202**, **407,374,257,909**, and
**779,374,257,909** content bytes respectively. These totals combine estimates for
unresolved collections with larger exact pins where known; they are not acquired
data. The full plan includes the additional 60 GB direct-reading allocation.
No new large collections or direct-reading export pipelines were built as part
of this update.

The four-file CLI demo built and independently verified **50 managed files**, with
zero missing, failed, or unknown files. Small local fixtures also exercised the
CLI selection flags, explicit partial builds, and a second build from a locked
catalog after removing its resource registry. A read-only plan against the
previous full critical test build found all **25 PDF files reusable**. The
previous physical-device and full-Wikipedia indexing limitations still apply.
