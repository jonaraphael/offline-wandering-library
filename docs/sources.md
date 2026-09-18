# Source notes and redistribution

The catalog is an explicit, pinned recipe. Source verification was performed on **2026-09-18 UTC**. Knowledge files and reader packages are downloaded during a build; they are not committed to this repository. A fixed hash pins the bytes even when a publisher reuses a URL. If the bytes change, the builder fails verification instead of silently adopting a new edition. Upstream servers may retire snapshots: keep the cache and two verified drives.

## What was verified

Every resolved entry in `catalog/library.yaml` has an exact byte count and SHA-256. The directly readable PDFs and four Kiwix reader packages were actually downloaded over HTTPS into temporary storage. PDF signatures were checked; titles, editions and licensing were checked against publisher pages and document notices. SHA-256 values were computed from complete files. Reader MD5 values were additionally compared with the publisher's `.md5` files; MD5 is supplemental provenance, never the build's integrity check. Reader binaries were not executed.

Large ZIM files were **not** downloaded during repository development. Their exact sizes and SHA-256 values came from the Kiwix publisher's HTTPS Metalink documents, available by appending `.meta4` to each pinned catalog source URL. The `<file><size>` and `<file><hash type="sha-256">` fields are used; piece hashes are not whole-file SHA-256. These are publisher-published hashes, not independently computed hashes or digital signatures. The builder verifies the complete download against the pinned value.

Hashes prove agreement with the catalog and detect damage; they do not establish medical accuracy, software safety, or an author's identity. Review upstream editions and publisher notices before intentionally changing a pin. The repository does not promise that external URLs stay online forever.

## Directly readable baseline

All four production profiles include these original PDFs, retaining their notices and credits:

| Subject | Included publication and source | Edition / scope |
| --- | --- | --- |
| First aid | [FEMA CERT Participant Manual, preserved by GPO](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo185734) | August 2019; first aid, disaster medical operations, public health and preparedness |
| Emergency medicine | [WHO–ICRC Basic Emergency Care](https://www.who.int/publications/i/item/9789241513081) | 2018; clinical training for first-contact health workers in limited-resource settings |
| Water | [EPA Emergency Disinfection of Drinking Water](https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water-0) | September 2017; EPA 816-F-15-003 |
| Sanitation | [CDC Preventing Diarrheal Illness After a Disaster](https://www.cdc.gov/water-emergency/communication-resources/fact-sheet-preventing-diarrheal-illness-after-a-disaster.html) | PDF dated November 27, 2018; publisher page posted in 2024 |
| Food preservation | [USDA Complete Guide to Home Canning](https://nchfp.uga.edu/resources/entry/about-the-usda-guide-to-home-canning-2015-revision) | 2015 revision, all eight files: introduction and guides 1–7 |
| Agriculture | [USDA NRCS Community Garden Guide](https://www.nrcs.usda.gov/plantmaterials/mipmcot9407.pdf) | November 2009; vegetable garden planning and development |
| Electrical | [Tony Kuphaldt, Lessons in Electric Circuits](https://www.ibiblio.org/kuphaldt/electricCircuits/index.htm) | DC fifth edition and AC sixth edition; license in Appendix 3 |
| Mechanical | [FAA Aviation Maintenance Technician Handbook: General](https://www.faa.gov/regulations_policies/handbooks_manuals/aviation) | FAA-H-8083-30B, 2023; tools, materials, electricity and mechanical principles |
| Shelter | [FEMA Residential Sheltering](https://www.fema.gov/sites/default/files/2020-07/residential-sheltering-safe-rooms_recovery-advisory.pdf) | June 2011; six-page advisory on storm shelter choices |
| Field shelter | [US Army ATP 3-50.21, Survival](https://armypubs.army.mil/epubs/DR_pubs/DR_a/pdf/web/ARN12086_ATP%203-50x21%20FINAL%20WEB%202.pdf) | September 18, 2018; chapter 6 covers field shelters and clothing, with illustrations |
| Navigation | [USGS Finding Your Way With Map and Compass](https://www.usgs.gov/media/files/finding-your-way-map-and-compass) | Fact Sheet 035-01, March 2001; publisher file posted May 3, 2019; explicitly marked public domain |
| Preparedness | [FEMA Emergency Supply Kit Checklist](https://www.fema.gov/sites/default/files/documents/fema_hm-emergency-supply-kit-checklist_english.pdf) | Undated publication; exact snapshot pinned |

The WHO publication is **CC BY-NC-SA 3.0 IGO**. Its own front matter permits noncommercial redistribution with attribution, requires preserving notices, and explains third-party exceptions. Suggested attribution: *Basic emergency care: approach to the acutely ill and injured. Geneva: World Health Organization and the International Committee of the Red Cross; 2018. Licence: CC BY-NC-SA 3.0 IGO.* There is no WHO or ICRC endorsement of OWL. The 2018 book predates WHO's November 2025 postpartum haemorrhage update; the publisher page records that update. Clinical references require training and periodic professional review. OWL does not certify medical content as current or appropriate for every patient.

Kuphaldt's included volumes identify **CC BY 4.0** in their license appendix. Federal-agency publications are generally US Government works; credited third-party illustrations and other contributions keep their own rights. Government hosting alone is not evidence that every separately credited component is public domain. Retain the complete original publications, their attribution and notices. The [Department of the Interior explains this distinction](https://www.doi.gov/copyright). The catalog's `redistributable` field means redistribution is permitted **subject to the named license and its conditions**, not that all uses in all jurisdictions are unrestricted.

These references have uneven depth and different publication dates. Garden guidance is US-oriented; aircraft-maintenance principles do not replace repair instructions for a particular machine; storm-shelter advice does not replace local building codes. The Army outdoor-survival handbook is publicly released government material in a military training context; its historical medical sections are supplementary to the civilian medical references. The corpus is a useful initial collection, not a professionally curated complete survival curriculum.

## Required textbooks and illustrated guides

Textbooks and illustrated guides are part of the directly readable baseline in **every production profile**, including `critical-64gb`. The two complete Kuphaldt electrical textbooks above are joined by five complete OpenStax textbooks under `BOOKS/TEXTBOOKS/`. They provide foundations for understanding quantities, materials, machines and living systems; they are not replacements for task-specific safety or clinical guidance.

| Textbook | PDF pages | Exact downloaded bytes | Foundation |
| --- | ---: | ---: | --- |
| [Prealgebra 2e](https://openstax.org/details/books/prealgebra-2e) | 1,074 | 63,194,495 | Arithmetic, fractions, ratios, measurement and algebra |
| [College Physics 2e](https://openstax.org/details/books/college-physics-2e) | 1,671 | 263,463,256 | Mechanics, fluids, heat, electricity, waves and optics |
| [Chemistry 2e](https://openstax.org/details/books/chemistry-2e) | 1,203 | 217,794,376 | Matter, reactions, solutions, thermodynamics and electrochemistry |
| [Biology 2e](https://openstax.org/details/books/biology-2e) | 1,475 | 401,298,122 | Cells, genetics, plants, animals and ecology |
| [Anatomy and Physiology 2e](https://openstax.org/details/books/anatomy-and-physiology-2e) | 1,347 | 476,335,014 | Human structures and organ systems |

The five files total **1,422,085,263 bytes** (about 1.42 GB), keeping the entire critical profile at **1,574,545,596 bytes** before generated search and navigation. Original PDF figures, labels, worked examples, tables and exercises are retained. OWL does not replace these books with text extracts, compress their images, or split them into missing-context snippets. Search extracts text separately while linking to the intact PDF. External activities, videos and publisher web features linked from the books are not downloaded.

The original download URLs were obtained from the publisher's book pages and [OpenStax's public book metadata](https://openstax.org/apps/cms/api/books/?format=json), then fully downloaded over HTTPS and hashed. The exact downloaded PDFs identify **©2026 Rice University, CC BY-NC-SA 4.0**, even where older API update timestamps remain. The catalog therefore records a dated publisher-PDF snapshot, not an inferred edition date from that API. These pins are for noncommercial reuse under the actual notices in the files; do not infer a different license from older OpenStax editions. Preserve all third-party credits, notices and trademark restrictions. The attribution required by the included PDFs is **“Access for free at openstax.org.”** Keep it on every digital page view of reused content, including extracted excerpts. The full author/book attribution and source URL are retained in the catalog and generated inventory. No OpenStax or Rice University endorsement is implied.

`resource_type: textbook` identifies a substantial teaching text. `illustrated: true` means representative pages were actually rendered and visually checked for relevant diagrams or photographs in this source snapshot. It does not claim every page is illustrated, every diagram is current, or a complete pedagogical review has occurred. Untagged/false entries can still contain illustrations; they have not been admitted to this curated shelf on that basis. Both shelves may include the same book. The following representative pages were inspected; PDF page numbers count from the first physical page, including covers:

| Included work | PDF page | Checked visual content |
| --- | ---: | --- |
| Prealgebra 2e | 38 | Figure 1.10: base-ten regrouping in addition, with worked examples |
| College Physics 2e | 45 | Figures 1.23–1.24: accuracy and precision target diagrams |
| Chemistry 2e | 28 | Figure 1.6: solid/liquid/gas diagrams; Figure 1.7: plasma photograph |
| Biology 2e | 40 | Figures 1.10–1.11: organism photographs explaining biological responses |
| Anatomy and Physiology 2e | 28 | Figure 1.4: labeled human organ-system illustrations |
| Lessons in Electric Circuits: DC | 22 | Electron-flow and marble-loop circuit diagrams |
| Lessons in Electric Circuits: AC | 14 | Figures 1.5–1.7: gear train, transformer and power-transmission schematics |
| FEMA CERT | 103 | Image 3.1: tourniquet photograph alongside first-aid instruction |
| WHO–ICRC Basic Emergency Care | 116 | Shock-treatment flowchart and anatomical illustration; 2018 clinical edition caveat applies |
| USDA Canning Guide 1 | 12 | Raw-pack/hot-pack jar-filling diagrams |
| FAA General Maintenance Handbook | 24 | Figures 1.1–1.2: nitrogen cylinder photograph and hazard-identification diamond |
| Army Survival | 140 | Figure 6-2: poncho lean-to, alongside field-shelter instructions |
| USGS Map and Compass | 1 | Annotated topographic-map example and scale table |

Every production profile enforces `minimum_coverage` floors of **seven required critical textbooks** and **eight required critical illustrated guides**. This snapshot includes seven and thirteen respectively. Only resolved, directly readable files count; a ZIM encyclopedia, optional book or reader package cannot satisfy these floors. The builder prioritizes required critical teaching material before large archives. The floor is an intentional guard against silently dropping the teaching collection when a catalog is edited.

## Archives, maps and larger profiles

Kiwix's [Wikipedia](https://download.kiwix.org/zim/wikipedia/), [Wiktionary](https://download.kiwix.org/zim/wiktionary/), [Wikibooks](https://download.kiwix.org/zim/wikibooks/), [iFixit](https://download.kiwix.org/zim/ifixit/) and [other collections](https://download.kiwix.org/zim/other/) directories supply the pinned ZIM snapshots.

- `compact-256gb` adds full English Wikipedia without pictures (June 2026), WikiMed (April 2026), English Wiktionary (August 2026), English Wikibooks (April 2026), and iFixit (December 2025).
- `standard-512gb` replaces no-picture Wikipedia with the full illustrated August 2026 archive and adds Appropedia (February 2026).
- `full-1tb` adds the March 2023 English Khan Academy educational collection, approximately 180 GB including video. Speech inside audio/video is not transcribed by OWL's text index.
- All three archive profiles also include [USGS This Dynamic Planet](https://pubs.usgs.gov/imap/2800/), third edition (2006), as two ordinary PDF sheets. These provide world geographic and tectonic reference, **not local roads, evacuation routes or live hazard information**.

[Wikimedia terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) and article/media notices govern Wikimedia archives. Text is generally CC BY-SA 4.0, with individual exceptions and media licenses retained in the archive. [iFixit](https://www.ifixit.com/Info/Licensing) is CC BY-NC-SA 3.0; redistribution must be noncommercial and preserve attribution. [Appropedia](https://www.appropedia.org/Appropedia:Terms_of_use) defaults to CC BY-SA 4.0, except where stated. [Khan Academy permits reuse under its content conditions](https://support.khanacademy.org/hc/en-us/articles/202262954-Can-I-use-Khan-Academy-s-videos-name-materials-links-in-my-project); video and exercise content uses CC BY-NC-SA and individual notices still apply. All Khan Academy content is available for free at [khanacademy.org](https://www.khanacademy.org/). None of these publishers endorses OWL.

The archive contents and applications have not all been opened or run during repository development. Pins establish downloadable releases and byte integrity, not end-to-end certification of hundreds of gigabytes. Larger profiles leave substantial capacity for indexes, working space, updates and user-selected regional material; profile names specify target drive capacities rather than a promise to fill the disk.

## Readers and corresponding source

| Platform | Pinned offline package | Upstream source |
| --- | --- | --- |
| Windows x64 | Kiwix Desktop 2.5.1 portable ZIP | [kiwix-desktop](https://github.com/kiwix/kiwix-desktop) |
| Linux x86_64 | Kiwix Desktop 2.5.1 AppImage | [kiwix-desktop](https://github.com/kiwix/kiwix-desktop) |
| macOS | Kiwix 3.14.0 DMG | [apple](https://github.com/kiwix/apple) |
| Android | Kiwix standalone 3.14.0 APK | [kiwix-android](https://github.com/kiwix/kiwix-android) |

These pinned versions are selected verified releases, not a claim to be the newest release. [Official download options](https://get.kiwix.org/en/solutions/applications/download-options/) link to the release channels. The standalone Android package can open external files through its file picker; it differs from the restricted Play Store package. Installation can still be forbidden by device policy.

Desktop/Android sources identify GPL version 3 or later; the Apple repository supplies GPL version 3. Bundled libraries have additional licenses. Keeping a private backup is different from distributing binary copies to others. **Before distributing completed SSDs containing GPL binaries, satisfy the applicable corresponding-source and notice obligations, including bundled GPL components.** Merely providing a GitHub URL is not a substitute for the obligations of a physical binary distribution. OWL currently pins reader binaries but does not assemble a complete corresponding-source bundle for all transitive dependencies. Review the packages' license/offer materials and arrange compliant source delivery before distribution. Do not sell a drive containing noncommercial content without the necessary rights.

The AppImage is not an ARM Raspberry Pi reader. Linux AppImages may need FUSE or extraction to a native Linux filesystem; exFAT generally does not preserve execute bits. Windows, macOS and Android may impose installation or security restrictions. Prepare and test each intended device while online. iPhone cannot generally install an iOS Kiwix app from a USB SSD offline; the ordinary critical PDFs and static indexes remain the baseline.

## Unresolved entries

`status: unresolved` records are visible in the catalog, excluded from selected downloads, and reported in build metadata. No fabricated byte count, checksum or direct URL stands in for missing evidence.

1. **Hesperian Where There Is No Doctor:** the [publisher's open-copyright policy](https://hesperian.org/open-copyright-policy/) requires written permission for use in any digital format, including distribution of online materials. This project has no such permission. Its optional record is excluded. WHO and FEMA provide the included medical baseline.
2. **Regional topographic and evacuation maps:** choose maps for the intended locality and record each verified source URL, edition, size, hash and rights. [USGS Map Locator](https://store.usgs.gov/map-locator) is a starting point for US locations. No single preselected region can serve an arbitrary user. The initial world map is not a substitute.

## Refreshing a source

Find the publication or release on the original publisher's page. Download the actual file over HTTPS, inspect its type and notices, record the exact edition, then compute its byte count and SHA-256. For a large Kiwix archive, inspect the publisher's `.meta4` whole-file fields before downloading. Never copy a hash from a differently named release, invent a size from a rounded directory listing, or trust a successful HTTP status alone: some retired PDF links return HTML with status 200. Update the catalog in a reviewed change and keep the old pinned cache for reproducible historical rebuilds.

`catalog/demo.yaml` refers only to tiny original files in `assets/demo/`, dedicated by OWL contributors under CC0 1.0. Those files test navigation and search; they are intentionally not emergency guidance.
