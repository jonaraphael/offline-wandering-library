# Offline Wandering Library (OWL)

OWL builds an offline knowledge library directly on an external drive. This repository contains URLs, hashes, selection rules, build tools and small interface assets. Books, maps, encyclopedias and reader packages download during the build.

The defaults prioritize knowledge for a post-internet, low-electronic life. **CRITICAL** covers survival, health, food, water and shelter. The Python default includes the entire critical tier. The browser plan shows which selected files it can fetch. **USEFUL** covers practical trades, repair, appropriate technology, general reference and education through high school. **NONESSENTIAL** covers stories, college textbooks, computing and enrichment. A small sampler preserves those subjects, while recommendations retain at least as much of the full USEFUL tier as of the full NONESSENTIAL tier.

Every selectable asset passes the [machine-readable content-type policy](src/owl/content_policy.json). The [priority policy](src/owl/utility_policy.json) requires practical domain coverage in every default, without book-count or content-size quotas. PDFs and ZIMs download unchanged; Python and Canadian map ZIPs are unpacked without altering the PDF files. No active selection requires EPUB conversion, HTML reconstruction or document rendering.

## Build a drive

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in desktop Chrome or Edge. Connect an exFAT drive and choose its folder. Confirm
the size if free space cannot be estimated. Edit the recommendation and choose
**Build library**. Keep the tab open and the drive attached. Downloads continue
automatically when an interrupted connection returns. Use **Resume** when
reopening a saved build. **Verify and repair files** reads the whole drive
selection again. Use **Show files** to edit individual files. Collections
available through the desktop tool are labeled in the editor.
Set up iPhone Kiwix with the builder’s App Store QR code while online.
The phone shelf links to the directly readable files included in your build.
[Browser build guide](docs/pages-builder.md) · [Device tests](docs/device-matrix.md)

### Build with Python

Use Python for the full catalog or when your browser cannot write to the drive.
Clone the repository and open [SELECT.html](SELECT.html) to choose a size, edit
the recommendation, and copy the build command.

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

Python 3.11+ and internet access are needed to build. Reading ordinary PDFs does not require Python. ZIM archives need a compatible reader; packages for Windows, macOS, Linux and Android are included. The planner sets aside 500 MB for them. The builder never formats the drive or executes downloaded software. Leave `--cache-dir` unset so original downloads and resumable partials stay exclusively on the selected drive.

Both builders assemble precomputed search shards for the selected files. Search
covers catalog titles, PDF passages, HTML sections and indexed ZIM articles,
with coverage varying by source. Search combines word matches and compact
Potion retrieval embeddings for passages and article leads. It favors relevant
critical references for emergency wording.
Catalog results appear while passage and
article results load. The search model, indexes and static navigation travel
on the drive.
See the [offline search guide](docs/search.md).

The standalone selector's command uses `--detach` to start a saved background job. Inspect, cancel or resume it with `scripts/build_job.py`; see [unattended builds](docs/unattended-builds.md). For foreground builds, pause with Ctrl-C, wait for the prompt and rerun the command to resume. Keep the drive connected while the job is active.

## Capacity and content

The default recommendation covers capacities from 16 GB. It accounts for
filesystem headroom, free space to retain, readers and discovery files. The
planner protects a core of essential or introductory references in all 15
fields. Each field retains at least half its highest earlier attributed size. In the
base ladder, health, water and sanitation, food preservation, agriculture, shelter and
navigation retain their prior attributed size at every step. English Wikipedia
starts with the top edition at 16 GB and upgrades through mini and nopic to
the illustrated maxi edition. Each upgrade retains or increases attributed
bytes in every field. World maps stay in the default once they enter.
A higher-priority archive that takes at least 10% of the drive label can
displace files in other fields.
Above 1 TB, the recommendation starts with the 1 TB library and adds
removable regional maps, additional Wikipedia languages and other pinned
collections toward 90% of the label, as the catalog and available space permit.
The Python builder checks actual free space.

For a 128 GB drive, use `--capacity-bytes 128000000000` or enter 128 in the
selector. The five common-size profiles use the same ladder. Selected content,
planned storage and the current inventory are in the
[generated capacity table](docs/content-selection.md) and
[content ledger](docs/content-ledger.md).

The direct foundation includes published medical and public-health chapters,
preservation and agriculture manuals, shelter and navigation references, and
practical trades and school textbooks. Additional Wikipedia languages and
detailed topographic sheet packs are optional at 1 TB and below. See the
[topic-by-topic completion plan](docs/full-1tb-coverage-plan.md) for editorial
coverage and [the target architecture](docs/design/target-architecture.md) for
the selection model.

## Customize and validate

Use the selector's priority filter and collection checkboxes, or its topic map to explore assets grouped by theme. Or use stable collection IDs:

```bash
python scripts/build_drive.py --list-resources
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --capacity-bytes 64000000000 --include topo-usgs-northeast --exclude ifixit --plan
python scripts/check_content_policy.py
python scripts/check_selection_policy.py
python scripts/build_capacity_ladder.py --check
python scripts/build_selector.py --check
```

Selecting ZIMs automatically includes their reader packages. Optional additions must fit the chosen capacity. No default requires `--allow-incomplete`; this flag cannot bypass the content policy. The [selector guide](docs/selector.md) explains storage and commands. See [catalog maintenance](docs/catalog.md) before admitting new sources.

## Use the completed SSD

Open `START_HERE.html`. A fresh build puts exactly two items in the chosen outer directory: this entry page and a `LIBRARY` folder containing everything else. Keep them together when moving or copying the library. An emergency directory comes first, followed by the reading shelves and topic atlas. The build report lists unavailable files. It also provides topic links, search, and ordinary static indexes. You can navigate directly through `LIBRARY` with the device’s file manager.

Python builds also write `CONTENT_SELECTION.json` and `LOCKED_CATALOG.yaml` for its rebuild workflow.

The default children's books and Python manuals are PDFs, so reading them does not require an EPUB app. On iPhone or iPad, use Files to open the PDF directly and choose **Preview with Quick Look** if offered. If the start-page preview cannot follow links, use its printed `LIBRARY/...` paths to locate the files manually. Retained EPUBs under `LIBRARY/REFERENCE/SOURCE_PACKAGES/EPUB/` are excluded from the reading shelves and search.

```text
EMERGENCY_LIBRARY/
├── START_HERE.html              # Open this first; static links work without JavaScript
└── LIBRARY/
    ├── SEARCH.html             # Dedicated automatic offline search
    ├── README.txt / VERIFY.py / SOURCE_NOTES.txt
    ├── INVENTORY.html / INVENTORY.json
    ├── BUILD_INFO.json / SHA256SUMS.txt
    ├── CRITICAL/               # Ordinary files grouped by emergency topic
    ├── REFERENCE/
    ├── BOOKS/TEXTBOOKS/         # Core directly readable textbooks
    ├── MAPS/
    ├── ZIM/                    # Large archives; a reader is required
    ├── SOFTWARE/               # Bundled readers for supported platforms
    ├── SEARCH/                 # Small discovery catalog and coverage report
    ├── INDEX/                  # Shelves, phone files, book routes, atlas and build report
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

This checks metadata, source presence and sizes, and republishes search and atlas together. It records that source integrity was not reverified. Use `scripts/verify.py` when a full source audit is needed. See [the discovery workflow](docs/search.md) for precomputing shards and reviewing source locations.

## Search without a server

Open `START_HERE.html` or `LIBRARY/SEARCH.html` in a desktop browser.
Search loads its model and index from files on the drive. PDF results link to
the source page. ZIM results show the archive’s filename and internal path.
Use an archive reader to open those entries. The topic atlas, sections index and
critical phone shelf remain readable with JavaScript off.

Search coverage varies by source. The coverage file in `LIBRARY/SEARCH/` lists
the indexed files. Keep that directory together when copying the drive.
[Search guide](docs/search.md)

Search depends on browser and file-manager capabilities:

| Platform | Ordinary files | JavaScript search | Large ZIM archives |
| --- | --- | --- | --- |
| Windows, macOS, Linux | Compatible standard browser/viewer | Browser must permit local JavaScript and neighboring local script files; test the chosen browser | Use a compatible bundled or already installed reader |
| Android / Pixel | File manager and compatible viewer | Browser launching, storage providers, and external-drive access vary; test the actual device | An appropriate APK may be installable offline if permitted |
| iPhone / iPad | Files and compatible document previews | Files may block both search scripts and links to neighboring files. Read the catalog and printed paths on START_HERE, then open documents directly in Files | Do not assume a reader can be installed from the SSD offline |
| Raspberry Pi | Compatible standard browser/viewer | Depends on the installed browser and available memory | Reader must match the Pi’s processor and operating system |

See [device tests](docs/device-matrix.md) for evidence and checks that still need hardware. START_HERE includes the catalog and drive-relative file paths on the page itself, so reading it does not require following links to another HTML page. If a file preview refuses links, close it and use those paths to open PDFs or text files directly in the file manager. Search controls appear only after discovery data loads successfully. Adapters, USB power, supported filesystem access, existing viewers, and OS permissions still matter. **Test the finished SSD on the exact devices you intend to use before an emergency.**

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
