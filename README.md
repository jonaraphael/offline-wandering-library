# Offline Wandering Library (OWL)

OWL builds a USB SSD containing an offline emergency knowledge library. **The SSD is the product.** This repository contains the catalog, build tools, search engine, small assets, and documentation. Large books, maps, encyclopedias, and reader packages are downloaded during a build and stay out of Git.

The library prioritizes reliable access when there is no internet, account, cloud service, app store, local server, Raspberry Pi, or opportunity to install software. **Core textbooks and illustrated practical guides are part of the smallest profile.** Critical material is stored in ordinary files such as HTML, PDF, and text. Large ZIM archives supplement those files and require a compatible reader.

Python 3.11+ builds the drive on a computer with internet access. Reading the completed drive does not require Python. The builder never formats or repartitions drives, executes downloaded binaries, or indiscriminately removes existing files.

## Build a drive

Use an already formatted USB SSD, preferably exFAT for cross-platform support. Confirm its mount path in your file manager. A nominal 512 GB disk has approximately 477 GiB of total capacity before filesystem overhead; 1 TB is approximately 931 GiB. Leave free space for the filesystem, future changes, and your own files.

```bash
git clone https://github.com/jonaraphael/offline-wandering-library.git
cd offline-wandering-library
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install -e '.[zim]'

# Validate the catalog, then inspect the plan before downloading.
python scripts/validate_catalog.py
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile full-1tb --plan

python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile full-1tb \
    --cache-dir ~/.cache/offline-wandering-library

python scripts/verify.py /path/to/EMERGENCY_LIBRARY
```

Replace `/path/to/EMERGENCY_LIBRARY` with a directory on the SSD. Nothing requires root privileges. A build can take many hours or days depending on the selected archives, connection, SSD, and indexing workload. Use a stable connection, adequate power, and enough temporary space on the build computer. The build reports its storage estimate and checks free space before proceeding. Installed commands `owl-build`, `owl-validate`, and `owl-verify` expose the same tools.

The optional cache stores downloaded assets so that a second drive can be built without fetching them again. It consumes additional disk space. Interrupted HTTP downloads use `.part` files and resume when the source supports byte ranges. Hashes are checked before completed files are accepted. Repeating the command reuses verified content and regenerates the library’s navigation and search artifacts.

The `zim` extra provides full-text extraction from ZIM archives. For the directly readable `critical-64gb` profile, a minimal installation is sufficient:

```bash
python -m pip install -e .
```

Profiles containing ZIM archives require `libzim`; the builder checks for it before downloading. Extraction coverage and warnings are recorded explicitly, including image-only material that has no searchable text. See [search design and limitations](docs/search.md).

## Profiles and content

| Profile | Intended nominal drive | Priority |
| --- | ---: | --- |
| `critical-64gb` | 64 GB or larger | Directly readable emergency material, core textbooks, and illustrated guides |
| `compact-256gb` | 256 GB or larger | The core library, Wikipedia without pictures, and compact archives |
| `standard-512gb` | 512 GB or larger | Full English Wikipedia and broader reference collections |
| `full-1tb` | 1 TB or larger | The most extensive selection, including the Khan Academy archive |

Profile names are capacity targets, not promises to fill the disk. The actual catalog controls what is included, and the plan reports current totals. Profiles reserve free space and budget for search. Resources with unresolved URLs, permissions, or packaging are documented rather than silently treated as available. Review [content sources](docs/sources.md) and the generated inventory before relying on a particular topic or reader.

The initial critical collection includes FEMA CERT material, WHO Basic Emergency Care, EPA water treatment guidance, CDC sanitation information, USDA food-preservation and agriculture references, open electrical textbooks, the FAA maintenance handbook, FEMA shelter material, and USGS navigation references. Critical topics include first aid, medicine, water and sanitation, food, agriculture, repair, electrical work, shelter, navigation, and reference material. Coverage is a curated starting point, not a guarantee that every situation is addressed.

The larger profiles add Wikipedia, WikiMed, Wiktionary, Wikibooks, iFixit, and educational collections. Sources have recorded licensing and attribution. Every critical asset must use an ordinary, directly readable format; a ZIM-only resource cannot satisfy this requirement. The builder validates IDs, destinations, profile membership, and manifest paths.

Textbooks provide sustained explanations beyond short emergency checklists. The core includes seven complete textbooks: two electrical texts plus OpenStax prealgebra, physics, biology, chemistry, and anatomy and physiology. All production profiles currently include thirteen illustrated teaching works, with overlap between these collections. Profile validation requires at least seven critical textbooks and eight critical illustrated works, and the builder downloads the required teaching core before large archives. The 25-file critical collection occupies about 1.57 GB before search and navigation. The OpenStax snapshots use CC BY-NC-SA 4.0; see their recorded notices and attribution in [content sources](docs/sources.md).

The PDFs retain their original diagrams, photographs, charts, and figures; the builder does not replace them with extracted text. `INDEX/textbooks.html` and `INDEX/illustrated-guides.html` provide dedicated, directly readable shelves from the landing page. The illustrated shelf includes both textbooks and practical guides. `INDEX/critical.html` includes every critical asset wherever it is stored, including `BOOKS/TEXTBOOKS/`. Reader-dependent archives and EPUBs do not count toward these direct-reading shelves. Textbook listings retain their attribution, and the inventory records each title’s own license.

Current unresolved additions include Hesperian’s digital redistribution permission and region-specific offline maps. The included USGS world-map reference is not a current local street or topographic map. Choose and verify suitable regional maps before relying on the library for local navigation.

To try the whole pipeline without downloading third-party content:

```bash
python scripts/build_drive.py /tmp/owl-demo \
    --catalog catalog/demo.yaml --profile demo --allow-local
python scripts/verify.py /tmp/owl-demo --strict
```

Use any temporary directory on Windows. The demo contains original test documents,
not emergency instructions. See [catalog maintenance](docs/catalog.md) for adding
sources and reproducing the tested extraction toolchain.

## Use the completed SSD

Open `START_HERE.html`. Its first shelves link to textbooks and illustrated guides with counts of critical resources, followed by topic links. It also provides search and ordinary static indexes. You can navigate directly through the folders with the device’s file manager.

```text
EMERGENCY_LIBRARY/
├── START_HERE.html          # Works without JavaScript
├── SEARCH.html             # Offline search with a local index file picker
├── README.txt / VERIFY.py / SOURCE_NOTES.txt
├── INVENTORY.html / INVENTORY.json
├── BUILD_INFO.json / SHA256SUMS.txt / LOCKED_CATALOG.yaml
├── CRITICAL/               # Ordinary files grouped by emergency topic
├── REFERENCE/
├── BOOKS/TEXTBOOKS/         # Core directly readable textbooks
├── MAPS/
├── ZIM/                    # Large archives; a reader is required
├── SOFTWARE/               # Bundled readers for supported platforms
├── SEARCH/                 # Precomputed full-text index and coverage report
└── INDEX/                  # Textbooks, illustrated guides, critical, category, A–Z
```

The static indexes list catalog files, including titles, categories, textbook/illustrated labels, and archive-reader requirements. Dedicated `textbooks.html` and `illustrated-guides.html` pages sit alongside `critical.html`, `categories.html`, and the alphabetical pages in `INDEX/`. They work without JavaScript and contain ordinary relative links. They do not expand every article inside an archive into separate HTML files.

## Search without a server

Open `SEARCH.html` in a browser that can execute local JavaScript, then use its file picker to select `SEARCH/library.owl`. All search processing stays on the device. The page contains its own interface and code; there are no CDNs, external fonts, network requests, or cloud APIs.

The builder extracts text and metadata once and creates an inverted index. Long documents are divided into passages so results can provide matching context. The browser uses `File.slice()` to read index sections, term postings, and result records as needed. It does not scan the library or load all document text for each query. Results use BM25-style ranking and show title, category/source, a snippet, and the content path.

Choose **All resources**, **Textbooks**, or **Illustrated guides** to search a collection. Filters apply before ranking the final results, so books are not hidden by a larger archive's matches. Illustrated textbooks appear in both learning collections. Results retain each document's license and attribution.

HTML, plain text, Markdown, EPUB, and text-bearing PDFs can be indexed. ZIM text extraction uses the `libzim` extra. Scanned PDFs and image content need OCR that OWL does not provide. Unsupported formats and material with no extractable text retain searchable catalog metadata, with gaps recorded in `SEARCH/coverage.json`, the inventory, and build information. Corrupt or encrypted documents that cannot be extracted fail the build. A search hit in a ZIM names the archive and article; the browser cannot directly open an internal ZIM article. Open the archive with its reader and use the supplied article name.

Search covers extractable textbook and guide text, not the visual meaning of diagrams or photographs. Open the original illustrated document to inspect a figure, formula, or image-only page. An illustration remains readable even when it cannot be found through full-text search.

Search depends on browser and file-manager capabilities:

| Platform | Ordinary files | JavaScript search | Large ZIM archives |
| --- | --- | --- | --- |
| Windows, macOS, Linux | Compatible standard browser/viewer | Designed for modern Chrome, Edge, Firefox, and Safari with local file selection | Use a compatible bundled or already installed reader |
| Android / Pixel | File manager and compatible viewer | Browser launching, storage providers, and external-drive access vary; test the actual device | An appropriate APK may be installable offline if permitted |
| iPhone / iPad | Files and compatible document previews | Files previews commonly do not execute JavaScript; static indexes and direct files are the dependable fallback | Do not assume a reader can be installed from the SSD offline |
| Raspberry Pi | Compatible standard browser/viewer | Depends on the installed browser and available memory | Reader must match the Pi’s processor and operating system |

This is a compatibility design, not a claim of hardware testing on every platform. Some file previews also refuse links between local HTML files. In that case, browse the topic folders and open PDFs or text files directly. Adapters, USB power, supported filesystem access, existing viewers, and OS permissions still matter. **Test the finished SSD on the exact devices you intend to use before an emergency.**

## Bundled readers

Reader packages are ordinary catalog assets under `SOFTWARE/`, with source, version, hash, and license information recorded alongside the content. They are downloaded and verified, never executed during a build. The initial catalog includes Kiwix Windows portable 2.5.1, Linux x86-64 AppImage 2.5.1, macOS 3.14.0, and Android 3.14.0. The generated inventory identifies what the selected profile includes. No Raspberry Pi ARM reader package is currently verified in the catalog.

A package’s presence does not guarantee it will run: CPU architecture, operating-system version, dependencies, signature checks, installation permissions, and Android’s install-from-files setting may matter. Offline installation of an arbitrary iPhone application from a USB SSD is not a dependable option. Critical files exist outside archives to preserve access on those devices.

## Integrity, updates, and backups

`SHA256SUMS.txt` records managed files using SHA-256. `INVENTORY.json` records the assets, source metadata, hashes, and verification provenance; `BUILD_INFO.json` records the build configuration and search results. The independent verifier uses the Python standard library and can run without installing OWL:

```bash
python scripts/verify.py /path/to/EMERGENCY_LIBRARY

# A copy also travels with the drive:
python /path/to/EMERGENCY_LIBRARY/VERIFY.py /path/to/EMERGENCY_LIBRARY
```

It reports `OK` for matching files, `MISSING` for absent expected files, `FAILED` for mismatches or unsafe entries, and `UNKNOWN` for files outside the checksum manifest. Unknown personal files are not deleted. Checking a large drive reads its content and can take hours. A stored checksum detects accidental changes, but it is not a digital signature: retain a trusted independent copy of the checksum manifest to detect changes to both files and checksums.

A pinned source hash verifies against the catalog’s expected bytes. When an upstream source supplies no trusted SHA-256, OWL records an observed hash after download; that is a baseline for future integrity checks, not independent authentication of the original download. The generated `LOCKED_CATALOG.yaml` captures measured hashes for repeat builds. Exact reproduction requires those bytes to remain available at the source or in your cache; timestamps and build metadata can differ.

To update, review catalog changes, inspect the new plan, rebuild with the intended profile, and verify again. Existing managed content may be replaced to match the selected catalog. Unrelated files are preserved. Keep the last verified drive intact until its replacement has passed verification and device checks. OWL does not prune obsolete files automatically. An update is not atomic across the entire SSD: after a failed build, rerun it and verify before considering the drive complete.

**Build two identical SSDs, verify both, and store the backup separately.** Keep the catalog and checksum manifests with your backup records. Periodically read and verify both drives, safely eject them, and replace unreliable media. Carry required adapters and power accessories with each drive. See [operating guide](docs/usage.md) for a practical checklist.

## Develop and test

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests use small local fixtures, simulated HTTP responses, and loopback HTTP servers, not real encyclopedia downloads. They cover catalog and path validation, capacity planning, checksums, interrupted transfers, repeat builds, search generation, and static navigation. Install `.[zim]` to include ZIM extraction tests. See [search design](docs/search.md) and [content sources](docs/sources.md) when extending the catalog or extraction pipeline.

Node.js 20+ runs the actual search JavaScript in automated tests; those tests are
explicitly skipped if Node is unavailable. Node is not a build or drive runtime
dependency. CI exercises Python 3.11 and 3.13 on Windows, macOS and Linux, with a
separate Linux job testing ZIM extraction. Hardware and full-corpus performance
remain distinct from these automated checks.

The repository’s code license is in [LICENSE](LICENSE). Downloaded content and bundled reader software retain their own licenses and attribution requirements, recorded in the catalog and inventory. Adding a source does not grant redistribution rights to unrelated material.
