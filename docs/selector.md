# Choose a library with the offline selector

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
The live summary reports their exact cataloged sizes and document counts.
Larger presets also describe intended collection scope that can remain incomplete
or unresolved. A capacity label alone never means that much knowledge is available.

For a fixed preset, a selected row can say **Preset files only**. This
keeps only the resource's exact files in that preset. For example, the current WHO
manual and selected OpenStax books do not necessarily fulfill the broader WHO or OpenStax
collection plans. Leaving those rows selected does not expand them. Choosing
**Published collection** explicitly selects the full intended collection and adds
the corresponding `--include` argument; its larger estimate and unresolved scope
then apply. Unchecking a preset resource removes its mapped files through
`--exclude`.

Resource choices use the stable IDs in `catalog/resources.yaml`. Required readers
are added when selected resolved ZIM archives need them. A reader package does
not make an archive directly readable in a standard file viewer.

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
- **Temporary search work:** the profile's explicit scratch budget, or twice its
  search budget when not specified; needed during the default in-place build.
- **Free-space reserve:** space deliberately left outside the build allocations.

The green meter measures exact downloadable files as a fraction of nominal drive
capacity; gray marks reserved free space. Search and temporary work are listed
separately and are not presented as knowledge. A prominent content-gap warning
appears when less than 80% of a planned knowledge allocation is pinned and the gap
is at least 250 MB. An unchanged preset below its configured minimum knowledge
size also warns and requires explicit partial-library acceptance before building.
The minimum excludes software, search, temporary files, and reserved space.

The in-place peak combines content, readers where applicable, search, metadata,
scratch, and reserve. The page reports both the intended selection and the
currently verified files. The current default plans fit nominal capacities, including their explicit scratch allowances. Custom selections or larger measured indexes can exceed them even when final-content targets appear to fit. Missing content and excess peak storage are separate problems.

The remaining capacity is not automatically filled by a number on the page. Search and scratch budgets
are estimates rather than measured upper bounds. The browser cannot check the
drive's real free space, filesystem, existing verified files, partial downloads,
old versions, or search checkpoints. The CLI performs those checks and computes
reuse on the actual target.

## Copy and run the command

Install Python 3.11+ and OWL on the build computer, then run copied commands from
the repository root with its environment active. Use
`python -m pip install -e '.[zim]'` to index the ZIM archives included in the
enriched presets; `python -m pip install -e .` supports custom selections of only
ordinary documents. New source downloads require
internet access even though the selector itself works offline.

Use **Copy plan command** first. It ends in `--plan` and creates no library files.
Review its actual target and capacity checks. Then use **Copy build command** when
the selection is ready. If the browser refuses clipboard access to a local page,
the tool selects the displayed command for manual copying through the device's
Copy action, Ctrl+C, or Command+C.

The selector quotes the destination for the chosen shell, including spaces and
apostrophes. PowerShell quoting is not Windows Command Prompt syntax. Enter the
path in the selector instead of adding shell quotes yourself, and copy into the
matching shell. Blank paths and control characters are rejected. The generated
command is displayed for inspection and is never executed by the page.

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
option on, and turns the partial-library option off. The chosen target and shell
remain unchanged; review the regenerated commands after each preset change.

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
