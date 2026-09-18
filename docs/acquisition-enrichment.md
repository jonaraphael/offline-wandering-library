# Published archive editions for useful defaults

Checked 18 September 2026. This acquisition fragment adds exact official download pins; it does not download or commit the archives. The builder must verify every archive against its full-file SHA-256. Twenty-seven new asset records pass the catalog validator. The existing 61 Book Dash EPUBs are referenced, not duplicated.

The proposed compact editions are concrete published collections. They are alternatives to the still unfinished direct HTML and question-level curation projects. Selecting a compact edition must show that it requires a ZIM reader. The critical directly readable library remains separate.

| Proposed compact edition | Exact source bytes | Scope |
|---|---:|---|
| Gutenberg selected nonfiction | 36,041,186,827 | English Library of Congress classes Q (science), T (technology), S (agriculture), L (education) |
| Children's published selection | 19,818,807,444 | Existing 61 Book Dash EPUBs plus Gutenberg English PZ (juvenile literature) |
| Practical Stack Exchange | 15,459,760,088 | Twelve complete published site archives listed below |
| Science Stack Exchange | 10,085,072,636 | Mathematics, physics, biology and chemistry |

“Ready” here means that this explicitly bounded published edition has verified download metadata. It does not mean that the broader original curation request is finished. The fragment leaves the published Gutenberg resource unresolved, preserves the children's resource's partial status and existing members, and leaves the direct Stack Exchange collections unresolved. It proposes no default inclusion of the whole English Gutenberg or Stack Overflow archives.

## Gutenberg

The [official Kiwix directory](https://download.kiwix.org/zim/gutenberg/) publishes English subject editions as well as the entire English archive. No smaller popular-books or mini English edition was listed during this check. The [Kiwix catalog](https://library.kiwix.org/catalog/v2/entries?count=100&q=gutenberg&lang=eng) identifies Q, T, S and L as science, technology, agriculture and education, and PZ as juvenile literature. These are published subject partitions, not a reviewed selection of individual works. Multiple classes can contain overlapping works; no cross-partition deduplication is claimed.

The catalog marks these archives as containing pictures and describes the English whole archive as all English books. That describes the dated published snapshot; it does not guarantee coverage of today's Gutenberg collection. The November 2025 whole English file is **221,251,590,584 bytes**, while subject files are from March 2026. They should be alternatives, not selected together to inflate totals. Optional English and American literature partitions add 16,152,121,320 and 16,022,294,302 bytes respectively. General class P is only 38,549,776 bytes and is not a substitute for the much larger literature classes.

The [openZIM Gutenberg project](https://github.com/openzim/gutenberg) packages books and browsing tools inside a ZIM. These files do not provide ordinary HTML book files outside that archive. No direct extraction, per-book quality inspection, representation deduplication, or OWL full-text coverage check was performed in this metadata-only work. The asset illustration flag remains conservative because individual pages were not inspected.

[Project Gutenberg's permission guidance](https://www.gutenberg.org/policy/permission) says most books are public domain in the United States, allows noncommercial use under its terms, and explains that some books have separate copyright restrictions. The [Project Gutenberg License](https://www.gutenberg.org/policy/license) and each book's own notices remain authoritative. The aggregate assets use `redistributable: false` to avoid promising blanket worldwide redistribution rights. This does not prohibit the user's personal offline acquisition from the offered Kiwix source. Preserve book headers, authors, translators, illustrators and licenses. Historical technical and medical texts must not be presented as current emergency instructions.

## Stack Exchange

The [official archive directory](https://download.kiwix.org/zim/stack_exchange/) and [openZIM Sotoki documentation](https://github.com/openzim/sotoki) establish the published archive source. Sotoki builds from Stack Exchange data dumps. A July or August 2026 archive filename is a packaging date, not proof that the input data contains contributions through that month.

The practical edition includes Home Improvement, Electrical Engineering, Gardening and Landscaping, GIS, Amateur Radio, Motor Vehicle Maintenance and Repair, The Great Outdoors, Sustainable Living, Unix and Linux, Woodworking, 3D Printing, and Super User. The science edition includes Mathematics, Physics, Biology, and Chemistry. These are complete published site archives. They have not undergone OWL's proposed answer-quality filter, durable-topic selection, or direct HTML export. Super User and GIS are broader than the original selected-topic scope.

The optional full Stack Overflow pin is **114,855,633,696 bytes**. It remains an unused research input, not a default or a replacement for the proposed 25 GB durable-topic corpus. It contains the broader site's platform and framework material, which the requested curation would exclude.

[Stack Overflow's licensing page](https://stackoverflow.com/help/licensing) specifies CC BY-SA 2.5 for contributions before 8 April 2011, 3.0 from that date until 2 May 2018, and 4.0 thereafter. Preserve per-post authorship, source links, dates and notices; a blanket CC BY-SA 4.0 label for the entire history would be inaccurate. Sotoki's software license is separate from the content licenses.

## Evidence and integration

Each asset's evidence record contains the exact `.zim.meta4` URL, SHA-256 of that metadata document, whole-file SHA-256 and byte size, plus an independent HTTP HEAD result. Every selected candidate returned HTTP 200 with a matching Content-Length from an official Kiwix-selected HTTPS mirror. The complete Gutenberg Metalink exceeds 2 MB because of piece hashes; its full document was retrieved and parsed, and the pin uses the direct child whole-file SHA-256, not a piece checksum. No archive bytes were downloaded.

`navigation_proposals` contains whole-document topic assignments for the existing vocabulary. It makes no section, figure, or per-question claim. `optional_assets` identifies useful pins that must not enter default selections accidentally. The proposed resource updates deliberately retain the original scope limitations.

One misleading candidate was rejected: Kiwix's `survivors_en_all_maxi` is the **Vampire Survivors game wiki**, as its [official catalog entry](https://library.kiwix.org/catalog/v2/entries?count=5&q=survivors) confirms. It is unrelated to the Survivor Library and is absent from the acquisition fragment.

## Pinned files

The complete hashes and metadata evidence are in [the acquisition fragment](../catalog/acquisition/enrichment.yaml). These exact sizes are source content only; search, scratch space, reader software and free-space reserve are additional.

| Asset | Source bytes | Version |
|---|---:|---|
| `gutenberg_en_lcc_q` | 17,724,714,270 | 2026-03 |
| `gutenberg_en_lcc_t` | 13,154,803,470 | 2026-03 |
| `gutenberg_en_lcc_s` | 4,532,683,039 | 2026-03 |
| `gutenberg_en_lcc_l` | 628,986,048 | 2026-03 |
| `gutenberg_en_lcc_pr` | 16,152,121,320 | 2026-03 |
| `gutenberg_en_lcc_ps` | 16,022,294,302 | 2026-03 |
| `gutenberg_en_lcc_b` | 6,365,165,314 | 2026-03 |
| `gutenberg_en_lcc_p` | 38,549,776 | 2026-03 |
| `gutenberg_en_lcc_pz` | 19,770,263,119 | 2026-03 |
| `gutenberg_en_all` | 221,251,590,584 | 2025-11 |
| `stackexchange_diy` | 2,062,547,155 | 2026-08 |
| `stackexchange_electronics` | 4,214,186,044 | 2026-08 |
| `stackexchange_gardening` | 926,805,273 | 2026-08 |
| `stackexchange_gis` | 2,129,919,887 | 2026-08 |
| `stackexchange_ham` | 75,931,239 | 2026-08 |
| `stackexchange_mechanics` | 339,833,641 | 2026-08 |
| `stackexchange_outdoors` | 141,407,927 | 2026-08 |
| `stackexchange_sustainability` | 27,666,982 | 2026-08 |
| `stackexchange_unix` | 1,312,634,563 | 2026-08 |
| `stackexchange_woodworking` | 105,570,459 | 2026-08 |
| `stackexchange_3dprinting` | 120,138,274 | 2026-07a |
| `stackexchange_math` | 7,417,271,999 | 2026-08 |
| `stackexchange_physics` | 1,827,690,763 | 2026-08 |
| `stackexchange_biology` | 422,849,825 | 2026-07 |
| `stackexchange_chemistry` | 417,260,049 | 2026-07 |
| `stackexchange_superuser` | 4,003,118,644 | 2026-08 |
| `stackoverflow_en_all` | 114,855,633,696 | 2026-07 |

## Bounded follow-up: Survivor Library and Khan Academy

The [Survivor Library home page](https://www.survivorlibrary.com/) announced on 29 August 2026 that category ZIPs were restored. Its [Smithing](https://www.survivorlibrary.com/index.php/library-smithing/), [Machine Tools](https://www.survivorlibrary.com/index.php/library-machine_tools/), and [Farming](https://www.survivorlibrary.com/index.php/library-farming/) pages list 128, 45 and 223 PDF links respectively, plus a category ZIP. Each exact ZIP link on those three pages returned HTTP 404 to a HEAD request on this check. None of those pages linked a checksum or machine-readable pinned manifest. The three ZIPs were not downloaded or added as resolved assets. Individual PDFs are a practical next acquisition route, but a title list, deduplication, quality checks and computed hashes still have to be completed before calling a curated 100 GB Tier A package ready. This is an acquisition and curation gap, not a general prohibition on personally downloading the books the site offers.

The [official Kiwix other directory](https://download.kiwix.org/zim/other/) lists a whole English Khan Academy archive from March 2023, approximately 168 GiB. No STEM-only variant was listed there. That full archive has not been relabeled as the requested 90 GB STEM selection or inserted merely to raise the drive's byte total.

## Reader mirror availability

During the real expanded SSD build, the primary Kiwix release endpoint was very
slow. Kiwix's own [mirror registry](https://lb.download.kiwix.org/mirrors.json)
lists `https://ny.mirror.driftle.ss/kiwix/`. HEAD checks of all four existing
reader release paths on that mirror returned HTTP 200, exact catalog byte counts
and Range support. The active catalog now prefers this approved mirror and
retains the original Kiwix URL as fallback. Versions and SHA-256 pins are unchanged;
a faster mirror is trusted only after the whole-file checksum passes. Downloaded
binaries are not executed by the build.

## Survivor individual PDF check — 18 September 2026

The individual download route works despite the category ZIP failures above.
The [official category index](https://www.survivorlibrary.com/index.php/main-category-index/)
links ordinary HTML tables containing book titles, displayed sizes and direct
PDF URLs; collecting these candidate records requires no browser automation or
account. A bounded check of 12 categories—Smithing, Machine Tools, Forging and
Casting, Construction, Wood Carpentry, Wind and Water, Steam Engines, Farming,
Cheese and Butter, Bookbinding, Leather and Chemistry—found 1,019 PDF rows and
**1,014 unique PDF URLs**. Their rounded publisher size labels total approximately
**17.693 GB** when interpreted as decimal units. These labels are not exact byte
counts, and unique URLs do not establish unique books or editions. The sample
does not establish the requested curated 75 GB or 100 GB Tier A collection.

Six individual downloads were probed with HEAD and a request for bytes 0–1023.
All returned HTTP 200 to HEAD, HTTP 206 to the range request, matching total sizes
in `Content-Range`, and a PDF signature in the returned prefix:

| Official PDF link | HEAD size, bytes |
|---|---:|
| [Practical sheet iron and tin plate workers, 1904](https://www.survivorlibrary.com/library/a_new_and_original_treatise_for_practical_sheet_iron_and_tin_plate_workers1904.pdf) | 1,767,771 |
| [Engineering and building foundations, 1920](https://www.survivorlibrary.com/library/a_practical_treatise_on_engineering_and_building_foundations_1920.pdf) | 24,168,267 |
| [Conveyance and distribution of water, 1918](https://www.survivorlibrary.com/library/conveyance_and_distribution_of_water_for_water_supply_1918.pdf) | 57,600,290 |
| [Angora goat raising, 1903](https://www.survivorlibrary.com/library/a_manual_of_angora_goat_raising__with_a_chapter_on_milch_goats-1903.pdf) | 14,593,684 |
| [History of bookbinding, 1894](https://www.survivorlibrary.com/library/a_history_of_the_art_of_bookbinding-with_some_account_of_the_books_of_the_ancients_1894.pdf) | 21,769,057 |
| [Industrial organic chemistry, 1900](https://www.survivorlibrary.com/library/a_handbook_of_industrial_organic_chemistry_1900.pdf) | 39,063,372 |

This check transferred 1,102,624 bytes of HTML and 6,144 bytes of PDF prefixes;
it did not download complete books, inspect their scans or verify whole-file
hashes. No new catalog pins were added. A reproducible acquisition can freeze
selected table rows, remove unwanted titles and duplicate editions, then obtain
exact sizes, download the selected PDFs resumably and compute SHA-256 hashes.
The site's offered downloads provide the acquisition route for the intended
personal offline library. This availability check does not establish a blanket
redistribution license: preserve each volume's source, author, publisher and
existing notices, and record its actual rights metadata when cataloging it.
