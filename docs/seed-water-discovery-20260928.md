# Seed and water selections — 28 September 2026

Five complete publisher PDFs were selected for **full-1tb**, adding **33,435,040
bytes (33.44 MB)**. Their five per-asset YAML pseudoindexes total **6,398 bytes**.
The full selection now contains **433 assets / 274,518,976,082 bytes**; smaller
presets retain their prior files and pins.

| Selected resource | Brief evaluation | Limits retained |
| --- | --- | --- |
| [FAO Seeds Toolkit, Module 2: Seed Processing (2018)](https://openknowledge.fao.org/handle/20.500.14283/ca1491en) — 92 PDF pages | Adds threshing, winnowing, cleaning, grading and equipment maintenance before storage. | Includes powered equipment and chemical treatments; does not supply crop-specific household seed-saving instructions. |
| [FAO Seeds Toolkit, Module 3: Seed Quality Assurance (2018)](https://openknowledge.fao.org/handle/20.500.14283/ca1492en) — 126 pages | Adds sampling, germination, viability, purity and field inspection. | Practitioner reference; many methods require laboratory equipment. Certification material is dated. |
| [CAWST Household Rainwater Harvesting (2011)](https://washresources.cawst.org/en/resources/273a0b51/introduction-to-rainwater-harvesting-manual) — 190 pages | Illustrated roof catchment, gutters, storage sizing and maintenance complement emergency treatment notes. | The currently offered English edition is from 2011; climate, materials and water-quality requirements need local assessment. |
| [RWSN Afridev Installation and Maintenance, revision 2 (2007)](https://www.rural-water-supply.net/en/resources/286) — 76 pages | Illustrated installation, fault diagnosis, repair, tools and spare parts. | Specific Afridev configurations; not universal pump or borehole-drilling guidance. |
| [SADC-GMI Groundwater Infrastructure Operation and Maintenance (2020)](https://2023.sadc-gmi.org/publications/) — 294 pages | Wells, boreholes, pumps, springs, pipes, storage and monitoring extend maintenance coverage across a water system. | Written for trained operators and managers, with Southern African examples; site assessment and equipment manuals remain necessary. |

FAO's [Module 1: Development of Small-Scale Seed Enterprises](https://openknowledge.fao.org/handle/20.500.14283/ca1490en)
downloaded successfully but was **deferred** after a contents review: its substantial
business-planning emphasis is lower priority than crop-specific seed-saving steps.
It has no production catalog entry or pseudoindex.

AI supplied selection judgments, scope limits and everyday search phrases. Python
downloaded bounded files unchanged, checked PDF readability, computed sizes and
SHA-256 pins, and validated each annotation through the existing loader. Review
covered publisher metadata, notices, contents, the first six physical pages,
midpoint and final page; SADC's later contents pages were also sampled. Covers
and one illustrated body page per selected file were inspected visually. This was
a brief selection review, not a technical certification or exhaustive reading.

FAO's retained notices permit attributed non-commercial copying and dissemination;
CAWST's manual carries CC BY 3.0 and asks websites to link to its current download.
Whole-document redistribution permission was not established for RWSN or SADC-GMI,
so those two assets retain `redistributable: false`. All notices remain in the
unchanged source PDFs. Downloaded bodies and review images stay in ignored
`.owl/seed-water-discovery-20260928/`, outside Git.

Reusable metadata lives in `catalog/navigation/assignments/<asset-id>.yaml`.
The new **Seed processing and quality** and **Water collection and system
maintenance** atlas topics connect the five files to existing subjects. Search
phrases include “clean harvested seeds,” “test seed germination,” “size a
rainwater tank,” “repair an Afridev handpump” and “reduced borehole yield.”
Assembly includes each file only after its downloaded bytes match its catalog
size and hash. No full-text index, OCR, embeddings or inferred page links were added.

Verification assembled three downloaded manuals, confirmed the other two were
absent from search, then added them and rebuilt successfully. The resulting
five-file partial drive passed 96 integrity checks with no missing, failed or
unknown files; it correctly remains incomplete relative to the full preset.
Discovery compilation read zero source-body bytes after the integrity pass.
Content and selection policies, generated-document freshness, five new search
finding tasks and the repository suite passed (842 tests, 5 skipped). Existing
catalog records and all smaller-profile selections were checked against the
pre-batch snapshot and remain unchanged.

[Machine-readable decisions and source pins](../catalog/acquisition/seed-water-discovery-20260928.json)
preserve the evaluations and review scope. The updated
[topic-by-topic completion plan](full-1tb-coverage-plan.md) keeps these areas
**partial**: crop-specific seed saving, household applicability, cold-climate water
systems, other pump types and accessible water-quality testing still need work.
