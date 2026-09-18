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

## Build and resume

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile critical-64gb \
    --cache-dir /path/to/cache \
    --work-dir /path/to/build-scratch
```

For an explicitly partial build of a larger target selection:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --allow-incomplete \
    --cache-dir /path/to/cache \
    --work-dir /path/to/build-scratch
```

The cache and scratch directories should have sufficient free space; putting them on the build computer can reduce removable-drive I/O. Scratch storage is used to construct search, including a build-time SQLite database. No database service or server is required, and the finished drive does not need SQLite to run search.

Capacity planning uses decimal drive capacity, the profile's reserve, exact known asset sizes, a search budget, and build overhead. Planned collection allocations are shown separately from known asset bytes. Free-space checks additionally allow for search scratch storage; allocations sharing one filesystem are added together, including cache and external scratch. Caching needs another copy of downloaded content.

The content targets and search budgets do not establish that a full Wikipedia index fits on the corresponding SSD. Index size can exceed the compressed source size, and the complete target corpus has not been benchmarked. Keep extra scratch space available and review the actual final-capacity check. `--allow-incomplete` permits content gaps, not an over-capacity drive or a failed integrity check.

If a connection fails, rerun the same command. Downloads stream to partial files and request HTTP byte ranges where supported. A source that ignores the range is downloaded from the beginning instead of blindly appending bytes. Files are accepted only after the builder’s checks and then renamed into place. Checksum failures are errors, not successful builds.

The cache stores downloaded bytes, not an alternative authoritative catalog. Hashes are rechecked before reuse. Drive files already present and verified can be reused. The builder preserves unrelated files and refuses unsafe paths or output collisions. Do not rename or edit the managed library while a build is running. A target lock prevents concurrent builds. Remove a stale lock only after confirming no builder is running; do not remove a lock to bypass an active build.

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
