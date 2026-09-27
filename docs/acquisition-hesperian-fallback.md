# Midwives whole-book fallback

The 2026 chapter set still needs its verified same-edition back matter. The official media API lists complete English 2013 and 2011 PDFs, but both exact publisher URLs returned HEAD 404 on 2026-09-23. Their identities and failed headers are preserved; no older pages are spliced into the current book.

The reviewed current fallback is [Hesperian’s English PDF variant](https://store.hesperian.org/products/a-book-for-midwives?variant=45190704136373), SKU PDF090, product 8160072597685, variant 45190704136373. Official product metadata describes Second Edition, 9th Revised Printing (2026), 527 pages, and lists the PDF at USD 7.95, checked 2026-09-23. This is a purchase identity, not a downloadable-file pin or proof of the delivered PDF edition. No purchase was made.

`catalog/acquisition/hesperian-whole-book-fallback.json` records this metadata and its hashes, public alternatives, exact availability failures and blockers. An authorized purchase or publisher-provided file must supply the complete book before exact-size, SHA256, edition, notices and completeness review. Only a whole reviewed edition can replace the chapter set; a paid listing alone cannot satisfy the missing content dependency.

The metadata-only workflow is reusable and cached:

```sh
python scripts/discover_hesperian_fallback.py --recipe catalog/acquisition/hesperian-whole-book-fallback-recipe.json --output catalog/acquisition/hesperian-whole-book-fallback.json --offline
```

Without `--offline`, it may fetch bounded publisher JSON/HTML and HEAD headers only. It never downloads a book or completes a purchase. Duplicate public media records are deduplicated by URL; non-English, partial and mismatched-year paths are excluded. A saturated inventory or changed product/edition structure fails for review.
