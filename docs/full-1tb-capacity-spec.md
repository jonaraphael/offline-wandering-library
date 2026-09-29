# Near-full 1 TB capacity specification

[Near-full selections for every preset](preset-capacity-plans.md) reuse this shared inventory.

Target **990 GB of library and support data** on a nominal **1,000 GB drive**. The current source inventory models **987.261 GB**, leaving **2.739 GB** for metadata growth, edition changes and later small reviewed gap manuals. The drive also retains **5 GB actually free** and a separate **5 GB filesystem/partition margin**.

The ready preset contains **274.519 GB** of pinned files. **7,095 newly enumerated downloads add 712.149 GB**, including all retained Canadian ZIPs and extracted files. Existing plus candidate file bytes total **986.668 GB**. Reader growth and existing metadata/discovery allowances add **0.594 GB**. These candidate bytes are fully named and measured; they are not yet admitted to the ready catalog.

[Source verification report](full-1tb-source-verification.md) · [Capacity ledger](../catalog/acquisition/full-1tb-capacity-20260928/plan.json) · [Topic-by-topic completion plan](full-1tb-coverage-plan.md)

## Source allocation

Decimal GB throughout; exact integer values are in the ledger.

| Source cohort | Download files | Retained GB |
| --- | ---: | ---: |
| [Whole ZIM archives](../catalog/acquisition/full-1tb-capacity-20260928/archives.json) | 10 | 442.130 |
| [Northeastern US topography](../catalog/acquisition/full-1tb-capacity-20260928/usgs-northeast.json) | 3,383 | 157.297 |
| [MD / DE / DC / VA topography](../catalog/acquisition/full-1tb-capacity-20260928/usgs-mid-atlantic.json) | 1,038 | 51.382 |
| [West Virginia extension](../catalog/acquisition/full-1tb-capacity-20260928/usgs-appalachian.json) | 386 | 20.436 |
| [Nearby Canada and northern Great Lakes](../catalog/acquisition/full-1tb-capacity-20260928/canada-nearby.json) | 1,051 | 30.874 |
| [English school curriculum PDFs](../catalog/acquisition/full-1tb-capacity-20260928/school.json) | 1,220 | 9.965 |
| [Practical manuals](../catalog/acquisition/full-1tb-capacity-20260928/practical-manuals.json) | 7 | 0.064 |

| Additional accounting | GB |
| --- | ---: |
| Existing pinned files | 274.519 |
| Reader growth and existing discovery/metadata allowances | 0.594 |
| Unfilled metadata/edition-growth allowance | 2.739 |
| Actually free reserve | 5.000 |
| Filesystem/partition margin | 5.000 |
| **Nominal drive allocation** | **1,000.000** |

The former 48.618 GB Canadian, 10 GB school and 5 GB practical-manual ceilings have been replaced by actual enumerated source totals. Unused capacity funded complete adjacent map cohorts: **386 West Virginia sheets** and **106 northern Great Lakes/Lake Superior sheets**. There is no duplicate source-URL padding and no arbitrary cutoff within these declared cohorts.

## Storage practicalities

- **Units:** 1 TB is 1,000,000,000,000 bytes, displayed as about 931 GiB. This unit conversion is not a separate capacity loss. Actual filesystem capacity still matters. [Manufacturer explanation](https://www.seagate.com/support/kb/why-does-my-hard-drive-report-less-capacity-than-indicated-on-the-drives-label-172191en/).
- **Readers:** four pinned packages totaling **439,739,570 bytes** are already included in the baseline. Their total 1 GB budget adds only **560,260,430 bytes** for growth/setup. Measure any unpacked on-drive reader installation against that allowance.
- **Pseudoindexes:** the saved 7,095 drafts occupy **3.566 MB** of raw YAML. The existing **16 MiB discovery** and **16 MiB metadata** allowances remain; generated output must fit the runtime budget. No full-text-index workspace is needed.
- **Canadian extraction:** retain both the original ZIP and every extracted file. Account for XML/notices as well as PDFs. Validate safe member paths, sizes and CRCs while unpacking, then hash the actual bodies.
- **Downloads:** use the default in-place spool, which renames a verified completed download into place. A second full download cache requires a separate filesystem. Updating a giant ZIM while retaining its old edition also requires external staging space.
- **Actual drive gate:** the existing builder checks real free bytes on each relevant filesystem, including its configured reserve. If the formatted destination cannot fit the plan, reduce the reviewed selection. Neither nominal capacity nor a successful source probe bypasses this check.

## Archive selections: brief evaluation

| Candidate | GB | Useful contribution | Limit that remains visible |
| --- | ---: | --- | --- |
| Khan Academy English, 2023-03 | 180.007 | School explanations and lessons | Dated snapshot. Verify embedded video and exercises; do not infer a complete offline learning system. Review mixed school/college content before assigning default utility. |
| Survivor Library, 2026-09 capture | 220.348 | Broad historical practical and technical reading | Capture date does not make old books current. Check embedded PDF availability and overlap with existing Survivor, Gutenberg and CD3WD material. No automatic credit for modern clinical, preservation or construction tasks. |
| Crash Course English, 2026-05 | 23.035 | School science, history and subject explanations | A video supplement, not exercises, assessment or a curriculum. Review college-level portions and offline playback. |
| Energypedia English, 2026-06 | 0.800 | Energy-access and renewable-energy background | Does not replace a complete small-system construction or maintenance manual. |
| Gardenology, 2026-09 | 0.112 | Horticultural reference | Local growing and diagnosis coverage remain unreviewed. |
| Wikispecies, 2026-07 | 3.431 | Taxonomic reference | Not field identification or an edible-plant guide. |
| MedlinePlus, 2025-01 | 1.945 | Patient health education | Dated supplement, not a current clinician or drug-dosing reference. |
| OER4Schools, 2025-10 | 1.242 | Teacher development and classroom examples | Not a student curriculum; review applicability of the classroom context. |
| VOA Learning English, 2025-01 | 7.094 | English listening and language learning | Does not close beginning-child-literacy gaps. Verify lesson and worksheet completeness. |
| Encyclopedia of the Environment, 2026-05 | 4.117 | Environmental-science background | Not a water-treatment or sanitation procedure manual; archive contents remain uninspected. |

All ten exact dated ZIM URLs, sizes, publisher SHA-256 pins and bounded binary-header checks are saved. Full-body hash verification, packaged-reader tests of representative content/media and source/rights review remain required. The capture date does not modernize old material. School/advanced-content mixtures need utility-policy review; college, fiction and computing remain opt-in under the existing selection policy.

## Geographic selection

**US core:** CT, MA, ME, NH, RI, VT, NY, NJ and PA: **3,383 current 1:24,000 sheets**. **MD/DE/DC/VA add 1,038** and **WV adds 386**, excluding all previously selected cell IDs. Border sheets are included once when their publisher state list intersects the chosen states.

Python joins current metadata to dated product filenames within the same [USGS bulk metadata release](https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/Metadata/topomaps_all.zip). No mutable `Current/` URL or guessed dated path is used. All **4,807 dated PDF sources** passed size/signature checks. The earlier New England planning subset overlaps this inventory and must not be added again.

**Canada:** **1,051 offered 1:50,000 sheets** intersecting **90°W–59°W, 42°N–50°N**. This comprises the original 945-sheet southern Ontario/Québec/Maritimes envelope and a 106-sheet northern Great Lakes/Lake Superior continuation. It is a bounded geographic envelope, not full provincial coverage. Select the latest offered CanTopo GeoPDF/PDF, otherwise the latest offered CanMatrix print PDF, one edition per sheet, using links offered in official directories.

Canadian downloads now work through the original public **ftp.maps.canada.ca HTTPS host** named by the [official index](https://www.download-telecharger.services.geo.ca/pub/nrcan_rncan/raster/topographic/index/topographic_index_50k.kml). The ZIP/member inventory measures **30.874 GB retained**. Directory checks and PDF-prefix checks passed; legacy editions do not establish current roads or complete geographic coverage. Full hashes, readable-page samples and authoritative footprint-gap comparisons remain admission tasks for both countries.

## School and practical depth

The [school manifest](../catalog/acquisition/full-1tb-capacity-20260928/school.json) contains **1,220 English PDFs**, **9.965 GB**, from all **366 selected publisher pages**. The [component matrix](../catalog/acquisition/full-1tb-capacity-20260928/school-units.json) records grades, series, teacher/student roles and exact file associations, including missing-review flags. The [39-file kindergarten subset](../catalog/acquisition/full-1tb-capacity-20260928/ckla-kindergarten.json) is fully downloaded and locally hashed; six additional kindergarten Skills ancillary PDFs are included in the wider manifest and still need full-body checks. Offered-file completeness does not establish a complete teaching sequence or eliminate live/paid/supply dependencies.

The [seven practical PDFs](../catalog/acquisition/full-1tb-capacity-20260928/practical-manuals.json) total **64.100 MB**: FEMA P-232 (2024), DOE Energy Saver (2022), Eawag sanitation compendium, NMSU Sewing Shortcuts, OSA seed saving (2010), ARRL ARES field resources (2005–2008 copyright), and UAF Root Cellars (2020 revision). Complete bytes were hashed and parsed, with representative rendered pages reviewed. Their narrow purposes and edition limits are recorded in the [source report](full-1tb-source-verification.md). Three other advertised PDF links returned HTML and are excluded.

The [Core Knowledge terms](https://www.coreknowledge.org/terms-of-use/) have series-specific and third-party conditions. Preserve notices and review document rights. No source's availability implies blanket redistribution rights.

## Lightweight pseudoindexes and admission

Each readable candidate has one saved assignment file under [the acquisition plan](../catalog/acquisition/full-1tb-capacity-20260928/pseudoindexes/), using the existing `schema_version: 1` navigation format. Canadian PDFs receive entries; retained ZIP/XML files do not. No internal section, page number or ZIM path is invented.

**Python** handles enumeration, typed metadata, deduplication, byte totals, format probes, member inventories, deterministic place/component aliases and schema validation. **AI/editorial work** chooses useful scope, evaluates audience and limitations, reconciles teaching requirements, reviews representative pages/playback and judges remaining task depth.

Review and admit each exact source with full hashes, rights and metadata; then copy its matching assignment into active navigation. The existing build workflow assembles discovery only from successfully completed, verified files. Failed or partial downloads remain absent. No new runtime indexing system is introduced.

This specification is **source-enumerated and availability/type/size-verified**, not a fully acquired or admitted 1 TB library. **46 small bodies** are fully downloaded and locally hashed; the remaining full-body and offline-usability gates are explicit. The editorial plan retains all topic gaps and no row becomes adequate because this ledger nearly fills a drive.
