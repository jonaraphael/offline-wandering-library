# OWL target architecture

## Catalog and recommendation

The planner keeps immutable download pins in the build catalog and gives each
selectable asset a primary planning domain, depth level (L0 essentials through
L4 deep collections), rank within that domain and level, and an optional edition
group. Regional topography and non-English Wikipedia require explicit
selection. Alternative editions are available for curation.

Each asset carries a pinned URL, size, digest algorithm and value, license and
redistribution decision. Verify publisher digest provenance separately from
verification of downloaded bytes. Record observed CORS and byte-range support
with the measurement scope. Keep archive-source and reader dependencies
explicit. A search shard reference binds its format version and digest to the
asset's content hash.

Python compiles the capacity ladder from the catalog. Python and JavaScript
load those same choices, accept decimal bytes and cap default content at 1 TB.
The compiler deducts filesystem headroom, free reserve, readers and room for
metadata and discovery. Every recommendation includes the entire CRITICAL tier
and small samplers for enrichment, computing and college study.

The reviewed order in `catalog/capacity-order.yaml` lists collection additions
and replacements. The compiler computes each transition from exact catalog
bytes and the reserve policy. Most steps add one collection. Collections stay
in the persistent core from their final entry onward. The compiler rejects
any removal of a file with attribution to health, water and sanitation, food
preservation, agriculture, or shelter. MDWiki enters before the large school
and general-reference archives. The default uses illustrated English Wikipedia
as its sole English Wikipedia edition. Compact Wikipedia editions also
contribute to protected fields and remain manual choices.

Each replacement that lowers an attributed field requires an incoming file of
at least 10% of the drive label whose primary field ranks higher. The five
protected fields take first priority because they cover basic survival needs.
Hand tools and repair follow because they help maintain the equipment used to
meet those needs. Navigation follows the trades. General reference ranks next
for broad offline lookup, then school math and science, then languages.
Culture, college study, and computing share the last rank. The compiler
uses the highest priority among the qualifying files entering a step. A
collection of several files qualifies only through an individual file.

The tests verify each transition and the final byte before the next transition.
The 14 checkpoints each retain at least 97% of the usable knowledge budget.
The 90% label-fill target has gaps between checkpoints before some larger
files fit. The current order retains at least 86.64% of the label at every byte capacity from
16 GB through 1 TB.

Each tier's retention is its selected knowledge bytes divided by its knowledge
bytes in the 1 TB default. USEFUL retention must meet or exceed NONESSENTIAL
retention at every drive size. At each checkpoint, a domain with at least 1 GB in
the full default keeps at least one third of overall retention. A domain can fall
short when its next asset exceeds 10% of the drive label. The next asset is the
earliest omitted contributor from the 1 TB default by planning level, rank and ID.
For multi-subject archives, the catalog records attribution weights and their
basis. These shares estimate subject breadth. Editorial review of actual tasks
and relevant source editions determines coverage.

## Browser build and drive layout

Round 2 uses the static Pages planner and a writable directory selected in
Chromium. The browser asks the user to confirm available capacity because the
directory handle exposes no volume statistics. The Python CLI can check free
space using the OS and serves as the fallback for browsers and sources that
cannot complete the browser flow. Kiwix routes through its CORS mirror. Other
sources need measured browser access, an authorized mirror or the CLI path.

The build streams into the selected directory. It verifies bytes before
publishing content and records completed parts on the same drive. It writes
parts below the FAT32 file limit where the selected reader supports a split
format. Browser builds need restartable checkpoints that survive a closed tab,
sleep or drive removal. The drive starts at `START_HERE.html`. Documents,
archives, readers, static indexes, search data, build state and checksums live
under `LIBRARY/`, with stable relative paths and visible manual locators.

## Offline discovery

Round 3 precomputes one versioned shard per source digest. A shard contains
stable PDF page or ZIM article locators, titles and passages, lexical postings,
and compact semantic retrieval data. The manifest pins shard digests and schema
versions. The builder assembles the manifest for the selected resources and
copies only their shards and the shared query runtime. Static navigation works
without scripts. Search uses local script-loadable chunks under `file://`.
Phone and desktop tests determine which viewers can run search or open split
archives, and which need a reader provisioned before going offline.
