# Static topic atlas

The atlas adds subject, practical-task, and learning routes to an existing OWL
library. A shared topic has one page even when several broader topics lead to it.
Topic pages show narrower choices, selected source locations, alternate routes,
and reader requirements. Topic A–Z includes aliases; an ambiguous label presents
the matching topics as choices.

Every generated page works without JavaScript, a server, or network access. The
existing critical-content, textbook, illustrated-guide, category, and title
indexes remain available. Local-link support still depends on the device's file
viewer. Filenames and human-readable locations provide a fallback when links or
PDF page fragments do not work.

The drive's outer directory contains `START_HERE.html` and `LIBRARY/`.
The commands below take that outer directory. Atlas pages and reports are under
`LIBRARY/INDEX/`; asset destinations in catalogs and inventories stay relative to
the inner `LIBRARY/` directory.

## Generate navigation from files already on a drive

From the repository, with OWL installed:

```bash
python scripts/build_atlas.py /media/SSD/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation
python scripts/verify.py /media/SSD/EMERGENCY_LIBRARY
```

This command uses the drive's existing inventory, verifies source integrity, and
publishes static navigation. It does not download missing collections, extract
full-text search again, or change the selected content. Supply `--catalog` when
using a different asset catalog. That catalog must contain every asset ID
referenced by the navigation metadata, including currently excluded assets.
Global reference validation does not imply those sources are present on the SSD.

When files have been downloaded to their exact catalog destinations under `LIBRARY/` but the drive
has no inventory, provide the profile and catalog explicitly:

```bash
python scripts/build_atlas.py /media/SSD/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation \
    --catalog catalog/library.yaml --profile critical-64gb
```

Only present files with matching catalog size and checksum are admitted. Missing
files are reported; malformed or mismatched existing files fail verification.
This mode creates a **human-index-only** inventory and navigation. It provides an
honest search-unavailable page when no search index exists. It does not turn a
partially populated directory into a complete planned library. If an inventory
already exists, use that inventory; change its profile through the drive builder.

To include the atlas during a full drive build, opt in explicitly:

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile critical-64gb --navigation-dir catalog/navigation
```

Repeat `--navigation-dir` on later builds that should retain atlas generation.
The ordinary build command does not enable this optional metadata layer by
default. The same source selection and content-completeness rules still apply.

The publisher locks the drive, checks output ownership and local links, records
metadata hashes, and includes generated pages in the drive's checksums. A
previously managed atlas page that no longer belongs to the selection becomes an
unavailable-in-this-build notice with links to current navigation. Unrelated files
are not deleted or overwritten. Interrupted publication can be retried with the
same command; it must not conceal an interrupted full build.

## What the starter metadata covers

[`catalog/navigation/`](../catalog/navigation/README.md) contains 46 starter
topics and 40 whole-document assignments based on the current asset catalog.
Those counts describe navigation metadata, not the 46-resource acquisition plan.
The vocabulary, assignments, and include list remain open to editorial revision.
This starter set does not assert chapter, page, or figure locations for third-party
books. Sources absent from a particular drive disappear from its available routes;
empty branches are omitted.

The original [demo metadata](../catalog/demo-navigation/README.md) exercises shared
parents, ambiguous aliases, and a reviewed HTML anchor for an inline SVG diagram.
It is a software fixture, not emergency guidance or evidence that an entire
production corpus has been curated.

## Metadata files

Keep download URLs, versions, rights, and hashes in the existing asset catalog.
The navigation directory has three inputs:

```text
topics.yaml
assignments.yaml
sections/<asset-id>.yaml       # optional reviewed source-contents maps
```

`topics.yaml` declares `schema_version: 1`, a `topics` list, and all three ordered
entrance lists: `subjects`, `tasks`, and `learn`. Every topic requires `id`,
`title`, and `description`. Optional fields are `parents`, `related`, `aliases`,
and integer `order`. IDs use lowercase letters, digits, underscores, and hyphens,
start with a letter or digit, and have at most 80 characters.

For example, the demo uses:

```yaml
schema_version: 1
entrances:
  subjects: [systems]
  tasks: [systems]
  learn: [learn]
topics:
  - id: systems
    title: Systems and maintenance
    description: Original demonstration material only.
  - id: learn
    title: Learn
    description: Demonstration textbook route.
  - id: build-process
    title: The library build process
    description: An inspected diagram in the original demonstration textbook.
    parents: [systems, learn]
    aliases: [Building a library]
```

Parent links must form a directed acyclic graph. Related links may be reciprocal;
they offer lateral recovery from plausible wrong turns. Every topic must be
reachable from at least one declared entrance through hierarchy links. A related
link alone does not make an orphan topic reachable. Ordered parents determine the
canonical breadcrumb; the first visible parent is used. This breadcrumb is not a
record of the visitor's actual path.

`assignments.yaml` declares `schema_version: 1` and an `assignments` list. Each row
requires `topic_id` and `asset_id`. It may contain `section_id`, `purpose`, integer
`order`, and a short plain-text `description`. Purposes are `start-here`,
`practical`, `explanation`, and `reference`; the default is `reference`.

```yaml
schema_version: 1
assignments:
  - topic_id: build-process
    asset_id: demo_textbook
    section_id: build-diagram
    purpose: explanation
```

Omit `section_id` for a whole-document assignment. Do not put a URL or arbitrary
filesystem path in an assignment. Repeated topic/asset/section declarations retain
the first declaration; the renderer also deduplicates equivalent locations within
a topic. Shared descendants do not inflate document or source-location counts.
Imported contents alone do not create reviewed cross-library assignments.

## Import and review source contents

The importer can propose source contents from PDF publisher outlines and HTML
headings with existing, unique IDs. It works entirely offline against an existing
inventory and exact source bytes:

```bash
python scripts/import_sections.py /media/SSD/EMERGENCY_LIBRARY \
    --asset electrical_dc \
    --output /path/to/drafts/electrical_dc.yaml
```

`--inventory /path/to/INVENTORY.json` overrides the default
`TARGET/LIBRARY/INVENTORY.json`; an explicit inventory or draft-output path is
used as written.
The command creates a draft YAML map and an adjacent
`electrical_dc.yaml.review.json` report. Repeating an identical import is safe;
existing edits are not overwritten. The report identifies skipped or ambiguous
locations, warnings, and any need for whole-document fallback.

Review the draft against the original document before copying the approved YAML
to `catalog/navigation/sections/electrical_dc.yaml`. Inspect section titles,
hierarchy, and representative destinations, then review the locations that will
receive topic assignments. An outline without usable destinations produces a
whole-document fallback report; it does not invent page numbers. Review reports
remain editorial artifacts outside the runtime section-map directory.

A section map requires `schema_version: 1`, `asset_id`, the exact reviewed
`source_sha256`, and `sections`. Every section needs `id`, `title`, `locator`, and
`provenance`. Optional fields are `parent`, `review`, and `illustrations`.
Provenance is `publisher-outline`, `publisher-heading`, or `manual`. Manual
locations, illustration claims, and media timestamps require
`review: {by: ..., date: YYYY-MM-DD}`.

The checked original demo section is:

```yaml
schema_version: 1
asset_id: demo_textbook
source_sha256: a902100fd5d778b5e57f1353bab670830e8f729950fe0510c678a73aa3d8ecb2
sections:
  - id: build-diagram
    title: The library build process
    locator:
      type: html-anchor
      id: diagram-title
    provenance: manual
    review:
      by: OWL original-fixture inspection
      date: '2026-09-18'
    illustrations:
      - kind: diagram
        label: Figure 1. The manifest records the recipe; verification checks the result.
        figure_id: diagram-title
```

Illustration kinds are `diagram`, `photograph`, `procedure`, or `figure`. Each
requires a plain-text `label`; `figure_id` and `caption` are optional. An asset's
`illustrated: true` label describes the whole work. It does not establish that
every mapped section contains a figure. Check the particular section before
adding its illustration annotation.

## Supported source locations

| Locator type | Required fields beyond `type` | Optional fields | Browser behavior |
| --- | --- | --- | --- |
| `pdf-page` | `page` | `end_page`, `printed_label` | Opens `#page=N` where supported; always shows physical page and whole-document link |
| `html-anchor` | `id` | — | Opens an existing unique local element ID |
| `text-lines` | `start` | `end` | Shows line range; opens the whole text/Markdown file |
| `epub-entry` | `path` | — | Shows chapter member identity; opens book in a compatible reader |
| `zim-entry` | `path` | — | Shows archive article identity; opens archive in a compatible reader |
| `image` | — | — | Opens the original image |
| `media-time` | `seconds` | `end_seconds` | Shows a reviewed time range; opens the original media without assuming fragment support |

PDF pages and text lines are one-based. Physical PDF pages count covers and front
matter; printed page labels are separate. Page/line bounds, HTML IDs, and EPUB/ZIM
member existence are validated against the selected source. Media duration is not
inferred: timestamp ranges require editorial review. Archive paths are reference
text, not extraction instructions or reader-specific deep links.

A selected reviewed map whose source hash differs fails validation. A new edition
requires a newly checked map even when old page numbers remain within bounds.
Whole-document fallback for an unsuccessful import is not permission to accept a
stale reviewed map. Keep original documents, illustrations, notices, and credits
intact; the atlas creates links rather than altered copies of source pages.

## Coverage, limits, and evaluation

`LIBRARY/INDEX/navigation-report.json` records included and omitted topic IDs, selected
source maps and provenance, per-topic deduplicated document/location counts,
reader-dependent coverage, metadata hashes, and generated output sizes. It also
reports unmapped critical assets and missing subject or learning routes for
required directly readable textbooks. Assets remain accessible through existing
indexes even when their curated topic coverage is incomplete.

To make those coverage gaps a publication error:

```bash
python scripts/build_atlas.py /media/SSD/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation --strict-coverage
```

Without `--strict-coverage`, the publisher reports gaps and writes the coverage
report. Passing strict checks establishes structural coverage, not clinical
quality, a finalized include list, or proof that a visitor can find every answer.

Topic pages, imported source contents, and A–Z lists paginate. Resource lists
contain at most 50 entries per page; topic-choice lists show at most 15 choices
before an explicit continuation. The renderer enforces a 128 KiB UTF-8 HTML limit
per page, splits lists when needed, and rejects an individual metadata entry too
large to fit. Each shared topic has one canonical page; continuations add a fixed
path component rather than reproducing every possible browsing route.

Use the generated pages with JavaScript disabled. Try representative practical
and learning tasks from several plausible entrances. Check that alternate routes
recover from wrong turns, reader-only branches are identified before opening
them, and page numbers remain usable when a viewer ignores fragments. Test the
actual phones, adapters, file managers, and desktop viewers intended for the
drive. Automated link and graph checks do not replace this finding-task review.
