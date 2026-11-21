# OWL target architecture

## Catalog and recommendation

The planner keeps immutable download pins in the build catalog and gives each
selectable asset a primary planning domain, depth level (L0 essentials through
L4 deep collections), rank within that domain and level, and an optional edition
group. Regional topography and non-English Wikipedia are opt-in at 1 TB and
below. Alternative editions are available for curation.

Each asset carries a pinned URL, size, digest algorithm and value, license and
redistribution decision. Verify publisher digest provenance separately from
verification of downloaded bytes. Record observed CORS and byte-range support
with the measurement scope. Keep archive-source and reader dependencies
explicit. A search shard reference binds its format version and digest to the
asset's content hash.

Python compiles the capacity ladder from the catalog. Python and JavaScript
load those same choices and accept decimal bytes. Larger drives begin with
the 1 TB selection. Regional maps and topo sheets enter first, followed by
non-English Wikipedia and the remaining pinned collections in tier and size
order. The expansion targets 90% of the drive label when enough distinct
content exists.
The compiler deducts filesystem headroom, free reserve, readers and room for
metadata and discovery. Every recommendation includes the entire CRITICAL tier
and small samplers for enrichment, computing and college study.

The reviewed order in `catalog/capacity-order.yaml` lists collection additions
and replacements. The compiler computes each transition from exact catalog
bytes and the reserve policy. Most steps add one collection. Collections stay
in the persistent core from their final entry onward. An addition can specify
a registered edition as `collection=edition`. When the collection is already
selected, its incoming edition must have more knowledge bytes and retain or
increase attributed bytes in every field. English Wikipedia uses the same
weights in all four editions and grows from top at 16 GB to mini, nopic, and
illustrated maxi. MDWiki enters before the large school and general-reference
archives.

The 15 core lists in `catalog/capacity-order.yaml` identify specific L0 and
L1 sources. The compiler keeps those sources at every transition and compares
each field with its highest earlier attributed byte count. At least half of
that peak must remain.

Health, water and sanitation, food preservation, agriculture, shelter, and
navigation stay at or above their previous attributed bytes at each transition.
An individual file that contributes to these fields can leave only through a
qualifying edition upgrade. World maps stay selected from their first entry.

Each replacement that lowers an attributed field requires an incoming file of
at least 10% of the drive label whose primary field ranks higher. Five
survival fields take first priority.
Hand tools and repair follow because they help maintain the equipment used to
meet those needs. Navigation follows the trades. General reference ranks next
for broad offline lookup, then school math and science, then languages.
Culture, college study, and computing share the last rank. The compiler
uses the highest priority among the qualifying files entering a step. A
collection of several files qualifies only through an individual file.

The tests verify each transition and check the selection through the final
byte before the next addition fits. The core and earlier-peak floors can
leave more free space ahead of a large archive. The browser fills toward
90% using deliverable collections and limits each proposed addition against
the smallest later delivered core and depth selection for its fields.

Each tier's retention is its selected knowledge bytes divided by its knowledge
bytes in the 1 TB default. USEFUL retention must meet or exceed NONESSENTIAL
retention at every compiled step.
For multi-subject archives, the catalog records attribution weights and their
basis. These shares estimate subject breadth. Editorial review of actual tasks
and relevant source editions determines coverage.

## Browser build and drive layout

The static Pages planner builds into a directory selected in Chromium.
The directory handle exposes no volume statistics. The site attempts an
allocation probe on macOS and Windows and otherwise asks the user to confirm capacity. The Python CLI can check free
space using the OS and serves as the fallback for browsers and sources that
cannot complete the browser flow. Kiwix routes through its CORS mirror. Other
sources need measured browser access, an authorized mirror or the CLI path.

The build streams into the selected directory. It verifies bytes before
publishing content and records completed parts on the same drive. Large ZIMs checkpoint in 1 GiB parts. The browser can join those parts
on the drive after verification. The journal supports resuming after
a tab closes or after reconnection to the same drive. The drive starts at `START_HERE.html`. Documents,
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
