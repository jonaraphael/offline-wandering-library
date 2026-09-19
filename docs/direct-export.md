# Export archive documents into ordinary files

`scripts/export_direct.py` turns selected documents from an already downloaded,
SHA-256-pinned ZIM into ordinary HTML, text, Markdown, or PDF files. It also copies
their local illustrations, stylesheets, and fonts. It never downloads anything or
executes archive scripts. The ZIM stays on the SSD, and exported files are written
directly into their final library paths; a second large derivative copy on the
computer is unnecessary.

The target argument is the outer directory containing `START_HERE.html` and
`LIBRARY/`. The source argument is the actual archive file path, including
`LIBRARY/` when that archive belongs to this drive. Catalog destinations remain
relative to the inner `LIBRARY/` directory.

This supplies an export mechanism, not an editorial selection. It does not
automatically choose a Wikipedia lifeboat, promise that a planned direct-reading
budget has been filled, or mark exported material critical or illustrated without
review. Curated selections and review remain separate work.

## Export a selection

Install the optional archive dependency on the build computer:

```sh
python -m pip install -e '.[zim]'
```

Create a UTF-8 text file with one exact archive entry path per line. Use paths from
the **pinned edition being exported**, such as paths shown in OWL's ZIM search
results. Paths are case-sensitive archive identifiers; they are not web URLs to
fetch. Blank lines are ignored. Redirects are followed and duplicate selections
are removed. Comments in this file are not supported.

For example, after downloading the catalog's Wikibooks archive, run:

```sh
python scripts/export_direct.py \
  /Volumes/OWL/EMERGENCY_LIBRARY/LIBRARY/ZIM/OTHER/wikibooks_en_all_maxi_2026-04.zim \
  /Volumes/OWL/EMERGENCY_LIBRARY \
  --catalog catalog/library.yaml --asset wikibooks_en \
  --entries selected-wikibooks-paths.txt --export-id wikibooks-selection \
  --max-bytes 2000000000 --max-files 10000
```

The entry list must exist and contain real paths; the command does not supply an
implicit selection. Substitute your SSD path and the archive filename from your
catalog. Both required limits cover documents **and all discovered supporting
files**. The byte limit measures the actual converted payload, not the ZIM's
compressed size. HTML conversion can make files larger.

Use `--all` instead of `--entries` only for a deliberately bounded collection:

```sh
python scripts/export_direct.py /path/to/pinned-small-collection.zim /path/to/OWL \
  --catalog /path/to/catalog.yaml --asset small_collection \
  --all --max-bytes 2000000000 --max-files 10000
```

Here `small_collection` must be a real, pinned ZIM asset in that catalog. `--all`
selects public HTML, XHTML, text, Markdown, and PDF entries. It does not copy every
binary item in an archive. Supporting files are discovered from selected pages.

## Import the completed export into OWL

The exporter writes payloads under
`LIBRARY/REFERENCE/DIRECT/<export-id>/<hash-prefix>/<entry-hash>.<extension>`. Hash-based
names avoid case, punctuation, and path-length collisions on portable filesystems.
Titles and original archive paths remain available in the generated metadata and
HTML attribution notice.

Its own files are under `LIBRARY/.owl/exports/<export-id>/`:

| File | Purpose |
| --- | --- |
| `state.json` | Resume checkpoint and ownership records |
| `parts/` | Incomplete, unpromoted outputs on the SSD |
| `catalog.yaml` | Completed catalog of documents and all supporting files |
| `inventory.json` | Source edition/hash, selected paths, warnings, and output hashes |
| `SHA256SUMS.txt` | Payload checksums with paths relative to the inner `LIBRARY/` directory |

This private export manifest is distinct from the global
`LIBRARY/SHA256SUMS.txt`, whose entries are relative to the outer drive directory.

A complete catalog is published only after every output has passed SHA-256
readback verification. The catalog uses local `file:` URLs pointing at the **same
final files**. Import it into the normal builder to regenerate global search,
navigation, inventory, and checksums:

```sh
python scripts/build_drive.py /Volumes/OWL/EMERGENCY_LIBRARY \
  --profile compact-256gb --include wikibooks-en \
  --extra-catalog /Volumes/OWL/EMERGENCY_LIBRARY/LIBRARY/.owl/exports/wikibooks-selection/catalog.yaml \
  --allow-local --plan
```

Review the plan, then rerun without `--plan` using the same profile and selection
flags as your existing library. If selected collection sources remain unresolved,
the usual explicit `--allow-incomplete` decision still applies. The builder
rehashes and adopts the matching files in place. Include this extra catalog on
subsequent builds to keep these derivatives in the managed library.

Extra catalogs add their actual bytes to the space plan. If your full-profile
selection includes the unresolved `direct-reading-expansion` planning allowance
and these exports are replacing that allowance, add
`--exclude direct-reading-expansion` to avoid budgeting both the planned copies
and their real replacements. This does not turn an unreviewed extract into a
completed editorial selection.

Every derivative records `derived_from_asset_id`; excluding its source collection
also excludes those derivatives from the active build. Exclusion does not delete
old files. Documents and supporting files must stay together: importing only HTML
would leave missing illustrations and styles.

The exporter does not rewrite the library's global `LIBRARY/SHA256SUMS.txt`, inventory, or
search by itself. Until the normal build finishes, new payloads may be reported as
`UNKNOWN` by the global verifier. Private `LIBRARY/.owl` checkpoints are intentionally
outside that manifest. After importing, verify normally:

```sh
python scripts/verify.py /Volumes/OWL/EMERGENCY_LIBRARY
```

## Resume and resource limits

Rerun the same export command after interruption. The source archive is rehashed,
finished outputs are reused only after fresh verification, and an intact `.part`
prefix is checked before continuing. A corrupt prefix restarts that file. Existing
owned files are replaced only after the replacement passes checksum readback.
Unowned files, symlinks, hardlinked output files, and case-conflicting paths are
refused. There is no pruning or automatic deletion of library content.

The selection, source pin, source metadata, and export ID define a job. Limits may
be increased to resume a job that reached its budget. A different selection or
edition requires a different `--export-id`. Completed manifests are withdrawn
before a resumed job changes outputs; an interrupted run is never reported as a
completed export. `Ctrl-C` and supported termination signals retain the checkpoint
and partial file. Source and target OWL build locks prevent simultaneous builds.

The default per-item limit is 16 MiB. `--max-item-bytes` can increase this up to a
hard 64 MiB ceiling; exports are also capped at 100,000 files and 64 MiB of generated
JSON metadata. Split larger selections into independent exports. Python libzim
materializes an individual item, so memory is bounded by those limits rather than
being constant per byte. The archive's cluster cache is limited, but decompression
still uses memory according to the archive's cluster structure. Copies to disk use
1 MiB blocks. Each write checks available target space plus a 16 MiB working
reserve; this is separate from the normal builder's larger search/reserve budgets.

## Conversion scope and review

Selected HTML pages retain text, headings, tables, common inline SVG shapes, and
ordinary local images. Local CSS imports, image references, supported web fonts,
simple responsive-image `srcset` values, and full-size image links are copied
transitively. Links between selected documents remain relative and navigable;
links to unselected articles become labelled text requiring the original archive.
Ordinary external source/license hyperlinks remain marked as requiring internet;
they do not load resources while the document is being read offline.
Fragment links are retained. Plain text, Markdown, and PDF documents are copied
unchanged.

HTML, CSS, and SVG are converted to a static subset. Scripts, forms, frames,
embedded active objects, event handlers, and remote active resource loads are
removed; generated HTML also carries a restrictive Content Security Policy.
External resources are never fetched. Absolute HTTP URLs are resolved only when
the archive contains that exact local entry. Original textual notices are retained,
and each HTML document displays the catalog attribution, license, source edition,
archive path, source URL, and conversion notice. Every output's catalog record carries the
same source/license information. The exporter does not grant additional rights to
redistribute an archive or its derivatives.

This is **not a general browser capture or an exact website reproduction**. Pages
whose main content is generated by JavaScript, including some Zimit collections,
may be unusable as static exports. Video/audio, interactive exercises, uncommon
HTML/SVG features, non-UTF-8 markup, and unusual CSS syntax are unsupported. CSS
containing escape syntax is omitted and reported; complex `srcset` data URLs are
omitted while any ordinary `src` fallback is retained. Missing dependencies are
reported, and unsupported or oversized local dependency types stop the export
rather than silently pretending those files were copied.

Read `inventory.json` warnings and inspect exported illustrations, equations,
tables, notices, and navigation before counting a collection as ready. Completion
means the selected static conversion and its output hashes finished; it is not a
claim that every source feature or illustration survived. Even a warning-free
conversion needs visual review before being labelled a curated illustrated guide.
The automated suite exercises small real ZIMs and search indexing. A separate
headless Chrome check on macOS opened an exported fixture through `file://` and
verified PNG/SVG images, CSS imports, a local font, and a selected-document link
with no console errors or HTTP(S) page requests. This does not establish rendering
compatibility on every phone's local file viewer.
