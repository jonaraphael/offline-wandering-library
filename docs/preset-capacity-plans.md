# Near-full capacity selections for every preset

Every drive size now has an **exact source-by-source expansion selection**, reusing the shared verified inventory and piecewise pseudoindexes. All five plans fit their practical ceilings. These expansion selections are **not yet the admitted build defaults**: missing full-file/member hashes and required content/offline reviews still gate promotion.

[Machine-readable selections](../catalog/acquisition/preset-capacity-20260929.json) · [Shared source verification](full-1tb-source-verification.md) · [Topic completion plan](full-1tb-coverage-plan.md)

## Capacity ledger

Decimal GB. Expanded footprints include every retained source/member, all four reader packages within a **1 GB total reader/setup budget**, and existing discovery/metadata allowances.

| Preset | Admitted files now, GB | Expanded files + support, GB | Ceiling, GB | Unfilled growth, MB | Free reserve, GB | Filesystem margin, GB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 GB | 7.801 | **15.738** | 15.750 | 12.1 | 0.125 | 0.125 |
| 64 GB | 46.824 | **63.303** | 63.360 | 56.7 | 0.320 | 0.320 |
| 256 GB | 219.440 | **253.422** | 253.440 | 17.8 | 1.280 | 1.280 |
| 512 GB | 274.519 | **506.812** | 506.880 | 68.0 | 2.560 | 2.560 |
| 1 TB | 274.519 | **987.261** | 990.000 | 2738.6 | 5.000 | 5.000 |

The two reserved amounts are separate. Each is 0.5% of nominal drive capacity, with a **125 MB minimum** for the 16 GB preset. A nominal 1 TB drive therefore still has 5 GB reserved for filesystem/partition variation and 5 GB required to remain actually free. The remaining 2.739 GB below its 990 GB ceiling is unfilled growth room, not invented content.

The tighter small presets have little edition-growth room. Exact dated sizes must remain pinned; if a replacement edition grows, reselect whole cohorts before updating it. The builder still checks real free bytes. Use the default in-place download spool and a separate disk for a retained download cache or old/new giant ZIM pairs.

## What each selection contains

### 16 GB — 15.738 GB

**School:** All offered English preschool–grade 5 components, plus complete grade 6 and 7 CKLA language-arts cohorts. Existing Siyavula school texts remain included.

**Maps:** Existing map-and-compass guide; no regional map archive or detailed topographic cohort at this size.

**Reference and media:** Existing small practical archives, plus Energypedia and Gardenology.

**Scope choices:** Grade 8 CKLA and grade 6–8 CKMath/CKSci/CKHG are outside this expansion. Whole grade/subject cohorts are omitted; no unit is truncated. Detailed geography and large encyclopedia/video archives start in larger plans.

### 64 GB — 63.303 GB

**School:** All offered English kindergarten–grade 8 components across CKLA, CKMath, CKSci and CKHG. Preschool is not included in this size.

**Maps:** Complete North America OSM ZIM, replacing the 9.156 GB dictionary in the previous default selection.

**Reference and media:** Energy, teacher-development and environmental-science supplements; existing medical, repair, trade and Wikibooks collections retained.

**Scope choices:** The full Wiktionary archive stays selectable but is no longer a default here; complete school material and regional maps take priority. Preschool and Gardenology are omitted to fit whole selected cohorts and the 1 GB reader/setup budget.

### 256 GB — 253.422 GB

**School:** All offered English kindergarten–grade 8 components. Preschool is not included in this size.

**Maps:** North America OSM plus all current 1:24000 sheets selected by publisher RI/DE state tags and MA Barnstable/Dukes/Nantucket county tags. Overlapping sheet IDs are counted once.

**Reference and media:** Full English Wikipedia, four historical nonfiction archives and all seven smaller ZIM candidates, including Wiktionary already in the ready base.

**Scope choices:** The new topographic cohort has a declared southern New England/Delaware scope; it does not imply full Northeast or Canadian coverage. Preschool and the large Khan Academy/Crash Course/Survivor archives are outside this size.

### 512 GB — 506.812 GB

**School:** All offered English preschool–grade 8 components.

**Maps:** World OSM replaces North America OSM; no duplicate regional street-map archive. Detailed topography remains in the 1 TB plan.

**Reference and media:** Adds whole Khan Academy and Crash Course archives and six smaller ZIM candidates; Gardenology is omitted.

**Scope choices:** Gardenology is a lower-priority supplement omitted to fit the complete video archives and support allowances. The 256 GB detailed map cohort is not included here; this size prioritizes broad education and world maps. These are curated alternatives, not strict nested supersets.

### 1 TB — 987.261 GB

**School:** All offered English preschool–grade 8 components.

**Maps:** World OSM plus 4,807 USGS PDFs and all 1,051 Canadian PDF ZIPs in the declared northeastern/adjacent-US and northern Great Lakes/nearby-Canada selections.

**Reference and media:** All ten candidate ZIM archives, including Survivor Library, Khan Academy and Crash Course.

**Scope choices:** Legacy maps and historical books remain clearly dated; byte totals do not establish current roads or modern practical standards. Full-body/map-footprint/offline-reader review gates remain explicit.

All five expansions include the seven source-verified practical manual candidates. The four previously admitted soil/farming, trail, seed-quality and water-system collections now belong to every active default. These are small, useful additions with existing hashes and pseudoindexes.

The sizes are curated alternatives, not strict nested supersets. Complete grade/subject sequences and geographic cohorts are explicit. For example, preschool fits the 16 GB selection but is omitted from the 64/256 GB selections to prioritize complete K–8 teaching material. The 512 GB plan prioritizes education media and world maps; detailed regional topography becomes broad in the 1 TB plan. No individual unit or declared map cohort is cut at an arbitrary byte boundary.

## What changed in the actual presets

- Updated the capacity/reserve arithmetic in all four smaller profile YAML files; retained the established 1 TB limits.
- Set **1 GB total** for reader packages plus setup/growth on every preset. The existing 439,739,570 reader bytes are counted once; the extra allowance is 560,260,430 bytes.
- Added the eleven already-admitted farming, trail, seed and water files to every smaller default.
- In the 64 GB default, replaced the full Wiktionary archive with the North America map archive. Wiktionary remains selectable and remains a default in larger sizes.
- Saved exact candidate download IDs for each expansion, referencing the shared manifests rather than copying thousands of source records or pseudoindexes.

## Remaining admission work

| Preset | Candidate downloads selected | Candidate downloads missing SHA-256 | Candidate PDF bodies fully downloaded this pass |
| --- | ---: | ---: | ---: |
| 16 GB | 1,006 | 958 | 46 |
| 64 GB | 1,175 | 1,126 | 46 |
| 256 GB | 1,321 | 1,268 | 46 |
| 512 GB | 1,235 | 1,181 | 46 |
| 1 TB | 7,095 | 7,039 | 46 |

The 1 TB Canadian packages additionally have **2,099 extracted members** needing full-body hashes. Publisher SHA-256 pins on ZIMs do not mean their bodies have already been downloaded or tested in readers. The ready catalog and current build command retain all existing checksum, content-policy and space gates.

Next admission order: verify complete selected school cohorts and the small practical manuals; then complete geographic cohorts and archive reader checks. Reuse each asset’s saved pseudoindex when it is admitted. The [34-topic editorial plan](full-1tb-coverage-plan.md) keeps practical and instructional gaps open until reviewed; no topic is promoted to adequate from these capacity figures.

## Validation

```sh
.venv/bin/python scripts/validate_capacity_spec.py
```

This offline check resolves every selected ID, verifies shared-manifest fingerprints, reproduces all five byte ledgers, enforces exact grade/subject and map-cohort membership, checks the current defaults, and validates all source-level pseudoindexes. It performs no full-body indexing and does not assert that unacquired bodies are verified.
