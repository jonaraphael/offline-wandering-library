# Building, carrying, and maintaining an OWL drive

## Prepare

1. Use a dependable SSD and cable. Format it with your operating system’s ordinary disk tools if needed; OWL does not format drives. exFAT is the intended cross-platform filesystem.
2. Identify the SSD’s mount location carefully. Use a dedicated `EMERGENCY_LIBRARY` directory so the library is easy to find.
3. Install Python 3.11+ and OWL on the build computer. Install the `.[zim]` extra for profiles containing ZIM archives; the minimal installation is sufficient for the directly readable critical profile.
4. Review the resource registry, asset catalog, and source notes. The larger profiles describe planned selections with unresolved or partial collections; the existing `critical-64gb` profile retains its verified directly readable collection. Use a profile that fits the actual available space. Reserve space for search output and build scratch storage as well as downloads.
5. Run a plan and inspect its selected files, source sizes, and warnings.

```bash
python scripts/validate_catalog.py
python scripts/build_drive.py --list-resources
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --plan
```

Mount locations differ by operating system. Typical roots include `/Volumes/` on macOS, `/media/` or `/run/media/` on Linux, and a drive letter such as `E:\` on Windows. These are examples; confirm the real destination yourself.

## Choose what to include

`catalog/resources.yaml` describes the 46 numbered resources and three support collections: `owl-direct-core`, `archive-readers`, and `direct-reading-expansion`. Actual downloadable files, licenses, sizes, and hashes live in `catalog/library.yaml`. A resource can be ready, partial, or unresolved. Review the plan's resource coverage as well as its byte totals; a plausible size estimate is not proof that the requested collection is available.

The larger content targets are 190–210 GB for compact, 390–420 GB for standard, and 750–820 GB for full, before search, reader, and free-space budgets. All three select full English Wikipedia. Compact selects the 10 GB topographic-map allocation without North America OSM; standard adds North American coverage; full uses world maps in place of North America. OpenStax defaults to standard/full, Spanish Wikipedia to full, and the science Stack Exchange collection to full. Additional languages and noncore Khan material are opt-in. The critical profile's existing collection remains separate from these larger target selections.

The full profile also allocates 60 GB of its planned content budget to `direct-reading-expansion`: additional ordinary HTML, PDFs, and images from selected Appropedia, CD3WD, iFixit, LibreTexts, and Wikibooks material, plus an expanded small directly readable Wikipedia subset. This is an unresolved content plan, not a completed package or an implemented export pipeline. It does not automatically turn the full Wikipedia archive into millions of local HTML pages. Preferences apply to selected resources, and any future exports require reviewed source selection, licensing, attribution, and verified files. To omit the allocation, add `--exclude direct-reading-expansion`.

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

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile critical-64gb
```

For an explicitly partial build of a larger target selection:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --allow-incomplete
```

The SSD is the build workspace and finished product. By default, downloaded
partials live under `.owl/downloads/`, search checkpoints under `.owl/work/`, and
the unfinished search output under `SEARCH/`. A verified download is renamed
into its final location on the same SSD without copying it through the computer.
SQLite's persistent database and rollback journal stay in the chosen workspace;
index construction does not spill large sorting files into the computer's OS
temporary directory. No local server or database service is required.

Do not add `--cache-dir` merely to enable resumption: the default already resumes.
A cache is an optional additional asset copy. `--work-dir` optionally relocates
search scratch when space is available elsewhere; the default is the SSD.
Keep either optional directory between runs if you use it.

Capacity planning uses decimal capacity, exact available asset sizes, a search
budget, scratch allowance, and free-space reserve. Allocations on the same
filesystem are added together. Existing owned partials and search checkpoints
are credited against new allocation needs, while retained previous versions
still occupy space. The plan distinguishes final size from peak in-place build
space. Current complete proposed larger selections exceed nominal-drive capacity
under the conservative scratch allowances, even though their final-content
budgets fit. The final include list and working-space requirements must be
measured and reconciled before calling those complete targets achievable in
place. Available-file partial builds are checked against their actual allocations.
The builder neither redirects scratch to the computer automatically nor shrinks
or silently omits selected content to force a fit.

Search size can exceed the compressed source size. Budgets are estimates, not
hard upper bounds; insufficient space can still stop a build. Files and durable
checkpoints remain for a later retry after freeing unrelated space yourself or
choosing a fitting recipe. OWL never automatically prunes personal files.

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
| PDF, EPUB, or ZIM extraction | Resume at the saved page, member, or raw archive-entry cursor. Checkpoints occur every 50 units or five seconds at a unit boundary. Work after the last durable checkpoint repeats. |
| Plain text or HTML extraction | Resume after completed files; the current file restarts. |
| Final search-index assembly | Reassemble from retained extracted text and postings; extraction does not repeat. |
| Unchanged completed search index | Verify input bytes, metadata/toolchain fingerprint, and index hash, then reuse. |
| Static pages, checksums, final verification | Regenerate small pages and repeat integrity checks as needed. Hashing itself is not checkpointed. |

Transfers flush durable checkpoints every 64 MiB or five seconds between chunks,
and on cooperative interruption. An unusually slow PDF page, decompression, or
blocked OS I/O can delay a checkpoint or interrupt response. Reopening and hashing
large existing files can take substantial time even when no download is needed;
files are not trusted merely because their name, size, or timestamp matches.
Changing content, selection metadata, or extractor versions invalidates the
extraction checkpoint deliberately.

An internet outage gets bounded retries with backoff. If retries are exhausted,
the command exits with an error and retains resumable work. Restore the connection
and rerun; there is no background daemon or requirement to keep it running.

`.owl/state.json` records the phase and stays incomplete until final verification.
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
files are preserved and are not copied. Source libraries retaining `.owl` state
need writable access for their concurrency lock. An intentionally partial-content
library remains partial after copying; copying does not fill missing collections.

Custom recipes use `--catalog /path/to/catalog.yaml`, `--profiles-dir /path/to/profiles`, and optionally `--resources-catalog /path/to/resources.yaml`. The registry defaults to `resources.yaml` beside the asset catalog. Use versioned, immutable URLs and known SHA-256 hashes where possible. `--allow-local` explicitly permits local test assets; it is useful for tiny demonstration builds and is not needed for ordinary public-source builds.

## Find learning and reading collections

`START_HERE.html` links directly to the textbook shelf and illustrated-guide shelf, showing each shelf’s total and critical-resource count. Both pages work without JavaScript. The textbook shelf contains ordinary, directly readable textbooks. The illustrated shelf includes illustrated textbooks and practical guides; reader-dependent archives, EPUBs, and software packages are excluded from these shelves.

The critical-content index spans folders. A core textbook stored under `BOOKS/TEXTBOOKS/` still appears in `INDEX/critical.html` and carries a Critical label in the other indexes. You do not need to know its folder to find it. The inventory shows resource-type and illustration labels alongside source, license, integrity, and search-coverage information.

Project Gutenberg and Children's Library also have prominent landing-page entries and static pages at `INDEX/gutenberg.html` and `INDEX/children.html`. These pages list only selected assets actually on the drive, using their catalog resource IDs. Counts refer to files or collection archives, not individual books inside archives. Reader-dependent formats are labeled. With no available assets, the page says the collection is absent; the presence of a shelf page is not a claim that its planned collection was downloaded.

In a partial build, consult the inventory's resource-selection table for missing or incomplete collections and their coverage notes. A successfully verified file set can still represent only part of the selected content plan. The proposed hierarchical topic atlas remains unimplemented; these are collection shelves and the existing category/title indexes.

Open the original PDFs to see diagrams, photographs, charts, and figures. Downloads retain the original file bytes and embedded illustrations. Search indexes extractable text; it does not interpret images or provide OCR. A diagram or scanned page can be useful even when its contents are absent from search results.

## Verify and practice

```bash
python scripts/verify.py /media/SSD/EMERGENCY_LIBRARY
# Or use the independent verifier copied to the drive:
python /media/SSD/EMERGENCY_LIBRARY/VERIFY.py /media/SSD/EMERGENCY_LIBRARY
```

Read the report:

| Status | Meaning | Action |
| --- | --- | --- |
| `OK` | File matches its recorded SHA-256 | No file-integrity action needed; check content-selection status separately |
| `MISSING` | Expected file is absent | Rebuild or restore it from the verified backup |
| `FAILED` | Hash mismatch, unreadable file, or unsafe manifest entry | Investigate; replace from a trusted source and verify again |
| `UNKNOWN` | File has no entry in the checksum manifest | Review whether it is your file or intentionally unmanaged material |

Keep a trusted copy of `SHA256SUMS.txt`, `INVENTORY.json`, `BUILD_INFO.json`, `LOCKED_CATALOG.yaml`, and the original catalog away from the drive. A checksum manifest stored beside its files cannot detect an attacker replacing both. OWL’s build timestamps and metadata may differ between builds even when the knowledge assets are identical.

Before storing the SSD, disconnect network access and try each intended device:

1. Attach the SSD with the necessary adapter and power source; find it in the file manager.
2. Open `START_HERE.html`, follow a category link, and open a critical PDF or text file.
3. If HTML links do not work, open a critical document directly from its folder.
4. Open a core textbook and an illustrated guide from their dedicated shelves. Navigate between pages and zoom into a diagram to confirm it is readable on the device.
5. Open `SEARCH.html` in an actual browser, select `SEARCH/library.owl`, and search for a known phrase. Verify the resulting document link. Treat this as optional on devices whose file previews restrict JavaScript.
6. Open the textbook, illustrated-guide, Gutenberg, children's, category, critical, and alphabetical indexes with JavaScript disabled. Confirm critical textbooks are reachable through the critical index even when their files are in `BOOKS/`. Check that missing planned collections are clearly reported.
7. On platforms that permit offline installation, check that the matching bundled reader can open a ZIM. The builder does not install or run it for you.
8. Safely eject the SSD before unplugging it.

An iPhone’s Files preview is useful for ordinary documents but is not a general-purpose browser for a local web application. A bundled APK or desktop executable cannot provide an offline iOS installation path. Android storage access also varies by file manager and browser. Keep direct document access as the primary path on phones.

## Update without losing a working copy

Keep one verified SSD untouched while building or updating the other. Review changed source licenses, URLs, versions, and expected hashes before accepting a new catalog. Plan the update, build it, verify it, and repeat the device checks before replacing the previous working copy. Replacements are atomic per file, but a failed update can leave files from different builds; an incomplete build is not a verified snapshot.

Rebuilding is safe to repeat, but it does not guarantee an old source remains downloadable. A mutable URL can change or disappear. Retain a cache for the exact approved catalog and build records for repeatability. Files removed from a newer recipe are not automatically deleted from an older drive; a fresh dedicated destination provides the clearest snapshot.

Build two identical SSDs, verify both, and store the backup separately. Keep required cables, adapters, and power equipment with them. Periodically verify all files and read a few important documents on the actual target devices. Investigate checksum changes before copying data between the drives so a bad copy does not replace a good one.
