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

The 16 GB and 64 GB presets keep the current 25 verified PDFs, including seven
textbooks and thirteen illustrated works. Their content totals 1,574,545,596 bytes.
This is a useful fixed selection, not a promise to fill the drive. Larger presets
describe intended collections, many of which remain incomplete or unresolved.

For a small preset, a selected row can say **Preset files only · direct**. This
keeps only the resource's exact files in that preset. For example, the current WHO
manual and five OpenStax books do not fulfill the broader WHO or OpenStax
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

The production registry currently has no alternate editions. The selector shows
these unsupported choices as disabled. It does not compress PDFs, decompress ZIMs,
invent exports, or assume a percentage saving. The unresolved 60 GB
`direct-reading-expansion` is a separate content plan, not an implemented
conversion button. Critical directly readable files must remain available when
a registered compact edition is selected.

An available alternate edition produces `--edition RESOURCE=direct` or
`--edition RESOURCE=compact` alongside the resource selection. The CLI rejects an
edition that is not registered; changing the command text cannot create it.

## Read the totals before copying a command

All capacities and GB totals use decimal units. The selector distinguishes:

- **Intended collection storage:** includes planning estimates for missing scope
  and uses larger known asset sizes where needed. These bytes are not all
  downloadable today.
- **Verified file bytes:** exact sizes of selected resolved asset definitions.
  This does not mean those files already exist on the destination drive.
- **Search and metadata allowances:** planned index space and 16 MiB for metadata.
- **Temporary search files:** the current scratch allowance is twice the search
  budget and is needed during the default in-place build.
- **Free-space reserve:** space deliberately left outside the build allocations.

The in-place peak combines content, readers where applicable, search, metadata,
scratch, and reserve. The page reports both the intended selection and the
currently verified files. The larger default collections can exceed nominal
drive capacity during building even when their final-content targets appear to
fit. Missing content and excess peak storage are separate problems.

For the unchanged `flash-16gb` preset:

| Allocation | Bytes |
| --- | ---: |
| Verified PDF content | 1,574,545,596 |
| Search budget | 2,000,000,000 |
| Metadata allowance | 16,777,216 |
| Temporary search files | 4,000,000,000 |
| Free-space reserve | 2,000,000,000 |
| Total peak including reserve | 9,591,322,812 |
| Nominal capacity | 16,000,000,000 |

The remaining capacity is not automatically filled. Search and scratch budgets
are estimates rather than measured upper bounds. The browser cannot check the
drive's real free space, filesystem, existing verified files, partial downloads,
old versions, or search checkpoints. The CLI performs those checks and computes
reuse on the actual target.

## Copy and run the command

Install Python 3.11+ and OWL on the build computer, then run copied commands from
the repository root with its environment active. `python -m pip install -e .` is
sufficient for the small direct-reading presets; use `python -m pip install -e '.[zim]'`
when selected archives need ZIM indexing. New source downloads require
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
