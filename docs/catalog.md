# Catalog maintenance

`catalog/library.yaml` is the production recipe. `catalog/demo.yaml` is a tiny,
original fixture for a network-free demonstration; it is not an emergency manual.
Profiles in `profiles/*.yaml` declare decimal capacity, free-space reserve and a
search-output allowance. The three large profiles select ordered collections
from `catalog/resources.yaml` through `default_resources`; `resource_overrides`
specifies smaller map or Survivor allocations. Their asset selection is derived
from the selected resources, not duplicated in each file's `profiles` list.
The fixed `flash-16gb`, `critical-64gb`, and demo baselines use asset `profiles` membership.
An empty asset `profiles` list means it is selected only through a named resource.

The fixed flash/critical/demo profiles declare `minimum_coverage` for `textbooks` and
`illustrated-guides`. These floors count **resolved, required, critical, directly
readable** assets. The large-profile defaults follow the explicit acquisition
list: OpenStax begins at 512 GB, while electrical textbooks and illustrated
practical material remain in the complementary direct core. Explicit resource
include/exclude customization overrides fixed-profile learning floors so a user
can remove unwanted books deliberately. Critical-format rules and reader
dependencies still apply. An illustrated textbook belongs to both learning
collections; those counts overlap and do not imply additional copies.

Resource entries describe intended scope, approximate target bytes, available
asset IDs, and `ready`, `partial`, or `unresolved` status. Their estimates must
never be used as exact downloadable file sizes or checksums. `--list-resources`
enumerates all 46 numbered entries and named support collections. `--include`
and `--exclude` accept stable IDs or numbers, repeated or comma-separated. Unknown
selectors or a resource both included and excluded are errors. See
[content selection](content-selection.md) for the complete curation rules.

A resource can optionally register `editions.direct` and `editions.compact`.
Each edition requires exactly `asset_ids`, `target_bytes`, `status`, and `reason`;
use the same types as the resource fields. Every referenced asset must already
exist in the catalog, be resolved, and have a reviewed SHA-256. A direct edition
contains only ordinary readable formats outside `ZIM/` and `SOFTWARE/`, with no
reader requirement. A compact edition contains at least one pinned ZIM. Both
must retain every critical asset in the resource's published membership.
Do not register guessed compression ratios or future exports as editions.

`--edition RESOURCE=direct` or `--edition RESOURCE=compact` selects these files
for an already selected resource; add `--include RESOURCE` if needed. The edition
replaces its resource's asset list, target, status, and reason. Profile membership
exclusions still apply, but its published target override does not. `published`
selects the original definition. Reader dependencies are recomputed from the
resulting files. Editions and exact selected assets are recorded in locked build
metadata. Explicit `--exclude RESOURCE` covers all of its registered editions.

The current production registry has no alternate editions. After registering
verified alternatives, run `python scripts/build_selector.py` to expose them in
[the offline selector](selector.md). The same command refreshes resource choices,
profile defaults, and estimates after any recipe change. CI checks that the
committed `SELECT.html` matches its inputs.

Plans distinguish requested budgets from verified available bytes. Known exact
file sizes raise planning estimates when necessary. A world-map selection
replaces the North America archive and credits its 21 GB allocation only when
that archive was otherwise selected; regional topography remains. Exclusion
changes the next build's inventory but does not delete old drive content.

Selected incomplete collections block a normal build before downloads or writes.
`--allow-incomplete` explicitly builds only available verified assets and records
`content_complete: false` in the inventory, build metadata, and
`CONTENT_SELECTION.json`, with prominent navigation notices. It does not bypass
hash checks, unsafe paths, required unresolved file checks, or reader dependencies.
`complete` describes a finished, verified build process; `content_complete`
separately describes fulfillment of the selected collection definitions.

Required asset fields are `id`, `title`, `category`, `format`, `source_url`,
`destination`, `version`, `size_bytes`, `sha256`, `license`, `redistributable`,
`required`, and `profiles`. Quote versions and dates. Sizes are exact source-file
bytes, not rounded estimates. Hashes are lowercase SHA-256, or `null` when no hash
has been reviewed. All initially resolved sources are pinned. Executable packages
under `SOFTWARE/` must have a pinned hash, including ZIP distributions.

Useful optional fields are `description`, `publisher`, `source_page`, `language`,
`snapshot_date`, `mirrors`, `tags`, `attribution`, `critical`, `reader_required`,
`resource_type`, `illustrated`, and `text_encoding` (UTF-8 by default). Keep metadata plain text. The catalog does
not authorize use contrary to a source's license. `redistributable: false` can
describe a lawfully downloadable personal-use source; review distribution terms
before giving a built SSD to someone else.

`resource_type` is one of `textbook`, `guide`, `reference`, `archive`, or `software`
(default `reference`). `illustrated` is a boolean (default `false`); mark it true
only after checking that the source contains useful diagrams, drawings, or
photographs. Textbooks and illustrated guides are separate shelves from their
subject categories, so a physics textbook remains discoverable as both a book
and a science reference. Both shelves require ordinary formats and no special
reader; assets under `ZIM/` or `SOFTWARE/` cannot count. The illustrated shelf
includes guides **and illustrated textbooks**, not every file containing an image.

Keep original illustrated PDFs intact. Text extraction produces the search index,
not a replacement for their page layouts, figures, captions or diagrams. Inspect
the original page for image content, which has no OCR guarantee. Keep licensing
and attribution notices in the PDF and supply its `attribution` field so search
results retain the required notice beside excerpts.

Core textbooks and illustrated guides download first, followed by other critical
documents, supplementary direct learning materials, other ordinary files,
software, and large archives. Smaller files are fetched first within each tier
so useful guides become available promptly. Profiles never silently drop books
to fit more encyclopedia/video data: the complete selected recipe must fit.

Destinations must be relative, portable ASCII paths under `CRITICAL`, `REFERENCE`,
`BOOKS`, `MAPS`, `ZIM` or `SOFTWARE`. IDs and case-insensitive paths must be unique.
Traversal, backslashes, Windows reserved names, trailing dots/spaces, symlinks and
conflicting file/directory paths are rejected. Do not add executables disguised
as documents. A `critical: true` asset must use HTML, PDF, TXT, Markdown or ordinary
image formats and cannot require a reader. ZIM assets require `reader_required:
true`; a profile with ZIM must also select a pinned bundled software asset.

An unresolved entry uses `status: unresolved`, an explicit `unresolved_reason`,
and `null` for unknown URL, size or hash. It must be optional (`required: false`)
for a profile to build. Optional unresolved entries are printed, excluded from the
download plan, and retained in the inventory; a required unresolved source stops
the build. A resolved download failure always stops the build, even if its
`required` flag is false. The flag is not permission to silently skip failed
downloads.

Only HTTPS is accepted normally. `--allow-local` additionally enables `file://`,
`repo://` and HTTP for trusted fixture builds. `repo://assets/demo/example.txt`
refers to a file in this checkout; it is never resolved from the current working
directory or an arbitrary parent. HTTPS certificate verification is never disabled.
If a Python installation lacks root certificates, repair its trust store or set
`SSL_CERT_FILE` to a trusted CA bundle; do not turn TLS checking off.

Validate before building:

```bash
python scripts/validate_catalog.py
python scripts/build_drive.py /path/to/drive --profile standard-512gb --plan
```

`--plan` checks actual available filesystem space too. It does not create the
target. Space allocations for output, cache and indexing scratch are added when
they share a filesystem. Budgets are deliberately conservative and are not
benchmarks of a full Wikipedia build. A separate `--work-dir` can place indexing
scratch on a larger disk. An existing cache is still budgeted conservatively;
reduce a reviewed profile's allowance only with measured evidence.

To reproduce a build's content, retain its `LOCKED_CATALOG.yaml` and the matching
profile files, then pass that catalog with `--catalog`. The lock captures the
exact selected files and collection coverage, bypassing current resource defaults;
it uses the original profile ID and does not require the resource registry. Do not
add include/exclude/edition flags to a locked selection: customize the source catalog
instead. Rebuilding an explicitly partial selection still requires
`--allow-incomplete`. Preserve the downloaded cache because upstream snapshots
may disappear. `BUILD_INFO.json` records Python
and extractor versions. `requirements-tested.txt` pins the initial tested Python
dependencies. Use the same tool commit, Python and dependency versions to reproduce
index bytes; build timestamps and provenance can legitimately differ.

Source refreshes are manual and reviewable. Verify a new snapshot at the original
publisher, inspect its license, obtain an upstream SHA-256 or compute it after a
trusted-source download, record exact bytes, and update the YAML. A checksum is
integrity evidence rather than a publisher signature. Never resolve a checksum
failure by accepting the newly downloaded bytes without reviewing the source.
