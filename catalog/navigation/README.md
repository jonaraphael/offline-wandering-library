# Starter topic metadata

This directory supplies the initial production-catalog topic vocabulary: **46
topics and 40 whole-document assignments**. Those numbers describe the navigation
layer, not the separate 46-resource acquisition list. The include list and exact
editorial coverage remain provisional.

`topics.yaml` declares subject, practical-task, and learning entrances into a
shared hierarchy. `assignments.yaml` connects those topics to known asset IDs from
`catalog/library.yaml`. Current mappings use catalog titles and scope; they do not
assert reviewed chapter, page, or figure locations for third-party works.

Only assets present in the verified drive selection appear in generated pages.
Excluded and unresolved files do not become usable links merely because an
assignment exists. Empty branches disappear and coverage gaps are reported.

To add this navigation to an existing drive:

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
