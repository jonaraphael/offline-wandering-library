# Lightweight discovery: minimal architecture

**Status: implemented.** Replaces exhaustive full-text indexing with a small catalog of useful destinations shared by search and the existing atlas.

**AI supplies creative judgment and starts Python work. Python loads, validates, and builds.** No AI runs during a user's drive build or search.

## 1. What to cut

| Cut from the earlier proposal | Use instead |
| --- | --- |
| New job service, request protocol, recipe registry, and workflow states | One ordinary Python CLI; reuse existing build-job handling if needed |
| Per-source packages, package registry, independent distribution, and release machinery | Approved metadata in this repository, shipped with OWL |
| Annotation-operation language and multiple publication schemas | A small JSON/YAML annotation file with runtime validation |
| Sharded postings, token buckets, binary encoding, and cache management | One generated JavaScript data file and a simple in-memory search |
| Mandatory agent pairs and approval pipelines | Mechanical checks and focused review of questionable or consequential claims |
| Adapters for every format and millions of archive titles | Existing catalog/navigation metadata, then selected publisher outlines |
| A new taxonomy and ambitious curation quotas | Improve the existing topics and routes where users struggle |
| Integrity-receipt infrastructure and download/copy redesign | Existing source hashes, inventory, and full verifier |
| Many speculative limits and a large benchmarking program | Existing capacity controls, bounded inspection, and 20–30 finding tasks |

Do not implement extension points for these deferred systems. Add something only when a real finding or performance problem needs it.

## 2. Keep the existing inputs

Use `catalog/library.yaml` for assets and `catalog/navigation/` for topics, aliases, assignments, and source-pinned sections. These remain the only approved sources of discovery metadata.

Save enrichment piecewise: `assignments/<asset-id>.yaml` contains one asset's
topic links, aliases, and evidence notes; optional `sections/<asset-id>.yaml`
contains its reviewed locations. Keep the shared topic graph in `topics.yaml`.
Reuse the same files for every drive size. They are ordinary repository inputs,
with no package registry, generated index cache, or per-profile copies.

Every selected readable asset gets a whole-document result from its catalog entry. Add chapter destinations where already verified. Topic pages are searchable destinations too. Missing enrichment means a book-level result, never automatic extraction. Excluded assets and supporting packages must not appear as reading material.

Reuse existing aliases for everyday search phrases. “Using a multimeter” does not need a separate question-record system. Add a short provenance note where new editorial wording needs supporting evidence; reuse existing section-map pins and review fields.

Python compiles a flat list containing titles, searchable labels/descriptions, destinations, and source/shelf references. Keep rights, attribution, and reader requirements from the catalog. Search and atlas use the same selection and locations. There is no second hand-maintained catalog, vector database, or stored full-text passage collection.

## 3. One small AI/Python loop

1. **Load with Python.** The agent chooses real asset IDs and starts the loader. Python collects existing metadata and, when requested, publisher PDF outlines. It writes a compact source summary to disk.
2. **Add useful judgment.** The agent reads that summary and proposes aliases, topic assignments, or better starting points. It supplies a small annotation file, not a rewritten catalog or thousands of generated records.
3. **Validate and build with Python.** Python checks the annotations, produces an ordinary metadata diff, and generates search data and atlas pages from accepted inputs.

The implemented CLI:

```text
python scripts/discovery.py prepare --inventory INVENTORY --asset electrical_dc --output DRAFT
python scripts/discovery.py annotate --inventory INVENTORY --navigation-dir NAVIGATION --annotations INPUT --output DRAFT
python scripts/discovery.py assemble --output DRIVE --profile flash-16gb
python scripts/discovery.py build --inventory INVENTORY --navigation-dir NAVIGATION --output DRIVE
```

Preparation reads catalog metadata by default; `--outline` explicitly inspects PDF publisher bookmarks using the existing importer. Annotations produce a reviewable assignments draft, without replacing approved metadata. Build refreshes search and atlas together on a completed drive without a source-body read. See [the CLI guide](search.md) for executable examples and limits. Normal drive builds call the same compiler directly.

`assemble` admits files already downloaded to their catalog destinations, checking
size and SHA-256 first. It builds from the verified subset and reports absent or
unfinished selections. Rerunning after another curl batch finishes adds those
assets and any newly populated topics. This audit reads source bytes; the shared
metadata compiler does not parse them or invoke AI.

An illustrative annotation shape:

```json
{
  "asset_id": "electrical_dc",
  "aliases": ["direct-current circuits"],
  "topic_ids": ["dc-circuits"],
  "basis": "Publisher title and contents in the prepared source summary."
}
```

Python supplies source pins, paths, generated IDs, and output structure. It validates types, allowed fields, referenced IDs, and string lengths before applying annotations. Type hints alone are insufficient. An evidence note supports review; its presence does not prove relevance.

The agent should actually launch loading and checking work. Large parsed collections stay on disk between Python steps. If a reusable loader is missing, implement and test a small Python function rather than having the agent manually reproduce the data.

| AI/editorial judgment | Python reliability |
| --- | --- |
| Choose useful sources and user needs | Load catalogs and requested source structure |
| Suggest familiar words and sensible groupings | Validate types, IDs, paths, source editions, and duplicates |
| Judge relevance and explain ambiguity | Check locator mechanics and generate files |
| Decide what failure is worth fixing next | Run repeatable queries, link checks, and size reports |

Literal publisher metadata and already approved mappings pass through mechanically. Review new semantic claims in the normal metadata diff. Concentrate review on ambiguity and consequential recommendations; do not require another agent for every alias. Preserve source audience/scope labels and use neutral book links when suitability is unresolved.

## 4. Make search deliberately ordinary

Generate one local script containing the selected data and load it through the existing shared search widget. Keep ordinary local script loading; no server, network, or neighboring-file `fetch()` is required.

Normalize searchable strings once when loaded. On a debounced query, filter the records, scan the small list, and rank exact title/alias matches before all-word and partial matches. Prefer title matches to description-only matches. Deduplicate destinations and preserve the existing shelves.

Begin with a linear scan. Measure cold loading and query time on a target device before adding a token lookup or splitting files. Keep the data small through useful selection and concise descriptions. If it exceeds the configured discovery allowance, report the size and stop; do not silently remove baseline assets or invent sharding machinery.

Display source titles, descriptions, attribution, and reader requirements. Descriptions are not quotations from unread pages. A chapter link also offers the whole document. Archive results name the archive and article; they do not promise a universal reader deep link.

Say “Search titles, chapters, and topics.” Explain that absent body-text matches do not prove the library lacks the information. Preserve static atlas pages, title lists, and printed paths when JavaScript is unavailable.

## 5. Enrich only where it helps

Start with existing metadata. Use a small selection of practical manuals and textbooks to discover the important gaps.

Try publisher bookmarks first, then selected contents/index pages. Reuse the existing outline importer. Add another format adapter only when a finding task demonstrates its value. Whole-archive title harvesting, full-book OCR, captions, and map-footprint processing are separate possible improvements, not launch requirements.

Preparation uses explicit source selection; selected-page inspection is deferred. If useful structure is unavailable, keep the whole-document result. Do not scan an entire book looking for better metadata. A parser may read more than the requested excerpt, so page counts alone do not establish byte savings.

Check deep links against the exact edition. Printed PDF page numbers are not necessarily physical pages. Python checks the location; editorial inspection checks relevance. Ambiguous locations remain book-level links. Reuse saved preparation outputs without creating a general caching service.

## 6. Keep correctness; avoid an integrity redesign

Retain runtime validation, source pins, valid local paths, selection filtering, existing attribution/rights rules, and publication ownership/locking safeguards. Reject stale section maps and unsupported location claims. Report catalog-only versus section-level discovery rather than claiming full-text coverage.

Keep current content verification on initial drive builds. Downloading and auditing content still read its bytes; removing indexing eliminates a different cost.

The discovery compiler reads metadata and the selected inventory, with presence/size checks as needed. It does not hash source files or parse their contents. Locator inspection belongs in preparation; compilation checks its source pin against the inventory.

For a discovery-only refresh, preserve the last source-audit information and state that content was not reverified. File sizes, timestamps, and recorded hashes do not prove current integrity. A previously unaudited drive needs the existing verifier before its edition-specific links can be described as verified.

Keep `owl-verify` as the full content audit. Optimizing redundant hashing is a separate change, not a prerequisite for lightweight search.

## 7. Implementation boundaries

**1. Replace the search path.** Add a small `src/owl/discovery.py` compiler and thin `scripts/discovery.py` wrapper. Replace `build_search()` in `build.py` and passage decoding in `templates/search.js`. Reuse the shared search widget and atlas rendering; separate source inspection from rendering. Update `postflight.py` and coverage to check discovery records instead of passages.

**2. Finish the operational cutover.** Remove corpus-index cache/workspace flags from new commands and the selector. Replace index/scratch planning with an explicit discovery allowance, while keeping acquisition, unpacking, retained-output, and reserve costs. Reuse existing job handling. Update docs and retire unused extraction, SQLite-posting, full-text cache, and binary-packing code. Move parser dependencies to preparation-only use where other features do not need them.

Existing completed drives keep their bundled runtime. Active jobs finish with their saved implementation or are explicitly stopped before switching. Preserve user content, checkpoints, and unrelated files. Do not keep a parallel legacy search mode in new builds.

**3. Improve the metadata.** Let agents run preparation, submit annotations, and rerun the compiler for sources that matter. Improve a failed route or missing label before adding infrastructure.

## 8. A small acceptance check

Use about 20–30 representative finding tasks, including ordinary wording, learning, exact titles, ambiguity, and absent material. Keep some unseen by the annotation agent. Check that the actual destination is useful within five search results or three to five atlas clicks.

Also check that:

- Selected books are findable; excluded books are absent.
- Invalid annotations and stale locations are rejected.
- Discovery compilation succeeds when source-body reads are forbidden in a test.
- Local-file search and static navigation work on a tested target browser/viewer.
- Output size and cold/warm query latency fit the intended device.

Record preparation effort, agent/editorial work, generated bytes, and assembly time; report acquisition/audit time separately. Compare with existing full-text search on a small collection when practical. Do not require a terabyte-scale baseline.

The 90%/1% ambition is a hypothesis. The first release must prove a small catalog is useful; it does not need to prove a general discovery platform is complete.

## Implementation check (2026-09-28)

The complete checked-in catalog compiles to 646 destinations (562 sources and 84
topic routes), with 775,946 bytes of generated discovery output. One local run
compiled it in 11 ms with zero source-body reads. Node prepared the records in
13 ms; 1,000 queries over four terms had a 0.022 ms median and 0.054 ms p95.
These are development-machine measurements, not phone/browser performance claims.

The 22 production-metadata finding tasks in `tests/test_discovery_findability.py`
pass. They check routes within five results, including familiar aliases, exact
sources and an absent term; they do not establish factual-answer recall. Separate
tests reject malformed annotations and stale source maps, forbid source reads
during compilation/refresh, and exercise interrupted publication. The built demo
and metadata refresh pass the independent full verifier. Local-file browser QA
remains unverified because this session's browser tool blocks `file://` URLs.
