# Offline Wandering Library (OWL)

OWL builds an offline knowledge library directly on an external drive. This repository contains URLs, hashes, selection rules, build tools and small interface assets. Books, maps, encyclopedias and reader packages download during the build.

The defaults prioritize substantial, diversified information useful in a post-internet, low-electronic life. **CRITICAL** covers survival, health, food, water and shelter. **USEFUL** covers practical trades, repair, appropriate technology and education through high school. **NONESSENTIAL** stories, college textbooks, computing and enrichment remain available as opt-in collections.

Every selectable asset passes the [machine-readable content-type policy](src/owl/content_policy.json). The [priority policy](src/owl/utility_policy.json) requires practical domain coverage in every default, without book-count or content-size quotas. PDFs and ZIMs download unchanged; the optional Python PDF ZIP is unpacked without altering its documents. No active selection requires EPUB conversion, HTML reconstruction or document rendering.

## Build a drive

Connect an already formatted drive, clone this repo, and open [SELECT.html](SELECT.html). Pick a size, select or deselect collections, and copy the generated build command into your terminal. The page itself does not execute commands or download files.

```bash
git clone https://github.com/jonaraphael/offline-wandering-library.git
cd offline-wandering-library
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install -e '.[zim]'
python scripts/check_selection_policy.py

# Replace this path with a directory on the external drive.
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY --profile flash-16gb --plan
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY --profile flash-16gb
python scripts/verify.py /path/to/EMERGENCY_LIBRARY
```

Python 3.11+ and internet access are needed to build. Reading ordinary PDFs does not require Python. ZIM archives need a compatible reader; packages for Windows, macOS, Linux and Android are included. The builder never formats the drive or executes downloaded software. Leave `--cache-dir` unset so original downloads and resumable partials stay exclusively on the selected drive.

Search and atlas now compile from titles, descriptions, aliases, topics, and reviewed section maps. Builds do not extract or index document bodies. Each profile reserves 16 MiB for discovery output; there is no indexing workspace or cache. Downloads and full integrity verification still read source bytes.

The selector's command uses `--detach` to start a saved background job. Inspect, cancel or resume it with `scripts/build_job.py`; see [unattended builds](docs/unattended-builds.md). For foreground builds, pause with Ctrl-C, wait for the prompt and rerun the command to resume. Keep the drive connected while the job is active.

## Profiles and content

| Drive preset | Pinned files, including readers | Default emphasis |
| --- | ---: | --- |
| 16 GB | 7.691 GB | Medical, food, water, shelter, hand tools, repair, school math/science and small practical archives |
| 64 GB | 33.218 GB | Adds WikiMed, dictionaries, Wikibooks and practical trade communities |
| 256 GB | 219.330 GB | Adds English Wikipedia, North America maps and historical nonfiction |
| 512 GB | 274.409 GB | Substitutes the world map for North America |
| 1 TB | 274.519 GB | Adds soil, seed, crop, water-system and trail manuals; room for further useful additions |

These are real pinned file sizes, not allocations for unavailable material. All five default plans fit their nominal drives with their configured discovery, metadata and reserve allowances. A 1 TB drive selection does **not** mean 1 TB of curated content is ready. [Generated content selection](docs/content-selection.md) contains the detailed current totals and collection scopes.

The [topic-by-topic completion plan](docs/full-1tb-coverage-plan.md) records intended
depth, existing resources, remaining gaps, next selections and adequacy criteria.
Topic tags establish presence; editorial review establishes whether a subject is
covered well enough. Update the plan alongside each resource admission.

The direct foundation includes published medical and public-health chapters, canning/freezing/drying manuals, agriculture and beekeeping, shelter and navigation, illustrated ax and saw manuals, electrical/mechanical references, and complete school textbooks and teacher guides. PhET simulations have matching offline screen-test evidence. College textbooks, programming references, juvenile literature and additional languages are optional.

Coverage remains incomplete in specific areas: local topographic maps, initial literacy and school humanities, missing Hesperian back matter, and finished SQLite/OpenSSH references. The [JSON review](catalog/content-review.json) records the disposition of every previous asset and distinguishes exact replacements from broader subject alternatives. Existing acquisition reports preserve research history; their old conversion recipes and planned byte targets do not authorize active content.

## Customize and validate

Use the selector's priority filter and collection checkboxes, or its topic map to explore assets grouped by theme. Or use stable collection IDs:

```bash
python scripts/build_drive.py --list-resources
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile critical-64gb --include childrens-library --exclude phet --plan
python scripts/check_content_policy.py
python scripts/check_selection_policy.py
python scripts/build_selector.py --check
```

Selecting ZIMs automatically includes their reader packages. Optional additions must fit the chosen capacity. No default requires `--allow-incomplete`; this flag cannot bypass the content policy. The [selector guide](docs/selector.md) explains storage and commands. See [catalog maintenance](docs/catalog.md) before admitting new sources.

## Use the completed SSD

Open `START_HERE.html`. A fresh build puts exactly two items in the chosen outer directory: this entry page and a `LIBRARY` folder containing everything else. Keep them together when moving or copying the library. Its first shelves link to textbooks, illustrated guides, Project Gutenberg, and Children's Library, with counts of available files. It also provides topic links, search, and ordinary static indexes. You can navigate directly through `LIBRARY` with the device’s file manager.

The default children's books and Python manuals are PDFs, so reading them does not require an EPUB app. On iPhone or iPad, use Files to open the PDF directly and choose **Preview with Quick Look** if offered. If the start-page preview cannot follow links, use its printed `LIBRARY/...` paths to locate the files manually. Retained EPUBs under `LIBRARY/REFERENCE/SOURCE_PACKAGES/EPUB/` are excluded from the reading shelves and search.

```text
EMERGENCY_LIBRARY/
├── START_HERE.html              # Open this first; static links work without JavaScript
└── LIBRARY/
    ├── SEARCH.html             # Dedicated automatic offline search
    ├── README.txt / VERIFY.py / SOURCE_NOTES.txt
    ├── INVENTORY.html / INVENTORY.json
    ├── BUILD_INFO.json / CONTENT_SELECTION.json / SHA256SUMS.txt / LOCKED_CATALOG.yaml
    ├── CRITICAL/               # Ordinary files grouped by emergency topic
    ├── REFERENCE/
    ├── BOOKS/TEXTBOOKS/         # Core directly readable textbooks
    ├── MAPS/
    ├── ZIM/                    # Large archives; a reader is required
    ├── SOFTWARE/               # Bundled readers for supported platforms
    ├── SEARCH/                 # Small discovery catalog and coverage report
    ├── INDEX/                  # Learning/reading shelves, critical, category, A–Z
    └── .owl/                   # Private build and resume state
```

Build, verify, copy, atlas and export commands take the outer
`EMERGENCY_LIBRARY` directory. Catalog `destination` values and private managed
paths remain relative to the inner `LIBRARY` directory: a catalog destination
such as `BOOKS/manual.pdf` is stored at `EMERGENCY_LIBRARY/LIBRARY/BOOKS/manual.pdf`.
The global `LIBRARY/SHA256SUMS.txt` instead records paths relative to the outer
directory so it covers both `START_HERE.html` and files under `LIBRARY/`.

The static indexes list catalog files, including titles, categories, textbook/illustrated labels, and archive-reader requirements. Dedicated `textbooks.html`, `illustrated-guides.html`, `gutenberg.html`, and `children.html` pages sit alongside `critical.html`, `categories.html`, and the alphabetical pages in `LIBRARY/INDEX/`. They work without JavaScript and contain ordinary relative links. They do not expand every article inside an archive into separate HTML files.

The [topic atlas](docs/topic-atlas.md) shares subject, practical-task, and learning routes with search. Normal builds with the bundled production catalog include it automatically; custom catalogs can supply `--navigation-dir`. Only topics with selected sources appear. Approved section maps must match the inventory's exact source edition.

Reusable topic links and aliases are saved per asset in
`catalog/navigation/assignments/`, alongside the shared topic tree and optional
reviewed section maps. After curl downloads to the catalog paths under
`DRIVE/LIBRARY/`, assemble just the completed, verified subset:

```bash
python scripts/discovery.py assemble --output /path/to/DRIVE --profile flash-16gb
```

This checks size and SHA-256, omits unfinished files and empty topics, and compiles
both search and atlas. Rerun after more downloads finish; no AI or content indexing
is required.

After improving metadata, refresh a completed drive without rereading document bodies:

```bash
python scripts/discovery.py build \
    --inventory /path/to/EMERGENCY_LIBRARY/LIBRARY/INVENTORY.json \
    --output /path/to/EMERGENCY_LIBRARY
```

This checks metadata, source presence and sizes, and republishes search and atlas together. It records that source integrity was not reverified. Use `scripts/verify.py` when a full source audit is needed. See [the discovery workflow](docs/search.md) for preparing metadata, validating AI annotations, and reviewing source locations.

## Search without a server

Open `START_HERE.html` and enter words in **Search titles, chapters, and topics**. Search loads automatically from neighboring files on the SSD; there is no index file to select. `LIBRARY/SEARCH.html` provides the same interface on a dedicated page. All processing stays on the device, without a server, account, CDN, or network connection.

The browser loads one small metadata list and scans it locally. Exact title and alias matches rank first, followed by all-word and partial matches. Results show source descriptions, locations, attribution, and reader requirements. Reviewed chapters link to their source location and the whole document. Topic matches open static atlas pages.

Search covers titles, chapters, topics, aliases, and catalog descriptions. It does not search body text or interpret images. No match does not establish that the information is absent: open a relevant document or use an archive's own reader search. Software and supporting source packages are excluded.

Choose **All resources**, **Textbooks**, or **Illustrated guides** to narrow the results before ranking. Search data, runtime, manifest, and coverage live in `LIBRARY/SEARCH/`; keep that folder together. Coverage reports distinguish catalog results from sources with approved sections. See [search behavior and the Python/AI workflow](docs/search.md).

Search depends on browser and file-manager capabilities:

| Platform | Ordinary files | JavaScript search | Large ZIM archives |
| --- | --- | --- | --- |
| Windows, macOS, Linux | Compatible standard browser/viewer | Browser must permit local JavaScript and neighboring local script files; test the chosen browser | Use a compatible bundled or already installed reader |
| Android / Pixel | File manager and compatible viewer | Browser launching, storage providers, and external-drive access vary; test the actual device | An appropriate APK may be installable offline if permitted |
| iPhone / iPad | Files and compatible document previews | Files may block both search scripts and links to neighboring files. Read the catalog and printed paths on START_HERE, then open documents directly in Files | Do not assume a reader can be installed from the SSD offline |
| Raspberry Pi | Compatible standard browser/viewer | Depends on the installed browser and available memory | Reader must match the Pi’s processor and operating system |

This is a compatibility design, not a claim of hardware testing on every platform. START_HERE includes the catalog and drive-relative file paths on the page itself, so reading it does not require following links to another HTML page. If a file preview refuses links, close it and use those paths to open PDFs or text files directly in the file manager. Search controls appear only after discovery data loads successfully. Adapters, USB power, supported filesystem access, existing viewers, and OS permissions still matter. **Test the finished SSD on the exact devices you intend to use before an emergency.**

## Bundled readers

Reader packages are ordinary catalog assets under `LIBRARY/SOFTWARE/`, with source, version, hash, and license information recorded alongside the content. They are downloaded and verified, never executed during a build. The initial catalog includes Kiwix Windows portable 2.5.1, Linux x86-64 AppImage 2.5.1, macOS 3.14.0, and Android 3.14.0. The generated inventory identifies what the selected profile includes. No Raspberry Pi ARM reader package is currently verified in the catalog.

A package’s presence does not guarantee it will run: CPU architecture, operating-system version, dependencies, signature checks, installation permissions, and Android’s install-from-files setting may matter. Offline installation of an arbitrary iPhone application from a USB SSD is not a dependable option. Critical files exist outside archives to preserve access on those devices.

## Integrity, updates, and backups

`LIBRARY/SHA256SUMS.txt` records managed files using SHA-256. `LIBRARY/INVENTORY.json` records the assets, source metadata, hashes, and verification provenance; `LIBRARY/BUILD_INFO.json` records the build configuration and search results. The independent verifier uses the Python standard library and can run without installing OWL:

```bash
python scripts/verify.py /path/to/EMERGENCY_LIBRARY

# A copy also travels with the drive:
python /path/to/EMERGENCY_LIBRARY/LIBRARY/VERIFY.py /path/to/EMERGENCY_LIBRARY
```

It reports `OK` for matching files, `MISSING` for absent expected files, `FAILED` for mismatches or unsafe entries, and `UNKNOWN` for files outside the checksum manifest. Unknown personal files are not deleted. Checking a large drive reads its content and can take hours. A stored checksum detects accidental changes, but it is not a digital signature: retain a trusted independent copy of the checksum manifest to detect changes to both files and checksums.

A pinned source hash verifies against the catalog’s expected bytes. When an upstream source supplies no trusted SHA-256, OWL records an observed hash after download; that is a baseline for future integrity checks, not independent authentication of the original download. The generated `LIBRARY/LOCKED_CATALOG.yaml` captures measured hashes for repeat builds. Exact reproduction requires those bytes to remain available at the source or in your cache; timestamps and build metadata can differ.

To update, review catalog changes, inspect the new plan, rebuild with the intended profile, and verify again. Existing managed content may be replaced to match the selected catalog. Unrelated files are preserved. Keep the last verified drive intact until its replacement has passed verification and device checks. OWL does not prune obsolete files automatically. An update is not atomic across the entire SSD: after a failed build, rerun it and verify before considering the drive complete.

**Build two identical SSDs, verify both, and store the backup separately.** Keep the catalog and checksum manifests with your backup records. Periodically read and verify both drives, safely eject them, and replace unreliable media. Carry required adapters and power accessories with each drive. See [operating guide](docs/usage.md) for a practical checklist.

## Develop and test

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests use small local fixtures, simulated HTTP responses, and loopback HTTP servers, not real encyclopedia downloads. They cover catalog and path validation, capacity planning, checksums, interrupted transfers, repeat builds, search generation, and static navigation. Install `.[zim,pdf]` to include ZIM extraction and EPUB-to-PDF conversion tests. See [search design](docs/search.md) and [content sources](docs/sources.md) when extending the catalog or extraction pipeline.

Node.js 20+ runs the actual search JavaScript in automated tests; those tests are
explicitly skipped if Node is unavailable. Node is not a build or drive runtime
dependency. CI exercises Python 3.11 and 3.13 on Windows, macOS and Linux, with a
separate Linux job testing ZIM extraction. Hardware and full-corpus performance
remain distinct from these automated checks.

The repository’s code license is in [LICENSE](LICENSE). Downloaded content and bundled reader software retain their own licenses and attribution requirements, recorded in the catalog and inventory. Adding a source does not grant redistribution rights to unrelated material.
