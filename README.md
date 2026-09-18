# Offline Wandering Library (OWL)

OWL builds a USB SSD containing an offline emergency knowledge library. **The SSD is the product.** This repository contains the catalog, build tools, search engine, small assets, and documentation. Large books, maps, encyclopedias, and reader packages are downloaded during a build and stay out of Git.

The library prioritizes reliable access when there is no internet, account, cloud service, app store, local server, Raspberry Pi, or opportunity to install software. **Core textbooks and illustrated practical guides are part of the smallest profile.** Critical material is stored in ordinary files such as HTML, PDF, and text. Large ZIM archives supplement those files and require a compatible reader.

Python 3.11+ builds the drive on a computer with internet access. Reading the completed drive does not require Python. The builder never formats or repartitions drives, executes downloaded binaries, or indiscriminately removes existing files.

## Build a drive

Open [SELECT.html](SELECT.html) in a browser to choose a 16 GB, 64 GB, 256 GB, 512 GB, or 1 TB preset, adjust resource inclusion, inspect live storage totals, and copy a POSIX-shell or PowerShell build command. The selector runs offline without installation; executing its command requires Python and OWL, plus internet for new downloads. See the [selector guide](docs/selector.md) for exact-file presets, unavailable edition choices, and capacity limits.

Use an already formatted USB SSD, preferably exFAT for cross-platform support. Confirm its mount path in your file manager. A nominal 512 GB disk has approximately 477 GiB of total capacity before filesystem overhead; 1 TB is approximately 931 GiB. Leave free space for the filesystem, future changes, and your own files.

```bash
git clone https://github.com/jonaraphael/offline-wandering-library.git
cd offline-wandering-library
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install -e '.[zim]'

# Validate the catalog and inspect resource choices before downloading.
python scripts/validate_catalog.py
python scripts/build_drive.py --list-resources
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile full-1tb --plan

# The existing directly readable collection has verified download assets.
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile critical-64gb

python scripts/verify.py /path/to/EMERGENCY_LIBRARY
```

Replace `/path/to/EMERGENCY_LIBRARY` with a directory on the SSD. Nothing requires root privileges. A build can take many hours or days depending on the selected archives, connection, SSD, and indexing workload. The default builds **in place on the SSD**: downloads, partial files, and persistent search checkpoints stay there. No full library copy or large indexing scratch directory on the computer is required. The SSD needs room for content, the finished index, temporary indexing work, and the profile reserve; the plan checks these allocations together. Installed commands `owl-build`, `owl-validate`, and `owl-verify` expose the same tools.

The larger profiles now describe the planned 46-resource library. The source-resolution pass has pinned medical collections, all 20 requested OpenStax core titles, LibreTexts, map archives, and other references. Remaining gaps are enumerated in [content selection](docs/content-selection.md); they include curated subsets, local topography, and reviewed direct editions. A normal build refuses an incomplete selection. Inspect `--plan`, adjust the include/exclude choices, or explicitly choose a partial build with `--allow-incomplete`; the larger profile names do not mean those collections have already been acquired.

**Pause with Ctrl-C, wait for the terminal prompt, then rerun the same command to continue.** Verified files are reused; HTTP downloads resume where the source supports byte ranges; interrupted local transfers validate their saved prefix before continuing. Search extraction resumes from durable checkpoints, and an unchanged completed index is reused after verification. Network failures receive bounded retries, then exit with work retained for the next run. See [pause and resume](docs/usage.md#pause-and-resume) for exact checkpoint boundaries and laptop/drive handling.

`--cache-dir` is optional and stores another copy of downloaded assets. `--work-dir` optionally relocates persistent indexing scratch. Omit both for an entirely in-place build; they are not prerequisites for large libraries. A second SSD can be copied directly from a completed first SSD with `python scripts/copy_drive.py SOURCE TARGET`, with verified reuse and resumable transfers, without internal-disk staging or rerunning search extraction.

The `zim` extra provides full-text extraction from ZIM archives. Every production preset now includes useful archives and bundled readers, so install with `python -m pip install -e '.[zim]'`. The build computer needs these dependencies; the finished drive's ordinary PDFs and HTML do not.

Profiles containing ZIM archives require `libzim`; the builder checks for it before downloading. Extraction coverage and warnings are recorded explicitly, including image-only material that has no searchable text. See [search design and limitations](docs/search.md).

## Profiles and content

| Profile | Intended nominal drive | Planned content target | Default emphasis |
| --- | ---: | ---: | --- |
| `flash-16gb` | 16 GB or larger | 9.70 GB pinned sources | 360 PDFs, medical chapters, complete textbooks, repair and appropriate-technology archives |
| `critical-64gb` | 64 GB or larger | 40.27 GB pinned sources | Everything in 16 GB, plus WikiMed, LibreTexts, Wikibooks, Wiktionary and education/reference archives |
| `compact-256gb` | 256 GB or larger | 190–210 GB | Survival, reading, repair, full English Wikipedia, and a 10 GB topographic-map allocation |
| `standard-512gb` | 512 GB or larger | 390–420 GB | Rebuilding and education, OpenStax, North American and topographic maps |
| `full-1tb` | 1 TB or larger | 750–820 GB | Broader references, world maps, Spanish Wikipedia, STEM education, and 60 GB of planned direct-reading copies |

These are decimal content targets, separate from index, reader, and free-space budgets. `catalog/resources.yaml` records the 46 numbered resources plus three support collections: `owl-direct-core`, `archive-readers`, and `direct-reading-expansion`. `catalog/library.yaml` records actual asset URLs, versions, sizes, hashes, and licenses. A resource's target size is an editorial allocation, not evidence that the corresponding data is available. The plan distinguishes planned targets from exact known asset bytes and reports incomplete resources. Review [content sources](docs/sources.md) and the generated inventory before relying on a particular topic or reader.

The `flash-16gb` preset selects **436 pinned files totaling 9,696,060,616 bytes**, over six times the former selection. Its 2 GB published-search budget, 4.5 GB indexing workspace, 16 MiB metadata allowance and 1.5 GB free-space reserve bring the planned in-place peak to **15,712,837,832 bytes**. A verified raw-index checkpoint releases extraction files before browser packaging, so those phases share working space. The 64 GB preset selects **450 files totaling 40,272,521,791 bytes**, with 4 GB search, 12 GB scratch and 6 GB reserve: **58,289,299,007 bytes** at the planning peak. These exact small presets contain only resolved files; individual broader collection scopes can still be partial. Optional caches and retained old generations need additional space. Nothing is padded merely to fill a drive.

All sizes now keep the same **427 ordinary-format documents (3.45 GB)**: 360 PDFs, 61 children's EPUBs, programming manuals and two self-contained circuit simulations. They include 23 directly readable textbooks and 50 illustrated teaching works. Medical chapters cover community health, dentistry, midwifery, women's health and disability support, alongside MSF, WHO, WASH and food/agriculture references. EPUBs need device support; publisher simulations may attempt optional network requests. The original PDF diagrams and photographs remain intact.

The 16 GB archive complement is WikEM, iFixit, Appropedia, CD3WD and Low-tech Magazine. Windows, Linux, macOS and Android readers are included. These archives broaden coverage without making any critical document depend on them. An iPhone without a compatible installed reader still has the entire ordinary-format foundation.

All three larger defaults select full English Wikipedia. Compact allocates 10 GB to topographic maps without the North America OSM package; standard selects North American plus topographic maps; full replaces the North America package with world maps. Spanish Wikipedia is a full-profile default; other additional languages require explicit inclusion. The science Stack Exchange collection is a full-profile default and an opt-in for standard. Noncore Khan material is never selected by default.

The full profile allocates an additional **60 GB to directly readable HTML, PDFs, and images** through `direct-reading-expansion`. This plans ordinary-format editions or exports from selected Appropedia, CD3WD, iFixit, LibreTexts, and Wikibooks content, plus an expanded small direct-reading Wikipedia subset. The preferences apply to selected resources. These copies would retain useful diagrams and images and could be opened without a ZIM reader. A [resumable in-place exporter](docs/direct-export.md) now converts explicitly selected ZIM articles and their supported local images/styles into ordinary files. The expansion remains unresolved until curated article/book lists and visually reviewed output editions are supplied; the allocation does not trigger automatic expansion of Wikipedia. Exclude the optional allocation with `--exclude direct-reading-expansion` if desired.

**The content targets do not prove that a full Wikipedia search index fits.** Index and scratch-space budgets are estimates, and full-corpus size and performance have not been established. Full-text indexing can produce more bytes than the compressed archive. The builder checks available space and actual final capacity; a drive that exceeds the budget cannot be declared complete merely because its content target looked suitable. The plan also reports peak in-place storage, including scratch. All five default plans now fit their nominal capacities including explicit scratch and reserve allowances. Full-corpus search measurements are still outstanding for the larger presets; indexing pauses with its checkpoints if its allowance is exceeded. SQLite work is monitored at checkpoints, rather than constrained by a filesystem quota. The tool never silently moves scratch onto the computer.

The initial critical collection includes FEMA CERT material, WHO Basic Emergency Care, EPA water treatment guidance, CDC sanitation information, USDA food-preservation and agriculture references, open electrical textbooks, the FAA maintenance handbook, FEMA shelter material, and USGS navigation references. Critical topics include first aid, medicine, water and sanitation, food, agriculture, repair, electrical work, shelter, navigation, and reference material. Coverage is a curated starting point, not a guarantee that every situation is addressed.

The larger profiles add Wikipedia, WikiMed, Wiktionary, Wikibooks, iFixit, and educational collections. Sources have recorded licensing and attribution. Every critical asset must use an ordinary, directly readable format; a ZIM-only resource cannot satisfy this requirement. The builder validates IDs, destinations, profile membership, and manifest paths.

Textbooks provide sustained explanations beyond short emergency checklists. All five production presets include the complete 20-title OpenStax math/science selection and two electrical textbooks, plus Pro Git. The required direct-reading floor protects 22 critical textbooks and 40 illustrated teaching works in the small presets. Most inspected current OpenStax PDFs use CC BY-NC-SA 4.0; Physics uses CC BY 4.0. See each recorded notice and attribution in [education evidence](docs/acquisition-education.md).

The PDFs retain their original diagrams, photographs, charts, and figures; the builder does not replace them with extracted text. `INDEX/textbooks.html` and `INDEX/illustrated-guides.html` provide dedicated, directly readable shelves from the landing page. The illustrated shelf includes both textbooks and practical guides. `INDEX/critical.html` includes every critical asset wherever it is stored, including `BOOKS/TEXTBOOKS/`. Reader-dependent archives and EPUBs do not count toward these direct-reading shelves. Textbook listings retain their attribution, and the inventory records each title’s own license.

Project Gutenberg and Children's Library have prominent landing-page entries and dedicated static shelves. The larger presets now select 36.04 GB of pinned English Gutenberg science, technology, agriculture and education archives. These are historical books, not current clinical advice; the curated direct-file Gutenberg edition remains unresolved. Their children's compact edition adds a 19.77 GB Gutenberg juvenile-literature archive to 61 Book Dash EPUBs. The small presets keep the EPUBs. Archives need Kiwix and EPUBs need EPUB support; the proposed ordinary-PDF children's collection is still incomplete. Hesperian now has 270 official chapter PDFs; its remaining gap is one unavailable midwives back-matter file. Map archives are pinned, while local topographic coverage still needs a region. General geographic reference material does not replace local navigation maps.

The [content-density policy](docs/content-density.md) records the actual selections, planning peaks, source gaps and minimum-content safeguards.

## Choose resources and partial builds

In [SELECT.html](SELECT.html), small-preset rows labeled **Preset files only** keep the exact existing files. Choosing **Published collection** explicitly adds the broader resource scope through `--include`; the small presets already contain all 20 pinned OpenStax titles, while some other resources have broader unresolved scope. Inclusion controls produce the same `--include` and `--exclude` flags shown below. The selector's atlas checkbox defaults on, and accepting incomplete content is a separate unchecked option.

Direct-readable or compact editions can be chosen only when registered asset alternatives exist. Verified compact editions are registered for Gutenberg, children, practical Stack Exchange and science Stack Exchange. Larger presets select these explicitly through `default_editions`; an explicit `--edition RESOURCE=published` overrides that choice. The selector does not compress content, convert archives, or invent storage savings. Its totals separate intended collection estimates, verified file bytes, search, temporary work, and reserve; the CLI checks the actual filesystem. Regenerate the page with `python scripts/build_selector.py`, or check freshness with `python scripts/build_selector.py --check`.

List stable resource IDs without supplying a drive path:

```bash
python scripts/build_drive.py --list-resources
```

Use `--include` and `--exclude` to customize a profile. Flags accept repeated occurrences or comma-separated IDs; the registry's numbered entries can also be selected by number:

```bash
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile full-1tb \
    --include wikipedia-fr \
    --exclude wikipedia-es,ted-ed \
    --plan
```

The verified source totals are **195.14 GB (256 GB preset), 261.61 GB (512 GB preset), and 393.59 GB (1 TB preset)**. The first now reaches its requested content range. The last two still need Survivor, durable Stack Overflow, Khan and other unresolved acquisitions to reach their 390–420 GB and 750–820 GB goals. Those absent bytes are shown as missing, never counted as content already acquired. Practical Stack Exchange now provides twelve complete site archives; the full preset adds mathematics, physics, biology and chemistry. These retain published answers and context without claiming question-level filtering.

Selecting resolved ZIM assets automatically adds `archive-readers`. Excluding that dependency while ZIM assets remain selected produces an error. Review the plan after every customization, including changes to map packages and languages.

To deliberately build only the verified assets available from an incomplete target selection:

```bash
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile compact-256gb --allow-incomplete
```

`--allow-incomplete` records `content_complete: false` in the build information and inventory when selected collections are missing or partial. `START_HERE.html` displays that status, and the inventory explains each resource's coverage. Files that are actually included must still download successfully and pass their integrity checks. Successful verification of those files does not turn a partial content selection into the complete planned library.

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

Open `START_HERE.html`. Its first shelves link to textbooks, illustrated guides, Project Gutenberg, and Children's Library, with counts of available files. It also provides topic links, search, and ordinary static indexes. You can navigate directly through the folders with the device’s file manager.

```text
EMERGENCY_LIBRARY/
├── START_HERE.html          # Works without JavaScript
├── SEARCH.html             # Automatic offline search, also on START_HERE.html
├── README.txt / VERIFY.py / SOURCE_NOTES.txt
├── INVENTORY.html / INVENTORY.json
├── BUILD_INFO.json / CONTENT_SELECTION.json / SHA256SUMS.txt / LOCKED_CATALOG.yaml
├── CRITICAL/               # Ordinary files grouped by emergency topic
├── REFERENCE/
├── BOOKS/TEXTBOOKS/         # Core directly readable textbooks
├── MAPS/
├── ZIM/                    # Large archives; a reader is required
├── SOFTWARE/               # Bundled readers for supported platforms
├── SEARCH/                 # Precomputed full-text index and coverage report
└── INDEX/                  # Learning/reading shelves, critical, category, A–Z
```

The static indexes list catalog files, including titles, categories, textbook/illustrated labels, and archive-reader requirements. Dedicated `textbooks.html`, `illustrated-guides.html`, `gutenberg.html`, and `children.html` pages sit alongside `critical.html`, `categories.html`, and the alphabetical pages in `INDEX/`. They work without JavaScript and contain ordinary relative links. They do not expand every article inside an archive into separate HTML files.

The optional [topic atlas](docs/topic-atlas.md) adds shared subject, practical-task, and learning routes, topic aliases, and book contents pages. Generate it after downloading a library:

```bash
python scripts/build_atlas.py /path/to/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation
python scripts/verify.py /path/to/EMERGENCY_LIBRARY
```

This uses the existing inventory, verifies source integrity, and publishes static pages without downloading content or rebuilding search. To generate the atlas during a full build, add the navigation directory:

```bash
python scripts/build_drive.py /path/to/EMERGENCY_LIBRARY \
    --profile critical-64gb --navigation-dir catalog/navigation
```

Repeat `--navigation-dir` on subsequent full builds that should generate the atlas. The starter metadata contains 46 topics and 40 whole-document assignments. These are initial browsing routes; the final source include list and deeper chapter, page, and figure curation remain open. Missing sources are omitted from available routes. The implemented importer can propose PDF-outline or existing HTML-heading locations for review, and selected section maps must match the exact source bytes. See the [atlas guide](docs/topic-atlas.md) for importing contents, reviewing maps, and checking coverage, and the [design specification](docs/topic-atlas-spec.md) for editorial goals.

## Search without a server

Open `START_HERE.html` and enter words in **Search this library**. Search loads automatically from neighboring files on the SSD; there is no index file to select. `SEARCH.html` provides the same interface on a dedicated page. All processing stays on the device, without a server, account, CDN, or network connection.

The builder extracts text and metadata once and creates an inverted index. Long documents become passages so results can provide matching context. The browser loads a small local manifest and requests index chunks as needed through ordinary local scripts. It keeps at most eight decoded 1 MiB chunks in its transport cache, instead of scanning the library at query time. Results use BM25-style ranking and show title, category/source, a snippet, and the content path.

The finished search files are `SEARCH/search.js`, `SEARCH/manifest.js`, and `SEARCH/chunks/<index-hash>/`. Base64 encoding adds roughly one third to the binary index size; profile search budgets cover the published output. There is no separate binary index to select on a fresh build. Keep both entry pages and the entire `SEARCH/` directory together. Very large archive indexes and common-word searches still need performance testing at their intended scale.

Choose **All resources**, **Textbooks**, or **Illustrated guides** to search a collection. Filters apply before ranking the final results, so books are not hidden by a larger archive's matches. Illustrated textbooks appear in both learning collections. Results retain each document's license and attribution.

HTML, plain text, Markdown, EPUB, and text-bearing PDFs can be indexed. ZIM text extraction uses the `libzim` extra. Scanned PDFs and image content need OCR that OWL does not provide. Unsupported formats and material with no extractable text retain searchable catalog metadata, with gaps recorded in `SEARCH/coverage.json`, the inventory, and build information. Corrupt or encrypted documents that cannot be extracted fail the build. A search hit in a ZIM names the archive and article; the browser cannot directly open an internal ZIM article. Open the archive with its reader and use the supplied article name.

Search covers extractable textbook and guide text, not the visual meaning of diagrams or photographs. Open the original illustrated document to inspect a figure, formula, or image-only page. An illustration remains readable even when it cannot be found through full-text search.

Search depends on browser and file-manager capabilities:

| Platform | Ordinary files | JavaScript search | Large ZIM archives |
| --- | --- | --- | --- |
| Windows, macOS, Linux | Compatible standard browser/viewer | Browser must permit local JavaScript and neighboring local script files; test the chosen browser | Use a compatible bundled or already installed reader |
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
