# Pinned local direct-reading candidates

Four existing originals were read without modifying the library drive. Their whole-file sizes and SHA256 values match the active catalog: Appropedia February 2026, CD3WD November 2025, iFixit December 2025 and Low-tech Magazine January 2025. The reusable inventory does no networking, extraction, export or production-library writes.

`catalog/acquisition/direct-local-selection-recipe.json` defines bounded English-oriented topic rules and complete captured book-directory expansion. `catalog/acquisition/direct-local-candidates.json` freezes exact entry IDs, titles, payload hashes, sizes, topic assignments and pending reviews. Redirect aliases are excluded. These are selection candidates, not accepted direct editions.

| Source | Candidate entries | Original PDFs | Document payload bytes |
| --- | ---: | ---: | ---: |
| Appropedia | 1,849 | 10 | 60,660,224 |
| CD3WD | 5,219 | 72 | 178,399,119 |
| iFixit | 1,399 | 0 | 124,604,274 |
| English Low-tech articles | 87 | 0 | 6,370,001 |
| Total | 8,554 | 82 | 370,033,618 |

CD3WD selection retains every captured document under 298 matched publisher book directories instead of isolating matching chapters. This preserves the captured context; completeness against the original publication still needs review. The full source contains 77 PDFs, so five unmatched PDFs remain outside this English practical-topic proposal. Topic matrices have no empty declared topic, but keyword classification is not a substantive coverage approval. Images, styles, fonts, captions, link closure and export overhead remain unmeasured. No amount in this table is credited to the additional direct-reading target or counted twice as new knowledge.

The inventory records seven unsupported archive paths, four in Appropedia and three in iFixit; they are excluded from export proposals and remain visible exceptions. Seven Appropedia candidate pages contain replacement characters requiring comparison with the original during preview review. All 1,399 selected iFixit guides declare `lang="fr"`; three sampled introductions and step headings are English. The conflict remains explicit rather than relabeling the entire archive from a sample. Detailed structural evidence, full inventories, sampled language observations and machine paths stay under `.owl/acquisition/zim-inventory/`.

`catalog/acquisition/direct-local-acquisition.json` is a separate original-source capture batch with all four official source identities and complete asset templates. It reserves 5,434,058,007 original bytes and 5,435,203,075 bytes including receipts/metadata. The local mapping `.owl/acquisition/zim-inventory/direct-local-sources.json` lets the acquisition build reuse those verified originals while preserving official provenance. It does not export their contents or mark any direct edition ready. Direct previews need their own bounded generation recipes, scratch/output allowance and review receipts.

```sh
python scripts/inspect_zim_candidates.py \
  --library-root /path/to/existing/LIBRARY \
  --recipe catalog/acquisition/direct-local-selection-recipe.json \
  --evidence-output .owl/acquisition/zim-inventory/direct-local-inspection.json \
  --output catalog/acquisition/direct-local-candidates.json \
  --capture-output catalog/acquisition/direct-local-acquisition.json \
  --local-manifest-output .owl/acquisition/zim-inventory/direct-local-sources.json
```

The script verifies each whole source before its first inventory, then reuses the unchanged file identity, source pin, inventory and per-selection checkpoints. A changed source, missing original, selection mismatch or exceeded bound stops the operation. Each inspection reads at most 16 MiB per existing document; inventories are limited to one million entries per archive and metadata to 64 MiB. All candidate counts are bounded by the recipe and fail instead of truncating to a quota. `--inventory-only` lists sources without reading document bodies; `--from-evidence` reuses a local inspection only when its recipe hash, source pin and complete selected-entry identities match the verified inventory.
