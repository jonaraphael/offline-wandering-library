# Enumerated near-full 1 TB selection

Acquisition planning data, **not an extra ready catalog or build queue**. See [the capacity specification](../../../docs/full-1tb-capacity-spec.md), [source verification report](../../../docs/full-1tb-source-verification.md) and [editorial plan](../../coverage-plan.yaml).

- `plan.json`: exact capacity ledger and declared geographic/curriculum scopes.
- `archives.json`: ten whole ZIMs; publisher SHA-256 and binary-header checks.
- `usgs-northeast.json`, `usgs-mid-atlantic.json`, `usgs-appalachian.json`: 4,807 dated PDF sources, observed sizes and original metadata values.
- `canada-nearby.json`: 1,051 verified source ZIP directories with all 2,099 members, exact retained sizes and individual PDF pseudoindexes.
- `school.json`: 1,220 English PDFs; `school-units.json`: all 366 selected publisher pages and their component matrix; `school-excluded.json`: explicit exclusions.
- `ckla-kindergarten.json`: a 39-file **subset of school.json**, fully downloaded and locally hashed. Never add its bytes again.
- `practical-manuals.json`: seven downloaded, hashed and briefly reviewed PDFs; `rejected-sources.json`: three URLs that returned HTML.
- `pseudoindexes/`: 7,095 per-readable-asset YAML assignments (3,565,685 raw bytes), validated using the existing navigation loader.
- `evidence/`: per-source observations and precisely labeled verification levels. Range checks are not full-body integrity checks.
- `source-probe-requests.json`: input for the existing bounded HEAD refresh tool; not an acquisition queue.
- `validation.json`: offline metadata/schema/capacity checks, rerunnable with `.venv/bin/python scripts/validate_capacity_spec.py`.

Named candidates total **712,148,641,197 retained bytes**; existing plus candidate files total **986,667,617,279 bytes**. Modeled support brings the footprint to **987,261,432,141 bytes**, leaving **2,738,567,859 bytes** below the 990 GB ceiling. Separate 5 GB free and 5 GB filesystem margins remain.

**46 small PDF bodies** have local SHA-256 pins and parsing evidence; ten ZIMs have publisher SHA-256 pins. Other source bodies still need full download/hash verification. Canadian CRCs and HTTP ETags are not SHA-256 pins. Admission also requires content/rights/reader review. No topic adequacy is inferred.

Drafts remain outside active navigation. Admit an exact file and its metadata first, then promote its matching assignment. The existing build assembles only successfully verified downloads. Never copy all candidates into active navigation or treat this inventory as proof that every body is present.
