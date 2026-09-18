# Validation evidence

The initial implementation was exercised on macOS/Apple Silicon with Python
3.12, Node.js 20, and the versions in `requirements-tested.txt`. The source audit
was performed on 2026-09-18 UTC. This document records evidence, not a claim that
all target hardware or the largest profiles have been tested. The milestones
below are historical: their test counts, artifact layouts, and browser restrictions
describe the implementation at that stage. Earlier file-selection and single-file
index measurements do not validate the current automatic script-chunk transport.
Use [the search guide](search.md) for the current workflow.

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

## In-place interruption and resumption

The pause/resume update was checked with 172 automated tests. New cases cover
cooperative interruption, HTTP retry exhaustion, validated local-prefix resume,
complete partial-file promotion, process-kill lock recovery, SQLite rollback
after abrupt process exit, resumed PDF/ZIM cursors, unchanged-index reuse,
interrupted final verification, insufficient remaining space, and replacement
of a destination directory during preflight or transfer. Integrity tests ensure
that changed content cannot be accepted by simply recording a new checksum.

A separate real CLI smoke test built 80 small original text assets, sent SIGINT
after an extraction checkpoint, observed exit status 130 and incomplete state,
then reran the same command. All 80 content files were reused, extraction resumed,
and the finished index was byte-identical to an uninterrupted clean build.
Independent verification reported **126 OK, 0 MISSING, 0 FAILED, 0 UNKNOWN**.
Both builds kept partials and search scratch within their target directories.

The four-file demo also built through the CLI, copied directly to a second
directory using `copy_drive.py`, and independently verified **50 managed files**
on each copy with no missing, failed, or unknown files. These are filesystem
fixtures, not a claim of physical USB/exFAT unplug or laptop sleep testing.

Peak in-place capacity remains distinct from final content capacity. With the
current conservative scratch allowances, the complete proposed larger resource
selections exceed their nominal drive sizes during construction. Plans now
report that explicitly. The source include list and full-corpus indexing sizes
remain unfinished; the tool does not assume an internal-disk copy can make those
default in-place budgets fit.

## Static topic atlas

The human-index mechanism passed **257 automated tests** on the local
macOS/Python 3.12 environment. Added checks cover multi-parent topic graphs,
ambiguous aliases, deduplicated counts, pagination and HTML size limits,
source-pinned locators, escaping, local links, profile filtering, and separate
subject/learning routes for required textbooks. Publisher-outline and heading
imports use small PDF/HTML fixtures, including malformed and missing structures.
Lifecycle tests interrupt publication, resume it, reject unowned collisions and
damaged sources, retire obsolete pages, and preserve ownership after backup
copying or removal of private build state. Source HTML link checks retain only
requested anchors while streaming each source once.

The post-download CLI ran against the existing **25-PDF, 1,574,545,596-byte**
critical library with strict coverage enabled. It generated **37 visible topics**
and **75 atlas files**, including its JSON report; the HTML totals **303,952
bytes**. Every critical asset was mapped and all seven required textbooks had
both subject and learning routes. An independent invocation of the drive's
copied verifier reported **145 OK, 0 MISSING, 0 FAILED, 0 UNKNOWN**. These are
whole-document starter mappings, not completed chapter or figure curation.

The original four-file demo exercised atlas generation during a full CLI build,
a separate post-download atlas rerun, and a direct backup copy. Both directories
independently verified **86 OK, 0 MISSING, 0 FAILED, 0 UNKNOWN**. Its reviewed SVG
anchor exercises a real section link; no third-party media was added to Git.
The offline importer also produced **136 publisher-outline section proposals**
with zero warnings from the pinned OpenStax *Prealgebra 2e* PDF. Those proposals
remain drafts outside the repository and were not published as reviewed topic
assignments.

The CI demo now exercises both atlas commands before verifying and copying the
library. These automated and local filesystem checks do not establish usability
on physical phones or exFAT devices. The device/viewer and finding-task evaluation
described in the atlas specification remains to be performed after curation.

## Offline library selector

The final local regression run passed **283 automated tests** on macOS/Python 3.12.

The self-contained `SELECT.html` was checked in the in-app Chromium browser at
1280 × 720 and 390 × 844. Preset changes, inclusion changes, automatic reader
selection, explicit partial-build acceptance, shell quoting, copy feedback, and
the mobile storage bar were exercised. Neither viewport had horizontal overflow;
the command controls remained reachable. Browser checks used a loopback preview
server for development because the automation browser does not open local file
URLs. The delivered page has inline code and data, no external dependencies, and
a policy forbidding network connections; local-file behavior on each intended
browser and physical device still needs testing.

Python/JavaScript parity tests compare all five presets and 50 deterministic
custom selections. Additional checks cover actual registered editions, baseline
edition membership, reader requirements, unavailable choices, empty selections,
coverage floors, shell metacharacters, embedded-metadata escaping, and generated
page freshness. The real 16 GB profile's no-write CLI plan confirms 25 PDFs,
1,574,545,596 content bytes, and 9,591,322,812 bytes of peak allowance including
reserve.

A separate smoke test generated commands with the same JavaScript engine against
the original demo fixtures. It excluded one resource, used a destination with
spaces and an apostrophe, ran the no-write plan, built the three remaining files,
and repeated the exact command. The second build reused all three source files
and the completed search index. Independent strict verification reported
**49 OK, 0 MISSING, 0 FAILED, 0 UNKNOWN**. No large source data was downloaded or
added to Git for these tests. Alternate edition tests use small fixtures; no
production direct/compact alternative or automatic content conversion is claimed.

## Source resolution and in-place direct exports

The 2026-09-18 source-resolution pass added **426 pinned file records**. The
active registry now has **25 ready, 13 partial and 11 unresolved resources**.
Readiness is collection scope, not a claim that all archive bytes were downloaded
or that the SSD is finished. Evidence and remaining work are regenerated in
`docs/content-selection.md` from the actual catalogs.

The local suite passes **309 tests** with the optional ZIM dependency installed.
It includes real small ZIM exports, interruption/restart, corrupt saved prefixes,
source pin changes, missing space, output ownership, symlinks, drive replacement,
malicious HTML, Unicode checkpoint resume and bounded archive enumeration.
Extra-catalog tests verify in-place reuse without downloading/copying again,
profile exclusion, source-edition hashes, conservative space allocation, reader
requirements and locked rebuilds. The production navigation tests require subject
routes for all 354 resolved critical assets and subject/learning routes for all
23 required ordinary-format textbooks. These are whole-file routes, not invented
page or figure mappings.

A new small end-to-end build used the actual pinned WHO WASH note and Bash
manual from verified local copies. It built search and navigation, reran with
all downloads forbidden, and independently verified **48 OK, 0 MISSING,
0 FAILED, 0 UNKNOWN**. MSF's original Public Health Engineering PDF was opened
with its empty password and text extracted using `pypdf[crypto]`; the publication
was not rewritten. The added crypto dependency supports this source format.

A fresh headless Google Chrome context opened an exported fixture through
`file://`: PNG and SVG illustrations, a real local TTF, imported CSS and the
selected-page anchor link all worked. There were zero console errors, failed
requests, or HTTP(S) requests. Browser inspection found and fixed a blank image
box left after removing a remote tracker. This confirms this local Chrome
fixture, not arbitrary Zimit applications, Safari/iPhone, Android file providers,
or every future source page.

Verified acquired documents totaling **1,873,085,081 bytes** were preserved in
an explicitly owned SHA-256 cache on the mounted OWL SSD for future builds.
Only source metadata, code, docs and fixtures were committed; no large archives
were downloaded for this pass and no production SSD build was declared complete.

## Automatic search on the start page

The start page and dedicated search page now share one widget and local runtime.
The former index-selection workflow is replaced by automatic loading of a local
manifest and bounded script chunks. Earlier single-file index measurements above
describe the decoded format and historical behavior, not this transport's full
browser memory or storage use.

Focused navigation and atlas tests pass for shared widget controls, local script
references, static fallback links, missing-search notices, and deterministic
atlas reruns that preserve every search artifact. Generated-script validation
permits only the expected deferred runtime on the start page, requires its
manifest and script to exist, and rejects inline or unexpected scripts. Topic,
category, critical-content, and alphabetical indexes remain script-free.

The full local suite passed **325 tests**. Real-browser checks also passed on
Chrome **153.0.8010.48** using a small completed demo build: 18 checks across fresh
contexts at desktop and 390-pixel widths, with network access disabled, no custom
file-access flags, and no permission grants. Both `START_HERE.html` and
`SEARCH.html` loaded their real generated index automatically. Body queries,
textbook and illustrated-guide filters, and local result links worked. There
were no file-picker events, HTTP(S) attempts, console errors, or horizontal
overflow. Both entry pages also supported category navigation with JavaScript
disabled. These are desktop-browser and publication checks; they do not certify
physical phone file providers, embedded previews, or the latency and browser
memory use of a full Wikipedia index. Device testing remains required.

The same automatic browser checks then passed on the exFAT OWL SSD's real
`flash-16gb` library: 9,505 passages in 50 chunks (51,723,366 decoded bytes;
68,969,995 bytes including chunk scripts, manifest, and ownership marker).
Startup requested one chunk, runtime, and manifest, about 1.42 MB of local script
bytes. Measured readiness was 59–103 ms and tested queries took 81–235 ms on this
Mac/browser; these are observations, not performance guarantees for other drives.
“Circuits” linked to the DC textbook, “water” to the EPA drinking-water guide, and
“stoichiometry” with the textbook filter to Chemistry 2e. Both entry pages also
retained category navigation with scripts disabled. All 18 checks passed with
no picker events, network attempts, or browser errors. Independent strict drive
verification reported **199 OK, 0 missing, 0 failed, 0 unknown**. The prior owned
binary index was retained and checksum-covered during this in-place upgrade;
fresh builds do not produce that duplicate.


## Content-density and budget regression pass (2026-09-18)

The expanded defaults select 9.696 GB, 40.273 GB, 195.141 GB, 261.614 GB and
393.589 GB of SHA-pinned sources for 16/64/256/512/1000 GB respectively. The
larger two remain explicitly partial against their requested content floors.
All five keep the same 427-file ordinary-format foundation; 365 of these are
reader-free PDFs/HTML, while 62 EPUBs need device support. The 16 GB preset's
436 files all have whole-document topic routes. No source datasets were added
to Git.

The complete local suite passed **352 tests**, including all existing atlas
policy tests and new minimum-content, edition-lock, exact-byte, search-budget,
UI-repair and low-free-space unchanged-rebuild regressions. A fresh demo build
with strict topic coverage verified **89 OK, 0 missing, 0 failed, 0 unknown**.
Fresh Chrome with networking disabled passed 18 search/navigation checks across
desktop/phone layouts and JavaScript-disabled fallback pages. The selector also
passed all five presets at phone width, with no network requests, JavaScript
errors or horizontal overflow.

The real expanded SSD build is recorded separately once full extraction and
independent verification finish. Small-fixture success alone does not establish
that a large archive index fits its allowance.

## Compact search and phased working space (2026-09-18)

The full local suite passed **374 tests** after the OWLIDX3 change. The logical
index now uses independently zlib-compressed document records and delta-coded
unsigned-varint postings. Streaming whitespace normalization preserves searchable
tokens while avoiding passages made mostly from HTML indentation. Tests cover
malformed/truncated/oversized data, multi-window posting lists, Unicode, ranking,
filters and attribution, including native decompression on Node 20 and 24.

A raw-index checkpoint is saved after serialization and SHA-256 verification.
Directory updates are synchronized where supported before owned extraction files
are reclaimed; real I/O errors preserve the extraction workspace. Tests interrupt
before the marker, during reclamation and during browser packaging, then resume
without re-extraction. Exact matching partial chunks receive space credit only
for their verified generation. A tight-free-space integration test confirms that
raw-ready restart does not reserve another extraction workspace. Separate-device
phase tests prevent reclaimed storage on one filesystem from crediting another.

A fresh strict-atlas demo independently verified **89 OK, 0 missing, 0 failed,
0 unknown**. Fresh offline Chrome 153 passed **18 search/navigation checks** on
both generated search pages at desktop and phone widths, including JavaScript-
disabled fallback. The regenerated selector passed all five presets at 390px,
with matching phase totals and CLI selections, no network requests or overflow.
These browser checks did not grant file access or relax browser security.

Bounded uniform archive samples exposed the old uncompressed format's excessive
space requirements. Normalized V3 samples estimate 1.35–1.58 GB of packaged search
and 2.60 GB of extraction workspace for the five flash archives alone, excluding
ordinary documents and shared tables. The 2 GB search and 4.5 GB phased scratch
allowances are therefore still subject to the real full-build measurement.
The expanded SSD build is in progress; the above results do not claim that it
has completed or that larger corpora have been performance-tested.
