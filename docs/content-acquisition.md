# Reusable content acquisition

OWL separates finding content, reviewing a reproducible edition, and building it.
The acquisition tools fetch bounded publisher **metadata** only. Books, archives,
map PDFs and lesson media are downloaded by the normal build command. Discovery
never changes collection readiness or silently replaces a source checksum.

## Small reports, reusable evidence

```sh
python scripts/acquire_content.py audit
python scripts/acquire_content.py audit --profile full-1tb --resource survivor-tier-a
python scripts/acquire_content.py discover --resource hesperian-health,regional-maps
python scripts/acquire_content.py discover --resource regional-maps --offline
python scripts/acquire_content.py report --format text
python scripts/acquire_content.py report --only-changed
```

JSON is the default. Standard output is approximately 2 KiB; its `detail` path
points to the complete report under `.owl/acquisition/reports/`. Metadata responses
and permanent HTTP failures are cached, so repeated attempts do not require an
agent to repeat research. `discover --refresh` deliberately rechecks cached
endpoints. `--offline` permits only saved metadata. Inputs, selections and review
decisions belong in versioned recipes; response bodies and large artifacts do not
belong in Git.

Audit uses each preset's **selected edition**. An unfinished broad Gutenberg or
Stack Exchange edition does not block a preset that explicitly selects its ready
compact alternative. Reports retain content-floor shortfalls separately from
coverage gaps. A URL, a recipe, or enough estimated gigabytes does not demonstrate
a complete collection.

For exact URL availability, byte counts and publisher checksum sidecars, use
`scripts/probe_source_pins.py`. Its HEAD requests never read library bodies,
including error/redirect bodies; cached reruns support `--offline`. MD5, SHA-1
and multipart ETags remain evidence rather than SHA-256 pins. The
[source-pin report](acquisition-source-pins.md) records the current 1 TB findings.
`scripts/freeze_map_selection.py` turns accepted discovery and HEAD evidence into
a deterministic [sheet manifest](acquisition-maps.md), retaining every unresolved
content pin and review requirement.

## Inspect and stage without downloading

```sh
python scripts/acquire_content.py inspect-local --resource food-preservation \
  --local-root /path/to/existing/LIBRARY
python scripts/acquire_content.py stage --fragment accepted-fragment.yaml \
  --output .owl/acquisition/candidate
```

Inspection streams hashes and reports PDF structure or HTML dependencies. It does
not certify clinical accuracy, scan legibility or physical-device support. Stage
writes a **new candidate directory**, validates catalog/registry/navigation and
all applicable profile budgets, and leaves the active catalogs untouched. Review
the delta before integrating accepted records. Existing asset pins cannot be
silently overwritten. A whole-resource readiness change needs an explicit
`review` with `status: approved`, `full_scope: true`, and evidence; approving one
generated subset is insufficient.

`prepare-local --fragment TEMPLATE --local-manifest PATHS --output FRAGMENT`
creates an accepted fragment from preserved originals. `PATHS` maps asset IDs to
existing local files. It streams whole-file hashes, rejects disagreement with
existing template pins, and performs no download or conversion. The programming
source-companion manifest was registered this way.

The prior food-preservation snapshot can be registered entirely from its existing
local originals and evidence:

```sh
python scripts/prepare_existing_evidence.py /path/to/health-evidence \
  .owl/acquisition/food-review
python scripts/acquire_content.py stage \
  --fragment .owl/acquisition/food-review/fragment.json \
  --output .owl/acquisition/food-candidate --resource food-preservation
```

This verifies the earlier reviewed snapshot, each original source hash, complete
section counts and normalized text. It renders the local originals and emits a
portable metadata fragment. It performs no network requests, SSD writes or
production library build. Dated snapshots remain dated; changed publisher bytes
require renewed review instead of accepting new bytes under an old checksum.

`scripts/prepare_openssh.py` reproduces the complete portable 10.5p1 manual
edition from its existing source archive. The [edition guide](acquisition-openssh.md)
documents source/notice preservation, renderer pins, local links and normal build
integration. Repeated preparation/staging adds no duplicate assets. Real builds
check the required renderer before downloading; plan-only runs do not require it.

## Recipes and normal builds

`catalog/acquisition/recipes.yaml` holds acquisition plans, including explicit
blockers. Only approved, fully pinned recipes are embedded in the active catalog
under `acquisition_recipes`. A generated asset references its recipe using
`generation: {recipe_id: ...}`. Recipes record resource, adapter/version, exact
input and output asset IDs, selection, review evidence and workspace allowance.
`dependency_asset_ids` names pinned companion files required by local links or
notices without loading those bodies into the renderer.

The normal builder downloads the pinned input assets first, then runs the local
renderer under its existing build lock. No renderer runs arbitrary shell commands
or fetches URLs. It verifies every generated output against the reviewed hash and
size before promotion. Generated files join ordinary search, navigation,
inventory and checksums; the locked catalog retains the complete recipes.

Interruption retains verified originals and owned generation state. Matching
outputs are reused. Changed sources, output mismatches, missing dependencies,
pending reviews and incompatible workspace ownership stop completion. Excluding
a source collection omits dependent generated editions and reports their gaps.
`--allow-incomplete` cannot bypass an invalid generated recipe.

Source downloads, generated output bytes, supporting files, retained generation
workspace, duplicate generation space during repair, search and index scratch
are accounted separately. Corpus recipes need a positive workspace allowance.
Large media remain ordinary downloaded assets; lesson HTML links them without
making a second copy. The small-document ZIP/export limits are not increased to
accommodate videos.

## Collection adapters

- **Health/manual HTML:** counted complete sections, exact source and text pins,
  local/embedded illustrations, retained tables and source links. Undeclared
  required illustrations and unsupported content fail visibly.
- **Maps:** USGS metadata plus state geometry; select complete New England
  coverage at the finest available scale fitting each map allowance, with USA
  overview coverage. Report dates, scale and actual holes; do not truncate a
  sheet list to pretend complete coverage. Install `.[acquisition]` for efficient
  polygon coverage checks on detailed state boundaries.
- **Survivor:** deterministic title/category proposals, explicit topic coverage,
  edition deduplication, exclusions and review queues. Title matching cannot
  certify scan quality or replace an approved title manifest.
- **Direct ZIM editions:** exact reviewed article lists and complete dependency
  manifests using the existing exporter. Whole Wikipedia expansion is excluded.
- **Stack Overflow:** stream local XML inputs, preserve disk-backed joins across
  retries, propose durable/legacy candidates, and render reviewed question IDs
  with answers, comments, canonical links and attribution. Inputs must contain
  posts, comments, users and duplicate links. Missing metadata is a blocker.
- **Lessons:** frozen English lesson IDs, ordinary local media and captions,
  context and notices. Unsupported essential lesson formats remain gaps; no
  learning-platform installation is required or silently substituted.

Legacy Stack Overflow has an explicit flag in search. Ordinary searches and
learning shelves exclude it before ranking; users can select **Legacy systems
only** or **All resources, including legacy**. Results carry the warning
**LEGACY — MAY APPLY ONLY TO OLD SYSTEMS**. Dates alone never classify a question
as legacy.

## Reusable offline QA

```sh
node scripts/check_phet.cjs --help
node scripts/check_phet.cjs --manifest qa-selection.json --root /path/to/files \
  --playwright /path/to/playwright --browser /path/to/chrome \
  --output .owl/acquisition/phet-qa.json
```

The manifest binds files to hashes and records interaction/reset actions. The
runner blocks networking and checks cold launch, model changes, reset and layout.
`--validate-only` checks manifest/files without claiming browser QA. Browser and
Playwright are development tools, not drive-reading requirements. Desktop mobile
viewports do not certify physical phones or storage-provider permissions.
Reviewed canvas scene actions and `--inspect-only` support older PhET editions.
`scripts/summarize_phet.py` exports bounded evidence bound to the exact manifest;
see the [32-check browser report](phet-browser-qa.md).

The default library is English-only; Spanish Wikipedia and multilingual books
remain optional. The original larger-profile content targets are retained.
Unfilled targets, inaccessible inputs and unreviewed selections remain explicit
until useful English content actually satisfies them.

For ordinary documents and lesson playback, use the reusable
[document browser checks](document-browser-qa.md) and
[synthetic lesson checks](lesson-browser-qa.md). The former can require every
local companion, count tables/images, verify anchors and save review screenshots.

```sh
python scripts/validate_acquisition.py
python scripts/validate_acquisition.py --full
```

This runner saves detailed logs and JSON while keeping stdout near 2 KiB. It
checks adapter tests (or the full regression suite), all five no-download build
plans, fixed small-preset bytes, optional language selection, and generated-file
freshness. Plan checks simulate ample development-disk space and separately
enforce each profile's real nominal capacity. They are not device certification.

See the [implementation report](acquisition-implementation.md) for completed
content gaps, verification evidence and remaining source/review blockers.
