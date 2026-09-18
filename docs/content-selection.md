# Content selection and acquisition status

Generated from `catalog/resources.yaml` and `catalog/library.yaml` by `python scripts/build_content_docs.py`.

The registry enumerates **46 numbered collections and three support resources**. The catalog contains exact downloadable file records; the registry describes intended scope. The repository contains metadata, not these datasets.

Current status: **25 ready, 13 partial, 11 unresolved**. There are **461 pinned available file records**. Large archive pins were checked against publisher whole-file SHA-256 metadata and exact HTTP byte counts; the archive bodies have not all been downloaded or device-tested.

- **Ready:** the declared acquisition scope has usable pinned files.
- **Partial:** usable files are available, but specific requested content or representations remain missing.
- **Unresolved:** no usable mapping fulfills the collection yet; the reason below states what is missing.
- **Redistributable: false:** OWL has not established a general right to redistribute the file. This does **not** disable a publisher-offered download for personal, noncommercial offline use.

Original notices and attribution remain intact. Private acquisition and public redistribution are recorded separately; personal use does not change a publication’s stated license or its download availability.

Evidence: [medical and emergency](acquisition-medical.md), [education and agriculture](acquisition-education.md), [large archives](acquisition-archives.md), [programming and Low-tech](acquisition-reference.md).

## Profiles and capacity

All values are decimal GB. Planning targets include unresolved collections and are not downloaded byte counts. Smaller presets retain their 25 directly readable PDFs (1.5745 GB), including seven textbooks and thirteen illustrated works.

| Profile | Content target | Known available files | Search | Scratch | Reserve |
| --- | ---: | ---: | ---: | ---: | ---: |
| `flash-16gb` | 1.575 GB | 1.575 GB | 2 GB | 4 GB | 2 GB |
| `critical-64gb` | 1.575 GB | 1.575 GB | 2 GB | 4 GB | 8 GB |
| `compact-256gb` | 209.186 GB | 136.449 GB | 24 GB | 48 GB | 16 GB |
| `standard-512gb` | 408.176 GB | 190.343 GB | 48 GB | 96 GB | 38 GB |
| `full-1tb` | 790.718 GB | 312.233 GB | 90 GB | 180 GB | 80 GB |

Reader and metadata allowances are additional. Complete large-profile targets currently exceed nominal capacity during in-place indexing under the conservative scratch allowances. Use the CLI `--plan` for the complete calculation and real free-space/reuse checks; do not assume the final content target proves the build fits.

Compact includes #1–18, with a 10 GB local topographic allocation instead of North America OSM. Standard includes #1–31 and a 75 GB Survivor Tier A target. Full includes #1–36, #42–44 and #46, with full Tier A and a 60 GB direct-reading allowance. Spanish is the default additional Wikipedia; other languages and remaining Khan content are opt-in. A world map replaces the North America archive while retaining local topo.

Use [SELECT.html](../SELECT.html) or repeat `--include RESOURCE` / `--exclude RESOURCE` (IDs or list numbers). Exclusion never deletes existing files. A normal build stops for partial/unresolved collections; `--allow-incomplete` explicitly builds the available subset and records the gaps.

## Direct editions and exports

The [in-place ZIM exporter](direct-export.md) converts explicit article selections and supported local images/styles/fonts into ordinary files on the SSD. Import its completed manifest with `build_drive.py --extra-catalog PATH --allow-local` to refresh global search, navigation, inventory and checksums without copying those files again. Excluding a source collection also excludes its derivatives; an export from a different source checksum is rejected.

A conversion mechanism does not establish a curated or visually checked edition. The 60 GB direct-reading expansion remains unresolved until article/book selections are reviewed and their output is verified. No production alternative direct/compact editions are registered yet, so the selector disables those alternatives. It does not invent compression savings or automatically expand Wikipedia.

Additional manifests count their actual bytes on top of selected planning targets. When actual exports replace the separate 60 GB estimate, explicitly exclude `direct-reading-expansion` to avoid reserving that estimate as well; other collection gaps remain reported.

## Resource scope and remaining work

| # | Resource | Status | Planned GB | Pinned files |
| --- | --- | --- | ---: | ---: |
| 1 | `hesperian-health` | partial | 0.5 | 270 |
| 2 | `msf-medical` | ready | 0.25 | 7 |
| 3 | `who-emergency-care` | ready | 0.1 | 11 |
| 4 | `who-wash` | ready | 0.1 | 15 |
| 5 | `sphere-handbook` | ready | 0.05 | 1 |
| 6 | `food-preservation` | partial | 0.1 | 10 |
| 7 | `niosh-chemical-hazards` | ready | 0.01 | 1 |
| 8 | `fao-agriculture` | partial | 0.5 | 7 |
| 9 | `gutenberg-core` | unresolved | 40 | 0 |
| 10 | `childrens-library` | partial | 22 | 61 |
| 11 | `wikipedia-en` | partial | 119 | 1 |
| 12 | `wikimed` | ready | 2.1 | 1 |
| 13 | `wikem` | ready | 0.36 | 1 |
| 14 | `regional-maps` | partial | 51 | 1 |
| 15 | `appropedia` | partial | 0.56 | 1 |
| 16 | `cd3wd` | partial | 0.55 | 1 |
| 17 | `ifixit` | partial | 3.3 | 1 |
| 18 | `low-tech-magazine` | partial | 0.7 | 1 |
| 19 | `survivor-tier-a` | unresolved | 100 | 0 |
| 20 | `stackoverflow-durable` | unresolved | 25 | 0 |
| 21 | `stackexchange-practical` | unresolved | 12 | 0 |
| 22 | `openstax-core` | ready | 12 | 20 |
| 23 | `libretexts-stem` | ready | 8.5 | 8 |
| 24 | `wikibooks-en` | ready | 5.8 | 1 |
| 25 | `wiktionary-en` | ready | 8.5 | 1 |
| 26 | `phet` | partial | 0.1 | 2 |
| 27 | `wikiversity-en` | ready | 2.3 | 1 |
| 28 | `civilian-preparedness` | ready | 0.5 | 1 |
| 29 | `wikivoyage-en` | ready | 1.1 | 1 |
| 30 | `world-factbook` | ready | 0.4 | 1 |
| 31 | `linux-programming-docs` | partial | 5 | 10 |
| 32 | `stackexchange-science` | unresolved | 9 | 0 |
| 33 | `wikisource-en` | ready | 18 | 1 |
| 34 | `ted-ed` | partial | 6 | 1 |
| 35 | `khan-core-stem` | unresolved | 90 | 0 |
| 36 | `wikipedia-es` | ready | 38 | 1 |
| 37 | `wikipedia-fr` | ready | 52 | 1 |
| 38 | `wikipedia-zh` | ready | 25 | 1 |
| 39 | `wikipedia-ar` | ready | 18 | 1 |
| 40 | `wikipedia-pt` | ready | 19 | 1 |
| 41 | `wikipedia-it` | ready | 30 | 1 |
| 42 | `world-maps` | ready | 72 | 1 |
| 43 | `gutenberg-multilingual` | unresolved | 30 | 0 |
| 44 | `survivor-tier-b` | unresolved | 30 | 0 |
| 45 | `khan-remaining` | unresolved | 80 | 0 |
| 46 | `stackoverflow-legacy` | unresolved | 15 | 0 |
| — | `owl-direct-core` | ready | 0.134022 | 11 |
| — | `archive-readers` | ready | 0 | 4 |
| — | `direct-reading-expansion` | unresolved | 60 | 0 |

### 1. Hesperian low-resource health library

`hesperian-health` · **partial** · planning target 0.5 GB

270 of 271 official chapter PDFs for eight explicitly selected books are pinned. A Book for Midwives 2026 back matter returns HTTP 404; no substitute is silently supplied. Personal publisher downloads are usable; redistributable:false concerns further sharing, not this private build.

**Include:**

- Publisher English chapter PDFs for Where There Is No Doctor (2025 printing), Where Women Have No Doctor (2024 printing), Where There Is No Dentist (2024), A Book for Midwives (2026 printing), A Community Guide to Environmental Health (2012), Disabled Village Children (2025 printing), Helping Children Who Are Blind (2000), Helping Health Workers Learn (2026 edition)
- Preserve whole-book context through chapter titles, front matter, indexes and publisher supplementary pages; one back-matter file remains missing

**Exclude:**

- Unlicensed redistribution or adapted digital editions
- Claiming these eight books comprise the entire Hesperian catalog
- Claiming the missing midwives back matter was acquired

Sources: [source 1](https://hesperian.org/open-copyright-policy/).

### 2. MSF Medical Guidelines

`msf-medical` · **ready** · planning target 0.25 GB



**Include:**

- Whole English publisher PDFs: Clinical Guidelines (December 2024), Essential Drugs (January 2026), Essential Obstetric and Newborn Care (2019), Cholera (2018), Measles (2025), Tuberculosis (2025), Public Health Engineering (2010)
- Retain the exact PDF edition and export date; preserve original illustrations, tables, appendices and clinical qualifications

**Exclude:**

- Claiming PDF editions match all current online updates
- HTML mirrors, apps or translations not explicitly pinned
- Further redistribution without permission

Sources: [source 1](https://medicalguidelines.msf.org/en).

### 3. WHO Basic Emergency Care and emergency clinical references

`who-emergency-care` · **ready** · planning target 0.1 GB



**Include:**

- Complete 2018 Basic Emergency Care manual
- November 2025 postpartum haemorrhage quick card; BEC quick cards; SBAR job aid; BEC frequently asked questions
- Emergency Care Toolkit pocket guide; acute transfer checklist; acute referral and counter-referral forms; medical and trauma resuscitation algorithm posters
- Original clinical limitations, authorship and image content; some poster text requires OCR for body search

**Exclude:**

- Unpinned training PowerPoints, videos, online course content and later clinical changes
- Presenting professional clinical references as layperson first-aid training

Sources: [source 1](https://www.who.int/publications/i/item/9789241513081).

### 4. WHO WASH in Emergencies

`who-wash` · **ready** · planning target 0.1 GB



**Include:**

- All 15 WHO/WEDC technical notes
- Water quantity
- Cleaning and disinfecting wells and boreholes
- Chlorination and chlorine measurement
- Tanks and tankers
- Piped distribution and treatment works
- Point-of-use drinking-water treatment
- Sanitation and excreta disposal
- Solid waste
- Dead-body disposal
- Hygiene promotion
- Wells after seawater flooding

**Exclude:**

- Substituting a general water leaflet for the full technical-note series

Sources: [source 1](https://www.who.int/teams/environment-climate-change-and-health/water-sanitation-and-health/environmental-health-in-emergencies/technical-notes-on-wash-in-emergencies).

### 5. Sphere Handbook

`sphere-handbook` · **ready** · planning target 0.05 GB



**Include:**

- Whole handbook
- Humanitarian Charter and protection principles
- Core Humanitarian Standard
- WASH, food security, nutrition, shelter and health standards

**Exclude:**

- Handbook fragments presented as the complete edition

Sources: [source 1](https://spherestandards.org/handbook/), [source 2](https://spherestandards.org/handbook/editions/).

### 6. USDA and NCHFP food preservation

`food-preservation` · **partial** · planning target 0.1 GB

The existing eight USDA 2015 canning files are retained; NCHFP-linked UGA 2026 kombucha safety and Montana 2017 vegetable-drying PDFs are now pinned. A verified current freezing publication, broader drying/food-safety selection and review of later canning changes remain outstanding.

**Include:**

- Current canning guidance
- Freezing
- Drying
- Fermentation
- Food safety
- Retain processing tables and illustrations in context

**Exclude:**

- Assuming the 2015 canning volumes alone cover all preservation methods or reflect every later update

Sources: [source 1](https://nchfp.uga.edu/resources/entry/about-the-usda-guide-to-home-canning-2015-revision).

### 7. NIOSH Pocket Guide to Chemical Hazards

`niosh-chemical-hazards` · **ready** · planning target 0.01 GB



**Include:**

- Whole current downloadable guide
- Chemical names, exposure limits, incompatibilities, protective measures and first aid
- Record the edition and differences from online updates

**Exclude:**

- A mobile-app-only copy

Sources: [source 1](https://www.cdc.gov/niosh/npg/default.html).

### 8. FAO practical agriculture core

`fao-agriculture` · **partial** · planning target 0.5 GB

Seven complete practical PDFs cover field-school crop production/IPM, compost (English/Spanish), seed storage, poultry, surface irrigation and aquaponics. Separate coverage for other requested vegetables, livestock/dairy/feed, greenhouse, postharvest/grain storage and tools remains incomplete; two older manuals have no verified redistribution grant.

**Include:**

- Crop production fundamentals
- Soil fertility and composting
- Irrigation
- Crop-water requirements
- Seed storage
- Small-scale post-harvest handling
- Grain storage
- Vegetable production
- Poultry
- Rabbits and small livestock
- Dairy basics
- Animal feeding
- Pest management
- Greenhouse and protected growing
- Food-loss reduction
- Small-farm tools
- Basic aquaculture where practical

**Exclude:**

- Policy documents
- Statistical yearbooks
- Meeting reports
- Economic forecasting
- Administrative material
- Country programme reports

Sources: [source 1](https://www.fao.org/sustainable-food-value-chains/training-and-learning-center/en/), [source 2](https://openknowledge.fao.org/).

### 9. Project Gutenberg core library

`gutenberg-core` · **unresolved** · planning target 40 GB

Gutenberg supports selective mirrors, but a reproducible book-ID selection, deduplication and pinned direct-format export are not implemented. A seed book would not fulfill the 40 GB collection.

**Include:**

- Major English-language literature
- World classics in English translation
- Poetry
- Mythology and folklore
- History
- Philosophy
- Biographies
- Science classics
- Mathematics classics
- Practical historical texts
- Dictionaries and reference works not better duplicated elsewhere
- Children and young-adult classics
- Major drama
- Language-learning and public-domain grammars
- Older technical books complementing Survivor Library
- One preferred reading representation per work; HTML with images when useful, UTF-8 TXT fallback and an EPUB where it adds phone-reading value
- Retain book-level rights notices and country-specific public-domain limitations

**Exclude:**

- Audio editions
- Kindle and MOBI duplicates
- Duplicate EPUB variants
- Low-value OCR scans when a good text edition exists
- Materially identical editions
- Periodicals without clear utility

Sources: [source 1](https://www.gutenberg.org/help/mirroring.html).

### 10. Children's Library

`childrens-library` · **partial** · planning target 22 GB

All 61 complete EPUBs at the publisher Book Dash archive commit are pinned in English, French and Xhosa. Current 221-title Book Dash PDF library download endpoint returns HTTP 403, and African Storybook full approved multilingual PDF export is not yet reproducibly acquired. EPUBs require a reader.

**Include:**

- Book Dash: essentially all available books, with normal ebook PDFs, extracted text, covers and illustrations, available translations and optional print-ready PDFs
- African Storybook: whole collection initially where authorized exports allow PDF, HTML or images plus text
- Gutenberg: picture books, fairy tales, folk tales, early readers, classics, adventure, nature and science, history and biography, teen classics and poetry
- Deduplicate titles already represented better by another source
- Top-level navigation alongside Gutenberg, health, food/water, repair, maps and search
- Preserve illustrations and per-book author, illustrator, translator and license credits

**Exclude:**

- Depending solely on the Book Dash ZIM
- A ZIM-only children’s collection when direct exports are practical
- Redundant editions across publishers

Sources: [source 1](https://bookdash.org/), [source 2](https://www.africanstorybook.org/), [source 3](https://www.gutenberg.org/help/mirroring.html), [source 4](https://ftp.fau.de/kiwix/zim/other/).

### 11. English Wikipedia, full

`wikipedia-en` · **partial** · planning target 119 GB

The full English maxi archive is pinned. The in-place direct exporter is available; the curated lifeboat article list and visually verified HTML/image edition are still missing.

**Include:**

- Whole pinned English maxi archive with images
- Small article-list-driven HTML lifeboat under WIKIPEDIA/DIRECT/; aim for roughly 2–5 GB within this planning envelope
- Lifeboat: human anatomy, common diseases, first-aid concepts and medicines
- Lifeboat: crops, food preservation, water treatment and sanitation
- Lifeboat: electricity, motors, generators, batteries, radios and mechanical systems
- Lifeboat: chemistry, materials, construction, navigation, meteorology and mathematics fundamentals

**Exclude:**

- Expanding millions of articles into individual exFAT files
- Replacing full maxi with nopic or mini without an explicit profile decision
- Selecting lifeboat articles solely to fill a quota

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 12. WikiMed / MDWiki

`wikimed` · **ready** · planning target 2.1 GB



**Include:**

- Whole pinned English medical encyclopedia
- Preserve clinical and licensing notices

**Exclude:**

- Treating encyclopedia access as professional medical training

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 13. WikEM

`wikem` · **ready** · planning target 0.36 GB



**Include:**

- Whole emergency-medicine reference
- Version and clinical caveats

**Exclude:**

- Unversioned clinical guidance

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 14. Regional maps and topography

`regional-maps` · **partial** · planning target 51 GB

North America OSM archive is pinned (22,652,513,201 bytes). Local/regional GeoPDF coverage still requires the intended location and corridor selection; this archive does not satisfy that requirement.

**Include:**

- North America OSM archive; 21 GB planning component
- Detailed local and regional GeoPDF/topographic maps; roughly 20–40 GB, with 30 GB in this default envelope
- Home state or region
- Neighboring states or regions
- Likely evacuation corridors
- Major watersheds
- National and state forests
- Major transport corridors
- Compact profile may use a 10 GB regional selection instead of the full default envelope

**Exclude:**

- High-resolution topography for the entire continent by default
- Treating physical-world/tectonic reference sheets as local road or evacuation maps
- Automatically retaining North America OSM when the world replacement is selected

Sources: [source 1](https://ftp.fau.de/kiwix/zim/maps/), [source 2](https://store.usgs.gov/map-locator).

### 15. Appropedia

`appropedia` · **partial** · planning target 0.56 GB

The whole Appropedia ZIM is pinned and the direct exporter is available. A reviewed critical-article selection and verified illustrated static output are still needed.

**Include:**

- Whole pinned snapshot
- Selected critical articles as directly readable HTML

**Exclude:**

- Critical practical content available only inside ZIM

Sources: [source 1](https://www.appropedia.org/Appropedia:Terms_of_use), [source 2](https://ftp.fau.de/kiwix/zim/other/).

### 16. CD3WD appropriate-development archive

`cd3wd` · **partial** · planning target 0.55 GB

The complete published 2025-11 Kiwix website archive is pinned and available for personal offline acquisition. Ordinary-format exports of original PDFs/HTML remain to be implemented; original publication rights vary and no blanket redistribution license is asserted.

**Include:**

- Whole current archive initially
- Extract original PDFs where available with notices intact

**Exclude:**

- Unreviewed assumption that every contained publication has the same redistribution license

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 17. iFixit repair references

`ifixit` · **partial** · planning target 3.3 GB

The whole English repair ZIM is pinned and a direct export mechanism is available. Curated critical guides with reviewed steps, photographs and complete static dependencies are still needed.

**Include:**

- Whole pinned English repair archive
- Selected critical repair guides as direct PDF or HTML
- Retain steps, photographs, parts context and attribution

**Exclude:**

- Critical repair instructions available only inside ZIM

Sources: [source 1](https://www.ifixit.com/Info/Licensing), [source 2](https://download.kiwix.org/zim/ifixit/).

### 18. Low-tech Magazine

`low-tech-magazine` · **partial** · planning target 0.7 GB

Published January 2025 Kiwix archive pinned from upstream whole-file SHA-256 and exact byte count. Ordinary HTML/image export and article-level visual review remain; no purchase or general redistribution grant is assumed.

**Include:**

- Useful editorial archive
- Article images, diagrams, captions and author credits
- Static local links and retained publication dates

**Exclude:**

- Analytics, advertisements and remote-only page dependencies

Sources: [source 1](https://solar.lowtechmagazine.com/about/).

### 19. Survivor Library — curated Tier A

`survivor-tier-a` · **unresolved** · planning target 100 GB

A durable-trades title list, per-volume rights review, quality/deduplication decisions and pinned PDFs are required. This does not authorize a whole-library mirror or include a curated 100 GB package yet.

**Include:**

- Metal/workshop: blacksmithing, forging, foundry and casting, machine tools, machining, welding, sheet metal, toolmaking, mechanical drawing, measurement and metrology, bearings and gears, workshop practice
- Construction: carpentry, joinery, masonry, concrete, brickmaking, roofing, plumbing fundamentals, drainage, surveying, structural fundamentals, roads and bridges
- Mechanical power: water power, wind power, steam engines, transmission, pumps, mills, engines, boilers and refrigeration fundamentals
- Agriculture/processing: farming, soil, crop cultivation, animal husbandry, dairying, cheese and butter, butchering, food drying, grain milling, farm machinery, beekeeping and horticulture
- Traditional fabrication: leatherworking, sewing, weaving, rope, papermaking, bookbinding, printing, pottery, glassmaking, woodworking, furniture and basketry
- Industrial fundamentals: process/materials chemistry, mining, metallurgy, fuels, lubricants and steam/water systems
- Historical safety warnings for boilers and other obsolete industrial practices
- Default resource target 100 GB; selected profiles may explicitly reduce it to 75 GB

**Exclude:**

- Obsolete medical diagnosis and treatment
- Anesthesia, historic surgery, old obstetrics as operational medicine, X-ray practice and historical nursing medicine
- Old encyclopedias
- Great Books and literature duplicated by Gutenberg
- Children’s books duplicated by Book Dash or Gutenberg
- Christmas and Thanksgiving collections
- Giant historical periodical runs
- Most finance, banking, accounting and economics
- Duplicated general history and repetitive travelogue
- Duplicate editions and scans
- Low-quality scans when a better edition exists
- Medical history outside an explicitly labeled optional HISTORICAL appendix

Sources: [source 1](https://www.survivorlibrary.com/).

### 20. Stack Overflow — durable curated corpus

`stackoverflow-durable` · **unresolved** · planning target 25 GB

A legally obtainable pinned input dump and deterministic quality/topic filters, canonical deduplication, static renderer and per-post license attribution are not implemented. The existing full-site Kiwix option is intentionally not substituted.

**Include:**

- Languages: C, C++, Python, Java, C#, shell/Bash, core JavaScript and HTML/CSS
- Systems: POSIX, Unix/Linux, filesystems, processes, threads, sockets, TCP/IP, serial communications, USB concepts, permissions, networking and memory management
- Data: SQL, SQLite, relational fundamentals, parsing, text processing, Unicode, regular expressions, binary file formats and serialization
- Tools: Git, GCC, compilers, assemblers, linkers, make/build systems, debuggers and package construction without cloud dependencies
- Computer science: algorithms, data structures, numerical computing, compression, basic cryptographic programming and concurrency
- Per question: question, accepted answer, one or two useful alternatives, relevant correction/warning comments, tags, dates, version context and attribution/license
- Canonical-question mapping for duplicates
- Generated static HTML with a reproducible selection recipe

**Exclude:**

- The whole roughly 107 GB English ZIM
- Unanswered questions
- Mapped duplicates and negative or very-low-score junk
- User profiles, badges, full edit history and trivial comments
- Page chrome, analytics and advertisements
- AWS, Azure, GCP, Firebase and SaaS-specific integrations
- Stripe, Twilio, advertising and social-media APIs
- App Store and Play Store workflows and CI SaaS
- React/Angular/framework version churn unless conceptually useful
- Old jQuery plugins and ancient web-framework minutiae
- WordPress/plugin-version questions
- Dead browser APIs, Flash, Flex and Silverlight
- BlackBerry, Symbian and Windows Phone app development

Sources: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 21. Practical Stack Exchange bundle

`stackexchange-practical` · **unresolved** · planning target 12 GB

Selected site dumps, quality rules, licensing metadata and deterministic static HTML exports have not been pinned or generated.

**Include:**

- Electrical Engineering
- Home Improvement / DIY
- Gardening
- Mechanics
- Unix and Linux
- Ham Radio
- Outdoors
- Sustainability
- Woodworking
- 3D Printing
- Selected SuperUser
- Selected GIS
- Substantially intact useful site content after quality filtering
- Question/answer context, dates, correction comments and per-post attribution
- Generated static HTML

**Exclude:**

- Junk
- Unanswered questions
- Duplicate material
- ZIM as the primary delivered representation

Sources: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 22. OpenStax core textbooks

`openstax-core` · **ready** · planning target 12 GB



**Include:**

- Math: Prealgebra, Elementary Algebra, Intermediate Algebra, College Algebra, Algebra and Trigonometry, Precalculus, Calculus volumes 1–3 and Introductory Statistics
- Science: Biology, Anatomy and Physiology, Chemistry, Physics, University Physics volumes 1–3, Astronomy and Microbiology
- College Physics
- Basic business/economics only if space permits
- Psychology/sociology only if broader education is desired
- Current original textbook PDFs with illustrations, notices, locally generated metadata and searchable text

**Exclude:**

- Bulk copying ancillary instructor resources
- Replacing illustrated books with text extracts
- Assuming older OpenStax editions establish the license of current PDFs

Sources: [source 1](https://help.openstax.org/s/article/student-book-access), [source 2](https://openstax.org/apps/cms/api/books/?format=json).

### 23. LibreTexts STEM and medicine

`libretexts-stem` · **ready** · planning target 8.5 GB



**Include:**

- Biology
- Chemistry
- Engineering
- Geology
- Mathematics
- Medicine
- Physics
- Statistics
- PDFs when easily available and appropriately licensed

**Exclude:**

- Business, humanities and social-science collections initially

Sources: [source 1](https://ftp.fau.de/kiwix/zim/libretexts/).

### 24. English Wikibooks

`wikibooks-en` · **ready** · planning target 5.8 GB



**Include:**

- Whole pinned English archive

**Exclude:**

- Treating archive-only books as directly readable critical textbooks

Sources: [source 1](https://download.kiwix.org/zim/wikibooks/).

### 25. English Wiktionary

`wiktionary-en` · **ready** · planning target 8.5 GB



**Include:**

- Whole pinned English text archive

**Exclude:**

- Duplicated dictionaries without clear added value

Sources: [source 1](https://download.kiwix.org/zim/wiktionary/).

### 26. PhET simulations

`phet` · **partial** · planning target 0.1 GB

Two exact-version regular English HTML5 simulations are pinned with embedded runtime and notices. Remaining useful simulations and actual offline device tests remain; optional analytics/update requests are retained in publisher files.

**Include:**

- English self-contained HTML5 simulations
- Offline dependencies and attribution retained
- Test file-based execution on intended devices

**Exclude:**

- Java and Flash dependence
- Assuming iPhone can execute arbitrary local HTML5 files or install an app offline

Sources: [source 1](https://phet.colorado.edu/en/offline-access), [source 2](https://phet.colorado.edu/en/licensing).

### 27. English Wikiversity

`wikiversity-en` · **ready** · planning target 2.3 GB



**Include:**

- Whole English archive

**Exclude:**

- Unpinned latest URLs

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 28. Ready.gov and FEMA civilian preparedness expansion

`civilian-preparedness` · **ready** · planning target 0.5 GB



**Include:**

- Whole FEMA P-2064 September 2020 Are You Ready? An In-Depth Guide to Citizen Preparedness
- Household planning and supplies, hazard-specific actions, sheltering, evacuation, communication and recovery beyond the existing core checklist/CERT references

**Exclude:**

- Claiming a complete mirror of all Ready.gov/FEMA web pages
- Counting core CERT, safe-room advisory or supply checklist twice

Sources: [source 1](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo185734), [source 2](https://www.fema.gov/sites/default/files/2020-07/residential-sheltering-safe-rooms_recovery-advisory.pdf), [source 3](https://www.fema.gov/sites/default/files/documents/fema_hm-emergency-supply-kit-checklist_english.pdf).

### 29. English Wikivoyage

`wikivoyage-en` · **ready** · planning target 1.1 GB



**Include:**

- Whole English travel archive
- Clear snapshot date

**Exclude:**

- Claims of current border, transport or safety conditions

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 30. CIA World Factbook snapshot

`world-factbook` · **ready** · planning target 0.4 GB



**Include:**

- Whole preserved historical snapshot
- Clearly displayed publication and capture dates

**Exclude:**

- Describing the discontinued publication as a live current service

Sources: [source 1](https://www.cia.gov/stories/story/spotlighting-the-world-factbook-as-we-bid-a-fond-farewell/), [source 2](https://ftp.fau.de/kiwix/zim/other/).

### 31. Offline Linux and programming documentation

`linux-programming-docs` · **partial** · planning target 5 GB

Ten complete official manuals are pinned: Bash, coreutils, Make, GCC, CPP, binutils, ld, glibc, Pro Git and Python EPUB. Linux man-pages, SQLite, OpenSSH, networking/filesystem tools and systemd, plus a direct Python HTML edition, remain to be pinned. No POSIX license is assumed.

**Include:**

- Linux man-pages project
- GNU coreutils
- Bash
- Git documentation
- GCC and binutils basics
- Python 3 documentation
- SQLite documentation
- POSIX reference where redistribution permits
- OpenSSH
- Networking commands
- Filesystem tools
- systemd documentation where relevant
- Basic C-library documentation
- Authoritative project docs with versions and licenses
- PDF only when it is a canonical offline form

**Exclude:**

- Substituting Stack Overflow for authoritative documentation
- Unnecessary packaging duplication such as a whole Python ZIM when a direct bundle suffices
- Restricted POSIX material without permission

Sources: [source 1](https://www.kernel.org/doc/man-pages/), [source 2](https://docs.python.org/3/download.html), [source 3](https://www.sqlite.org/docs.html).

### 32. Math, Physics and Biology Stack Exchange

`stackexchange-science` · **unresolved** · planning target 9 GB

Site selection, minimum quality thresholds, legally obtained input snapshots and static exports remain to be implemented.

**Include:**

- Almost all Mathematics questions meeting quality thresholds
- Physics
- Biology
- Chemistry optionally
- Question/answer context, dates, corrections and attribution
- Generated static HTML

**Exclude:**

- Junk, unanswered questions and canonical duplicates

Sources: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### 33. English Wikisource

`wikisource-en` · **ready** · planning target 18 GB



**Include:**

- Whole English archive if space permits

**Exclude:**

- Assuming every historical work is public domain in every jurisdiction

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 34. TED-Ed

`ted-ed` · **partial** · planning target 6 GB

Pinned September 2026 TED-Ed topic archive from the Kiwix TED collection (6,380,955,947 bytes), suitable for intact personal noncommercial playback. This is a specific TED topic package; complete ed.ted.com lesson/animation coverage and ordinary-file media exports are not established.

**Include:**

- Educational lessons at lower priority
- Offline video with lesson context and notices

**Exclude:**

- Required learning content available only through streamed video

Sources: [source 1](https://www.ftp.fau.de/kiwix/zim/zimit/).

### 35. Khan Academy — core STEM

`khan-core-stem` · **unresolved** · planning target 90 GB

The previously cataloged whole 180 GB Khan archive has been retired from profile selection. No verified curated core-STEM package exists here; course selection and Kiwix/Kolibri packaging remain unresolved.

**Include:**

- Math: arithmetic, pre-algebra, algebra I/II, geometry, trigonometry, precalculus, calculus, differential equations where available, statistics/probability and linear algebra
- Science: physics, chemistry, biology, earth science and electrical engineering where present
- Computing: algorithms, computer-science basics and durable programming fundamentals
- Subset manifest and original license/attribution retained

**Exclude:**

- Automatically downloading every course
- Standardized-test preparation
- Finance
- Career preparation
- Contemporary civics and news-dependent content
- Duplicated humanities
- Material substantially duplicated by stronger textbook sources
- Substituting the existing unsplit 180 GB archive for this 90 GB subset

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 36. Spanish Wikipedia

`wikipedia-es` · **ready** · planning target 38 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Included in the 1 TB default selection

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 37. French Wikipedia

`wikipedia-fr` · **ready** · planning target 52 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Opt-in language expansion

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 38. Chinese Wikipedia

`wikipedia-zh` · **ready** · planning target 25 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Opt-in language expansion

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 39. Arabic Wikipedia

`wikipedia-ar` · **ready** · planning target 18 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Opt-in language expansion

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 40. Portuguese Wikipedia

`wikipedia-pt` · **ready** · planning target 19 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Opt-in language expansion

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 41. Italian Wikipedia

`wikipedia-it` · **ready** · planning target 30 GB



**Include:**

- Whole maxi archive with images
- Select according to languages used by the intended community
- Opt-in language expansion

**Exclude:**

- Selecting a language only because it is globally popular when intended users do not read it

Sources: [source 1](https://ftp.fau.de/kiwix/zim/wikipedia/).

### 42. Upgrade regional map to entire world

`world-maps` · **ready** · planning target 72 GB



**Include:**

- Whole world OSM archive
- Replace the 21 GB North America OSM component
- Retain selected local GeoPDF/topographic maps from the regional collection
- 72 GB absolute planning target, with a conditional 21 GB replacement credit

**Exclude:**

- Counting both world and North America OSM as independent default content
- Removing the local topographic selection when replacing the continent map

Sources: [source 1](https://ftp.fau.de/kiwix/zim/maps/).

### 43. Gutenberg multilingual expansion

`gutenberg-multilingual` · **unresolved** · planning target 30 GB

Language choices and a reproducible non-English book-ID selection, rights checks, deduplication and pinned export remain unresolved.

**Include:**

- Languages used by likely readers
- Canonical literature
- Children’s literature
- Dictionaries
- Language instruction
- Major historical and scientific works
- One preferred representation with useful text fallback and EPUB

**Exclude:**

- Audio
- Redundant formats and materially identical editions
- Language selection disconnected from the intended community

Sources: [source 1](https://www.gutenberg.org/help/mirroring.html).

### 44. Survivor Library — Tier B

`survivor-tier-b` · **unresolved** · planning target 30 GB

Specialist title selection, scan quality, per-volume rights and exact pins remain unresolved; this is an optional appendix rather than a whole-library expansion.

**Include:**

- Only after Tier A
- Shipbuilding
- Advanced mining
- Specialized foundry books
- Radio and electronics history
- Refrigeration
- Advanced steam engineering
- Industrial chemical processes
- Railroad engineering
- Textile machinery
- Historical transportation engineering
- Specialized agricultural journals
- Historical context and safety warnings

**Exclude:**

- Generic history, literature or obsolete operational medicine added merely to fill space
- Duplicates of Tier A or other libraries

Sources: [source 1](https://www.survivorlibrary.com/).

### 45. Remaining Khan Academy

`khan-remaining` · **unresolved** · planning target 80 GB

A non-overlapping remainder package has not been selected and pinned. The retired whole-archive asset is not a substitute for this optional 80 GB resource.

**Include:**

- Non-core subjects and broader course catalog
- Only after the core STEM selection and higher priorities
- Explicit opt-in
- Deduplicate against the core STEM package

**Exclude:**

- Automatic default inclusion
- Counting the whole 180 GB archive as both core and remaining subsets

Sources: [source 1](https://ftp.fau.de/kiwix/zim/other/).

### 46. Stack Overflow legacy-computing appendix

`stackoverflow-legacy` · **unresolved** · planning target 15 GB

A separate legacy corpus, deterministic topic rules, pinned inputs, license-preserving HTML export and dedicated search treatment are not implemented.

**Include:**

- Python 2
- Older GCC
- Java 6, 7 and 8
- Old .NET
- Windows XP/7 internals and repair
- Old BIOS and MBR booting
- 32-bit Linux
- Legacy serial and parallel ports
- Old filesystems
- Ancient compiler/toolchain issues
- Older Android only where useful for hardware reuse
- Separate from normal search ranking
- Visible result badge: LEGACY — MAY APPLY ONLY TO OLD SYSTEMS
- Preserve dates, versions and per-post attribution

**Exclude:**

- Every old web framework
- Legacy content silently mixed into current operational advice

Sources: [source 1](https://ftp.fau.de/kiwix/zim/stack_exchange/).

### OWL complementary directly readable core

`owl-direct-core` · **ready** · planning target 0.134022 GB



**Include:**

- Verified baseline first aid, water, sanitation, gardening, electrical textbooks, mechanical reference, shelter, navigation and preparedness
- Original ordinary PDFs with illustrations and notices
- Complements the separately selected WHO, food-preservation and OpenStax resources

**Exclude:**

- Files already assigned to numbered resource collections
- USGS Dynamic Planet reference sheets presented as regional maps

Sources: [source 1](https://www.govinfo.gov/app/details/GOVPUB-HS5_100-PURL-gpo185734), [source 2](https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water-0), [source 3](https://www.cdc.gov/water-emergency/communication-resources/fact-sheet-preventing-diarrheal-illness-after-a-disaster.html), [source 4](https://www.nrcs.usda.gov/plantmaterials/mipmcot9407.pdf), [source 5](https://www.ibiblio.org/kuphaldt/electricCircuits/DC/index.html), [source 6](https://www.ibiblio.org/kuphaldt/electricCircuits/index.htm), [source 7](https://www.faa.gov/regulations_policies/handbooks_manuals/aviation), [source 8](https://www.fema.gov/sites/default/files/2020-07/residential-sheltering-safe-rooms_recovery-advisory.pdf), [source 9](https://www.usgs.gov/media/files/finding-your-way-map-and-compass), [source 10](https://www.armyupress.army.mil/Journals/NCO-Journal/Archives/2020/June/NCO-C3/), [source 11](https://www.fema.gov/sites/default/files/documents/fema_hm-emergency-supply-kit-checklist_english.pdf).

### Bundled offline archive readers

`archive-readers` · **ready** · planning target 0 GB



**Include:**

- Pinned Kiwix Windows portable reader
- Pinned Kiwix Linux x86_64 AppImage
- Pinned Kiwix macOS package
- Pinned standalone Kiwix Android APK
- Preserve notices and satisfy corresponding-source obligations before redistributing binaries

**Exclude:**

- Assuming an iPhone can install Kiwix from the SSD offline
- Assuming the x86_64 AppImage runs on Raspberry Pi

Sources: [source 1](https://get.kiwix.org/en/solutions/applications/download-options/).

### Additional directly readable editions of selected material

`direct-reading-expansion` · **unresolved** · planning target 60 GB

The tested in-place ZIM exporter and extra-catalog import are implemented. Reviewed article/book lists, collection-specific visual checks and complete verified output editions are still missing. The 60 GB target is an additional representation allowance, not downloaded content.

**Include:**

- Additional directly readable copies of material from source resources already selected for this build
- Prioritize Appropedia, CD3WD, iFixit, LibreTexts STEM and English Wikibooks
- Broaden the article-list-driven high-priority English Wikipedia HTML lifeboat
- Preserve diagrams, photographs, labels, captions, instructions, article context and book context
- Retain licensing and attribution notices, source versions and ordinary local entry links
- Treat the 60 GB target as additional storage beyond existing direct copies and their existing budgets
- Limit derivative subjects to the selected source collections; excluding a source collection excludes its planned derivatives from this expansion
- Full-1tb default preference for direct reading without a ZIM reader

**Exclude:**

- Expanding all of Wikipedia into millions of individual exFAT files
- Counting existing directly readable source files or previously budgeted direct editions twice
- Acquiring additional Khan, language or map collections to fill this budget
- Exporting an excluded collection through this representation resource
- Dropping illustrations or presenting decontextualized text as an equivalent illustrated guide
- Implying that an ordinary-format derivative is redistributable without checking the source license

Sources: [source 1](https://www.appropedia.org/Appropedia:Terms_of_use), [source 2](https://ftp.fau.de/kiwix/zim/other/), [source 3](https://www.ifixit.com/Info/Licensing), [source 4](https://ftp.fau.de/kiwix/zim/libretexts/), [source 5](https://download.kiwix.org/zim/wikibooks/), [source 6](https://ftp.fau.de/kiwix/zim/wikipedia/).
