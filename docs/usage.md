# Building, carrying, and maintaining an OWL drive

A fresh drive has `START_HERE.html` beside a single `LIBRARY` folder. Open the
start page first and keep those two items together. All drive-target commands
below take this outer directory; the verifier, inventories, indexes, content and
private resume state live inside `LIBRARY`. Catalog destinations remain relative
to `LIBRARY`, while the global checksum manifest records outer-directory paths.

## Prepare

1. Use a dependable SSD and cable. Format it with your operating system’s ordinary disk tools if needed; OWL does not format drives. exFAT is the intended cross-platform filesystem.
2. Identify the SSD’s mount location carefully. Use a dedicated `EMERGENCY_LIBRARY` directory so the library is easy to find.
3. Install Python 3.11+ and OWL on the build computer. Install with `python -m pip install -e .` for normal builds. These dependencies are needed only while building.
4. Review the resource registry, asset catalog, and source notes. The larger profiles describe planned selections with unresolved or partial collections; the small presets retain the verified directly readable collection. Use a profile that fits the actual available space. Reserve space for discovery, metadata, and downloads.
5. Run a plan and inspect its selected files, source sizes, and warnings.

```bash
python scripts/validate_catalog.py
python scripts/build_drive.py --list-resources
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --plan
```

Mount locations differ by operating system. Typical roots include `/Volumes/` on macOS, `/media/` or `/run/media/` on Linux, and a drive letter such as `E:\` on Windows. These are examples; confirm the real destination yourself.

## Choose what to include

Open [`SELECT.html`](../SELECT.html) locally for the [offline selection tool](selector.md). Choose a 16 GB, 64 GB, 256 GB, 512 GB, or 1 TB preset, adjust inclusion controls, and inspect live totals. Enter the destination without adding shell quotes and choose POSIX shell or PowerShell. Copy the planning command and run it from the installed repository before running the build command. The browser page needs no installation or network; Python builds and fresh downloads still require their normal dependencies and internet access.

Small-preset rows marked **Preset files only** retain exact files from the preset. Selecting **Published collection** adds the full intended resource with `--include`; it can introduce unresolved scope and a much larger budget. Unchecking a selected row produces `--exclude`. Direct-readable and compact editions require registered alternatives. Larger profiles default to the verified compact Gutenberg/children editions; standard and full add compact practical Stack Exchange, and full adds compact science Stack Exchange. Other unavailable alternatives remain disabled. No compression ratio, conversion, or download is performed by the page.

The bundled atlas is included automatically. **Build only currently verified files (partial library)** starts unchecked and adds `--allow-incomplete` only when explicitly checked. Storage estimates include a small discovery allowance, metadata and reserve. The CLI checks actual free space. Regenerate the selector with `python scripts/build_selector.py`; `--check` detects stale output.

Current preset counts and planning peaks are generated in [content selection](content-selection.md). Each profile includes a 16 MiB discovery allowance, with no indexing scratch or cache. Source files, any acquisition workspace, metadata, and reserve are counted separately.

`catalog/resources.yaml` describes the 46 numbered resources and five support collections: `owl-direct-core`, `archive-readers`, `direct-reading-expansion`, `books-culture-expansion`, and `complete-courses-expansion`. Actual downloadable files, licenses, sizes, and hashes live in `catalog/library.yaml`. A resource can be ready, partial, or unresolved. Review the plan's resource coverage as well as its byte totals; a plausible size estimate is not proof that the requested collection is available.

The larger content targets are 190–210 GB for compact, 390–420 GB for standard, and 750–820 GB for full, before search, reader, and free-space budgets. All three select full English Wikipedia. Compact selects the 10 GB topographic-map allocation without North America OSM; standard adds North American coverage; full uses world maps in place of North America. OpenStax contributes 36 complete PDFs across all eight subject families in 16 GB; the 64 GB and larger sizes include all 73 current English PDF titles. The smaller selection preserves math/science foundations and adds nursing, business, humanities, social sciences, computing, and college success. Spanish Wikipedia requires explicit inclusion; compact science Stack Exchange defaults to full. Other languages and noncore Khan material are opt-in. All sizes retain the same acquired ordinary-format foundation, with additional archives chosen by available capacity.

The full profile also allocates 60 GB of its planned content budget to `direct-reading-expansion`: additional ordinary HTML, PDFs, and images from selected Appropedia, CD3WD, iFixit, LibreTexts, and Wikibooks material, plus an expanded small directly readable Wikipedia subset. The [in-place exporter](direct-export.md) is implemented, but curated selections and complete reviewed output editions remain unresolved. It does not automatically turn the full Wikipedia archive into millions of local HTML pages. Preferences apply to selected resources, and any future exports require reviewed source selection, licensing, attribution, and verified files. To omit the allocation, add `--exclude direct-reading-expansion`.

Use stable IDs or resource numbers from `--list-resources`. Both options can be repeated and accept comma-separated selections:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile full-1tb \
    --include wikipedia-fr \
    --exclude wikipedia-es,ted-ed \
    --plan
```

Selecting resolved ZIM assets automatically brings `archive-readers` into the plan. Explicitly excluding that reader collection while ZIM assets remain selected is an error. Review the resulting selection after adding or excluding resources; an archive cannot be made directly readable by removing its reader requirement. Source and licensing gaps still require resolution.

A normal build stops when selected resources are unresolved or only partially represented. You can revise the selection, resolve the missing source metadata, or explicitly accept a partial content build with `--allow-incomplete`. That option does not waive download checks or file integrity. It records incomplete content selection in the inventory and build information and places a notice on the landing page.

## Build in place on the SSD

The selector adds `--detach` to start a saved background Python job. Use its
printed directory with `python scripts/build_job.py status JOB_DIR`, `cancel
JOB_DIR`, or `resume JOB_DIR`. Verification and postflight run automatically; see
[unattended builds](unattended-builds.md). Search and atlas compile from approved
metadata without opening document bodies. The commands below run in the foreground.

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile critical-64gb
```

For an explicitly partial build of a larger target selection:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --allow-incomplete
```

The SSD is the build workspace and finished product. Download partials live under
`LIBRARY/.owl/downloads/`; verified files move into their final locations on the
same SSD. Discovery output lives under `LIBRARY/SEARCH/` and uses one small metadata
list, without an indexing database or extraction checkpoints.

Leave `--cache-dir` unset to keep downloads on the external drive. This optional
flag caches original files; `--work-dir` applies only to temporary acquisition
inputs. The selector needs neither option for the current default catalog.

Capacity planning includes exact selected file sizes, discovery output, navigation
metadata, acquisition workspace where applicable, and free-space reserve. Existing
owned files can be reused after verification. The builder checks actual space and
rejects discovery output above its allowance before publication. Failed builds
retain owned partial downloads; unrelated files are preserved.

## Pause and resume

1. Press **Ctrl-C once** to pause. Wait for the pause message and terminal prompt.
2. If disconnecting the SSD, use the operating system's safe-eject command.
3. Reconnect the same SSD, confirm its mount path, and rerun the **same command**.
   Keep the same catalog, selection, cache, and work-directory arguments. No
   `--resume` flag is needed.

This also lets you release the computer for another task. Normal OS sleep pauses
the process; after wake, broken network connections enter the retry path. For a
predictable stop before closing a laptop, pausing and safely ejecting first avoids
relying on how that laptop powers its USB ports during sleep. Terminal close and
termination signals use cooperative cleanup where the OS delivers them. A forced
kill or power cut cannot run cleanup, but prior durable checkpoints remain.

| Interrupted phase | Behavior on the next run |
| --- | --- |
| Download | Reuse verified files; resume `.part` bytes with HTTP Range where supported. A server that ignores ranges causes that file to restart safely. |
| Local/cache copy | Compare the saved prefix with the source, append the missing suffix, then check the completed file's SHA-256 before promotion. |
| Discovery compilation | Recompile the small metadata list; no source extraction or index cache is needed. |
| Static pages, checksums, final verification | Regenerate small pages and repeat integrity checks as needed. Hashing itself is not checkpointed. |

Transfers flush durable checkpoints every 64 MiB or five seconds between chunks,
and on cooperative interruption. An unusually slow transfer or
blocked OS I/O can delay a checkpoint or interrupt response. Reopening and hashing
large existing files can take substantial time even when no download is needed;
files are not trusted merely because their name, size, or timestamp matches.
Changing content or selection requires a new metadata compilation.

An internet outage gets bounded retries with backoff. Foreground commands exit
after those attempts; restore the connection and rerun. Saved background jobs
also apply their configured transient retry window, then record an actionable
failure if it is exhausted. Use `resume` on the saved job after recovery.

`LIBRARY/.owl/state.json` records the phase and stays incomplete until final verification and postflight.
The independent verifier reports an incomplete build or copy as `FAILED`, even
if all previous files still match. Existing completed files stay in place until
verified replacements are ready; an update is atomic per file, not per whole SSD.
Treat the library as finished only after the command completes and verification
passes. Do not edit managed files while a build is active.

OS-held locks prevent concurrent writers and release automatically when a process
exits or is killed. Lock files remain on disk by design; **do not delete them**.
Directory identity checks stop writes if a mounted build directory disappears or
is replaced, rather than recreating its path on the computer. These checks cannot
make an unsafe unplug or damaged exFAT filesystem transactional: reconnect the
original drive, address filesystem errors if necessary, and verify before use.

## Copy directly to a second SSD

A finished SSD can supply a second SSD without a full copy on the computer:

```bash
python scripts/copy_drive.py /media/FIRST/EMERGENCY_LIBRARY \
    /media/SECOND/EMERGENCY_LIBRARY
python scripts/verify.py /media/SECOND/EMERGENCY_LIBRARY
```

`owl-copy SOURCE TARGET` is the same command. It copies checksum-listed files,
including the existing index, and preserves their bytes exactly. It skips verified
target files, checkpoints owned partials on the destination SSD, copies the
checksum manifest last, and marks interrupted copies incomplete. Ctrl-C and the
same command resume it. No downloads or extraction are involved. Unknown personal
files are preserved and are not copied. Source libraries retaining `LIBRARY/.owl` state
need writable access for their concurrency lock. An intentionally partial-content
library remains partial after copying; copying does not fill missing collections.

Both copy arguments name the outer directories. The result keeps
`START_HERE.html` beside `LIBRARY`; do not copy only the inner folder.

Custom recipes use `--catalog /path/to/catalog.yaml`, `--profiles-dir /path/to/profiles`, and optionally `--resources-catalog /path/to/resources.yaml`. The registry defaults to `resources.yaml` beside the asset catalog. Use versioned, immutable URLs and known SHA-256 hashes where possible. `--allow-local` explicitly permits local test assets; it is useful for tiny demonstration builds and is not needed for ordinary public-source builds.

## Find learning and reading collections

`START_HERE.html` links directly to the textbook shelf and illustrated-guide shelf, showing each shelf’s total and critical-resource count. Both pages work without JavaScript. The textbook shelf contains ordinary, directly readable textbooks. The illustrated shelf includes illustrated textbooks and practical guides; reader-dependent archives, EPUBs, and software packages are excluded from these shelves.

The critical-content index spans folders. A core textbook stored under `LIBRARY/BOOKS/TEXTBOOKS/` still appears in `LIBRARY/INDEX/critical.html` and carries a Critical label in the other indexes. You do not need to know its folder to find it. The inventory shows resource-type and illustration labels alongside source, license, integrity, and search-coverage information.

Project Gutenberg and Children's Library also have prominent landing-page entries and static pages at `LIBRARY/INDEX/gutenberg.html` and `LIBRARY/INDEX/children.html`. These pages list only selected assets actually on the drive, using their catalog resource IDs. Counts refer to files or collection archives, not individual books inside archives. Reader-dependent formats are labeled. With no available assets, the page says the collection is absent; the presence of a shelf page is not a claim that its planned collection was downloaded.

In a partial build, consult the inventory's resource-selection table for missing or incomplete collections and their coverage notes. A successfully verified file set can still represent only part of the selected content plan.

Open PDFs to see diagrams, photographs, charts, and figures. Publisher PDFs retain their original bytes. The 61 Book Dash editions are reviewed PDF conversions with original text, illustrations, language and credits retained; each story illustration starts a page with its following text. Their source EPUBs stay under `LIBRARY/REFERENCE/SOURCE_PACKAGES/EPUB/`, excluded from reading shelves and search. Ordinary PDF viewing does not require an EPUB reader.

Python's reading collection contains 37 original publisher PDFs for Python 3.14.0, dated October 7, 2025. The newer September 2026 EPUB is retained separately as a supporting source package; it is not the source of those older PDFs. See [PDF reading editions](pdf-editions.md) for exact edition and conversion details.

On iPhone or iPad, open the PDFs directly in Files and choose **Preview with Quick Look** if offered. If an HTML preview refuses links, close it and navigate using the exact `LIBRARY/...` paths printed in the start page's inline catalog. Search covers titles, approved sections and topics; it does not search bodies or interpret images. A diagram or scanned page can be useful even when its contents are absent from search results.

## Add the topic atlas after downloading

The [topic atlas](topic-atlas.md) provides static subject, practical-task, and learning routes alongside the collection shelves. Shared topics can be reached through several broader subjects without duplicating source files. Topic aliases and book contents pages also work without JavaScript.

For a library that already has an inventory:

```bash
python scripts/build_atlas.py /media/SSD/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation
python scripts/verify.py /media/SSD/EMERGENCY_LIBRARY
```

The command verifies existing sources and publishes both the atlas and metadata
search. To refresh discovery without that source audit, use the
[discovery CLI](search.md). It checks inventory/source pins, presence and size and
records that source verification was not repeated. The bundled production catalog
includes atlas generation during full builds. Custom catalogs can specify:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile critical-64gb --navigation-dir catalog/navigation
```

Repeat `--navigation-dir` on later full builds that should generate the atlas. Normal content-selection and completeness rules still apply. After publication, start at `LIBRARY/INDEX/topics.html` or the topic-atlas link on `START_HERE.html`.

Production routes use the approved topics and assignments in `catalog/navigation/`. Sources absent from the current drive and branches with no available material are omitted. The final include list, topic vocabulary, and deeper section curation remain editorial work. The atlas guide explains how to import publisher contents into drafts, review exact source locations, and use `--strict-coverage` to reject missing critical or textbook routes. Structural coverage does not establish the quality or completeness of the underlying guidance.

## Verify and practice

```bash
python scripts/verify.py /media/SSD/EMERGENCY_LIBRARY
# Or use the independent verifier copied to the drive:
python /media/SSD/EMERGENCY_LIBRARY/LIBRARY/VERIFY.py /media/SSD/EMERGENCY_LIBRARY
```

Read the report:

| Status | Meaning | Action |
| --- | --- | --- |
| `OK` | File matches its recorded SHA-256 | No file-integrity action needed; check content-selection status separately |
| `MISSING` | Expected file is absent | Rebuild or restore it from the verified backup |
| `FAILED` | Hash mismatch, unreadable file, or unsafe manifest entry | Investigate; replace from a trusted source and verify again |
| `UNKNOWN` | File has no entry in the checksum manifest | Review whether it is your file or intentionally unmanaged material |

After rejecting symlinks, the verifier skips macOS volume directories `.Trashes`, `.Spotlight-V100`, `.fseventsd`, and `.TemporaryItems` only at the outer root; same-named directories inside `LIBRARY` remain subject to verification.

Keep a trusted copy of `LIBRARY/SHA256SUMS.txt`, `LIBRARY/INVENTORY.json`, `LIBRARY/BUILD_INFO.json`, `LIBRARY/LOCKED_CATALOG.yaml`, and the original catalog away from the drive. A checksum manifest stored beside its files cannot detect an attacker replacing both. OWL’s build timestamps and metadata may differ between builds even when the knowledge assets are identical.

Before storing the SSD, disconnect network access and try each intended device:

1. Attach the SSD with the necessary adapter and power source; find it in the file manager.
2. Open `START_HERE.html`, follow a category link, and open a critical PDF or text file.
3. If HTML links do not work, use the catalog printed on START_HERE itself. Note a document's `LIBRARY/...` path, close the preview, and open that file through the file manager.
4. Open a core textbook and an illustrated guide from their dedicated shelves. Navigate between pages and zoom into a diagram to confirm it is readable on the device.
5. In a compatible browser, search controls appear on `START_HERE.html` after discovery data loads. Enter known words, then try `LIBRARY/SEARCH.html` as well and open a result in a compatible document viewer. No index-file selection is needed. File previews may block both scripts and local links; the inline catalog and direct folder access remain the fallback.
6. Open the textbook, illustrated-guide, Gutenberg, children's, category, critical, and alphabetical indexes with JavaScript disabled. If generated, try the atlas through subject, practical-task, and learning entrances, including recovery from a wrong turn. Confirm critical textbooks are reachable through the critical index even when their files are in `LIBRARY/BOOKS/`. Check that missing planned collections are clearly reported.
7. On platforms that permit offline installation, check that the matching bundled reader can open a ZIM. The builder does not install or run it for you.
8. Safely eject the SSD before unplugging it.

An iPhone’s Files preview is useful for ordinary documents but is not a general-purpose browser for a local web application. It can show START_HERE while leaving search unavailable and failing to open a linked file, even after an Open confirmation. Changing the page's relative paths does not grant the preview access to the library. Full interactive use needs a viewer that can run scripts and access the library folder, or the library served over a local network to a browser; OWL does not currently supply an iOS app or a local server. A bundled APK or desktop executable cannot provide an offline iOS installation path. Android storage access also varies by file manager and browser. Keep direct document access as the primary path on phones.

## Update without losing a working copy

Keep one verified SSD untouched while building or updating the other. Review changed source licenses, URLs, versions, and expected hashes before accepting a new catalog. Plan the update, build it, verify it, and repeat the device checks before replacing the previous working copy. Replacements are atomic per file, but a failed update can leave files from different builds; an incomplete build is not a verified snapshot.

Rebuilding is safe to repeat, but it does not guarantee an old source remains downloadable. A mutable URL can change or disappear. Retain a cache for the exact approved catalog and build records for repeatability. Files removed from a newer recipe are not automatically deleted from an older drive; a fresh dedicated destination provides the clearest snapshot.

Build two identical SSDs, verify both, and store the backup separately. Keep required cables, adapters, and power equipment with them. Periodically verify all files and read a few important documents on the actual target devices. Investigate checksum changes before copying data between the drives so a bad copy does not replace a good one.
