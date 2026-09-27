# Acquisition implementation and remaining content gaps

The reusable acquisition workflow is implemented. It closes the dated
food-preservation snapshot gap, registers two preserved programming source
companions, and adds the complete source-pinned OpenSSH portable edition. It does **not** make the three larger presets content-complete.
No new library bodies were downloaded during this implementation. All new
content pins come from previously preserved local evidence; online work fetched
bounded publisher metadata only.

## Completed

- `scripts/acquire_content.py` provides audit, metadata discovery, local
  inspection, local-record preparation, candidate staging and concise reporting.
  Detailed evidence and checkpoints stay under `.owl/acquisition/`; versioned
  recipes and accepted manifests contain portable source identities.
- Approved recipes run through the normal locked build. Inputs and linked
  companions must be pinned and selected; outputs must match reviewed whole-file
  hashes before joining search, navigation, inventory and checksums. Pending
  recipes cannot be enabled with `--allow-incomplete`.
- Interrupted generation reuses verified inputs and staged outputs. Recipe
  ownership includes source/dependency pins. Storage separates downloads,
  expanded files, derivatives, generation work/repair, search, scratch and caches.
- The September 18 food edition preserves 27 complete updates, eight linked
  recipe/prerequisite pages and the UGA oils article, including nine tables and
  four images. Six linked PDF companions are required dependencies. All sources
  and rendered output are pinned; the edition remains explicitly dated.
- The complete OpenSSH portable 10.5p1 edition replaces the eight partial OpenBSD
  default manuals in larger presets with 16 manuals, original roff companions and
  the release notice. All 33 generated outputs are pinned; 32 offline browser
  checks pass. [Edition and build evidence](acquisition-openssh.md).
- Linux man-pages 6.19 and OpenSSH portable 10.5p1 original release archives now
  accompany the programming manuals and notices. Their 4,241,795 bytes count as
  supporting files, adding no artificial knowledge coverage.
- Reusable adapters cover complete HTML sections, reviewed ZIM selections,
  durable/legacy Stack Overflow XML selections, ordinary lesson pages, and
  bounded metadata proposals. Explicit legacy classifications override durable
  ones; search hides legacy results by default and provides a visible filter.
- Offline browser scripts check document structure/layout/links, synthetic
  lesson playback and native captions, and PhET interactions/reset. Large media
  remain ordinary files rather than in-memory static-export payloads.
- Spanish Wikipedia and multilingual Gutenberg remain optional. The fixed
  16/64 GB presets, compact book/Stack Exchange editions, and original larger
  content windows remain intact.

The accepted manifests are [food updates](../catalog/acquisition/food-updates.yaml)
and [programming companions](../catalog/acquisition/programming-source-companions.yaml).
Food [source evidence](../catalog/acquisition/food-updates-evidence.json) and
[browser evidence](../catalog/acquisition/food-updates-browser-evidence.json)
bind the edition to its reviewed bytes. Desktop and mobile browser checks found
all images/tables, valid internal anchors, every companion PDF, no page overflow,
and no network requests or browser errors.

## Remaining external content and review requirements

| Collection | Actionable remaining work |
| --- | --- |
| Hesperian | The exact missing 2026 midwives back-matter source returns HTTP 404. Its body and whole-file checksum remain unavailable; keep 270/271 status. |
| Maps | [Frozen proposal](acquisition-maps.md): 75 sheets, 2,107,297,354 bytes, complete New England publisher-footprint coverage using 1:100,000 sheets and 1:24,000 gap supplements. The identified all-50-states National Atlas overview adds 19,527,583 bytes (2,126,824,937 combined). All 76 SHA-256 pins and PDF coverage/scale/notice reviews remain pending. Exact HEAD checks corrected 65 stale inventory sizes. |
| Survivor A/B | Metadata enumerates 1,963 A candidates and 775 B candidates. Coverage matrices and review queues are generated; three previously reviewed A works remain accepted. New works still need whole-file pins, complete practical-content review, scan checks and recorded exclusions. |
| Direct editions | Appropedia, CD3WD, iFixit, Low-tech and the Wikipedia lifeboat still need reviewed article/book lists and verified output/dependency manifests. The additional full-preset expansion remains separate. |
| Stack Overflow | [Four official input identities](acquisition-source-pins.md) now cover Posts, Comments, Users and PostLinks, totaling 31,166,034,729 download bytes. Publisher hashes are SHA-1/MD5, so whole-file SHA-256, safe extraction, XML/dependency pins and reviewed question selections remain pending. |
| Khan/TED | Ordinary media/caption rendering is implemented and browser-tested. Actual English course/lesson manifests, media pins and unsupported essential lesson decisions remain pending. |
| Programming | Complete portable OpenSSH 10.5p1 manuals close the four missing functional manuals and add the rest of the release. Outside-release system/platform references remain explicit; programming stays partial. |
| PhET | The [portable runner and pinned check manifest](phet-browser-qa.md) now pass 32/32 checks: 16 simulations at desktop and phone-sized viewports with reviewed interaction/reset state. Physical-device usability and broader screen coverage remain outstanding. |

[Portable discovery evidence](../catalog/acquisition/discovery-evidence.json)
records publisher URLs, metadata hashes, observed counts and explicit blockers.
Map discovery uses the official [USGS access routes](https://www.usgs.gov/the-national-map-data-delivery/topographic-map-access-points)
and never truncates a selected sheet list to claim complete coverage. Historical
maps retain publication dates and scale; boundary holes are not dismissed as a
tolerance.

## All five default plans

These are exact pinned file bytes, including supporting sources and generated
outputs. Knowledge shortfalls exclude supporting files and reader software.
All five plans fit their nominal capacity allowances. A fitting plan does not
certify a completed physical build or a full-corpus search measurement.

| Preset | Pinned files, bytes | Incomplete collections | Knowledge minimum shortfall |
| --- | ---: | ---: | ---: |
| 16 GB | 9,696,060,616 | 0 | 0 |
| 64 GB | 40,272,521,791 | 0 | 0 |
| 256 GB | 195,427,459,956 | 9 | 0 |
| 512 GB | 261,984,210,179 | 11 | 128,511,355,829 |
| 1 TB | 353,192,847,870 | 16 | 397,302,718,138 |

The 16/64 GB selections remain exactly 436/450 assets. Larger content targets
remain 190–210, 390–420 and 750–820 decimal GB. No padding or duplicate broad
editions were added to fill those windows.

## Repeatable validation

Final validation passed **all 10 checks**, including the **612-test regression
suite**, all five plans and generated-file freshness. The default environment
skipped three optional geometry tests; a separate 49-test map/provider/pin pass
with Shapely installed passed without skips. [Portable validation evidence](../catalog/acquisition/validation-evidence.json)
records the checked catalog/profile hashes, exact plan counts and raw-report digest.
The bound PhET browser run passed 32/32 checks; OpenSSH passed 32/32 page checks,
83-file local build verification and a fully reused second build.

```sh
python scripts/validate_acquisition.py --full --export-evidence catalog/acquisition/validation-evidence.json
python scripts/acquire_content.py audit
python scripts/acquire_content.py discover --resource regional-maps,survivor-tier-a,survivor-tier-b --offline
python scripts/acquire_content.py report --only-changed
```

The validation runner checks the regression suite, catalog, all five no-download
profile plans, small-preset invariants, optional language selection and generated
selector/document freshness. Tests cover changed sources, interrupted download
and generation, missing dependencies, duplicate/path collisions, exclusion
propagation, output hashes, map holes, preserved document structure and legacy
search ranking. Full logs remain local and summaries are bounded.

Production builds, paused-drive recovery and physical-device certification remain
separate work. A source URL or recipe without pins and required review is never
reported as ready content.
