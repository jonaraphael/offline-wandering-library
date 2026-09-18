# Content selection and acquisition status

`catalog/resources.yaml` records all **46 numbered collections** in the requested acquisition list and **three unnumbered support resources**, for 49 entries. Its stable resource IDs are the units selected by the three larger profiles and optional include/exclude choices. `catalog/library.yaml` contains the separate, exact file metadata used by the downloader. An entry in this planning registry is not evidence that the collection has already been assembled.

All targets use decimal bytes: **1 GB = 1,000,000,000 bytes**. The numbered `target_bytes` values are the user's approximate curation budgets, not verified download sizes, quotas that should be filled, or promises about today's upstream archives. A source URL belongs in the downloadable asset catalog only after its file, rights, exact size and SHA-256 are established. Do not substitute a rounded directory listing or a collection's planning target for those values.

The snapshot currently has **five ready resource mappings, six partial mappings and 38 unresolved mappings**, including the three unnumbered support resources. `ready` means the stated scope has pinned resolved asset entries; it does not mean every multi-gigabyte file was downloaded or every device tested during development. `partial` identifies usable pinned files with material scope still missing. `unresolved` identifies a planned collection without a usable complete mapping, whether the missing work is permission, title selection, package generation, source metadata or locality choice. Reasons are explicit below and in the registry. A build must not silently present a partial or unresolved collection as fulfilled.

## Profile planning

The [offline selector](selector.md) at [`SELECT.html`](../SELECT.html) presents presets for nominal 16 GB, 64 GB, 256 GB, 512 GB, and 1 TB drives, with inclusion controls, live estimates, and copied CLI commands. Its embedded recipe can be regenerated with `python scripts/build_selector.py` and checked with `python scripts/build_selector.py --check`. The page works offline without installation; executing a build needs the Python project and network access for new downloads.

`flash-16gb` and `critical-64gb` are fixed selections of 25 verified directly readable PDFs totaling **1,574,545,596 bytes**, including seven textbooks and thirteen illustrated works. Small-preset selector rows use **Preset files only · direct**: existing WHO or OpenStax files are not relabeled as fulfillment of their broader collection plans. Choosing **Published collection** explicitly requests the whole intended resource through `--include`, with its full target and availability status. Inclusion/exclusion controls produce the normal CLI selection arguments.

The 16 GB preset has no unresolved selected files or archive-reader dependency. Its content, 2 GB index budget, 4 GB scratch allowance, 16 MiB metadata allowance, and 2 GB reserve total **9,591,322,812 bytes** of planned in-place peak storage. The unused capacity is left free, not filled with estimated or unresolved content. The 64 GB preset retains the same verified files and an 8 GB reserve.

The ordered list expresses acquisition priorities. Larger profiles retain direct readable material before adding specialized archives, video and optional language collections. Ordinary PDF, HTML, TXT, EPUB and images are preferred whenever practical. Textbook diagrams, children's illustrations, guide steps and safety context must survive any export. ZIM is useful for full encyclopedias; it cannot replace the directly readable emergency baseline.

| Profile | Requested content envelope | Sum of currently selected planning targets | Search budget | Reader budget | Free-space reserve |
| --- | ---: | ---: | ---: | ---: | ---: |
| `compact-256gb` | 190–210 GB | 200.314 GB | 24 GB | 5 GB | 16 GB |
| `standard-512gb` | 390–420 GB | 397.514 GB | 48 GB | 5 GB | 38 GB |
| `full-1tb` | 750–820 GB | 769.514 GB | 90 GB | 5 GB | 80 GB |

These sums are estimates for the **intended** selected collections, including unresolved work; they are not the much smaller amount of content downloadable from today's verified catalog. The 1 TB plan includes an additional **60 GB for directly readable editions of selected material**, following the user's preference for access without a ZIM reader. Its declared estimate is 769.514 GB; using larger known asset sizes where they exceed an estimate raises its effective planning budget to approximately **779.374 GB**. That effective budget still includes unresolved estimates and is not a claim that 779 GB has been sourced or acquired.

The compact plan covers numbered resources 1–18 and limits regional maps to a **10 GB** local/regional selection, excluding the 21 GB North America OSM component. The standard plan covers 1–31 and overrides Survivor Tier A to **75 GB**. The 1 TB plan includes 1–36 and 42–44 and 46, including **Spanish Wikipedia by default**, plus `direct-reading-expansion`. French, Chinese, Arabic, Portuguese and Italian Wikipedia remain opt-in, as does **#45 remaining Khan Academy**. The added direct-reading allowance does not add further Khan, language or map collections. Selected archive content also brings the pinned reader support resource. The independent small profiles remain concrete directly readable asset selections.

The selector separates intended targets from known verified asset bytes, and shows search, temporary search work, metadata, reader allowances, and reserve. Current complete larger targets can exceed nominal capacity during in-place building even when their final-content targets appear suitable. The page cannot inspect filesystem free space or reuse existing files; the CLI plan does that. A partial build requires the explicit, initially unchecked `--allow-incomplete` option and remains recorded as incomplete. The selector's default-on human-atlas option affects generated navigation, not collection availability.

## Registered storage editions

A resource may define optional `direct` and `compact` entries under `editions`, each naming actual catalog assets, a target size, availability, and an explanation where incomplete. The default **Published collection** keeps the existing resource's formats and scope. Registered alternatives are selected using `--edition RESOURCE=direct` or `--edition RESOURCE=compact` for an included resource. They must retain critical ordinary-format files; a compact archive cannot become their only representation.

No production alternate editions are registered yet. The selector displays unavailable direct-readable and compact choices as disabled. It does not estimate savings from a made-up compression factor, build archives, extract millions of pages, or imply identical content between unreviewed formats. Exact files and rights must be established before an edition is offered. The separately planned `direct-reading-expansion` below remains unresolved.

The raw sum of all 46 absolute planning targets is **954.38 GB**. If both regional maps and the world-map upgrade are selected, replacing North America receives a **21 GB** credit, producing **933.38 GB** for the numbered candidate pool. The earlier approximately 936 GB figure was a rough estimate. The complementary direct core adds 0.134021877 GB, and the unnumbered direct-reading expansion adds 60 GB when selected; search, readers, filesystem overhead and free-space reserve are separate. The entire candidate pool therefore does not comfortably fit a nominal 1 TB drive.

## Additional directly readable editions

`direct-reading-expansion` reserves **60 GB of additional representation storage** in the 1 TB default. It prioritizes ordinary HTML, PDF, TXT and image copies of selected Appropedia, CD3WD, iFixit, LibreTexts STEM and English Wikibooks material, plus a broader high-priority Wikipedia HTML lifeboat. The goal is useful reading without a ZIM reader. Keep diagrams, photographs, labels, captions, instructions, article or book context, source versions, licensing notices and navigable local entry pages.

The allowance covers additional copies beyond directly readable files and editions already budgeted elsewhere. It does not double-count existing PDFs, authorize new subject collections or require filling a quota. It also does not mean expanding all of Wikipedia into millions of files on exFAT. The derivative selection must follow a reviewed article/book list drawn only from source resources selected for that build. Excluding a source collection also excludes its planned derivatives; this expansion must never silently restore excluded material.

The resource remains **unresolved**: no extraction pipeline, curated derivative manifest or pinned output package is implemented yet. These are requirements for resolving it, not claims of existing automatic conversion. To omit its additional 60 GB allowance while keeping the normal directly readable baseline, pass `--exclude direct-reading-expansion` to the resource-aware build or planning command. Excluding it does not remove direct content already supplied by another selected resource.

## Map replacement and optional selections

`regional-maps` contains two distinct needs: the North America OSM archive and directly readable local topographic maps. Its normal **51 GB** envelope comprises a 21 GB continental map component and a roughly 30 GB topo allowance. Its unresolved `regional_topographic_maps` asset records the missing locality selection. Existing USGS world geographic/tectonic reference sheets are not road, terrain or evacuation coverage and do not fulfill this resource.

`world-maps` is an **absolute 72 GB** resource, not a 51 GB file. Its `replaces_asset_ids` suppresses only `map_osm_north_america`; its `replacement_credit` subtracts 21 GB only when that North America component would otherwise be selected. The local topographic component remains selected. If the regional resource is absent, or the compact override already excludes North America, no replacement credit applies. Both OSM archive entries are currently unresolved placeholders, not invented download URLs.

Language choices should follow the intended readers. Optional Survivor Tier B, multilingual Gutenberg and legacy-computing material need their own quality and deduplication decisions. To reduce space, the original curation priorities cut remaining Khan, Survivor Tier B, the legacy appendix, unused-language Wikipedias, TED-Ed, redundant Wikisource and the world-map upgrade before reducing health, books, children's material, agriculture, repair or local terrain coverage. Gutenberg and Children's Library are first-class navigation categories even while their acquisition packages remain unresolved.

## Source and format decisions

Official source pages were reviewed on **2026-09-18 UTC** for the specific checks summarized here. A verified information page is not a verified bulk package.

- [Project Gutenberg's mirroring guide](https://www.gutenberg.org/help/mirroring.html) supports selective mirrors and distinguishes curated HTML/text from generated formats. Use a stable book-ID selection, preserve notices, check public-domain status for the destination jurisdiction and avoid redundant editions.
- [Book Dash](https://bookdash.org/) expressly supports reading, downloading, adapting, printing and distributing its books. [African Storybook](https://www.africanstorybook.org/) provides offline download/print access and displays CC BY 4.0. The registry still requires per-book files, credits and reproducible exports before the full children's collection is fulfilled.
- [WHO's WASH technical-note page](https://www.who.int/teams/environment-climate-change-and-health/water-sanitation-and-health/environmental-health-in-emergencies/technical-notes-on-wash-in-emergencies) identifies 15 notes. Their rights must be checked independently of the separately licensed BEC manual. [MSF's guideline portal](https://medicalguidelines.msf.org/en) distinguishes online guidance from PDFs that may not be updated.
- [Hesperian's digital-use policy](https://hesperian.org/open-copyright-policy/) requires written permission; this project has none. Its unresolved entry is deliberate. Permission to read a web page does not establish permission to redistribute a digital library.
- [Sphere's editions page](https://spherestandards.org/handbook/editions/) and [NIOSH's Pocket Guide page](https://www.cdc.gov/niosh/npg/default.html) provide official download entry points, but exact packages still require pinning.
- [PhET's offline-access guidance](https://phet.colorado.edu/en/offline-access) supports individual simulation downloads and documents device-specific access. Check the current [license terms](https://phet.colorado.edu/en/licensing) of each package and test actual local execution. Do not infer that older licensing or a desktop result guarantees iPhone external-drive support.
- [CIA's official notice](https://www.cia.gov/stories/story/spotlighting-the-world-factbook-as-we-bid-a-fond-farewell/) says the World Factbook ended on February 4, 2026. Resource 30 therefore needs an explicitly historical preserved snapshot, not a fictional current CIA feed.

The checked OpenStax PDFs, their actual CC BY-NC-SA 4.0 notices, required attribution and inspected illustration pages are documented in [sources.md](sources.md). Five books are a useful starting point for resource 22; they do not fulfill the much broader requested textbook list. Likewise, a full English Wikipedia, Appropedia or iFixit ZIM cannot satisfy the requested complementary direct-HTML/PDF selections. The old full 180 GB Khan package has been removed from profile selection; neither the 90 GB core-STEM target nor the optional 80 GB remainder is a renamed copy of it.

The following enumeration preserves the requested subject filters. These are curation requirements for a future resolved package, not claims that all filtering/export pipelines are implemented. In particular, Stack Exchange needs a pinned lawful input, per-post attribution and license handling, deterministic quality filters, deduplication and static rendering. The legacy corpus additionally needs separate ranking and the visible historical-system badge before it can be marked ready.

## Registry overview

| # | Resource ID | Planning target | Availability |
| --- | --- | ---: | --- |
| 1 | `hesperian-health` | 0.5 GB | unresolved |
| 2 | `msf-medical` | 0.25 GB | unresolved |
| 3 | `who-emergency-care` | 0.1 GB | partial |
| 4 | `who-wash` | 0.1 GB | unresolved |
| 5 | `sphere-handbook` | 0.05 GB | unresolved |
| 6 | `food-preservation` | 0.1 GB | partial |
| 7 | `niosh-chemical-hazards` | 0.01 GB | unresolved |
| 8 | `fao-agriculture` | 0.5 GB | unresolved |
| 9 | `gutenberg-core` | 40 GB | unresolved |
| 10 | `childrens-library` | 22 GB | unresolved |
| 11 | `wikipedia-en` | 119 GB | partial |
| 12 | `wikimed` | 2.1 GB | ready |
| 13 | `wikem` | 0.36 GB | unresolved |
| 14 | `regional-maps` | 51 GB | unresolved |
| 15 | `appropedia` | 0.56 GB | partial |
| 16 | `cd3wd` | 0.55 GB | unresolved |
| 17 | `ifixit` | 3.3 GB | partial |
| 18 | `low-tech-magazine` | 0.7 GB | unresolved |
| 19 | `survivor-tier-a` | 100 GB | unresolved |
| 20 | `stackoverflow-durable` | 25 GB | unresolved |
| 21 | `stackexchange-practical` | 12 GB | unresolved |
| 22 | `openstax-core` | 12 GB | partial |
| 23 | `libretexts-stem` | 8.5 GB | unresolved |
| 24 | `wikibooks-en` | 5.8 GB | ready |
| 25 | `wiktionary-en` | 8.5 GB | ready |
| 26 | `phet` | 0.1 GB | unresolved |
| 27 | `wikiversity-en` | 2.3 GB | unresolved |
| 28 | `civilian-preparedness` | 0.5 GB | unresolved |
| 29 | `wikivoyage-en` | 1.1 GB | unresolved |
| 30 | `world-factbook` | 0.4 GB | unresolved |
| 31 | `linux-programming-docs` | 5 GB | unresolved |
| 32 | `stackexchange-science` | 9 GB | unresolved |
| 33 | `wikisource-en` | 18 GB | unresolved |
| 34 | `ted-ed` | 6 GB | unresolved |
| 35 | `khan-core-stem` | 90 GB | unresolved |
| 36 | `wikipedia-es` | 38 GB | unresolved |
| 37 | `wikipedia-fr` | 52 GB | unresolved |
| 38 | `wikipedia-zh` | 25 GB | unresolved |
| 39 | `wikipedia-ar` | 18 GB | unresolved |
| 40 | `wikipedia-pt` | 19 GB | unresolved |
| 41 | `wikipedia-it` | 30 GB | unresolved |
| 42 | `world-maps` | 72 GB | unresolved |
| 43 | `gutenberg-multilingual` | 30 GB | unresolved |
| 44 | `survivor-tier-b` | 30 GB | unresolved |
| 45 | `khan-remaining` | 80 GB | unresolved |
| 46 | `stackoverflow-legacy` | 15 GB | unresolved |
| — | `owl-direct-core` | 0.134022 GB | ready |
| — | `archive-readers` | 0 GB | ready |
| — | `direct-reading-expansion` | 60 GB | unresolved |

## Detailed selection rules

### 1. Hesperian low-resource health library

Resource `hesperian-health`; target **0.5 GB**; preferred formats: pdf, html. Availability: **unresolved**.

Publisher policy requires written permission for digital use; OWL has no permission or pinned authorized package. The existing unresolved single-title record does not fulfill this collection.

Mapped asset IDs: `hesperian_wtnd`.

Include:

- Where There Is No Doctor.
- Where Women Have No Doctor.
- Where There Is No Dentist.
- A Book for Midwives.
- Environmental health.
- Disability and child-health guides.
- Health-worker training.

Exclude or avoid:

- Digital copying or redistribution without the required publisher permission.

Source pages: [source 1](https://hesperian.org/open-copyright-policy/).

### 2. MSF Medical Guidelines

Resource `msf-medical`; target **0.25 GB**; preferred formats: pdf, html. Availability: **unresolved**.

The publisher offers several guidelines but warns that some PDFs are not updated. Current titles, authorized snapshot method, licensing and exact file pins require review.

Mapped asset IDs: none yet.

Include:

- Clinical Guidelines.
- Essential Drugs.
- Obstetric and newborn care.
- Cholera.
- Measles.
- Tuberculosis.
- Public-health engineering.
- Versioned PDF and static HTML snapshots with update dates.

Exclude or avoid:

- Unreviewed claims that an older PDF matches the current online guidance.

Source pages: [source 1](https://medicalguidelines.msf.org/en).

### 3. WHO Basic Emergency Care and emergency clinical references

Resource `who-emergency-care`; target **0.1 GB**; preferred formats: pdf. Availability: **partial**.

The verified 2018 BEC PDF is available. Related emergency references and subsequent updates have not been selected and pinned; the whole requested collection is incomplete.

Mapped asset IDs: `medical_bec`.

Include:

- Complete Basic Emergency Care manual.
- Directly related emergency-care reference material.
- Explicit edition dates and clinical limitations.

Exclude or avoid:

- Treating a single historical manual as a complete current emergency-care collection.

Source pages: [source 1](https://www.who.int/publications/i/item/9789241513081).

### 4. WHO WASH in Emergencies

Resource `who-wash`; target **0.1 GB**; preferred formats: pdf. Availability: **unresolved**.

The complete 15-note source page is verified, but individual downloads and rights have not been pinned. The 2013 notes carry copyright notices; do not infer the BEC license applies.

Mapped asset IDs: none yet.

Include:

- All 15 WHO/WEDC technical notes.
- Water quantity.
- Cleaning and disinfecting wells and boreholes.
- Chlorination and chlorine measurement.
- Tanks and tankers.
- Piped distribution and treatment works.
- Point-of-use drinking-water treatment.
- Sanitation and excreta disposal.
- Solid waste.
- Dead-body disposal.
- Hygiene promotion.
- Wells after seawater flooding.

Exclude or avoid:

- Substituting a general water leaflet for the full technical-note series.

Source pages: [source 1](https://www.who.int/teams/environment-climate-change-and-health/water-sanitation-and-health/environmental-health-in-emergencies/technical-notes-on-wash-in-emergencies).

### 5. Sphere Handbook

Resource `sphere-handbook`; target **0.05 GB**; preferred formats: pdf, html. Availability: **unresolved**.

Official handbook and download pages are verified; an edition-specific PDF/HTML package, permissions and integrity pins are still needed.

Mapped asset IDs: none yet.

Include:

- Whole handbook.
- Humanitarian Charter and protection principles.
- Core Humanitarian Standard.
- WASH, food security, nutrition, shelter and health standards.

Exclude or avoid:

- Handbook fragments presented as the complete edition.

Source pages: [source 1](https://spherestandards.org/handbook/), [source 2](https://spherestandards.org/handbook/editions/).

### 6. USDA and NCHFP food preservation

Resource `food-preservation`; target **0.1 GB**; preferred formats: pdf, html. Availability: **partial**.

All eight files of the verified USDA 2015 canning guide are pinned. Current freezing, drying, fermentation and broader food-safety selections are not yet pinned.

Mapped asset IDs: `food`, `canning_00`, `canning_02`, `canning_03`, `canning_04`, `canning_05`, `canning_06`, `canning_07`.

Include:

- Current canning guidance.
- Freezing.
- Drying.
- Fermentation.
- Food safety.
- Retain processing tables and illustrations in context.

Exclude or avoid:

- Assuming the 2015 canning volumes alone cover all preservation methods or reflect every later update.

Source pages: [source 1](https://nchfp.uga.edu/resources/entry/about-the-usda-guide-to-home-canning-2015-revision).

### 7. NIOSH Pocket Guide to Chemical Hazards

Resource `niosh-chemical-hazards`; target **0.01 GB**; preferred formats: pdf. Availability: **unresolved**.

NIOSH confirms an official PDF is available; the exact downloadable file and edition have not yet been hashed and entered in the asset catalog.

Mapped asset IDs: none yet.

Include:

- Whole current downloadable guide.
- Chemical names, exposure limits, incompatibilities, protective measures and first aid.
- Record the edition and differences from online updates.

Exclude or avoid:

- A mobile-app-only copy.

Source pages: [source 1](https://www.cdc.gov/niosh/npg/default.html).

### 8. FAO practical agriculture core

Resource `fao-agriculture`; target **0.5 GB**; preferred formats: pdf, html. Availability: **unresolved**.

The instructional scope is defined, but a title-level FAO selection, rights review and pinned files remain to be created. The baseline NRCS garden guide is not this collection.

Mapped asset IDs: none yet.

Include:

- Crop production fundamentals.
- Soil fertility and composting.
- Irrigation.
- Crop-water requirements.
- Seed storage.
- Small-scale post-harvest handling.
- Grain storage.
- Vegetable production.
- Poultry.
- Rabbits and small livestock.
- Dairy basics.
- Animal feeding.
- Pest management.
- Greenhouse and protected growing.
- Food-loss reduction.
- Small-farm tools.
- Basic aquaculture where practical.

Exclude or avoid:

- Policy documents.
- Statistical yearbooks.
- Meeting reports.
- Economic forecasting.
- Administrative material.
- Country programme reports.

Source pages: [source 1](https://www.fao.org/sustainable-food-value-chains/training-and-learning-center/en/), [source 2](https://openknowledge.fao.org/).

### 9. Project Gutenberg core library

Resource `gutenberg-core`; target **40 GB**; preferred formats: html, txt, epub. Availability: **unresolved**.

Gutenberg supports selective mirrors, but a reproducible book-ID selection, deduplication and pinned direct-format export are not implemented. A seed book would not fulfill the 40 GB collection.

Mapped asset IDs: none yet.

Include:

- Major English-language literature.
- World classics in English translation.
- Poetry.
- Mythology and folklore.
- History.
- Philosophy.
- Biographies.
- Science classics.
- Mathematics classics.
- Practical historical texts.
- Dictionaries and reference works not better duplicated elsewhere.
- Children and young-adult classics.
- Major drama.
- Language-learning and public-domain grammars.
- Older technical books complementing Survivor Library.
- One preferred reading representation per work; HTML with images when useful, UTF-8 TXT fallback and an EPUB where it adds phone-reading value.
- Retain book-level rights notices and country-specific public-domain limitations.

Exclude or avoid:

- Audio editions.
- Kindle and MOBI duplicates.
- Duplicate EPUB variants.
- Low-value OCR scans when a good text edition exists.
- Materially identical editions.
- Periodicals without clear utility.

Source pages: [source 1](https://www.gutenberg.org/help/mirroring.html).

### 10. Children's Library

Resource `childrens-library`; target **22 GB**; preferred formats: pdf, html, epub, png, jpeg, txt. Availability: **unresolved**.

Book Dash permits redistribution and African Storybook offers offline downloads, but complete authorized direct-format exports, per-title metadata, deduplication and hashes are not yet assembled.

Mapped asset IDs: none yet.

Include:

- Book Dash: essentially all available books, with normal ebook PDFs, extracted text, covers and illustrations, available translations and optional print-ready PDFs.
- African Storybook: whole collection initially where authorized exports allow PDF, HTML or images plus text.
- Gutenberg: picture books, fairy tales, folk tales, early readers, classics, adventure, nature and science, history and biography, teen classics and poetry.
- Deduplicate titles already represented better by another source.
- Top-level navigation alongside Gutenberg, health, food/water, repair, maps and search.
- Preserve illustrations and per-book author, illustrator, translator and license credits.

Exclude or avoid:

- Depending solely on the Book Dash ZIM.
- A ZIM-only children’s collection when direct exports are practical.
- Redundant editions across publishers.

Source pages: [source 1](https://bookdash.org/), [source 2](https://www.africanstorybook.org/), [source 3](https://www.gutenberg.org/help/mirroring.html), [source 4](https://ftp.fau.de/kiwix/zim/other/).

### 11. English Wikipedia, full

Resource `wikipedia-en`; target **119 GB**; preferred formats: zim, html. Availability: **partial**.

The full English maxi ZIM is pinned. The requested direct HTML lifeboat and curated article list are missing. The 119 GB target is a planning envelope including its allowance, not the exact ZIM byte count.

Mapped asset IDs: `wikipedia_en`.

Include:

- Whole pinned English maxi archive with images.
- Small article-list-driven HTML lifeboat under WIKIPEDIA/DIRECT/; aim for roughly 2–5 GB within this planning envelope.
- Lifeboat: human anatomy, common diseases, first-aid concepts and medicines.
- Lifeboat: crops, food preservation, water treatment and sanitation.
- Lifeboat: electricity, motors, generators, batteries, radios and mechanical systems.
- Lifeboat: chemistry, materials, construction, navigation, meteorology and mathematics fundamentals.

Exclude or avoid:

- Expanding millions of articles into individual exFAT files.
- Replacing full maxi with nopic or mini without an explicit profile decision.
- Selecting lifeboat articles solely to fill a quota.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 12. WikiMed / MDWiki

Resource `wikimed`; target **2.1 GB**; preferred formats: zim. Availability: **ready**.

The stated scope maps to resolved, pinned asset entries.

Mapped asset IDs: `wikimed_en`.

Include:

- Whole pinned English medical encyclopedia.
- Preserve clinical and licensing notices.

Exclude or avoid:

- Treating encyclopedia access as professional medical training.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 13. WikEM

Resource `wikem`; target **0.36 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole emergency-medicine reference.
- Version and clinical caveats.

Exclude or avoid:

- Unversioned clinical guidance.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 14. Regional maps and topography

Resource `regional-maps`; target **51 GB**; preferred formats: zim, pdf. Availability: **unresolved**.

The North America OSM asset is an unresolved placeholder pending exact source metadata. Locality-specific GeoPDF coverage is not selected. Existing USGS Dynamic Planet reference sheets do not fulfill this resource.

Mapped asset IDs: `map_osm_north_america`, `regional_topographic_maps`.

Include:

- North America OSM archive; 21 GB planning component.
- Detailed local and regional GeoPDF/topographic maps; roughly 20–40 GB, with 30 GB in this default envelope.
- Home state or region.
- Neighboring states or regions.
- Likely evacuation corridors.
- Major watersheds.
- National and state forests.
- Major transport corridors.
- Compact profile may use a 10 GB regional selection instead of the full default envelope.

Exclude or avoid:

- High-resolution topography for the entire continent by default.
- Treating physical-world/tectonic reference sheets as local road or evacuation maps.
- Automatically retaining North America OSM when the world replacement is selected.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/maps/), [source 2](https://store.usgs.gov/map-locator).

### 15. Appropedia

Resource `appropedia`; target **0.56 GB**; preferred formats: zim, html. Availability: **partial**.

The whole Appropedia ZIM is pinned; the required selection and offline HTML export of critical articles are not yet generated.

Mapped asset IDs: `appropedia_en`.

Include:

- Whole pinned snapshot.
- Selected critical articles as directly readable HTML.

Exclude or avoid:

- Critical practical content available only inside ZIM.

Source pages: [source 1](https://www.appropedia.org/Appropedia:Terms_of_use), [source 2](https://ftp.fau.de/kiwix/zim/other/).

### 16. CD3WD appropriate-development archive

Resource `cd3wd`; target **0.55 GB**; preferred formats: zim, pdf. Availability: **unresolved**.

An exact archive snapshot, contained-publication rights and PDF extraction plan remain unresolved; historical archive availability alone is not license evidence.

Mapped asset IDs: none yet.

Include:

- Whole current archive initially.
- Extract original PDFs where available with notices intact.

Exclude or avoid:

- Unreviewed assumption that every contained publication has the same redistribution license.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 17. iFixit repair references

Resource `ifixit`; target **3.3 GB**; preferred formats: zim, pdf, html. Availability: **partial**.

The English iFixit ZIM is pinned. A curated set of directly readable critical guides has not yet been exported and verified; noncommercial share-alike conditions apply.

Mapped asset IDs: `ifixit_en`.

Include:

- Whole pinned English repair archive.
- Selected critical repair guides as direct PDF or HTML.
- Retain steps, photographs, parts context and attribution.

Exclude or avoid:

- Critical repair instructions available only inside ZIM.

Source pages: [source 1](https://www.ifixit.com/Info/Licensing), [source 2](https://download.kiwix.org/zim/ifixit/).

### 18. Low-tech Magazine

Resource `low-tech-magazine`; target **0.7 GB**; preferred formats: html, png, jpeg. Availability: **unresolved**.

The official editorial site is verified, but an authorized static snapshot, image-rights review, exact scope and integrity metadata have not been prepared.

Mapped asset IDs: none yet.

Include:

- Useful editorial archive.
- Article images, diagrams, captions and author credits.
- Static local links and retained publication dates.

Exclude or avoid:

- Analytics, advertisements and remote-only page dependencies.

Source pages: [source 1](https://solar.lowtechmagazine.com/about/).

### 19. Survivor Library — curated Tier A

Resource `survivor-tier-a`; target **100 GB**; preferred formats: pdf. Availability: **unresolved**.

A durable-trades title list, per-volume rights review, quality/deduplication decisions and pinned PDFs are required. This does not authorize a whole-library mirror or include a curated 100 GB package yet.

Mapped asset IDs: none yet.

Include:

- Metal/workshop: blacksmithing, forging, foundry and casting, machine tools, machining, welding, sheet metal, toolmaking, mechanical drawing, measurement and metrology, bearings and gears, workshop practice.
- Construction: carpentry, joinery, masonry, concrete, brickmaking, roofing, plumbing fundamentals, drainage, surveying, structural fundamentals, roads and bridges.
- Mechanical power: water power, wind power, steam engines, transmission, pumps, mills, engines, boilers and refrigeration fundamentals.
- Agriculture/processing: farming, soil, crop cultivation, animal husbandry, dairying, cheese and butter, butchering, food drying, grain milling, farm machinery, beekeeping and horticulture.
- Traditional fabrication: leatherworking, sewing, weaving, rope, papermaking, bookbinding, printing, pottery, glassmaking, woodworking, furniture and basketry.
- Industrial fundamentals: process/materials chemistry, mining, metallurgy, fuels, lubricants and steam/water systems.
- Historical safety warnings for boilers and other obsolete industrial practices.
- Default resource target 100 GB; selected profiles may explicitly reduce it to 75 GB.

Exclude or avoid:

- Obsolete medical diagnosis and treatment.
- Anesthesia, historic surgery, old obstetrics as operational medicine, X-ray practice and historical nursing medicine.
- Old encyclopedias.
- Great Books and literature duplicated by Gutenberg.
- Children’s books duplicated by Book Dash or Gutenberg.
- Christmas and Thanksgiving collections.
- Giant historical periodical runs.
- Most finance, banking, accounting and economics.
- Duplicated general history and repetitive travelogue.
- Duplicate editions and scans.
- Low-quality scans when a better edition exists.
- Medical history outside an explicitly labeled optional HISTORICAL appendix.

Source pages: [source 1](https://www.survivorlibrary.com/).

### 20. Stack Overflow — durable curated corpus

Resource `stackoverflow-durable`; target **25 GB**; preferred formats: html. Availability: **unresolved**.

A legally obtainable pinned input dump and deterministic quality/topic filters, canonical deduplication, static renderer and per-post license attribution are not implemented. The existing full-site Kiwix option is intentionally not substituted.

Mapped asset IDs: none yet.

Include:

- Languages: C, C++, Python, Java, C#, shell/Bash, core JavaScript and HTML/CSS.
- Systems: POSIX, Unix/Linux, filesystems, processes, threads, sockets, TCP/IP, serial communications, USB concepts, permissions, networking and memory management.
- Data: SQL, SQLite, relational fundamentals, parsing, text processing, Unicode, regular expressions, binary file formats and serialization.
- Tools: Git, GCC, compilers, assemblers, linkers, make/build systems, debuggers and package construction without cloud dependencies.
- Computer science: algorithms, data structures, numerical computing, compression, basic cryptographic programming and concurrency.
- Per question: question, accepted answer, one or two useful alternatives, relevant correction/warning comments, tags, dates, version context and attribution/license.
- Canonical-question mapping for duplicates.
- Generated static HTML with a reproducible selection recipe.

Exclude or avoid:

- The whole roughly 107 GB English ZIM.
- Unanswered questions.
- Mapped duplicates and negative or very-low-score junk.
- User profiles, badges, full edit history and trivial comments.
- Page chrome, analytics and advertisements.
- AWS, Azure, GCP, Firebase and SaaS-specific integrations.
- Stripe, Twilio, advertising and social-media APIs.
- App Store and Play Store workflows and CI SaaS.
- React/Angular/framework version churn unless conceptually useful.
- Old jQuery plugins and ancient web-framework minutiae.
- WordPress/plugin-version questions.
- Dead browser APIs, Flash, Flex and Silverlight.
- BlackBerry, Symbian and Windows Phone app development.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 21. Practical Stack Exchange bundle

Resource `stackexchange-practical`; target **12 GB**; preferred formats: html. Availability: **unresolved**.

Selected site dumps, quality rules, licensing metadata and deterministic static HTML exports have not been pinned or generated.

Mapped asset IDs: none yet.

Include:

- Electrical Engineering.
- Home Improvement / DIY.
- Gardening.
- Mechanics.
- Unix and Linux.
- Ham Radio.
- Outdoors.
- Sustainability.
- Woodworking.
- 3D Printing.
- Selected SuperUser.
- Selected GIS.
- Substantially intact useful site content after quality filtering.
- Question/answer context, dates, correction comments and per-post attribution.
- Generated static HTML.

Exclude or avoid:

- Junk.
- Unanswered questions.
- Duplicate material.
- ZIM as the primary delivered representation.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 22. OpenStax core textbooks

Resource `openstax-core`; target **12 GB**; preferred formats: pdf, html. Availability: **partial**.

Five verified illustrated PDFs (Prealgebra, College Physics, Chemistry, Biology, Anatomy and Physiology) are pinned, totaling 1.42 GB. The larger requested textbook list and HTML coverage are incomplete. Included 2026 PDFs require CC BY-NC-SA 4.0 and the OpenStax attribution notice.

Mapped asset IDs: `openstax_prealgebra_2e`, `openstax_college_physics_2e`, `openstax_chemistry_2e`, `openstax_biology_2e`, `openstax_anatomy_and_physiology_2e`.

Include:

- Math: Prealgebra, Elementary Algebra, Intermediate Algebra, College Algebra, Algebra and Trigonometry, Precalculus, Calculus volumes 1–3 and Introductory Statistics.
- Science: Biology, Anatomy and Physiology, Chemistry, Physics, University Physics volumes 1–3, Astronomy and Microbiology.
- College Physics.
- Basic business/economics only if space permits.
- Psychology/sociology only if broader education is desired.
- Current original textbook PDFs with illustrations, notices, locally generated metadata and searchable text.

Exclude or avoid:

- Bulk copying ancillary instructor resources.
- Replacing illustrated books with text extracts.
- Assuming older OpenStax editions establish the license of current PDFs.

Source pages: [source 1](https://help.openstax.org/s/article/student-book-access), [source 2](https://openstax.org/apps/cms/api/books/?format=json).

### 23. LibreTexts STEM and medicine

Resource `libretexts-stem`; target **8.5 GB**; preferred formats: zim, pdf. Availability: **unresolved**.

Eight requested subject packages total roughly 8.48 GB in the supplied estimates. Exact pinned archives and collection-specific rights have not been added.

Mapped asset IDs: none yet.

Include:

- Biology.
- Chemistry.
- Engineering.
- Geology.
- Mathematics.
- Medicine.
- Physics.
- Statistics.
- PDFs when easily available and appropriately licensed.

Exclude or avoid:

- Business, humanities and social-science collections initially.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/libretexts/).

### 24. English Wikibooks

Resource `wikibooks-en`; target **5.8 GB**; preferred formats: zim. Availability: **ready**.

The stated scope maps to resolved, pinned asset entries.

Mapped asset IDs: `wikibooks_en`.

Include:

- Whole pinned English archive.

Exclude or avoid:

- Treating archive-only books as directly readable critical textbooks.

Source pages: [source 1](https://download.kiwix.org/zim/wikibooks/).

### 25. English Wiktionary

Resource `wiktionary-en`; target **8.5 GB**; preferred formats: zim. Availability: **ready**.

The stated scope maps to resolved, pinned asset entries.

Mapped asset IDs: `wiktionary_en`.

Include:

- Whole pinned English text archive.

Exclude or avoid:

- Duplicated dictionaries without clear added value.

Source pages: [source 1](https://download.kiwix.org/zim/wiktionary/).

### 26. PhET simulations

Resource `phet`; target **0.1 GB**; preferred formats: html5. Availability: **unresolved**.

Official offline-download support is verified, but individual simulation versions, current license terms, self-contained files and offline device tests are not pinned. Do not assume historical licensing applies.

Mapped asset IDs: none yet.

Include:

- English self-contained HTML5 simulations.
- Offline dependencies and attribution retained.
- Test file-based execution on intended devices.

Exclude or avoid:

- Java and Flash dependence.
- Assuming iPhone can execute arbitrary local HTML5 files or install an app offline.

Source pages: [source 1](https://phet.colorado.edu/en/offline-access), [source 2](https://phet.colorado.edu/en/licensing).

### 27. English Wikiversity

Resource `wikiversity-en`; target **2.3 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole English archive.

Exclude or avoid:

- Unpinned latest URLs.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 28. Ready.gov and FEMA civilian preparedness expansion

Resource `civilian-preparedness`; target **0.5 GB**; preferred formats: html, pdf. Availability: **unresolved**.

Expanded civilian-preparedness pages and publications are not selected or pinned. Complementary baseline FEMA PDFs belong to owl-direct-core and are not counted twice here.

Mapped asset IDs: none yet.

Include:

- Disaster types.
- Sheltering.
- Evacuation.
- Communications.
- Household preparation.
- Static HTML and PDFs beyond the existing OWL baseline manuals.

Exclude or avoid:

- Claiming the core CERT, shelter advisory and supply checklist alone fulfill the broader Ready.gov/FEMA collection.

Source pages: [source 1](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo185734), [source 2](https://www.fema.gov/sites/default/files/2020-07/residential-sheltering-safe-rooms_recovery-advisory.pdf), [source 3](https://www.fema.gov/sites/default/files/documents/fema_hm-emergency-supply-kit-checklist_english.pdf).

### 29. English Wikivoyage

Resource `wikivoyage-en`; target **1.1 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole English travel archive.
- Clear snapshot date.

Exclude or avoid:

- Claims of current border, transport or safety conditions.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 30. CIA World Factbook snapshot

Resource `world-factbook`; target **0.4 GB**; preferred formats: html, zim. Availability: **unresolved**.

CIA officially discontinued the Factbook on 2026-02-04. An approved preserved snapshot with exact provenance, rights and integrity metadata must be selected; no current CIA download is assumed.

Mapped asset IDs: none yet.

Include:

- Whole preserved historical snapshot.
- Clearly displayed publication and capture dates.

Exclude or avoid:

- Describing the discontinued publication as a live current service.

Source pages: [source 1](https://www.cia.gov/stories/story/spotlighting-the-world-factbook-as-we-bid-a-fond-farewell/), [source 2](https://ftp.fau.de/kiwix/zim/other/).

### 31. Offline Linux and programming documentation

Resource `linux-programming-docs`; target **5 GB**; preferred formats: html, txt, man, pdf. Availability: **unresolved**.

Authoritative offline sources exist, but the requested multi-project bundle, versions, rights and safe direct-format extraction are not yet pinned.

Mapped asset IDs: none yet.

Include:

- Linux man-pages project.
- GNU coreutils.
- Bash.
- Git documentation.
- GCC and binutils basics.
- Python 3 documentation.
- SQLite documentation.
- POSIX reference where redistribution permits.
- OpenSSH.
- Networking commands.
- Filesystem tools.
- systemd documentation where relevant.
- Basic C-library documentation.
- Authoritative project docs with versions and licenses.
- PDF only when it is a canonical offline form.

Exclude or avoid:

- Substituting Stack Overflow for authoritative documentation.
- Unnecessary packaging duplication such as a whole Python ZIM when a direct bundle suffices.
- Restricted POSIX material without permission.

Source pages: [source 1](https://www.kernel.org/doc/man-pages/), [source 2](https://docs.python.org/3/download.html), [source 3](https://www.sqlite.org/docs.html).

### 32. Math, Physics and Biology Stack Exchange

Resource `stackexchange-science`; target **9 GB**; preferred formats: html. Availability: **unresolved**.

Site selection, minimum quality thresholds, legally obtained input snapshots and static exports remain to be implemented.

Mapped asset IDs: none yet.

Include:

- Almost all Mathematics questions meeting quality thresholds.
- Physics.
- Biology.
- Chemistry optionally.
- Question/answer context, dates, corrections and attribution.
- Generated static HTML.

Exclude or avoid:

- Junk, unanswered questions and canonical duplicates.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 33. English Wikisource

Resource `wikisource-en`; target **18 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole English archive if space permits.

Exclude or avoid:

- Assuming every historical work is public domain in every jurisdiction.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 34. TED-Ed

Resource `ted-ed`; target **6 GB**; preferred formats: video, html, zim. Availability: **unresolved**.

An exact authorized offline lesson collection, video rendition and package rights have not been pinned; the target is a curation estimate.

Mapped asset IDs: none yet.

Include:

- Educational lessons at lower priority.
- Offline video with lesson context and notices.

Exclude or avoid:

- Required learning content available only through streamed video.

Source pages: [source 1](https://www.ftp.fau.de/kiwix/zim/zimit/).

### 35. Khan Academy — core STEM

Resource `khan-core-stem`; target **90 GB**; preferred formats: zim, kolibri. Availability: **unresolved**.

The previously cataloged whole 180 GB Khan archive has been retired from profile selection. No verified curated core-STEM package exists here; course selection and Kiwix/Kolibri packaging remain unresolved.

Mapped asset IDs: none yet.

Include:

- Math: arithmetic, pre-algebra, algebra I/II, geometry, trigonometry, precalculus, calculus, differential equations where available, statistics/probability and linear algebra.
- Science: physics, chemistry, biology, earth science and electrical engineering where present.
- Computing: algorithms, computer-science basics and durable programming fundamentals.
- Subset manifest and original license/attribution retained.

Exclude or avoid:

- Automatically downloading every course.
- Standardized-test preparation.
- Finance.
- Career preparation.
- Contemporary civics and news-dependent content.
- Duplicated humanities.
- Material substantially duplicated by stronger textbook sources.
- Substituting the existing unsplit 180 GB archive for this 90 GB subset.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 36. Spanish Wikipedia

Resource `wikipedia-es`; target **38 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Included in the 1 TB default selection.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 37. French Wikipedia

Resource `wikipedia-fr`; target **52 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Opt-in language expansion.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 38. Chinese Wikipedia

Resource `wikipedia-zh`; target **25 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Opt-in language expansion.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 39. Arabic Wikipedia

Resource `wikipedia-ar`; target **18 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Opt-in language expansion.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 40. Portuguese Wikipedia

Resource `wikipedia-pt`; target **19 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Opt-in language expansion.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 41. Italian Wikipedia

Resource `wikipedia-it`; target **30 GB**; preferred formats: zim. Availability: **unresolved**.

Pinned files, exact sizes, SHA-256 values and applicable redistribution notices are not yet recorded.

Mapped asset IDs: none yet.

Include:

- Whole maxi archive with images.
- Select according to languages used by the intended community.
- Opt-in language expansion.

Exclude or avoid:

- Selecting a language only because it is globally popular when intended users do not read it.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 42. Upgrade regional map to entire world

Resource `world-maps`; target **72 GB**; preferred formats: zim. Availability: **unresolved**.

The world-map asset is a placeholder pending exact source metadata. It replaces only map_osm_north_america when that component would otherwise be selected; it is not a 51 GB downloadable file.

Mapped asset IDs: `map_osm_world`.

Include:

- Whole world OSM archive.
- Replace the 21 GB North America OSM component.
- Retain selected local GeoPDF/topographic maps from the regional collection.
- 72 GB absolute planning target, with a conditional 21 GB replacement credit.

Exclude or avoid:

- Counting both world and North America OSM as independent default content.
- Removing the local topographic selection when replacing the continent map.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/maps/).

### 43. Gutenberg multilingual expansion

Resource `gutenberg-multilingual`; target **30 GB**; preferred formats: html, txt, epub. Availability: **unresolved**.

Language choices and a reproducible non-English book-ID selection, rights checks, deduplication and pinned export remain unresolved.

Mapped asset IDs: none yet.

Include:

- Languages used by likely readers.
- Canonical literature.
- Children’s literature.
- Dictionaries.
- Language instruction.
- Major historical and scientific works.
- One preferred representation with useful text fallback and EPUB.

Exclude or avoid:

- Audio.
- Redundant formats and materially identical editions.
- Language selection disconnected from the intended community.

Source pages: [source 1](https://www.gutenberg.org/help/mirroring.html).

### 44. Survivor Library — Tier B

Resource `survivor-tier-b`; target **30 GB**; preferred formats: pdf. Availability: **unresolved**.

Specialist title selection, scan quality, per-volume rights and exact pins remain unresolved; this is an optional appendix rather than a whole-library expansion.

Mapped asset IDs: none yet.

Include:

- Only after Tier A.
- Shipbuilding.
- Advanced mining.
- Specialized foundry books.
- Radio and electronics history.
- Refrigeration.
- Advanced steam engineering.
- Industrial chemical processes.
- Railroad engineering.
- Textile machinery.
- Historical transportation engineering.
- Specialized agricultural journals.
- Historical context and safety warnings.

Exclude or avoid:

- Generic history, literature or obsolete operational medicine added merely to fill space.
- Duplicates of Tier A or other libraries.

Source pages: [source 1](https://www.survivorlibrary.com/).

### 45. Remaining Khan Academy

Resource `khan-remaining`; target **80 GB**; preferred formats: zim, kolibri. Availability: **unresolved**.

A non-overlapping remainder package has not been selected and pinned. The retired whole-archive asset is not a substitute for this optional 80 GB resource.

Mapped asset IDs: none yet.

Include:

- Non-core subjects and broader course catalog.
- Only after the core STEM selection and higher priorities.
- Explicit opt-in.
- Deduplicate against the core STEM package.

Exclude or avoid:

- Automatic default inclusion.
- Counting the whole 180 GB archive as both core and remaining subsets.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 46. Stack Overflow legacy-computing appendix

Resource `stackoverflow-legacy`; target **15 GB**; preferred formats: html. Availability: **unresolved**.

A separate legacy corpus, deterministic topic rules, pinned inputs, license-preserving HTML export and dedicated search treatment are not implemented.

Mapped asset IDs: none yet.

Include:

- Python 2.
- Older GCC.
- Java 6, 7 and 8.
- Old .NET.
- Windows XP/7 internals and repair.
- Old BIOS and MBR booting.
- 32-bit Linux.
- Legacy serial and parallel ports.
- Old filesystems.
- Ancient compiler/toolchain issues.
- Older Android only where useful for hardware reuse.
- Separate from normal search ranking.
- Visible result badge: LEGACY — MAY APPLY ONLY TO OLD SYSTEMS.
- Preserve dates, versions and per-post attribution.

Exclude or avoid:

- Every old web framework.
- Legacy content silently mixed into current operational advice.

Source pages: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### OWL complementary directly readable core

Resource `owl-direct-core`; target **0.134022 GB**; preferred formats: pdf. Availability: **ready**.

The stated scope maps to resolved, pinned asset entries.

Mapped asset IDs: `cert`, `water`, `sanitation`, `agriculture`, `electrical_dc`, `electrical_ac`, `mechanical`, `shelter`, `navigation`, `survival_shelter`, `reference`.

Include:

- Verified baseline first aid, water, sanitation, gardening, electrical textbooks, mechanical reference, shelter, navigation and preparedness.
- Original ordinary PDFs with illustrations and notices.
- Complements the separately selected WHO, food-preservation and OpenStax resources.

Exclude or avoid:

- Files already assigned to numbered resource collections.
- USGS Dynamic Planet reference sheets presented as regional maps.

Source pages: [source 1](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo185734), [source 2](https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water-0), [source 3](https://www.cdc.gov/water-emergency/communication-resources/fact-sheet-preventing-diarrheal-illness-after-a-disaster.html), [source 4](https://www.nrcs.usda.gov/plantmaterials/mipmcot9407.pdf), [source 5](https://www.ibiblio.org/kuphaldt/electricCircuits/DC/index.html), [source 6](https://www.ibiblio.org/kuphaldt/electricCircuits/index.htm), [source 7](https://www.faa.gov/regulations_policies/handbooks_manuals/aviation), [source 8](https://www.fema.gov/sites/default/files/2020-07/residential-sheltering-safe-rooms_recovery-advisory.pdf), [source 9](https://www.usgs.gov/media/files/finding-your-way-map-and-compass), [source 10](https://www.armyupress.army.mil/Journals/NCO-Journal/Archives/2020/June/NCO-C3/), [source 11](https://www.fema.gov/sites/default/files/documents/fema_hm-emergency-supply-kit-checklist_english.pdf).

### Bundled offline archive readers

Resource `archive-readers`; target **0 GB**; preferred formats: zip, appimage, dmg, apk. Availability: **ready**.

Its content target is zero because the profile reserves reader storage separately; actual downloaded package sizes still come from the asset catalog. Installation restrictions and GPL corresponding-source obligations remain documented in sources.md.

Mapped asset IDs: `kiwix_windows`, `kiwix_linux`, `kiwix_macos`, `kiwix_android`.

Include:

- Pinned Kiwix Windows portable reader.
- Pinned Kiwix Linux x86_64 AppImage.
- Pinned Kiwix macOS package.
- Pinned standalone Kiwix Android APK.
- Preserve notices and satisfy corresponding-source obligations before redistributing binaries.

Exclude or avoid:

- Assuming an iPhone can install Kiwix from the SSD offline.
- Assuming the x86_64 AppImage runs on Raspberry Pi.

Source pages: [source 1](https://get.kiwix.org/en/solutions/applications/download-options/).

### Additional directly readable editions of selected material

Resource `direct-reading-expansion`; target **60 GB**; preferred formats: html, pdf, txt, png, jpeg. Availability: **unresolved**.

Additional storage for ordinary-format derivatives of selected collections. No curated export manifests, licensed derivative packages, extraction pipeline or verified output assets are implemented yet. This is a representation budget, not a new acquired collection or a claim of available files.

Mapped asset IDs: none yet.

Include:

- Additional directly readable copies of material from source resources already selected for this build.
- Prioritize Appropedia, CD3WD, iFixit, LibreTexts STEM and English Wikibooks.
- Broaden the article-list-driven high-priority English Wikipedia HTML lifeboat.
- Preserve diagrams, photographs, labels, captions, instructions, article context and book context.
- Retain licensing and attribution notices, source versions and ordinary local entry links.
- Treat the 60 GB target as additional storage beyond existing direct copies and their existing budgets.
- Limit derivative subjects to the selected source collections; excluding a source collection excludes its planned derivatives from this expansion.
- Full-1tb default preference for direct reading without a ZIM reader.

Exclude or avoid:

- Expanding all of Wikipedia into millions of individual exFAT files.
- Counting existing directly readable source files or previously budgeted direct editions twice.
- Acquiring additional Khan, language or map collections to fill this budget.
- Exporting an excluded collection through this representation resource.
- Dropping illustrations or presenting decontextualized text as an equivalent illustrated guide.
- Implying that an ordinary-format derivative is redistributable without checking the source license.

Source pages: [source 1](https://www.appropedia.org/Appropedia:Terms_of_use), [source 2](https://ftp.fau.de/kiwix/zim/other/), [source 3](https://www.ifixit.com/Info/Licensing), [source 4](https://ftp.fau.de/kiwix/zim/libretexts/), [source 5](https://download.kiwix.org/zim/wikibooks/), [source 6](https://ftp.fau.de/kiwix/zim/wikipedia/).
