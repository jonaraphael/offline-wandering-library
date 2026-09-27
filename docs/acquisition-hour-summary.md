# One-hour source-resolution result

This pass prepares **future build-time acquisition**. The public catalog contains
source URLs, editions, exact sizes, SHA-256 pins and notices; resource bodies are
not committed. Selected originals had already been downloaded to temporary storage
before the user clarified that acquisition should wait for a build. Further body
downloads stopped at that point. Existing temporary evidence was used for local
checks. **No actual library build, SSD staging or SSD copy was performed.**

## Catalog integration

The pass adds **85 download sources, 256,991,594 bytes**: 83 ordinary files plus
two documentation ZIPs. It also pins **1,655 extracted files**, including 1,373
readable HTML documents and 282 supporting files. The added source files plus
expanded outputs require **361,924,938 bytes on disk** before search and navigation.
The active catalog has **2,222 resolved file records and one unresolved map placeholder**;
1,655 of those records are outputs extracted from ZIPs, not separate downloads.
Across 49 collections, readiness is **26 ready, 13 partial, 10 unresolved**.

| Collection | Added download sources | Result | Remaining work |
| --- | ---: | --- | --- |
| FAO practical agriculture | 9 | **Ready**: 16 complete PDFs cover all 17 declared topics | Build-time acquisition of selected originals; individual redistribution restrictions remain |
| Food preservation | 7 | Partial: 17 PDFs cover all five topic groups | Reproducible dated NCHFP updates and complete current recipe context |
| PhET | 14 | Partial: 16 exact-version HTML5 files | Actual intended-device tests and broader screen coverage; desktop smoke checks passed |
| Linux/programming | 52 | Partial: 60 ordinary manuals/notice files plus full Python and SQLite HTML packages | Four OpenBSD manuals, source/notice companions and remaining external cross-references |
| Survivor Tier A | 3 | Partial, previously unresolved | Broad trades coverage, title curation and better scans; current three are explicitly historical |

The new records use HTTPS sources, not temporary local paths. Their `profiles: []`
keeps the two fixed small presets unchanged; larger resource selections acquire
the new members when a build is explicitly run. A normal build still refuses an
incomplete selection unless the caller chooses `--allow-incomplete`. No resource
was marked ready by shrinking its scope or treating a metadata recipe as content.

## Build-time documentation packages

The normal build command now downloads each selected publisher ZIP once, verifies
it, and extracts the individually pinned members into ordinary readable files.
Both packages retain every shipped member and their original local structure and
notices. They add 24,677,458 download bytes and 104,933,344 expanded bytes.
Source ZIPs, images, stylesheets, scripts and auxiliary files remain in inventory
and checksums while substantive pages enter search and reading navigation.

The implementation rejects unsafe paths, links, collisions, oversized expansion
and changed source/output bytes; completed outputs support verified reuse. A
locked catalog preserves the recipe. The selector distinguishes build downloads
from files on disk and does not count supporting files as readable knowledge.
See [package evidence](acquisition-programming-zip.md) and the
[extraction contract](archive-extraction.md). Python's publisher URL follows a
release line: a replaced upstream archive will fail the old hash and requires a
reviewed full-package refresh. No archive body was fetched during implementation.

Subject navigation gained 35 routes: 16 food/agriculture guides, 14 simulations,
three historical references and the two documentation home pages.

## Evidence and limits

- [FAO topic matrix and source/notice review](acquisition-hour-fao.md).
- [Food preservation and Hesperian investigation](acquisition-hour-health.md).
- [PhET desktop checks](acquisition-hour-phet.md) and [observations](acquisition-hour-phet-checks.json).
- [Programming source pins and archive inputs](acquisition-hour-programming.md).
- [Survivor accepted titles and excluded scans](acquisition-hour-survivor.md).

PDF verification used exact full-body hashes and structural checks, with sampled
visual review of notices, illustrations, tables and endings. It does not certify
every page or every substantive instruction. Sixteen PhET simulations passed
cold `file://` launches plus one model-changing interaction and reset in desktop
Chrome with HTTP/HTTPS blocked; mobile or other platforms were not certified.

Hesperian's same-edition Midwives 2026 back matter remains unavailable at its
publisher link. Three Survivor candidates were excluded for poor fit or scan
quality. Temporary snapshots and converted manuals without a reproducible
build-time source were not silently admitted.

The [twelve-hour plan](resolution-plan-12h.md) describes the next step and acceptance
criteria for every originally incomplete collection. Sixteen saved Kiwix input
pins now match existing compact alternatives; the [input manifest](resolution-input-pins.json)
records those mappings. Compact alternatives do not satisfy missing curated direct
editions. Regional maps still need the desired region/corridors; multilingual
Gutenberg still needs the desired reading languages.

## Verification

Catalog validation and **all 396 tests pass**, including synthetic ZIP extraction,
reuse, locked rebuilds, unsafe archives, zero-byte files, copy/verification, atlas
and selector parity. Local HTTP tests use only a loopback fixture server. The
initial sandbox run exposed missing atlas routes (fixed) and could not bind local
HTTP sockets; the complete rerun with loopback access passed.

The selector and generated guide match the active catalogs. Browser QA checked all
five presets at desktop and mobile widths: ten combinations passed with no page
errors, horizontal overflow or remote requests. Incomplete selections still
withhold a build command until explicitly accepted. Neither production content nor
the SSD was built. The two fixed small presets and all original asset pins remain
unchanged.
