# OWL target architecture

## Catalog and recommendation

Round 1 keeps immutable download pins in the build catalog and gives each
selectable asset a primary planning domain, depth level (L0 essentials through
L4 deep collections), rank within that domain and level, and an optional edition
group. The ten practical domains remain first-class. General reference, additional
education, and culture can grow independently of emergency material. An edition
group contains one selected variant at a time. An upgrade must preserve the
earlier variant's subject coverage. Regional topography and non-English
Wikipedia require explicit selection.

Each asset carries a pinned URL, size, digest algorithm and value, license and
redistribution decision. Verify publisher digest provenance separately from
verification of downloaded bytes. Record observed CORS and byte-range support
with the measurement scope. Keep archive-source and reader dependencies
explicit. A search shard reference binds its format version and digest to the
asset's content hash.

Python compiles a capacity ladder from the catalog. Python and JavaScript consume
the same ladder, and shared test vectors check both consumers against the same
plans. Capacity is decimal and the default stops growing at 1 TB. The planner
deducts filesystem headroom, free reserve, readers and index/workspace before
recommending content. Advancing to level L requires every domain to have
reached its highest available level below L. A domain with no such offering has no prerequisite. The same rule applies
at each transition. Common capacity checkpoints bound the packing passes.
The compiler tries breadth and depth orderings using whole collections and the
incremental cost of edition upgrades. Within each packed band, smaller
eligible steps enter first. At intermediate capacities the planner takes the
longest fitting prefix. Large archives can leave gaps between
checkpoints. The default preserves selected assets as capacity
grows, except for upgrades within a group. Explicit user additions, removals and
edition changes can change that balance and still pass through the fit check.

Measure depth by the highest selected level per domain. Measure proportional
retention for each domain as its selected bytes divided by its 1 TB selected
bytes. Compare with overall selected bytes divided by 1 TB selected bytes. At
the capacity checkpoints, each domain must keep at least 7.5% of its
proportional share. For example, at 100 GB of selected content against a
1,000 GB reference, a domain must keep at least 0.75% of its full-selection
bytes. This floor detects missing foundations while allowing indivisible
archives. The planning domains beyond the ten practical domains cover general
reference, advanced study, computing, culture and languages. Reader bytes are
accounted for as support.

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
