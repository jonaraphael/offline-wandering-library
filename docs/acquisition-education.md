# Education and agriculture acquisition evidence

This acquisition batch adds **85 complete publisher files, 1,554,194,963 bytes**. The
files are SHA-256 pinned in [`catalog/acquisition/education.yaml`](../catalog/acquisition/education.yaml).
Only recipes and metadata belong in Git. Downloaded files were written to the OWL
SSD's `OWL_SOURCE_CACHE/owl-v1/<sha256>` cache; builds can reuse them with
`--cache-dir /Volumes/OWL/OWL_SOURCE_CACHE`. Every new asset has `profiles: []`;
resource selection controls inclusion without silently enlarging fixed presets.

| Resource | This batch | Status after acquisition |
| --- | --- | --- |
| #22 OpenStax core | 15 additional original PDFs, 1,406,833,207 bytes | Ready: all 20 requested core mathematics/science PDFs, including the existing five pins |
| #8 FAO practical agriculture | 7 original illustrated PDFs, 93,728,147 bytes | Partial: useful title-level coverage, with remaining topics listed below |
| #10 Children's library | All 61 EPUBs in the pinned Book Dash publisher archive, 48,544,325 bytes | Partial: current Book Dash PDFs and African Storybook remain unresolved |
| #26 PhET | 2 exact-version English HTML5 simulations, 5,089,284 bytes | Partial: wider selection and actual offline device tests remain |

Verification date: 2026-09-18. Exact hashes and sizes were computed from complete
file downloads. PDF physical page counts and embedded publication notices were
inspected with pypdf. Every EPUB container, package manifest, reading-order
reference and presence of packaged illustration assets was checked. This is
structural validation, not a claim that every page was visually inspected.

## OpenStax: complete mathematics and science core

Discovery used the [publisher books API](https://openstax.org/apps/cms/api/v2/pages/30/),
following its `pdf_url` fields. The new books are Elementary Algebra 2e,
Intermediate Algebra 2e, College Algebra 2e, Algebra and Trigonometry 2e,
Precalculus 2e, Calculus volumes 1–3, Introductory Statistics 2e, University Physics
volumes 1–3, Astronomy 2e, Microbiology and Physics. These supplement the existing
Prealgebra 2e, College Physics 2e, Chemistry 2e, Biology 2e, and Anatomy and
Physiology 2e pins. No existing pin was changed.

Fourteen of the fifteen downloaded editions actually state **CC-BY-NC-SA-4.0** in their PDF
notices. Physics instead states **CC-BY-4.0** and is recorded accordingly. The catalog follows those downloaded notices rather than assuming an
older license based on publication year or API timestamp. Preserve the original
PDFs, credited third-party notices and the required attribution, “Access for free
at openstax.org.” Catalog attribution also carries this notice for search results.
The API's `last_updated_pdf` values are recorded only as publisher metadata:
several predate the current PDF notices and are not a substitute for byte pins.

These are complete illustrated original PDFs, not extracted-text substitutes.
Optional business, economics, psychology and sociology books were not part of
this batch; neither were alternate HTML renditions or instructor materials.

## FAO: practical manuals with title-specific rights

The batch contains:

- [Seeds toolkit, Module 6: Seed storage](https://www.fao.org/3/ca1495en/CA1495EN.pdf),
  2018, 118 physical pages; CC-BY-NC-SA-3.0-IGO.
- [Farmer Field School on Climate Smart Agriculture in coastal/delta Myanmar](https://openknowledge.fao.org/3/ca3815en/ca3815en.pdf),
  2019, 101 pages; CC-BY-NC-SA-3.0-IGO. Crop rotation, green manure, conservation
  agriculture, rice intensification and integrated pest management, with regional context retained.
- [Farmer's compost handbook](https://www.fao.org/3/i3388e/i3388e.pdf), 2015,
  112 pages, and its [Spanish original](https://www.fao.org/4/i3388s/i3388s.pdf),
  2013, 112 pages. Both allow noncommercial copying with FAO attribution;
  translation/adaptation and commercial rights require separate permission.
- [Small-scale aquaponic food production](https://www.fao.org/3/i4021e/i4021e.pdf),
  2014, 288 pages. The publication expressly permits noncommercial copying with
  attribution; original diagrams, photographs and third-party notices remain.
- [Small-scale poultry production](https://openknowledge.fao.org/3/a-y5169e.pdf),
  2004, 120 pages, and [Irrigation Manual, Volume II, Module 7](https://www.fao.org/4/ai596e/ai596e.pdf),
  2002, 168 pages. These are official public downloads suitable for the user's
  personal library. No redistribution grant was established, so their catalog
  `redistributable` value is **false**. Do not represent them as Creative Commons works.

The shelf remains partial. Dedicated coverage of all requested vegetables,
postharvest/grain storage, other livestock, dairy, animal feed, greenhouse
management and farm tools has not yet been acquired. These older technical
manuals retain their publication dates and geographic context.

## Children: exact archive scope and current export gaps

[Book Dash's own ebook site](https://bookdash.github.io/bookdash-books/) links its
[publisher GitHub repository](https://github.com/bookdash/bookdash-books) as the
EPUB source and states CC-BY-4.0. All 61 `download/*.epub` files (38 distinct works: 38 English, 16 Xhosa and 7 French editions) at commit
`54916310c5c06a5282e2d5d4add18d64f90e5fde` are pinned with raw commit URLs. Package
metadata supplies titles, creators and languages; the publisher's `_data/meta.yml`
supplies translation credits. Original cover, illustrations, reading order and
credits remain inside each EPUB. These EPUBs require a compatible reader and do
not satisfy the requested direct-PDF library by themselves.

The current [Book Dash source browser](https://bookdash.org/book-source-files/)
exposed 221 title folders. A current title's English ebook folder advertised an
actual PDF, but its publisher `?download=` and `?view-file=` endpoints returned
HTTP 403 during acquisition. The 61-file archive is therefore explicitly a
partial collection, not a claim to include all current books or translations.
A subsequent exporter should enumerate every publisher title/language folder,
retain complete ebook PDFs and creator/translator credits, and pin only actual
successful downloads. Print editions are optional; video and text-free artwork
folders are not substitutes for complete storybooks.

[African Storybook's terms](https://www.africanstorybook.org/terms.php) allow
copying/downloading with per-book creator, illustrator and translator attribution;
some books also require noncommercial use. Its public approved-catalog endpoint
`https://www.africanstorybook.org/lists/booklist.approved.php` returned 7,603 records.
Those records are JavaScript data, not a downloaded offline library. No script
from that catalog was executed.

The public reader for approved story 51957 showed a complete illustrated Fante
story with author, translator, illustrator and CC-BY-4.0 credits. However, its
publisher PDF export prepended the diagnostic string
`https://www.africanstorybook.org/include/pdf_html.php` before the PDF signature.
No malformed or silently repaired PDF was admitted as a resolved asset. A full
exporter still needs reviewed handling of this endpoint, immutable/cacheable
snapshots, all approved languages and faithful per-title credits. No tiny sample
is presented as the full African Storybook collection.

## PhET: original regular HTML5 files

The batch pins [Ohm's Law](https://phet.colorado.edu/en/simulations/ohms-law)
**1.4.31** and [Circuit Construction Kit: DC](https://phet.colorado.edu/en/simulations/circuit-construction-kit-dc)
**1.5.2** at exact version URLs. The original files state CC-BY-NC-4.0 and contain
embedded simulation JavaScript, assets and third-party notices. The catalog uses
the publisher's required attribution near the point of use. These are regular
PhET simulations, not PhET-iO, Java or Flash distributions. See
[PhET licensing](https://phet.colorado.edu/en/licensing).

Static inspection found one externally referenced HTML script in each file:
Cloudflare analytics. Publisher update checks, help and outbound links also
remain. The original files have not been rewritten to remove those features;
do not describe them as making no network requests. Core simulation resources
are embedded, but actual disconnected execution has **not** been validated on
phones or desktop browsers in this acquisition. The resource remains partial
pending those tests and a broader useful selection. HTML/JavaScript execution
from external storage can be restricted on iOS and other devices.

## Reproducing or extending this acquisition

The manifest is the reproducible export: every admitted file has an actual source
URL, exact byte size, SHA-256, version/snapshot, title, publisher, attribution and
resource membership. Ordinary OWL downloads already stream, resume, verify and
reuse these files; no new downloader or provider-specific runtime is required.
Source URLs that update in place will fail verification rather than silently
changing editions. Keep two independently verified SSDs and retain this cache
when publisher endpoints change.

Refreshing a provider catalog is a separate reviewed acquisition step. Do not
replace pinned hashes automatically, infer licenses from a provider name, execute
publisher metadata JavaScript, or mark the unresolved whole collections ready
because a smaller subset downloaded successfully.
