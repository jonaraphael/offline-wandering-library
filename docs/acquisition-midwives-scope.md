# Midwives 2026 scope review

Retain the 31 included same-edition publisher PDFs. Removing the entire book
is not supported by the present equivalence evidence. No purchase was made.

`catalog/acquisition/midwives-scope-evidence.json` records whole-file matches
for all 31 files, their page ranges, the official download-index identity and
the current free-source HEAD checks. The files contain 546 PDF pages: 530
distinct printed page labels in the range 1–531, plus 16 unlabelled pages.
Every source contains the 2026 edition label. The original PDFs remain intact,
including front matter, notices, illustrations, medicine pages, resources,
glossary, index and the cut-out due-date calculator.

The actual book's contents list all 25 chapters, medicines starting at p467,
resources at p503, glossary at p507, index at p509 and the calculator at p531.
The store's 527-page count therefore does not describe the current chapter
files reliably. It is not used as completeness evidence.

Two exceptions remain explicit:

- The official publisher chapter20 file contains printed pp372–390; chapter21
  starts at p392. No included page has the printed label391, and no reference
  to391 was found in the included text or index. This is consistent with an
  omitted blank page, but a blank page has **not** been verified. Neither a
  missing clinical instruction nor a confirmed blank may be inferred solely
  from that gap.
- The missing `en_midw_2026_bm.pdf` is labeled **Other resources from Hesperian**
  on the official download index. It is not a clinical section in the included
  book's contents. Its pages were not acquired; their count and numbers remain
  unknown. Treating it as an optional publisher-resource appendix is a proposed
  scope decision, not verification of its unseen content or a claim that the
  uncaptured whole-book PDF is complete.

The bounded comparison inspected 109 included non-Midwives PDF sources,
verified every whole-file pin, and found no missing local source. MSF's
*Essential obstetric and newborn care* is the 2019 edition (279 PDF pages).
OpenStax's *Maternal-Newborn Nursing* has 1,241 PDF pages. Together with
*Where There Is No Doctor*, *Where Women Have No Doctor* and *Helping Health
Workers Learn*, these provide substantial overlapping maternal and newborn
coverage. They do not establish a complete substitute for Midwives:

| Specific content to preserve | Verified alternative evidence | Remaining distinction |
| --- | --- | --- |
| IUD loading, insertion and removal instructions (Midwives pp392–403) | OpenStax §5.5, PDF pp244–249; WWHD chapter13; MSF drug/device guidance | Indications, risks, aftercare and referral do not establish equivalent complete illustrated insertion/removal instructions. |
| Cut-out due-date wheel (Midwives p531, referenced at p448) | MSF obstetric PDF p13 mentions a pregnancy wheel | A usable printable wheel template was not located in the alternatives. |
| Anatomical teaching models (Midwives chapter25) | HHWL chapter11 PDF p5 and chapter22 PDF pp10–12 include birth-box, birth-pants and flexibaby teaching methods | Equivalent detailed pelvis/womb/vagina and placenta/cord/baby construction was not established. |
| Low-cost timers, stethoscopes and scales | HHWL chapter16 PDF pp1–8 | Substantive alternative construction instructions are present; this finding does not establish equivalence for the rest of the book. |
| Obstetric and newborn clinical procedures | MSF's complete obstetric manual; OpenStax's complete nursing text | Preserve each edition's qualifications, context and complete statements. Older obstetric guidance and a nursing textbook are not automatically interchangeable with the 2026 community-midwifery book. |

Keyword probes are review locators only. Their positive matches include
indexes, cross-references and non-equivalent wording; they never approve a
replacement. Detailed local page locators are in
`.owl/acquisition/maternal-coverage-evidence.json`. Reproduce both inspections
without fetching any new resource bodies:

```sh
.venv/bin/python scripts/inspect_midwives_scope.py \
  --library-root /Volumes/OWL/LIBRARY \
  --output .owl/acquisition/midwives-scope.json
.venv/bin/python scripts/inspect_pdf_topic_coverage.py \
  --recipe catalog/acquisition/maternal-coverage-probes.json \
  --library-root /Volumes/OWL/LIBRARY \
  --output .owl/acquisition/maternal-coverage-evidence.json
```

Four current official HEAD checks—one published back-matter URL and three
explicitly unlisted whole-book naming candidates based on the publisher's
historical naming forms—returned404. No new PDF body was downloaded. The
whole-book naming probes are not claimed to be discovered download links.
