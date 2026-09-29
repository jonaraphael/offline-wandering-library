# Starter topic metadata

This directory supplies the production-catalog topic vocabulary and reusable
discovery metadata. The include list and exact editorial coverage remain
provisional.

`topics.yaml` declares subject, practical-task, and learning entrances into a
shared hierarchy. `assignments/<asset-id>.yaml` stores each asset's topic links,
aliases, and editorial notes separately in Git. Download details stay in
`catalog/library.yaml`. Current mappings include the acquired Hesperian publisher chapter PDFs, WHO and
MSF manuals, FAO practical guides, all 73 current English OpenStax PDF textbooks,
Pro Git, the Python PDF manuals, and resolved map archives. OpenStax routes cover humanities, social
sciences, business, nursing, computing, college success, mathematics, and science.
Subject and learning entrances lead to the same whole-document assignments; the
16 GB edition selects a subset of these books. Each Hesperian chapter PDF is linked as a whole source
file, including its front matter/index companions; it is not an inferred deep
link into another PDF. Current mappings use catalog titles and scope; they do not
assert reviewed chapter, page, or figure locations for third-party works.

Only assets present in the verified drive selection appear in generated pages.
Excluded and unresolved files do not become usable links merely because an
assignment exists. Empty branches disappear and coverage gaps are reported.

After downloading files with curl to their catalog destinations under
`DRIVE/LIBRARY/`, assemble the available subset with:

```bash
python scripts/discovery.py assemble --output /path/to/DRIVE --profile flash-16gb
```

Python checks sizes and SHA-256 values, then compiles search and atlas from the
verified subset. Missing, partial, and mismatched files are reported and excluded.
Rerun after more downloads finish. No AI or document parsing runs during assembly.

To audit and regenerate navigation on an existing inventoried drive:

```bash
python scripts/build_atlas.py /media/SSD/EMERGENCY_LIBRARY \
    --navigation-dir catalog/navigation
```

Use `--strict-coverage` to fail on unmapped critical assets or missing subject and
learning routes for required directly readable textbooks. This checks structural
coverage; it does not certify content quality or finalize source selection.

Reviewed source maps may be added as `sections/<asset-id>.yaml`. Keep proposed
imports and their review reports in a separate drafts directory. Every published
map pins the exact source SHA-256. Changing a source requires renewed location
review. An illustrated-asset label does not authorize a figure claim for every
section.

See the [atlas editor and user guide](../../docs/topic-atlas.md) for the schema,
offline importer, deep-link behavior, reporting, and publication workflow. The
[original demo metadata](../demo-navigation/README.md) demonstrates verified
section links without adding third-party content.
