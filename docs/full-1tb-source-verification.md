# Full 1 TB source enumeration and verification

[Near-full selections for every preset](preset-capacity-plans.md) reuse this shared inventory.

Snapshot: **2026-09-29 UTC**. **7,095 candidate downloads are explicitly enumerated and passed their applicable source checks**, with **7,095 per-asset pseudoindexes** saved. They add **712,148,641,197 retained bytes** to the existing selection. Source verification does not promote these candidates into the ready catalog.

Existing and candidate files total **986.668 GB**. With reader growth, discovery and existing metadata allowances, the modeled footprint is **987.261 GB**, leaving **2.739 GB** below the **990 GB library/support ceiling**. A further **5 GB free reserve** and **5 GB filesystem/partition margin** remain outside that ceiling. No provisional Canadian, school or practical-manual byte bucket is counted as content.

| Source cohort | Download files | Retained GB |
| --- | ---: | ---: |
| [Whole ZIM archives](../catalog/acquisition/full-1tb-capacity-20260928/archives.json) | 10 | 442.130 |
| [Northeastern US topography](../catalog/acquisition/full-1tb-capacity-20260928/usgs-northeast.json) | 3,383 | 157.297 |
| [MD / DE / DC / VA topography](../catalog/acquisition/full-1tb-capacity-20260928/usgs-mid-atlantic.json) | 1,038 | 51.382 |
| [West Virginia extension](../catalog/acquisition/full-1tb-capacity-20260928/usgs-appalachian.json) | 386 | 20.436 |
| [Nearby Canada and northern Great Lakes](../catalog/acquisition/full-1tb-capacity-20260928/canada-nearby.json) | 1,051 | 30.874 |
| [English school curriculum PDFs](../catalog/acquisition/full-1tb-capacity-20260928/school.json) | 1,220 | 9.965 |
| [Practical manuals](../catalog/acquisition/full-1tb-capacity-20260928/practical-manuals.json) | 7 | 0.064 |

Canadian retained sizes count each source ZIP and **all 2,099 extracted files**: 15,344,108,911 ZIP bytes + 15,530,019,639 member bytes. Each of the 1,051 sheets has one selected PDF. Supporting XML and notices are retained without separate atlas entries. The kindergarten manifest is a **subset** of the school manifest and is never counted again.

## What was verified

| Cohort | Checks completed | What remains |
| --- | --- | --- |
| Ten ZIMs | Final HTTP size, publisher SHA-256 header, bounded binary ZIM header, internal checksum-position/size consistency | Full-body hash comparison on acquisition; packaged-reader and embedded-media tests offline; content/rights review |
| 4,807 USGS PDFs | Every dated URL returned a positive HEAD size and a 206 range response with PDF magic; Content-Range size and ETag match the HEAD | Full-file hashes, page readability and authoritative footprint/coverage review |
| 1,051 Canadian ZIPs/PDFs | Every source is offered in an official directory; HEAD plus central directory size accounting; safe unencrypted regular member paths; PDF local header and bounded decompression expose valid PDF magic | Complete ZIP/member hashes, ZIP CRC checks on extraction, full PDF readability and geographic gaps |
| 1,220 English curriculum PDFs | Every URL listed on a publisher page; matching HEAD/range sizes and ETags; valid PDF signatures | Full-body checks for 1,181 PDFs; component dependency, pedagogy and progression review |
| 39 kindergarten PDFs | Complete bodies downloaded, locally SHA-256 hashed, parsed without password and sample pages rendered | Editorial sequencing and requirements review; six ancillary Skills PDFs have only header/signature checks |
| Seven practical PDFs | Complete bodies downloaded, locally hashed and parsed; representative rendered pages visually inspected | Task-depth and rights review before catalog admission |

**46 small files** were downloaded completely, totaling **233,685,125 bytes**. The large ZIMs/maps were checked with small byte ranges. ZIP CRCs and ETags are not mislabeled as SHA-256 hashes. No large body was indexed.

## Corrections and exclusions

- **240 USGS metadata lengths differ by exactly one byte** from the mutually consistent HEAD/Content-Range lengths. Both values and the signed difference are retained in [size corrections](../catalog/acquisition/full-1tb-capacity-20260928/evidence/usgs-size-corrections.json). The manifest uses the observed HTTP length; acquisition must still verify the actual body.
- The Canadian government's original **ftp.maps.canada.ca HTTPS host works**. The earlier replacement-host 403s are resolved using the original download links published in the official sheet index. All 945 original sheets and 106 northern Great Lakes/Lake Superior extension sheets passed. See [Canadian records](../catalog/acquisition/full-1tb-capacity-20260928/canada-nearby.json).
- Core Knowledge HTML pagination repeated its first page. The public publisher API supplied **407 unique records**; **366** English curriculum pages were retained and **41** unrelated/non-English/adaptation pages excluded. Fourteen rate-limited pages succeeded on a later slower retry. All retained pages now have component inventories.
- **1,233 distinct PDF URLs** were offered by those pages. **13 Spanish translations** were excluded from the English selection. All 1,220 selected PDFs passed source checks. Shared PDFs are counted once.
- Three advertised PDF URLs returned **HTML**: Penn State's private-water guide and well-maintenance download URLs, and the NRCan 2002 wood-heating PDF URL. They are in [rejected sources](../catalog/acquisition/full-1tb-capacity-20260928/rejected-sources.json), contribute zero bytes and have no pseudoindexes. Water and heating gaps remain open.

## School coverage and completeness

The [unit/component matrix](../catalog/acquisition/full-1tb-capacity-20260928/school-units.json) records each publisher page, grade, series, teacher/student roles, component URLs and selected asset IDs. It includes offered preschool–grade 8 CKLA and K–8 CKMath/CKSci/CKHG material. Separate state adaptations and standalone literary enrichment are excluded; required readers offered within curriculum units are retained for unit review.

The **39 fully hashed kindergarten Skills PDFs cover the offered components on units 1–10**. The broader school inventory also includes **six ancillary kindergarten Skills PDFs**. These additional materials must be acquired and reviewed before claiming the kindergarten sequence is ready. PDF files labeled “Online Resources” may themselves refer to live websites; their presence does not make those dependencies available offline.

The matrix flags pages without an explicit teacher component as review cues. Supplemental pages can legitimately lack their own guide. No automatic “complete curriculum” or adequate-topic status is inferred from file counts or card labels.

## Practical sources selected

| Source | Pages | MB | Brief evaluation |
| --- | ---: | ---: |
| [Homebuilders' Guide to Earthquake-Resistant Design and Construction — FEMA P-232 (2024)](https://www.fema.gov/sites/default/files/documents/fema_p-232_september2024.pdf) | 266 | 43.171 | Illustrated seismic housing design reference; not a general weatherproofing or repair course. |
| [Energy Saver Guide (2022)](https://www.energy.gov/sites/default/files/2022-08/energy-saver-guide-2022.pdf) | 56 | 3.251 | Household efficiency and weatherization overview. Does not teach complete off-grid wiring or generator service. |
| [Compendium of Sanitation Systems and Technologies — second edition](https://www.eawag.ch/fileadmin/Domain1/Abteilungen/sandec/schwerpunkte/sesp/CLUES/Compendium_2nd_pdfs/Compendium_2nd_Ed_Lowres_1p.pdf) | 180 | 9.483 | Illustrated comparison of sanitation technologies and systems. Site design and cold-climate suitability still require review. |
| [Sewing Shortcuts — NMSU C-104](https://pubs.nmsu.edu/_c/C104.pdf) | 12 | 1.124 | Illustrated sewing techniques for hems, zippers and fasteners. Assumes basic machine sewing; does not close the beginner hand-mending gap. |
| [A Seed Saving Guide for Gardeners and Farmers (2010)](https://seedalliance.org/wp-content/uploads/2010/04/seed_saving_guide.pdf) | 30 | 5.463 | Historical offered PDF, distinct from the 2026 web revision. Crop-specific seed-saving supplement; regional applicability needs review. |
| [ARES Field Resources Manual — ARRL (copyright 2005–2008)](https://www.arrl.org/files/file/ARES_FR_Manual.pdf) | 90 | 1.363 | Historical emergency radio operating reference; not current licensing or a complete novice radio course. Retain copyright notices. |
| [Root Cellars — University of Alaska Fairbanks HGA-00331](https://smfarm.cfans.umn.edu/sites/smfarm.cfans.umn.edu/files/2021-03/UAlaskaRootCellarsHGA-00331-2.pdf) | 4 | 0.245 | Compact cold-climate storage and cellar reference; not a complete engineered cellar construction plan. |

The seed-saving PDF is the offered **2010 edition**, not the publisher's 2026 web revision. NMSU's sewing guide is **revised 2015** and the UAF cellar guide **revised 2020**. ARRL's file bears **2005–2008 copyright** and does not establish current licensing rules. Historical context remains explicit.

## Saved artifacts and repeatable checks

- [Capacity ledger](../catalog/acquisition/full-1tb-capacity-20260928/plan.json): all exact byte sums, selected scopes and remaining headroom.
- [Per-asset pseudoindexes](../catalog/acquisition/full-1tb-capacity-20260928/pseudoindexes/): **3,565,685 bytes** of YAML using the existing navigation schema, outside active navigation until each asset is admitted.
- [Evidence](../catalog/acquisition/full-1tb-capacity-20260928/evidence/): per-source HTTP observations, range/signature results, ZIP directories and local full-body SHA-256 results. HEAD observations correctly record zero response-body bytes.
- [Validation report](../catalog/acquisition/full-1tb-capacity-20260928/validation.json): metadata, deduplication, source-evidence consistency, capacity and navigation-schema results.
- [HEAD refresh input](../catalog/acquisition/full-1tb-capacity-20260928/source-probe-requests.json): the 7,095 source URLs and expected sizes in the existing probe tool's format. This is a verification queue, not a build queue.

Run the local checks without network or source-body reads:

```sh
.venv/bin/python scripts/validate_capacity_spec.py
```

To refresh availability and publisher pins with the existing bounded tool, using a new cache directory:

```sh
.venv/bin/python scripts/probe_source_batches.py \
  catalog/acquisition/full-1tb-capacity-20260928/source-probe-requests.json \
  --output .owl/capacity-refresh.json \
  --cache-dir .owl/capacity-refresh --workers 2 --request-interval 0.5
```

This HEAD-only refresh does not repeat the range/ZIP checks. A “pending” result can mean the publisher supplies no whole-file SHA-256; it does not mean a successful HEAD has verified the body. Preserve the stronger saved evidence and compute complete hashes on acquisition.

The [topic-by-topic completion plan](full-1tb-coverage-plan.md) remains authoritative for intended depth, current resources, gaps and next selections. **No topic has been upgraded to adequate in this pass.** Source availability, whole-body integrity, offline usability and editorial adequacy are distinct gates.
