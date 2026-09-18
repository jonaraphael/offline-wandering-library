# Medical and emergency acquisition evidence

Verified on 2026-09-18. The acquisition fragment is
[`catalog/acquisition/medical.yaml`](../catalog/acquisition/medical.yaml).
It contains original publisher PDF download records, exact byte counts and
locally computed SHA-256 hashes: 307 PDFs, 277,352,875 bytes and 7,771 pages.
No downloaded publication is committed to Git.
The collection updates describe the scope actually acquired; they do not imply
that every publication from a publisher has been collected.

| Resource | Acquisition result | Remaining gap |
| --- | --- | --- |
| Hesperian health library | 270 original chapter PDFs from eight selected books | One publisher-linked 2026 midwives back-matter PDF returns HTTP 404 |
| MSF Medical Guidelines | All seven selected English publisher PDF manuals | PDF editions can lag online guidance; no HTML mirror claimed |
| WHO emergency care | Ten related PDFs, supplementing the existing whole 2018 BEC manual | Bounded reference selection, not every WHO emergency training resource |
| WHO WASH | All 15 original four-page technical notes, 2013 update | None within the specified 15-note series |
| Sphere Handbook | Whole 458-page 2018 handbook acquired from IFRC Disaster Law | None within the specified edition |
| Food preservation | Two NCHFP-linked extension PDFs supplement the existing eight USDA canning files | Freezing, broader food safety/drying selection and later canning updates still need acquisition/review |
| NIOSH Pocket Guide | Whole 454-page 2007 third-printing PDF from University of Wisconsin, matching CDC's SHA-512 exactly | Later online updates are separate from this published PDF |
| FEMA civilian preparedness | Whole September 2020 *Are You Ready?* guide | Bounded comprehensive guide; no full Ready.gov website mirror claimed |

## Private downloads and redistribution

This acquisition follows the user's personal, noncommercial offline-use scope.
An official publisher's offered PDF download is used directly. A
`redistributable: false` flag records that OWL has not established a general
right to distribute another person's copy; it does not block the private
download or claim that reading the publisher's download is prohibited.

The original notices remain inside each file. No blanket open license is
inferred for all WHO publications, all university extension publications, or
all medical guidance. In particular, the WHO WASH notes say copyright 2013;
MSF's PDFs retain all-rights-reserved notices. Hesperian provides free chapter
downloads but places conditions on digital adaptations and redistribution.
These sources are not relabeled as Creative Commons or public domain.

Relevant publisher policies and download pages:

- [Hesperian English chapter downloads](https://languages.hesperian.org/pages/en/pdf.html)
  and [Open Copyright Policy](https://hesperian.org/open-copyright-policy/).
- [MSF's offered English manuals](https://medicalguidelines.msf.org/en) and
  [disclaimer](https://medicalguidelines.msf.org/en/node/1338).
- [WHO terms of use](https://www.who.int/about/policies/terms-of-use) and
  [open-access policy](https://www.who.int/about/policies/publishing/open-access).
  A publication's own license takes precedence over an assumption based on
  the publisher's name or a later policy date.
- [Sphere download instructions](https://spherestandards.org/handbook/read-download-order/)
  and [intellectual-property policy](https://spherestandards.org/intellectual-property/).
- [NIOSH's CDC Stacks record](https://stacks.cdc.gov/view/cdc/21265), which marks
  the publication public domain and provides a publisher SHA-512 checksum.
  The acquired Wisconsin copy matches that checksum exactly; SHA-256 was
  separately computed over its downloaded bytes.

## Hesperian: eight books with their context intact

The download set follows the publisher's English chapter listing, including
listed front matter, indexes, glossaries and supplementary pages. Files retain
the book title in catalog metadata and stay together in a book-specific folder.
No chapters are excerpted, recompressed, translated or reconstructed.

| Book | Edition or printing observed in original front matter | Retrieved files |
| --- | --- | ---: |
| Where There Is No Doctor | Twenty-second updated printing, March 2025 | 32 |
| Where Women Have No Doctor | Second edition April 2023; eleventh printing June 2024 | 38 |
| Where There Is No Dentist | Publisher's 2024 PDF revision | 14 |
| A Book for Midwives | Ninth updated printing, July 2026 | 31 of 32 |
| A Community Guide to Environmental Health | First update 2012; first edition May 2008 | 29 |
| Disabled Village Children | Thirteenth updated printing, March 2025 | 72 |
| Helping Children Who Are Blind | 2000 | 21 |
| Helping Health Workers Learn | Second edition, June 2026 | 33 |

The missing file is the publisher's
[2026 midwives back matter](https://hesperian.org/wp-content/uploads/pdf/en_midw_2026/en_midw_2026_bm.pdf).
The collection remains `partial`; the catalog does not silently use an older
printing to fill that gap. The other seven listed book download sets are complete
relative to the publisher's listing checked on the acquisition date.

## MSF and WHO reference scope

The [MSF homepage](https://medicalguidelines.msf.org/en) currently offers the seven
English PDFs acquired here. Dates are taken from the actual PDFs, not the URL's
upload folder:

| Manual | Actual PDF edition/export |
| --- | --- |
| Clinical Guidelines | December 2024; exported 2025-01-30 |
| Essential Drugs | January 2026; exported 2026-04-28 |
| Essential Obstetric and Newborn Care | 2019 edition; exported 2025-04-21 |
| Management of a Cholera Epidemic | 2018 edition; exported 2025-04-01 |
| Management of a Measles Epidemic | 2025 edition; copyright 2026 |
| Tuberculosis | 2025 edition |
| Public Health Engineering in Precarious Situations | Second edition, 2010 |

`ready` means those seven explicitly selected published PDF editions are pinned.
It does not assert clinical currency, equivalence to every current website
update, or suitability as training for an unfamiliar reader. The original MSF
qualifications and intended professional audience remain in each PDF.

The [WHO BEC publication page](https://www.who.int/publications/i/item/basic-emergency-care-approach-to-the-acutely-ill-and-injured)
supplies four added downloads: the November 2025 postpartum-haemorrhage quick
card, BEC quick cards, SBAR job aid, and BEC frequently asked questions.
The [Emergency Care Toolkit page](https://www.who.int/teams/integrated-health-services/clinical-services-and-systems/emergency-and-critical-care/emergency-care-toolkit)
supplies six: the pocket guide, acute-transfer checklist, acute-referral form,
counter-referral form, and medical and trauma resuscitation posters. Together
with the existing whole 2018 BEC manual, these constitute the declared bounded
reference set. Slides, videos and other WHO publications are not claimed.

The [WHO/WEDC WASH series](https://www.who.int/teams/environment-climate-change-and-health/water-sanitation-and-health/environmental-health-in-emergencies/technical-notes-on-wash-in-emergencies)
is complete: notes 1–15 cover wells, boreholes, tanks, piped distribution,
point-of-use treatment, treatment works, solid waste, dead bodies, water
quantity, hygiene, chlorine measurement, tanker delivery, planning excreta
disposal, disposal options and seawater-contaminated wells. Every original
four-page PDF is preserved with its 2013 copyright and illustration credits.

## Other sources and specific gaps

The [FEMA guide archived by GPO](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo159555)
is *Are You Ready? An In-Depth Guide to Citizen Preparedness*, FEMA P-2064,
September 2020. This whole guide adds household preparation, hazard-specific
actions, evacuation, sheltering, communications and recovery beyond OWL's
existing core FEMA manuals. The resource's declared scope is this comprehensive
guide, not all Ready.gov webpages.

For food preservation, NCHFP links to the [UGA kombucha publication](https://fieldreport.caes.uga.edu/publications/C1312/whats-the-word-on-homemade-kombucha/)
and [Montana vegetable-drying guide](https://extension-store.montana.edu/montguides/drying-vegetables).
The acquired PDFs are Circular 1312, revised April 2026, and MontGuide
MT200907HR, revised May 2017. The latter was reviewed by NCHFP's director, as
recorded in its acknowledgments. University authorship is not a public-domain
grant. The Montana notice permits specified nonprofit reprinting but requires
permission for electronic reuse; OWL records personal publisher download only.
Historical UGA freezing and drying PDF links returned HTTP 404 and are not
entered as working assets. These two additions do not complete the full
preservation collection.

The [NIOSH publication page](https://cdc.gov/niosh/publications/numbered/2005-149.html)
identifies DHHS 2005-149, third printing September 2007. Its online counterpart
has later updates. The original CDC and CDC Stacks downloads returned HTTP 403
in this acquisition environment. A bounded alternate-source check found the
[University of Wisconsin's official policy attachment](https://policy.wisc.edu/attachments/UW-6066/6066_NIOSH_Pocket_Guide_2007_2005-149.pdf).
Its full SHA-512 matches CDC Stacks' published checksum exactly, establishing
byte-for-byte identity with the publisher's archival file. The complete
454-page PDF is 6,339,883 bytes; OWL independently computed SHA-256
`c008054cef5aae66addaeab70549d4d549de409f3db75df73c5e7c631a674ad9`.
The original PDF explicitly states public-domain status. It is recorded as the
2007 printing, never as an incorporation of subsequent online updates.

Sphere's publisher download initially returned HTTP 403, and a ReliefWeb
attempt returned non-PDF content. The [IFRC Disaster Law record](https://disasterlaw.ifrc.org/media/1726)
offers the complete fourth-edition PDF directly. Its front matter identifies
2018 and PDF ISBN 978-1-908176-707; its contents include the Humanitarian Charter,
protection principles, Core Humanitarian Standard, WASH, food and nutrition,
shelter, health, annexes and index. The 458-page PDF is 6,274,447 bytes, with
SHA-256 `eeb7e680c296e15389ca8a1e5882a3796f23cbba31cfb21dd4661332c4c8cf63`.
The notice allows educational reproduction with acknowledgment while reserving
other reuse. OWL records this private educational acquisition without claiming
unrestricted online redistribution. No publisher checksum was found, so this
is a locally computed integrity pin for the inspected IFRC-offered edition,
not a claim of independently proven identity with the inaccessible publisher
endpoint. No authentication or access protection was bypassed for either file.

The obsolete unresolved `hesperian_wtnd` single-file placeholder has been
retired from the active shared catalog. The explicit,
verified publisher chapter set now represents that title; retaining the old
placeholder would incorrectly suggest that its acquisition still awaits
blanket permission. The actual remaining Hesperian gap is the one specific
midwives back-matter download described above.

## Verification and search limits

Each acquired file was streamed from its HTTPS source, checked for a PDF
signature, parsed with Poppler `pdfinfo`, hashed using SHA-256, and text-extracted
with `pdftotext`. Editions were inspected in the original front matter. Source
URLs, individual byte counts, hashes, page counts and inspection results are
stored in the acquisition fragment's asset and evidence records.

Representative pages were rendered using `pdftoppm` and visually checked.
`illustrated: true` is assigned only to individually inspected files: the first
chapter of each selected Hesperian book, WHO WASH notes 1 and 5, the WHO pocket
guide and two resuscitation posters, and UGA's kombucha guide. Other PDFs retain
their original images without claiming an individual visual classification.

The two single-page WHO resuscitation posters have no extractable body text;
search can use their metadata unless OCR is added. The toolkit pocket guide has
both searchable text and image/vector-only pages. These PDFs remain directly
viewable. MSF's original 2010 engineering manual uses AES encryption with an
empty opening password; Poppler opens it, while pypdf needs its optional
`cryptography` dependency for text extraction. No original file was decrypted
and rewritten or stripped of notices.

Local verification material is outside Git at
`/private/tmp/owl-acquisition-medical/`. `verified-files.json` maps each new
asset ID to its exact local PDF, byte count and SHA-256, allowing verified files
to be copied into the SSD cache under their digest names without another
download. Temporary downloads are evidence for this run, not a durable public
distribution source or an additional dependency of the catalog.
