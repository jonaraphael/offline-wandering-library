# Food preservation and Hesperian source-resolution follow-up

**Subsequent implementation:** the preserved September 18 snapshot is now a
source-pinned build-time recipe with complete desktop/mobile browser checks.
See the [implementation report](acquisition-implementation.md). The historical
partial-status notes below describe the earlier research checkpoint.

Research date: September 18, 2026, US Eastern time (HTTP checks occurred
2026-09-19 01:01–01:08 UTC). Candidate metadata is in
[`catalog/acquisition/hour-health.yaml`](../catalog/acquisition/hour-health.yaml).
Shared catalog files, profiles, selector and runtime were not edited by this worker.

The fragment adds **seven HTTPS-only original-PDF pins: 12,203,176 bytes and
131 physical pages**. Full bodies were downloaded to temporary storage to establish
hashes and inspect contents before the user clarified the intended metadata-only
scope. No resource bodies were copied to the SSD and no build was run. Further
body downloads stopped on that clarification; temporary evidence is preserved.
Future acquisition can use these exact URL, size and SHA-256 pins at build time.

| Added original | Version actually inside file | Physical pages |
| --- | --- | ---: |
| [NDSU Food Freezing Guide](https://www.ndsu.edu/agriculture/sites/default/files/2024-01/fn403.pdf) | FN403, reviewed January 2024 | 21 |
| [UMD Grow It Eat It Dry It for Adults](https://extension.umd.edu/sites/extension.umd.edu/files/publications/67.%20Grow%20It%2C%20Eat%20It%2C%20Dry%20It%2C%20EC-12%20%282%29_0.pdf) | EC-12, 2021 | 88 |
| [Steam Can It Right!](https://www.ncrfsma.org/files/page/files/fn2065_steam_can_it_right_fillable.pdf) | FN2065, October 2022 | 2 |
| [Safe Changes and Substitutions](https://www.ndsu.edu/agriculture/sites/default/files/2024-03/fn2102.pdf) | FN2102, revised March 2024 | 4 |
| [Using Pressure Canners](https://nchfp.uga.edu/papers/factsheets/Preserving_Food__Using_Pressure_Canners.pdf) | Circular 1344-02, June 2025 | 7 |
| [Crafting Kombucha at Home FAQ](https://nchfp.uga.edu/images/uploads/FAQs_Consumer_version_Kombucha.pdf) | UGA Extension, 2026 | 4 |
| [Using Boiling Water Canners](https://nchfp.uga.edu/papers/factsheets/Preserving_Food__Using_Boiling_Water_Canners.pdf) | Circular 1344-01, May 2025 | 5 |

All seven downloaded originals passed PDF-signature, byte-count, SHA-256,
`pdfinfo` and pypdf parsing checks. Representative processing tables, diagrams,
photos and notices were rendered with Poppler and visually inspected. No original
was rewritten, merged or stripped of notices. The freezing guide's 21 physical
pages include facing-page spreads. `profiles: []` avoids silently enlarging fixed
presets; resource membership is proposed in the fragment.

The freezing guide contains an attribution/noncommercial/share-alike Creative
Commons notice without identifying a license version; that exact limitation is
recorded. The other guides retain university/third-party notices and do not receive
an assumed public-domain or blanket Creative Commons designation. The UMD
curriculum includes an educational reproduction notice for incorporated UGA
material and explicitly reserves permission for website posting.

## Status remains partial

The proposed food-preservation resource has 17 PDF pins and material covering all
five requested topic areas. It still lacks a reproducible build-time acquisition
of later NCHFP updates and complete current recipe context. In particular:

- [NCHFP Newsflash](https://nchfp.uga.edu/newsflash) contains a September 2026
  atmospheric steam-canning statement with additional qualifications. The older
  FN2065 PDF alone does not incorporate that statement.
- The [second newsflash page](https://nchfp.uga.edu/newsflash/P10) and
  [third page](https://nchfp.uga.edu/newsflash/P20), with the first page, held 27
  entries, including stock/broth and ground-turkey guidance.
- The [current kombucha recipe](https://nchfp.uga.edu/how/ferment/recipes/kombucha-tea/)
  has instructions beyond its companion FAQ. Pinning the FAQ is not pinning the
  complete recipe.

A temporary self-contained research snapshot preserves all 27 newsflashes,
eight linked complete recipe/prerequisite pages and the UGA oils article, with
nine tables and four embedded images. Text, table and image counts were compared
against captured article bodies. Offline Chrome loaded every image, made zero
failed requests and found zero broken internal anchors. **This local snapshot is
not a catalog asset, not a build-time source, and not grounds to mark the collection
ready.** A subsequent authorized implementation could turn this into a reproducible
export recipe. No `file:` URL is included in the candidate catalog.

One additional [UGA infused-oils original PDF](https://fieldreport.caes.uga.edu/wp-content/uploads/2025/08/C-1334_1.pdf)
was acquired but excluded from the fragment: Poppler showed an illustration
obscuring some introductory text on physical page 2. The publisher's
[HTML version](https://fieldreport.caes.uga.edu/publications/C1334/how-to-safely-make-infused-oils/)
provides readable complete wording and is preserved in temporary research evidence.
The original PDF was not silently repaired or counted among the seven admitted pins.

## Hesperian

The [publisher's current chapter listing](https://languages.hesperian.org/pages/en/pdf.html)
still links the missing
[2026 midwives back matter](https://hesperian.org/wp-content/uploads/pdf/en_midw_2026/en_midw_2026_bm.pdf),
which again returned HTTP 404. The listing's complete-book store link also returned
404. The bounded probe ended without supplying an older edition or relabeling the
270/271-file collection ready.

Temporary evidence remains at `/private/tmp/owl-one-hour/health/`:
`verified-files.json` maps the seven admitted asset IDs to verified bodies;
`download*-results.json` records HTTP results and exact raw-response hashes;
`snapshot-evidence.json` records the excluded snapshot; `qa/` contains render and
browser evidence. These files are evidence only, not public catalog dependencies.
The fragment passed the repository's normal catalog validator with local URLs
disallowed. No SSD staging or build occurred.
