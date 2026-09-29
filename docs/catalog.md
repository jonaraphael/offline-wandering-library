# Current admission and selection rules

Every active file must pass `src/owl/content_policy.json`. Every asset and collection must declare `utility_tier`, `utility_reason` and `knowledge_domains`; defaults must pass `src/owl/utility_policy.json`. Run `python scripts/check_selection_policy.py` after catalog or profile edits and regenerate SELECT.html and the content-selection reference.

Use finished publisher PDFs, whole ZIMs and verified self-contained files. Do not add build-time conversions, source-only manuscripts or unverified HTML bundles. Preserve full-file size/hash pins and notices. Prefer domain breadth and substantial complete works over object counts. Keep NONESSENTIAL fiction, college education and computing opt-in. New alternatives must record what coverage they do and do not replace.

`catalog/content-review.json` preserves the review of the prior catalog; acquisition recipe descriptions below are historical tooling details, not exemptions from these admission rules.

# Catalog maintenance

The authoritative format and materialization rules are in [`src/owl/content_policy.json`](../src/owl/content_policy.json). `python scripts/check_content_policy.py [CATALOG ...]` reports every violation as JSON and exits nonzero on failure. Catalog validation, candidate staging and selected build inputs enforce this policy, including existing and extra-catalog entries. The low-level structural loader remains usable for inspecting rejected records. Older generated-edition descriptions below document implementation only; they do not authorize admission. HTML/SVG require an `offline_ready: true` review declaration, optional EPUB reading editions require `optional_format: true`, and media codecs must match the policy. Declarations are not a substitute for testing the actual files; the checker does not download or certify content.

`catalog/library.yaml` is the production recipe. `catalog/demo.yaml` is a tiny,
original fixture for a network-free demonstration; it is not an emergency manual.
Profiles in `profiles/*.yaml` declare decimal capacity, free-space reserve and a
`discovery_budget_bytes` allowance (16 MiB in bundled profiles). There is no search scratch budget. All production profiles select collections
from `catalog/resources.yaml` through `default_resources`. Their asset selection is derived
from the selected resources, not duplicated in each file's `profiles` list.
The demo baseline uses asset `profiles` membership; all production presets use named collections.
An empty asset `profiles` list means it is selected only through a named resource.

Production profiles select ready named collections through `default_resources`. Every asset has a tier, explanation and topic-domain list. Defaults contain CRITICAL and USEFUL files and meet the domain coverage policy; optional exclusions may deliberately reduce coverage. There are no production file-count or byte quotas. The small `demo` fixture uses direct asset membership.

Resources list actual finished files with exact summed sizes, source limitations and shared priority. Split different priorities into separate collections so NONESSENTIAL material can remain opt-in. `--include` and `--exclude` accept stable resource IDs or existing collection numbers. Never create empty wishlist entries to inflate available content.

Maintain [the editorial coverage plan](full-1tb-coverage-plan.md) in
`catalog/coverage-plan.yaml` in the same change as new selections. Record intended
depth, existing sources, gaps, next candidates and an adequacy criterion per
topic. The documentation generator checks references and includes every atlas
topic; it never treats source counts, tags or completed downloads as proof of
adequate depth. Unselected candidates belong in this plan, not in ready collections.

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

The production registry currently selects finished PDFs and ZIMs as published collections. Verified alternative editions may be added later only if their files independently pass the same policy. Regenerate SELECT.html after catalog, topic metadata or profile changes; CI checks freshness.



Plans distinguish requested budgets from verified available bytes. Known exact
file sizes raise planning estimates when necessary. A world-map selection
replaces the North America archive and credits its 21 GB allocation only when
that archive was otherwise selected; regional topography remains. Exclusion
changes the next build's inventory but does not delete old drive content.

Selected incomplete collections block a normal build before downloads or writes.
Active profiles have no minimum-content-byte or book-count quotas. Intended
depth and remaining subject gaps are recorded in the editorial coverage plan;
passing build checks does not mark those gaps complete. A planned source is
never counted as an acquired file.
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
`resource_type`, `illustrated`, `supporting_file`, `archive_member`, `generation`,
`legacy`, and `text_encoding` (UTF-8 by default). Keep metadata plain text. The catalog does
not authorize use contrary to a source's license. `redistributable: false` can
describe a lawfully downloadable personal-use source; review distribution terms
before giving a built SSD to someone else.

Generated editions use `generation: {recipe_id: ID}` and an approved, pinned
`acquisition_recipes` record. The builder obtains its source inputs and required
linked companions before rendering. Source pins bind checkpoints; exact output
hashes and review requirements gate completion. Generated bytes, ordinary
downloads, expanded ZIP files and retained generation workspace have separate
totals. See [reusable acquisition](content-acquisition.md) for contracts and commands.

Pinned ZIP packages can become ordinary readable files during a future build.
Mark the pinned ZIP source `supporting_file: true`; each individually size/hash-pinned
output adds `archive_member: {source_asset_id: SOURCE_ID, path: ORIGINAL_MEMBER_PATH,
document: true}` and uses the source ZIP's exact URL/mirrors. Supporting CSS, scripts,
images and auxiliary pages use `document: false` and `supporting_file: true`. Select
the source and all package members together in the same resource; omitting a
selected member's source fails before writing. Outputs retain explicit reviewed
destinations and original relative structure. Only valid pinned archive members
may have zero-byte sizes. These files remain ordinary files after extraction.

Supporting files remain in machine inventory, locked catalogs and checksums, but
are omitted from reading navigation, search, atlas and learning-coverage totals.
Disk planning includes retained source ZIPs and outputs; download totals include
only ZIP sources. Supporting bytes do not inflate pinned-knowledge totals. Member
extraction obeys the normal build lock and ownership checks, rejects unsafe archive
entries and excessive expansion, and promotes only verified output bytes. See the
full [archive extraction contract](archive-extraction.md) for limits, restart
behavior and complete-package recipes. Use ordinary resource membership for these
packages; the stricter `editions.direct` schema does not accept ZIP dependencies.

`resource_type` is one of `textbook`, `guide`, `reference`, `archive`, or `software`
(default `reference`). `illustrated` is a boolean (default `false`); mark it true
only after checking that the source contains useful diagrams, drawings, or
photographs. Textbooks and illustrated guides are separate shelves from their
subject categories, so a physics textbook remains discoverable as both a book
and a science reference. Both shelves require ordinary formats and no special
reader; assets under `ZIM/` or `SOFTWARE/` cannot count. The illustrated shelf
includes guides **and illustrated textbooks**, not every file containing an image.

Keep original illustrated PDFs intact. Search uses approved metadata and links to
the source; it does not extract text or understand diagrams. Keep licensing and
attribution notices and supply the catalog `attribution` field so results display
the required notice.

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
target. Capacity planning includes source files, discovery, metadata, acquisition
workspace where needed, and reserve. Discovery output is bounded before publication
and has no indexing scratch or retained cache. `--work-dir` is only for temporary
acquisition inputs; `--cache-dir` optionally retains original downloads.

To reproduce a build's content, retain its `LOCKED_CATALOG.yaml` and the matching
profile files, then pass that catalog with `--catalog`. The lock captures the
exact selected files and collection coverage, bypassing current resource defaults;
it uses the original profile ID and does not require the resource registry. Do not
add include/exclude/edition flags to a locked selection: customize the source catalog
instead. Rebuilding an explicitly partial selection still requires
`--allow-incomplete`. Preserve the downloaded cache because upstream snapshots
may disappear. `BUILD_INFO.json` records Python
and installed dependency versions. `requirements-tested.txt` pins the initial tested Python
dependencies. Use the same tool commit, Python and dependency versions to reproduce
discovery bytes; build timestamps and provenance can legitimately differ.

Source refreshes are manual and reviewable. Verify a new snapshot at the original
publisher, inspect its license, obtain an upstream SHA-256 or compute it after a
trusted-source download, record exact bytes, and update the YAML. A checksum is
integrity evidence rather than a publisher signature. Never resolve a checksum
failure by accepting the newly downloaded bytes without reviewing the source.
