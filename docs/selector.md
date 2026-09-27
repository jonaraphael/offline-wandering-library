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
groups. Totals and warnings update immediately. Enter the destination directory
on the drive and choose the shell you will use: POSIX shell or PowerShell.

The 16 GB and 64 GB presets select fixed sets of pinned files: ordinary emergency,
medical, public-health, repair, and reference documents; complete illustrated
textbooks; useful smaller ZIM archives; and bundled readers. The 64 GB selection
adds larger medical, engineering, educational, dictionary, and travel references.
OpenStax supplies 36 complete PDFs across eight subject families in 16 GB and
all 73 current English PDF titles in 64 GB and larger profiles.
The live summary reports their exact cataloged sizes and document counts.
Larger presets also describe intended collection scope that can remain incomplete
or unresolved. A capacity label alone never means that much knowledge is available.

For a fixed preset, a selected row can say **Preset files only**. This
keeps only the resource's exact files in that preset. For example, the current WHO
manual does not fulfill the broader WHO collection plan. The 16 GB preset's
36 OpenStax books are a subset of the complete 73-title published collection.
Leaving those rows selected does not expand them. Choosing
**Published collection** explicitly selects the full intended collection and adds
the corresponding `--include` argument; its larger estimate and unresolved scope
then apply. Selecting all 73 OpenStax PDFs exceeds the 16 GB budget; the 64 GB
preset already includes them. Unchecking a preset resource removes its mapped files through
`--exclude`.

Resource choices use the stable IDs in `catalog/resources.yaml`. Required readers
are added when selected resolved ZIM archives need them. A reader package does
not make an archive directly readable in a standard file viewer.

## Choose where generated index files are stored

The selector defaults to a shared index cache at `.owl/index-cache` and a search
workspace at `.owl/index-work`. Both paths are relative to the repository root
where you run the commands; edit either path to use another location. The cache
holds only generated, independent per-asset index artifacts that can be reused
across builds. The workspace holds generated scratch files and resumable search
checkpoints. Source files, downloads, and partial downloads stay on the selected
destination drive.

Both generated commands include `--index-cache-dir`,
`--index-cache-budget-bytes`, and `--work-dir`. They never add `--cache-dir`, which
would create a separate source-download cache. The editable index cache budget
must be a positive whole number of bytes. It defaults to the selected profile's
search allowance: **2,000,000,000 bytes for the 16 GB preset**. This is an
additional allowance for retained generated artifacts, separate from the
profile's final search output and temporary-work allowances. Retained versions from earlier recipes also count toward this budget; increase the editable allowance when preserving multiple versions. The PDF migration on the existing OWL drive uses a 4,000,000,000-byte repo cache allowance to retain both old and updated indexes without changing the 16 GB drive profile.

## Storage editions describe actual catalog entries

**Published collection** uses the resource's existing formats and scope, which can
be ordinary files, archives, or a mixture. **Direct-readable edition** and
**Compact archive edition** require separately registered entries in the resource's
optional `editions` mapping, with exact asset references and explicit size and
availability information.

The selector enables an alternate edition only when its actual pinned files are
registered. Unsupported choices stay disabled. It does not compress PDFs,
decompress ZIMs, invent exports, or assume a percentage saving. The
`direct-reading-expansion` collection is a separate content allowance, not an
automatic conversion button; selected derivative files require the separate
[direct-export workflow](direct-export.md). Critical directly readable files
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
- **Knowledge allocation, planned:** includes budget for missing collection scope.
  **Unmet knowledge budget** is its difference from pinned knowledge bytes; it is
  neither downloadable content nor an exact prediction of the missing files' size.
- **Additional reader allowance:** reader budget beyond already pinned software.
- **Search and metadata allowances:** planned index space and 16 MiB for metadata.
- **Search work allowance, all locations:** the profile's explicit scratch budget, or twice its
  search budget when not specified. It covers the extraction database and records
  plus a temporary binary index. The workspace path controls where extraction
  files are stored; the temporary binary index remains on the destination drive.
- **Workspace extraction allowance:** the part of that scratch budget used at
  the chosen workspace directory, excluding the drive's temporary binary index.
- **Retained index cache, additional:** the editable allowance for generated
  indexes kept across builds; it is excluded from the in-place reference peak.
- **Free-space reserve:** space deliberately left outside the build allocations.

The green meter measures exact downloadable files as a fraction of nominal drive
capacity; gray marks reserved free space. Search and temporary work are listed
separately and are not presented as knowledge. A prominent content-gap warning
appears when less than 80% of a planned knowledge allocation is pinned and the gap
is at least 250 MB. An unchanged preset below its configured minimum knowledge
size also warns and requires explicit partial-library acceptance before building.
The minimum excludes software, search, temporary files, and reserved space.

The displayed in-place peak is a reference calculation with search work on the
destination drive; it excludes the separate retained index cache allowance. The
default commands instead use the workspace and cache paths described above. The
CLI groups the actual paths by filesystem and checks each filesystem's peak,
including retained cache space. Paths with different names can share one
filesystem. A cache placed inside the destination library also counts against
that profile's capacity.

The in-place reference follows two search phases. Extraction first produces a
temporary binary index. Once that index has been durably saved and verified,
OWL releases the owned extraction database and records before publishing the
browser search files. The temporary index remains available until publication
finishes. The larger of those phases determines peak working space.

The calculation is explicit, in bytes:

```text
raw index allowance = ceil(0.75 × search allowance)
extraction allowance = scratch allowance − raw index allowance
search build peak = raw index allowance + max(extraction allowance, search allowance)
build-input work = temporary recipe downloads + expanded recipe inputs
in-place peak = content and reader files + metadata + reserve
               + acquisition workspace + max(search build peak, build-input work)
```

Acquisition workspace includes each selected recipe's explicit allowance,
retained staged outputs and receipts. Original source packages retained in the
library are already counted in content bytes. Temporary build inputs are a
separate phase; the CLI also checks their configured storage location.

The displayed scratch allowance keeps its configured value; it is not added
again to the finished search allowance. The page calculates separate peaks for
the intended collection and currently verified files. For example, 9,869,555,191
pinned asset bytes, 68,497,118 bytes of acquisition workspace, 2 GB search,
4.5 GB scratch, 1.5 GB reserve, 16 MiB metadata and no temporary build inputs
produce a **15,954,829,525-byte** planned peak. The 4.5 GB scratch allocation
contains 1.5 GB for the temporary index and 3 GB for extraction. This fits the
nominal 16 GB budget; it does not establish that an unmeasured corpus's actual
index or extraction database fits those allowances.

Custom selections or larger measured indexes can exceed the allowances even
when final-content targets appear to fit. Missing content and excess peak
storage are separate problems. Retained old versions and the shared index cache
consume additional space, which the CLI checks on the actual filesystem.

The remaining capacity is not automatically filled by a number on the page. Search and scratch budgets
are estimates rather than measured upper bounds. The browser cannot check the
drive's real free space, filesystem, existing verified files, partial downloads,
old versions, or search checkpoints. The CLI performs those checks and computes
reuse on the actual target.

## Copy and run the command

Install Python 3.11+ and OWL on the build computer, then run copied commands from
the repository root with its environment active. Use
`python -m pip install -e '.[zim,pdf]'` for the production presets' ZIM indexes
and Book Dash PDF generation. Custom selections without archives or generated
EPUB-to-PDF editions can use `python -m pip install -e .`. New source downloads require
internet access even though the selector itself works offline.

Use **Copy plan command** first. It ends in `--plan` and creates no library files.
Review its actual target and capacity checks. Then use **Copy build command** when
the selection is ready. If the browser refuses clipboard access to a local page,
the tool selects the displayed command for manual copying through the device's
Copy action, Ctrl+C, or Command+C.

The selector quotes the destination, index cache, and workspace paths for the
chosen shell, including spaces and apostrophes. PowerShell quoting is not Windows
Command Prompt syntax. Enter paths in the selector instead of adding shell quotes
yourself, and copy into the matching shell. Blank paths and control characters are
rejected. The generated command is displayed for inspection and is never executed
by the page.

**Add the human topic atlas** starts checked and adds
`--navigation-dir catalog/navigation`. It generates the current reviewed browsing
metadata during the build; it does not select more content. See the
[atlas guide](topic-atlas.md) for its scope and separate post-download command.

**Build only currently verified files (partial library)** starts unchecked. Enable it only when deliberately
building the currently verified subset of an incomplete collection. It adds
`--allow-incomplete`; the completed files remain subject to integrity checks, and
the library records its incomplete content scope. It does not resolve permissions,
create missing files, waive capacity checks, or claim a full collection. Errors
or unaccepted incomplete selections prevent a usable build command.

Changing or resetting the preset restores its resource choices, turns the atlas
option on, turns the partial-library option off, and resets the index cache budget
to the new profile's search allowance. The chosen target, index cache and workspace
paths, and shell remain unchanged; review the regenerated commands after each
preset change.

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
