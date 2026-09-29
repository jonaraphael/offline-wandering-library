# Choose a library with the offline selector

Build commands include `--detach`: Python starts a saved background job, then
returns its job directory for status, cancellation, or resume. Planning commands
remain read-only foreground checks. See [unattended builds](unattended-builds.md).

Open [`SELECT.html`](../SELECT.html) from the repository in a browser. The page
contains its catalog snapshot, controls, and calculations. It needs JavaScript,
but no installation, server, account, or network connection. It does not download
content or write to the chosen drive; it produces commands for the Python builder.

## Choose a preset and inspect the selection

Choose the 16 GB, 64 GB, 256 GB, 512 GB, or 1 TB preset; the page initially selects
16 GB. Each starts with its configured selection. Change the inclusion checkboxes to add or remove resource
groups. Totals and warnings update immediately. In **Take this plan to your terminal**,
enter the destination directory on the drive, choose POSIX shell or PowerShell,
and review the partial-library option before copying a command.

All five presets select actual finished files. Defaults include CRITICAL survival material and USEFUL trades, repair, appropriate technology and school education. NONESSENTIAL fiction, college textbooks, computing and enrichment are opt-in. Additional Wikipedia languages are also opt-in. Filter collections by priority or search their topics, then change individual checkboxes.

Each collection displays its priority, formats, exact bytes and scope limitations. All active choices pass the content-type policy. School books and practical hand-tool manuals are separate from college textbooks. The 512 GB and 1 TB defaults currently contain the same practical corpus; capacity labels do not promise a full drive.

Required reader packages are added when selected ZIM archives need them. PDF documents remain ordinary files. Python's optional PDF ZIP is unpacked unchanged. No active choice invokes document conversion.

## Discovery comes with the library

Search and atlas use the selected catalog metadata and approved navigation maps.
There is no index-cache path, indexing workspace, or atlas switch to configure.
Downloads and partials stay on the selected drive. Custom catalogs without
navigation metadata still receive title/description search and static file lists.

## Storage editions describe actual catalog entries

**Published collection** uses the resource's existing formats and scope, which can
be ordinary files, archives, or a mixture. **Direct-readable edition** and
**Compact archive edition** require separately registered entries in the resource's
optional `editions` mapping, with exact asset references and explicit size and
availability information.

The selector enables an alternate edition only when its actual pinned files are
registered. Unsupported choices stay disabled. It does not compress PDFs,
decompress ZIMs, invent exports, or assume a percentage saving. No active collection requests generated exports or conversion. Critical directly readable files
remain available when a registered compact edition is selected.

A profile can default to a verified compact edition while preserving the ordinary
document foundation. The selector displays that choice. Keeping a profile's
default emits no redundant edition flag; changing it produces
`--edition RESOURCE=direct`, `--edition RESOURCE=compact`, or
`--edition RESOURCE=published`. The CLI rejects an edition that is not registered;
changing the command text cannot create it.

## Read the totals before copying a command

All capacities and GB totals use decimal units. The selector distinguishes:

- **Downloadable knowledge:** exact cataloged sizes of selected resolved knowledge
  files, excluding reader/software packages. Each unique asset is counted once,
  even when several collections include it. This is not a claim that the files
  already exist on the drive; the builder verifies downloaded bytes.
- **Directly readable knowledge:** the portion available in ordinary formats
  without a specialized reader. The summary also shows direct file, textbook,
  illustrated book/guide, and category counts. Archive contents are not counted
  as thousands of separate directly readable files.
- **Reader / software files, exact:** separately counted downloadable packages.
  These and knowledge files make up **All downloadable files, exact**.
- **Knowledge allocation, planned:** matches the finished files in current collections. There is no unmet content allowance in default selections.
- **Additional reader allowance:** reader budget beyond already pinned software.
- **Discovery and metadata allowances:** 16 MiB for search output and 16 MiB for other metadata.
- **Free-space reserve:** space deliberately left outside the build allocations.

The green meter measures exact downloadable files as a fraction of nominal drive
capacity; gray marks reserved free space. Search and temporary work are listed
separately and are not presented as knowledge. A prominent content-gap warning
appears when less than 80% of a planned knowledge allocation is pinned and the gap
is at least 250 MB. An unchanged preset below its configured minimum knowledge
size also warns and requires explicit partial-library acceptance before building.
The minimum excludes software, search, temporary files, and reserved space.

The in-place peak is calculated in bytes:

```text
build-input work = temporary recipe downloads + expanded recipe inputs
in-place peak = content and reader files + metadata + reserve
               + acquisition workspace + max(discovery allowance, build-input work)
```

Acquisition workspace includes selected recipes' explicit allowances, retained
staged outputs and receipts. The current production catalog needs no document
conversion. Discovery is a small metadata compilation, with no extraction scratch.
The builder checks its actual output against the allowance before publishing.
The browser cannot inspect real drive space, partial downloads, or retained old
versions; the CLI checks those on the target filesystem.

## Copy and run the command

Install Python 3.11+ and OWL on the build computer, then run copied commands from
the repository root with its environment active. Use
`python -m pip install -e .`. Archive export and other optional editorial tools
retain their own extras. New source downloads require internet access even
though the selector itself works offline.

Use **Copy plan command** first. It ends in `--plan` and creates no library files.
Review its actual target and capacity checks. Then use **Copy build command** when
the selection is ready. If the browser refuses clipboard access to a local page,
the tool selects the displayed command for manual copying through the device's
Copy action, Ctrl+C, or Command+C.

The selector quotes the destination path for the
chosen shell, including spaces and apostrophes. PowerShell quoting is not Windows
Command Prompt syntax. Enter paths in the selector instead of adding shell quotes
yourself, and copy into the matching shell. Blank paths and control characters are
rejected. The generated command is displayed for inspection and is never executed
by the page.

The bundled topic atlas is included automatically and does not select extra
content. See the [atlas guide](topic-atlas.md).

**Build only currently verified files (partial library)** starts unchecked. Enable it only when deliberately
building the currently verified subset of an incomplete collection. It adds
`--allow-incomplete`; the completed files remain subject to integrity checks, and
the library records its incomplete content scope. It does not resolve permissions,
create missing files, waive capacity checks, or claim a full collection. Errors
or unaccepted incomplete selections prevent a usable build command.

Changing or resetting the preset restores its resource choices and turns off
partial-library acceptance. The destination and shell stay unchanged; review the
regenerated commands.

After the build, run `python scripts/verify.py /path/to/EMERGENCY_LIBRARY`, test
the intended devices, and make a separately stored verified backup.

## Refresh the embedded recipe

The checked-in selector is generated from the catalog, registry, profiles, and
templates. After changing those inputs, regenerate it from the repository:

```bash
python scripts/build_selector.py
```

Check that the existing file matches current inputs without rewriting it:

```bash
python scripts/build_selector.py --check
```

These maintenance commands require the installed Python project. Opening the
already generated page does not. A stale page can show outdated choices, so keep
`SELECT.html` with the matching repository revision and review the CLI plan.

## Topic map

The topic map and collection list appear together. Each dot represents one asset. Click a major theme circle to zoom into labeled subtopic circles, then click a subtopic to highlight it and filter the list. The circles keep their positions; click the same subtopic again to clear its filter. Use the breadcrumb buttons to return to the theme or all topics. The collection list remains below the map and follows the same topic scope. Related school and college subjects stay together even when their utility levels differ. Colors indicate CRITICAL, USEFUL and NONESSENTIAL; filled dots are selected and hollow dots are optional. Major themes come from catalog tags and `src/owl/topic_verticals.json`. Subtopics use the first declared route in the validated `catalog/navigation/assignments/` pseudoindex, falling back to the asset’s catalog domain. All assigned topic titles and aliases are searchable. The selector embeds this metadata during regeneration; it does not open, download or analyze document text. One ZIM dot can contain thousands of articles.

The same search, priority and selected-only filters work in both views. Click a dot for its title, priority, topics, size and file toggle. Search, priority and topic filters share one matching-file set across the map, list and bulk controls. Filtered collection checkboxes affect only matching files and show a mixed state when some are selected. Individual file checkboxes allow finer choices. Use All topics in the breadcrumbs to leave a topic, and reset the search, priority or selected-only fields to remove those filters. Keyboard users can focus a dot, move with arrow keys and press Enter to inspect it.

“Include all shown” and “Exclude all shown” apply to a snapshot of the currently matching files, respecting topic, search, priority and selected-only filters. With no filters they apply to all files. Files outside the filters stay unchanged, including other files within a matching collection. Required archive readers and ZIP source packages remain selected. Empty results disable both buttons.

The generated command uses `--resource-assets RESOURCE=ASSET,ASSET` for collections with a custom file subset. This repeatable flag selects only the named members of an already selected collection; unknown, duplicate, or out-of-collection IDs are rejected. Intentional subsets use the selected files’ exact size and are recorded in the selection lock. For an optional collection, `--include RESOURCE` accompanies the subset. Omit the subset flag to use its regular edition. Neither collection exclusion nor file exclusion deletes previously downloaded files from an existing drive.

The content-size bar chart follows the same matching-file set and counts only
selected assets, once each. At the overview it compares major themes; inside a
theme it compares subtopics. Selecting a subtopic leaves one bar whose faint
segments show its individual files. Click a segment to inspect the file and its
include/exclude control. The expandable file list reaches segments too small to
click. Topic labels navigate using the same breadcrumbs and list filters.

Bar lengths use uncompressed content sizes. A cataloged `uncompressed_size_bytes`
value takes precedence. Without one, the selector uses explicit rough planning
assumptions: 3× stored bytes for ZIMs; 2× for ZIP, AppImage, DMG and APK packages.
These factors are heuristics, not measured compression ratios; media-heavy and
text-heavy archives may differ substantially. An ≈ marks any estimated value,
and “How sizes are estimated” explains the method. Ordinary files and extracted
PDFs use their original file sizes without decoding their internal compression.
Missing sizes remain unknown. The chart also reports actual stored bytes;
capacity checks and build commands continue to use the existing exact file sizes.
Reader packages and retained source ZIPs count separately from extracted members;
these totals measure selected files, not deduplicated intellectual content.
