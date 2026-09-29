# Lightweight offline search

Search titles, approved chapters, topics, aliases, and catalog descriptions from
`START_HERE.html` or `LIBRARY/SEARCH.html`. Results link to whole documents, reviewed
sections, or static atlas pages. Body text is not searched: no match does not mean
the library lacks the information. Search inside a relevant book or archive when
more detail is needed.

A normal build compiles existing metadata without opening source bodies. It does
not extract PDF text, enumerate archive articles, run OCR, or build postings,
embeddings, databases, or index caches. Downloading and full integrity verification
still read source bytes. No AI runs during builds or queries.

## What is included

Every selected readable asset receives a catalog result. Approved section maps
add destinations only for the exact source hash in the inventory. Topics appear
only if they lead to selected sources. Supporting packages and excluded assets
are omitted. Source titles, rights, attribution, and reader requirements travel
with the results. Descriptions are catalog/editorial text, not excerpts from
unread documents.

The existing shelf filters apply before ranking. Exact titles and aliases rank
first, then results containing all query words, then partial matches. Title and
alias words rank above description words. Matching uses Unicode normalization and
whole words, with up to 32 distinct query words and 50 results. There is no
stemming, semantic model, phrase operator, or fuzzy matching.

PDF section links use physical `#page=N` locations where supported. Other reviewed
locations show a readable locator. A section result also links to the whole
source. EPUB and ZIM entries require a compatible reader; their internal paths
are guidance, not universal reader deep links.

## Files and limits

```text
LIBRARY/SEARCH/
├── search.js                 # shared, small linear-scan runtime
├── manifest.js               # identifies this generation
├── coverage.json             # catalog/section coverage and file checksums
└── data/<sha256>.js           # one flat metadata list
```

Both entry pages load neighboring classic scripts under `file://`, without
`fetch`, a server, account, CDN, or network connection. Text is rendered with
`textContent`, and links must be safe relative paths. The browser checks generation
and record counts; the build and independent verifier check file hashes.

Profiles allow 16 MiB of generated search output (`discovery_budget_bytes`),
separate from navigation metadata, content, acquisition workspace, and free-space
reserve. Compilation stops before publication if its complete output exceeds that
allowance. There is no indexing scratch or retained index-cache allowance.

`coverage.json` lists each selected source as `catalog` or `sections` and reports
record counts and zero source-body bytes read by the compiler. These labels describe
discovery metadata, not how much of a book's knowledge has been inspected.

Keep `START_HERE.html` next to the entire `LIBRARY` folder. Some phone previews
block local scripts or neighboring links. The inline file catalog, printed paths,
and static atlas remain the fallback; test the intended browser and device.

## AI judgment, Python execution

Use the same small CLI for preparation, annotation checking, and publication:

```sh
python scripts/discovery.py prepare \
    --inventory /path/to/DRIVE/LIBRARY/INVENTORY.json \
    --asset electrical_dc --output /path/to/draft.json
```

By default this collects metadata only. Explicit `--outline` uses the existing
PDF-bookmark importer against the exact source. This editorial operation can read
and hash the PDF; it is separate from ordinary compilation. It does not read every
page looking for text. The existing `scripts/import_sections.py` additionally
supports HTML headings and produces reviewable section-map drafts.

The agent reads the prepared evidence and writes a JSON object (or list):

```json
{
  "asset_id": "electrical_dc",
  "aliases": ["direct-current circuits"],
  "topic_ids": ["dc-circuits"],
  "basis": "Publisher title and contents in the prepared source summary."
}
```

The IDs above are illustrative; use actual IDs from the inventory and topics.
Python rejects unknown fields, wrong types, invalid references, and oversized
strings. The agent launches validation instead of manually rewriting assignments:

```sh
python scripts/discovery.py annotate \
    --inventory /path/to/DRIVE/LIBRARY/INVENTORY.json \
    --navigation-dir catalog/navigation --annotations /path/to/annotations.json \
    --output /path/to/assignments-draft.yaml
```

Each annotation run targets one asset. Review the draft diff and save accepted
labels in `catalog/navigation/assignments/<asset-id>.yaml`. The command never
silently replaces approved metadata. An evidence note is not proof that a
semantic claim is correct. Section locations still use reviewed, source-pinned
maps; the annotation input cannot invent paths or page numbers.
Supply `--catalog` for custom catalogs. Python validates repository references
against the full catalog even when the drive inventory contains only a subset.

## Assemble completed downloads

Reusable metadata lives in Git: shared `topics.yaml`, per-asset
`assignments/<asset-id>.yaml`, and optional `sections/<asset-id>.yaml` under
`catalog/navigation/`. An asset needs no assignment file to receive its baseline
catalog search result. Python selects the relevant records at build time; there
are no generated per-profile indexes to keep in Git.

When curl or another downloader has saved files at their catalog destinations
under `DRIVE/LIBRARY/`, run:

```sh
python scripts/discovery.py assemble \
    --output /path/to/DRIVE --profile flash-16gb
```

This command needs no existing inventory and performs no downloads. It enforces
the same content policy as a normal build, then checks selected files against
catalog sizes and SHA-256 pins and publishes inventory,
search, and atlas for the verified subset. Missing files, partial downloads, and
size/checksum mismatches are excluded and recorded in `INVENTORY.json`. Empty
topics disappear. A `.part` file does not count as the final catalog destination.
Rerun the same command after another batch finishes to add those sources.

The inventory records `content_complete: false` while selected content is missing.
An interrupted full build remains incomplete even though its atlas is usable.
Files outside the profile and unverified files remain untouched; the full verifier
may report them as unknown. If no selected files verify, assembly stops without
publishing an empty library.

Before marking publication complete, assembly checks the inventory, locked
selection, learning coverage, search metadata, navigation links, and capacity
together. Its postflight result is saved in `LIBRARY/.owl/state.json`.

This initial admission reads source bytes to check integrity. Metadata compilation
does not parse them. Normal drive builds already use their verified inventory and
the same per-asset inputs automatically.

## Refresh metadata

Refresh a completed drive after accepting metadata:

```sh
python scripts/discovery.py build \
    --inventory /path/to/DRIVE/LIBRARY/INVENTORY.json \
    --navigation-dir catalog/navigation --output /path/to/DRIVE
```

Supply `--catalog` for a custom catalog. This refresh republishes search and atlas
together under existing ownership and locking rules. It checks the recorded
inventory, source pins, presence, and sizes, without rehashing or parsing sources.
Build information explicitly records that source verification was not repeated.
Same-size source corruption requires `python scripts/verify.py /path/to/DRIVE` to
detect. Initial builds and the standalone verifier retain their full audit.

Existing drives retain their bundled runtime until refreshed. Finish active saved
jobs with their saved implementation. Old owned generations and unrelated files
are preserved; the new build path never uses the retired full-text engine.
