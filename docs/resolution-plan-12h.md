# Twelve-hour asset resolution plan

Prepared 2026-09-18 from `SELECT.html`, the active catalogs, acquisition evidence, implementation inspection, and current publisher sources. This is the original twelve-hour execution plan; the planning review itself changed no acquisition status. H0 means the start of execution and H12 is the delivery deadline. Effort estimates are engineering budgets, not measured download times.

## Current execution scope

The user subsequently requested a one-hour implementation pass, then clarified
that resource downloads should wait until somebody calls the build command.
**Current work is limited to source metadata, reproducible build-time mechanisms,
and local verification using already-existing evidence. Do not execute the download,
export, installation or SSD-build steps below without a later acquisition request.**
Selected temporary originals had been downloaded before that clarification; further
resource acquisition stopped immediately. No SSD build or copy was performed.

The one-hour pass began with 482 resolved records plus one unresolved placeholder,
after separate compact-edition enrichment had landed. Its final integration adds
83 ordinary sources plus two ZIP inputs and 1,655 pinned outputs, marks FAO ready,
and moves Survivor Tier A from unresolved to partial. See the [one-hour result](acquisition-hour-summary.md) for final counts,
verified changes and outstanding work; the schedule below remains the broader future
plan rather than evidence that those steps ran.

## Intended result

Aim for **4–6 selector resources to become ready**, plus **2–3 additional reviewed local direct editions** and reproducible acquisition recipes for harder collections. Food preservation, FAO, PhET and programming docs are the primary closure candidates; maps and Hesperian are conditional. These are planning targets, not guarantees. If an early integration prototype succeeds, some local editions can also become selector closures; otherwise their parent rows remain partial. Completing all 24 to their existing scope in twelve hours is not credible. Smaller pilots remain partial; merely reducing a target or removing a requirement does not count as resolution.

The initial planning baseline was **25 ready, 13 partial, and 11 unresolved resources**. There are **461 resolved file records and one unresolved file placeholder**, `regional_topographic_maps`. Most collection gaps therefore require adding missing content or representations, rather than fixing existing file URLs. The selector's embedded statuses match the registry, and catalog validation and selector freshness checks pass.

Prioritize food preservation, practical agriculture, programming documentation, PhET, Appropedia, iFixit, and Low-tech Magazine. Hesperian, CD3WD, Wikipedia's direct lifeboat, and regional maps are conditional opportunities. Large curated corpora receive bounded work packages after those opportunities are protected.

## Twelve-hour schedule

Use four workers, with one integration owner. Workers submit acquisition records and recipes; only the integration owner changes shared catalogs. Parallelize discovery, curation, small-file acquisition, and review. **Run OWL exports/builds into the same library serially:** the exporter takes the common `.owl/build.lock`.

| Window | Worker A: practical references | Worker B: integration and docs | Worker C: direct editions | Worker D: curated libraries |
| --- | --- | --- | --- | --- |
| H0–1 | Hesperian investigation, capped at 45–60 minutes | Confirm scope inputs/cache; begin a capped derivative-registration feasibility spike | Start bounded archive downloads; freeze Appropedia/iFixit selections | Freeze Gutenberg metadata and selection rules |
| H1–4 | Food preservation, then FAO topic coverage | Close integration spike by H2; proceed with Python/SQLite/man-pages/OpenSSH docs | Export/review Appropedia and iFixit; start an early bounded build benchmark | Gutenberg pipeline, then children's publisher-access pilot |
| H4–7 | Finish FAO; acquire/test PhET syllabus | Finish docs; maps if region supplied; otherwise inspect Khan/TED handoff | Low-tech first; CD3WD gate after higher-confidence jobs; Wikipedia only with source and review capacity | Children acquisition; Survivor Tier A manifest and small verified batch |
| H7–9 | Finish PhET; help inspect children's PDFs/images | Register completed packages; resolve navigation and byte accounting | Finish direct editions; additional LibreTexts/Wikibooks material only if capacity remains | Stack Exchange input/renderer pilot; write remaining corpus manifests and blockers |
| H9–10 | Review new practical material | Freeze candidate catalog and run selection checks | Finish existing jobs; retain checkpoints for unfinished work | Reconcile selected/downloaded/failed counts; no new acquisition technique |
| H10–12 | Visual/device QA and fixes | Final import/build verification on a bounded selection; regenerate selector/docs; publish report | Repair missing images, links and notices | Check attribution, duplicates, scope counts and exception lists |

The schedule has approximately 40 worker-hours before final QA. Per-resource budgets below overlap through shared tooling and are **not additive promises**. Optional Tier B, multilingual expansion, Khan remainder, and legacy/science corpus work borrow time only after higher-priority work passes its gates.

At H2, abandon repeated inaccessible-endpoint experiments and record the exact blocker. The derivative-registration spike also stops at H2: either demonstrate and test a reproducible supported path, or explicitly deliver local editions without claiming selector closure. At H6, compare measured completion rates with remaining time and stop expanding slow queues. At H9, stop feature development. Reserve the final two hours for producing a trustworthy result. If maps consume Worker B's spare slot, Khan/TED receive only a route/manifest handoff in this window.

## Plan for every incomplete resource

### 1. Hesperian health — `hesperian-health` — partial

**Budget:** 45–60 minutes; conditional completion. The only missing item is the 2026 midwives book's “Other resources” back matter, not a clinical chapter. Re-enumerate the [publisher's English PDF listing](https://languages.hesperian.org/pages/en/pdf.html), check corrected publisher-linked locations, and check whether a publicly offered complete **same-edition** book contains it. The currently linked [back-matter URL](https://hesperian.org/wp-content/uploads/pdf/en_midw_2026/en_midw_2026_bm.pdf) still returned 404 during this review.

**Done:** 271/271 expected originals, or a verified complete equivalent 2026 book, with hash, size, edition and intact notices. **Fallback:** retain seven complete books and the existing midwives chapters, explicitly name the missing back matter, and leave the parent partial. Do not substitute an older edition silently or depend on a publisher response within this window.

### 6. Food preservation — `food-preservation` — partial

**One-hour update:** seven new originals are pinned; freezing, broader drying and safety references are now covered. Remaining work is reproducible current NCHFP statements/recipe context. See [evidence](acquisition-hour-health.md).

**Budget:** 2–3 hours; strong completion candidate. Add the publisher's [NDSU Food Freezing Guide, reviewed January 2024](https://www.ndsu.edu/agriculture/extension/publications/food-freezing-guide), broader fruit/general drying guidance from [NCHFP](https://nchfp.uga.edu/how/dry/), and an explicit food-safety reference. Preserve the existing canning and fermentation originals. Review and capture complete dated [NCHFP updates](https://nchfp.uga.edu/newsflash), including the September 2026 steam-canning statement, and connect updates to the affected older guidance.

**Done:** a five-topic coverage matrix—canning/updates, freezing, drying, fermentation and food safety—with complete pinned documents, legible tables and illustrations, and an explicit review date. Do not rewrite processing instructions or call the 2015 collection universally current. **Fallback:** add verified manuals and retain a precise remaining update/coverage gap.

### 8. FAO agriculture — `fao-agriculture` — partial

**One-hour update: ready.** Nine new originals plus the seven existing guides cover all 17 declared topics. See the [complete source and coverage matrix](acquisition-hour-fao.md). The original work package below is complete at the acquisition-catalog level; no SSD build was performed.

**Budget:** 2–3 hours; completion candidate if every declared topic is covered. Build a matrix of all 17 existing inclusion topics and map the seven pinned manuals to it. Fill gaps with complete originals: [greenhouse vegetable production](https://www.fao.org/4/i3284e/i3284e.pdf), [small-scale postharvest handling](https://www.fao.org/4/ae075e/ae075e00.htm), [grain storage](https://www.fao.org/4/t1838e/t1838e00.htm), [small-scale dairy farming](https://www.fao.org/4/t1265e/t1265e.htm), and [rabbit husbandry/feed](https://www.fao.org/4/x5082e/X5082E00.htm). Find a complete small-farm tools reference and verify crop-water coverage separately. Prefer publisher PDFs; capture all chapters/images when only HTML is available.

**Done:** each requested topic has an appropriate complete source; publication date, climate/geographic context and individual notices remain visible. Inspect contents, one technical table and one illustrated procedure per title. The older sources are candidates to review, not automatically current operational recommendations. **Fallback:** preserve added titles and name uncovered topics; incomplete tools or livestock coverage keeps the resource partial.

### 9. Gutenberg core — `gutenberg-core` — unresolved

**Budget:** 3 hours for reusable acquisition and a first substantial batch; further acquisition in background. Freeze the official CSV/RDF metadata, select English books across every declared subject, exclude audio/periodicals and duplicate editions, and store stable book IDs plus a written selection rule. Use [Gutenberg's supported mirroring routes](https://www.gutenberg.org/help/mirroring.html), with text for the broad baseline and selected illustrated HTML/EPUB enrichment. A bulk archive is an input; unpack and catalog ordinary files before claiming direct access.

**Done:** the entire declared selected-ID manifest is acquired, deduplicated, rights-noticed, navigable and checksum-pinned; illustrated works keep their pictures. A smaller curated first release needs an explicit scope label and cannot silently satisfy the original broad collection. **Likely H12 result:** a working reproducible pipeline and useful partial library. The 40 GB planning target is not a reason to add duplicates or low-value material.

### 10. Children's Library — `childrens-library` — partial

**Budget:** 2-hour access/format pilot in Worker D's lane, then background acquisition and shared QA. Follow the normal [Book Dash source browser](https://bookdash.org/book-source-files/) download flow once in a browser to distinguish session problems from unavailable public PDFs. Enumerate title → ebook → language → complete PDF; avoid whole source folders containing large video/production assets. Respect 403/429 responses and back off. Freeze the [African Storybook approved catalog](https://www.africanstorybook.org/lists/booklist.approved.php), parse its data without executing publisher JavaScript, and test ten varied books through its official reader/export.

The prior African Storybook PDF response had text before the PDF signature. If still present, retain the raw response and validate an explicitly recorded normalization; never label repaired bytes as an unchanged original. A faithful HTML/image export is another candidate. Preserve author, illustrator, translator and per-book license credits. Reuse Gutenberg's children's IDs for deduplication.

**Done:** reconcile all selected title/language records against usable illustrated files, navigation and explicit failures. The existing scope includes essentially all current Book Dash and approved African Storybook content; a 50-book pilot does not finish it. **Fallback:** convert the existing 61 licensed EPUBs into complete directly readable HTML/image books and add successful current PDFs; retain partial status. The [publisher's reuse information](https://bookdash.org/re-using-the-book-dash-content/) supports the Book Dash route.

### 11. English Wikipedia — `wikipedia-en` — partial

**Budget:** 2–3 hours of curation/review with an additional reviewer, plus a 127.418 GB source download; stretch only. Freeze a reviewed lifeboat list covering every declared topic cluster, resolve exact entry paths in the pinned maxi edition, and use the existing direct exporter. A proposed 200–400-article discovery list must be reduced to a reviewable, coverage-complete selection or scheduled beyond this window; it is not a claim that all those articles can be inspected in three hours. Preserve references, images, tables, equations and context; cross-link to authoritative medical/practical manuals.

**Done:** full maxi pin remains, and the complete reviewed lifeboat manifest produces verified offline HTML/images and a usable shelf. Reconcile the requested `WIKIPEDIA/DIRECT/` entry point with the exporter's actual `REFERENCE/DIRECT/` output. **Gates:** source fully downloaded/verified by H6, an available reviewer, and a tested integration path that fits the indexing deadline. A small extra catalog still requires selecting the source ZIM and triggers full source indexing today. Without a supported source-bound direct edition or explicit archive indexing policy, this is not a deadline closure. **Fallback:** commit the exact selection/recipe and leave partial; no claim that a few web snapshots satisfy the pinned edition. The requested 2–5 GB is a planning aim, not a quality test.

### 14. Regional maps — `regional-maps` — partial

**Budget:** 1–2 hours setup/review plus downloads; requires home region and corridors. For a US region, use the [USGS TNM Access API](https://www.usgs.gov/faqs/there-api-accessing-national-map-data) to enumerate current US Topo sheets intersecting the home area, neighboring regions and named corridors, with an explicit surrounding buffer. Freeze sheet IDs, edition dates and official download URLs; deduplicate repeated sheets. Produce separate 10 GB compact and broader regional manifests based on geographic coverage, not filler.

**Done:** a map index shows the chosen coverage, all included sheets open offline, scale/legend/coordinates are legible, and there are no unexplained holes along requested corridors. Replace the unresolved placeholder with actual file records. Retain the existing North America/world replacement behavior. **Fallback:** a reproducible geographic selection recipe remains awaiting the user's region; do not infer it from the computer timezone. Outside the US, identify the corresponding national mapping authority before choosing products.

### 15. Appropedia — `appropedia` — partial

**Budget:** 1.5–2.5 hours after the 0.582 GB archive arrives; strong candidate. Freeze critical articles spanning water, sanitation, agriculture, cooking/energy, shelter and appropriate technology. Resolve redirects, export their full local dependencies, and review each selected practical procedure's figures and steps. A proposed 30–50-page starting list is a curation aid, not automatic sufficiency.

**Done:** whole archive plus the complete reviewed direct selection, linked from the library and registered as verified outputs. Preserve page-specific notices: [Appropedia's terms](https://www.appropedia.org/Appropedia:Terms_of_use) distinguish text and hardware-design licensing. **Fallback:** quarantine failed entries and retain partial rather than omit essential diagrams.

### 16. CD3WD — `cd3wd` — partial

**Budget:** 1 hour inspection, another hour only if straightforward. Download the 0.581 GB pinned archive, enumerate original PDF/HTML entries, and distinguish actual manuals from navigation/JavaScript wrappers. Export complete originals and a title/topic index with publication-level notices. Inventory what the published archive actually contains before claiming it is the historical full CD3WD corpus.

**Done:** requested ordinary originals present in the pinned archive are acquired and reviewed, with complete supporting files. Any missing required publication or chapter keeps the resource partial; exception reports only document the gap. **Gate:** stop the compatibility investigation after 45–60 minutes if replay-generated pages, oversized items, or missing originals require a new crawler. **Fallback:** preserve usable complete exports but leave partial. The [existing archive evidence](acquisition-archives.md) and [exporter limitations](direct-export.md) govern this work.

### 17. iFixit — `ifixit` — partial

**Budget:** 2–3 hours after the 3.571 GB archive arrives; strong candidate. Select useful bicycle, tool, appliance, power-system and computer repairs actually present in the pinned edition. Proposed first review set: 30–50 complete guides across those categories. Export every step, step image, tool/part list, warning and relevant context, with [iFixit attribution/license notices](https://www.ifixit.com/Info/Licensing). Publisher-offered complete guide PDFs are a fallback if static galleries cannot preserve every step/photo; record their own edition and provenance.

**Done:** every selected guide is complete and visually checked against its source, has a local entry link, and is registered for offline search/navigation. **Fallback:** a guide missing a step or photograph fails acceptance; keep the resource partial and list the exact failures.

### 18. Low-tech Magazine — `low-tech-magazine` — partial

**Budget:** 1–1.5 hours after the 0.701 GB archive arrives; candidate with a Zimit risk. Enumerate the pinned January 2025 archive's article set and export useful complete articles, dates, credits, diagrams and captions. Use a static snapshot of the same source edition if replay wrappers block the general exporter; do not silently combine a newer website with older archive metadata.

**Done:** the declared useful editorial selection renders offline with no essential remote dependencies and has a complete manifest. **Gate:** after 30 minutes of failing wrapper conversion, stop that technique. **Fallback:** verified subset remains partial; buying a separate [publisher offline edition](https://solar.lowtechmagazine.com/offline-reading/) is not assumed.

### 19. Survivor Tier A — `survivor-tier-a` — unresolved

**One-hour update: partial.** Three reviewed historical source pins cover cone-pattern sheet metal, ordinary foundations and water distribution. Three candidates were excluded. Broad trade coverage remains. See [title decisions](acquisition-hour-survivor.md).

**Budget:** 2 hours for title selection and a verified first batch. Freeze a title manifest spanning all six requested trade groups; prioritize roughly 40–80 strong candidates, then remove duplicate editions and poor scans. Follow individual PDFs from the [publisher's category indexes](https://www.survivorlibrary.com/), rather than depending on bulk ZIPs. Check each volume's identity, contents, rights evidence, scan legibility and diagrams. Retain historical context, especially for obsolete machinery/practices.

**Done:** the full curated Tier A manifest passes those checks, including all declared subject groups. **Likely H12 result:** a useful reviewed partial batch plus a resumable queue. Do not claim that a few PDFs complete the planned 75–100 GB library; do not mirror excluded medicine, literature or periodicals merely to reach a size target.

### 20. Stack Overflow durable — `stackoverflow-durable` — unresolved

**Budget:** shared 1–2-hour feasibility/renderer pilot with the Stack Exchange resources; original scope unlikely in H12. Obtain a permitted, pinned input with post text, comments, dates, authors, per-post licenses and duplicate links. Freeze allowlisted durable topics and excluded cloud/framework topics. Proposed initial filters: answered question, nonnegative question score, accepted or positively scored answer; retain the accepted answer plus at most two useful alternatives and substantive correction comments. Review a stratified sample before applying thresholds broadly.

**Done:** deterministic selection, canonical duplicates, attribution, version context and offline rendering across the selected corpus. The current whole-site ZIM would require about **114.856 GB** as an input and does not by itself supply all required metadata. **Fallback:** a fixture-tested pipeline and a clearly marked small pilot; keep unresolved if no usable collection is admitted. Do not substitute the whole ZIM for the curated deliverable.

### 21. Practical Stack Exchange — `stackexchange-practical` — unresolved

**Budget:** shares the corpus pilot above; scale only with spare time. Freeze the twelve named sites, beginning with the smallest useful practical sites to validate the pipeline. Kiwix archives may supply content inputs, but quality rules, canonical duplicates and per-post license evidence still need an explicit solution. The twelve current input archives total approximately **15.460 GB**, before direct HTML expansion, so the 12 GB output estimate must be measured.

**Done:** complete selected-site coverage after documented filters, including SuperUser/GIS selections, all required metadata, illustrations and offline navigation. **Likely H12 result:** one or a few validated site subsets, with remaining sites queued and partial status. Inputs and packaging sources: [Kiwix Stack Exchange directory](https://download.kiwix.org/zim/stack_exchange/) and [openZIM Sotoki](https://github.com/openzim/sotoki).

The planning pass saved [17 exact candidate input pins](resolution-input-pins.json) from upstream whole-file `.meta4` metadata. Their bodies were not downloaded by this planning pass. Sixteen now match admitted compact Stack Exchange alternatives exactly; the whole Stack Overflow input is not admitted. These alternatives do not complete the curated direct editions. The manifest records each matching catalog ID. For a dump-based implementation, obtain the official [permitted dump access](https://stackoverflow.com/help/data-dumps) and preserve `Posts`, `Comments`, `Users`, and `PostLinks` data using the [published schema](https://meta.stackexchange.com/questions/2677/database-schema-documentation-for-the-public-data-dump-and-sede). Login/access requirements remain a dependency; no current authenticated dump download was established.

### 26. PhET — `phet` — partial

**One-hour update:** the full proposed 16-file syllabus is pinned and passed representative desktop offline interaction/reset checks. Actual intended-device testing remains. See [evidence](acquisition-hour-phet.md).

**Budget:** 2–3 hours acquisition and desktop testing, plus intended-device availability. Freeze a useful regular-English HTML5 syllabus across circuits, forces/energy, waves, atoms/chemistry and basic mathematics. Proposed 16-simulation starter: the existing Ohm's Law and Circuit Construction Kit DC, plus Forces and Motion Basics, Energy Skate Park Basics, Projectile Motion, Pendulum Lab, Wave on a String, Gravity Force Lab Basics, Bending Light, States of Matter Basics, Build an Atom, Balancing Chemical Equations, pH Scale Basics, Natural Selection, Fractions Intro, and Area Builder. Confirm availability and resolve exact versions from the [publisher's individual offline downloads](https://phet.colorado.edu/en/offline-access). Retain notices; exclude Java, Flash and PhET-iO. Raise the 100 MB planning allowance if measured files require it.

**Done:** every selected simulation cold-launches from `file://` with network access denied, controls change the model, reset works, and local navigation/attribution are present. Test actual intended devices; desktop emulation does not certify iPhone support. **Fallback:** document tested desktop support and the remaining device gap honestly; acquisition success alone cannot satisfy an untested required platform.

### 31. Linux/programming documentation — `linux-programming-docs` — partial

**One-hour update:** 50 ordinary-file records are added, including Linux man-pages, systemd, networking/filesystem commands and eight release-pinned OpenSSH manuals. Complete Python/SQLite ZIP recipes and safe build-time extraction are implemented, covering 1,655 files. Four OpenBSD manuals and selected external references remain gaps. See [source evidence](acquisition-hour-programming.md) and [package completion](acquisition-programming-zip.md).

**Budget:** 3 hours; strong candidate. Keep the ten existing complete manuals. Add [Python's official HTML bundle](https://docs.python.org/3/download.html), [SQLite's static HTML documentation ZIP](https://www.sqlite.org/download.html), and the [Linux man-pages book or source release](https://www.kernel.org/pub/linux/docs/man-pages/book/). Add version-pinned [OpenSSH manuals](https://www.openssh.org/manual.html), networking (`ip`, `ss`, `ping`), filesystem tools (`mount`, `lsblk`, `findmnt`, filesystem checking), and systemd service/journal references from their official releases. Do not mistake development manual pages for a stable release.

**Done:** all declared topic groups have complete directly readable documents, retained licenses and local indexes/links. Implement safe extraction into ordinary files for ZIP/tar inputs and pin extracted bytes; OWL currently does not automatically turn downloaded documentation archives into readable folders. Use source-rendered HTML/text if official generated pages are unavailable. **Fallback:** add verified docs, list remaining utilities, and keep partial. No restricted POSIX text needs to be added without a verified permission basis.

### 32. Science Stack Exchange — `stackexchange-science` — unresolved

**Budget:** one equation-heavy pilot using the shared corpus work; expansion is a stretch. Freeze Mathematics, Physics and Biology inputs (approximately **9.668 GB** total compressed inputs; Chemistry is optional). Apply the shared quality/attribution rules. The upstream pages depend on MathJax, while OWL's direct exporter strips scripts: add build-time equation rendering to supported static MathML/SVG and test the actual sanitizer output before large export.

**Done:** selected useful questions retain equations, diagrams, answers, corrections and licenses with no runtime network dependency. **Fallback:** verified equation fixtures and a small labeled pilot, leaving the broad resource incomplete. No “ready” status for pages displaying raw TeX or missing formulas.

### 34. TED-Ed — `ted-ed` — partial

**Budget:** shared 1–2-hour official-channel feasibility pass with Khan, plus downloads if successful. [TED-Ed explicitly offers offline access through Kolibri and Endless Key](https://ed.ted.com/offline). Inspect the offered channel revision, actual lesson inventory and licenses. Retain the existing 6.381 GB pinned Kiwix topic archive; determine precisely how its coverage differs from the official channel and requested lessons.

**Done:** a complete declared lesson set with local context, intact video, audio/captions where supplied, credits, offline playback/seek tests, and supported OWL delivery. **Fallback:** verified playback of the named topic/channel subset with missing scope recorded; retain partial. The current direct exporter does not support video, and native Kolibri needs a supported runtime/handoff. Do not spend the window writing an unsupported whole-site video scraper.

### 35. Khan core STEM — `khan-core-stem` — unresolved

**Budget:** shares the official-channel pass above; prototype rather than broad completion. Inspect the live published Kolibri Khan channel and freeze revision, course/content-node IDs, licenses and dependency sizes. Select the requested math/science/computing courses using [Kolibri's selective content import](https://kolibri.readthedocs.io/en/latest/manage/resources.html). Check exercises and required assets as well as videos. Preserve unavailable-course and unsupported-content reports.

**Done:** full declared core course set, dependencies, subset manifest, supported offline player and OWL catalog/navigation integration, within measured storage. **Gate:** after at most two hours of combined channel/handoff work, stop if reproducible transfer and a working offline lesson are not demonstrated. **Fallback:** a pinned course plan and a small working pilot if possible; keep unresolved/partial according to admitted content. A Kolibri installation requirement is a product decision; it does not satisfy OWL's no-install reading promise automatically. No live channel UUID, current channel size or full course coverage was verified by this planning pass. Do not restore the retired unsplit 180 GB ZIM as the core subset.

### 43. Gutenberg multilingual — `gutenberg-multilingual` — unresolved

**Budget:** 30–60 minutes incremental to the Gutenberg pipeline; needs reading-language selection. Partition the same frozen metadata by the user's languages, select literature/children/reference/language-learning works, and deduplicate within each language and against existing files. Keep useful translations as distinct editions rather than accidentally deleting them as duplicates.

**Done:** every ID in the declared language-specific manifests has the chosen ordinary representations and notices. **Fallback:** complete recipe and awaiting-language status; do not infer languages from popularity or from the default Spanish Wikipedia selection. A small language starter set remains a labeled partial expansion.

### 44. Survivor Tier B — `survivor-tier-b` — unresolved

**Budget:** 30–60 minutes after Tier A only. Reuse title discovery, rights evidence and scan checks. Select nonoverlapping shipbuilding, mining/foundry, radio, refrigeration/steam, industrial chemistry, rail and textile references; propose 15–25 high-value candidates and record exclusions. Keep historical labels and remove Tier A duplicates.

**Done:** the entire declared specialist manifest passes quality and metadata checks. **Fallback:** reviewed acquisition queue or a small verified appendix; keep incomplete. This optional resource cannot displace Tier A or final QA merely to approach its 30 GB allocation.

### 45. Remaining Khan — `khan-remaining` — unresolved

**Budget:** at most 30 minutes after a working core package. Compute the chosen remainder as an explicit content-node set difference from the same channel revision, then independently select and verify it. Share supporting files without double-counting bytes.

**Done:** reproducible nonoverlapping remainder, working runtime/import and explicit opt-in. **Fallback:** a machine-readable remainder manifest only; leave unresolved until files and reader integration are verified. No core package means no reliable remainder package.

### 46. Stack Overflow legacy — `stackoverflow-legacy` — unresolved

**Budget:** 30–60 minutes of rules/fixtures after durable pipeline feasibility. Define explicit old-version/topic rules from the existing requested list; test ambiguous cases and ensure legacy records cannot enter normal results by default. Implement the visible legacy warning in both document pages and search results, with preserved dates/version context.

**Done:** verified selected corpus, attribution/duplicates, and actual separate search treatment. Current OWL search has no implemented legacy filtering/badge path; a title prefix alone does not fulfill the requirement. **Fallback:** selection rules and failing/passing fixtures, or a separately browsable labeled pilot; parent remains incomplete.

### Support. Additional direct editions — `direct-reading-expansion` — unresolved

**Budget:** 1 hour incremental planning/integration, then spare conversion time. Track reviewed additional Appropedia/CD3WD/iFixit/LibreTexts/Wikibooks/Wikipedia editions in one manifest with source asset IDs, source hashes, exact entry lists and output hashes. Add LibreTexts/Wikibooks chapters or whole small books only after the baseline direct editions above are reviewed. Preserve book context and equations.

**Done:** a complete explicitly selected additional-edition manifest, verified files, source-selection dependency handling and measured storage. Baseline direct copies required by resources #11/#15/#16/#17 are not automatically an additional 60 GB expansion. **Likely H12 result:** a smaller reviewed tranche, with broad expansion still partial. Do not count the same files twice or export an excluded source collection. Existing behavior and limits are documented in [direct export](direct-export.md).

## Shared engineering work that makes the result real

1. **Freeze scope before downloading.** Store source snapshot/revision, stable IDs, inclusion rules, exclusions, expected count and coverage matrix for each job. Use original `include` requirements as the acceptance checklist. A smaller named first release is an explicit deliverable; it does not change the parent resource's requirements.
2. **Reuse the downloader and cache.** Existing OWL transfer code already supports pins, bounded retries, resumption and reuse. Use one or two concurrent requests per publisher, backoff on throttling, exact sizes and SHA-256. Prefer immutable URLs; retain a local verified cache for mutable/generated documents. Do not change a stored hash merely to accept an unexpected response.
3. **Add only missing packaging capabilities.** Safe ZIP/tar/EPUB extraction needs path traversal, symlink, case-collision and size checks; per-file manifests; rewritten local links; and retained original notices. ZIM export already exists. Video, Kolibri handoff, and science equation rendering are distinct features with separate gates.
4. **Connect exports to the selector.** `--extra-catalog` adds verified local files to a build, but does not satisfy or update the parent resource's declared status in `SELECT.html`. It also adds actual bytes on top of planning allowances. The H0–2 spike must prove source-hash-bound generation/registration, output hash checks, correct resource membership, exclusion propagation, actual-byte accounting and meaningful failure/resume tests. If this cannot be completed safely inside the cap, abandon selector closure for local derivatives in this window. Register reproducible acquisitions/derivatives before changing `status`; regenerate the selector only from the source catalogs. For local-only exports, deliver an explicit local build manifest/recipe and keep the public registry honest until that path is supported. Do not insert this Mac's `file:` paths as portable public assets.
5. **Classify after review.** The exporter starts documents as noncritical, nonillustrated references. Promote only reviewed works to guide/textbook/illustrated metadata. Preserve source exclusions, source checksum binding, and asset ownership. Keep support images/styles with their documents.
6. **Prove usability.** Check file magic/containers, complete counts and hashes; crawl local links and required dependencies; inspect all selected critical procedure pages and representative beginning/middle/end/credits and figure/table pages for other books. Test interactive simulations and media offline. Record exactly which real devices were tested.

## Capacity and throughput decisions

The mounted OWL SSD had approximately **994.7 GB free** during this review. None of the five relevant Appropedia/CD3WD/iFixit/Low-tech/Wikipedia full source files was present at its expected library path or content-addressed cache path. Existing pins are not proof that their bodies are already local.

The four smaller direct-source archives total **5.434 GB**. Prioritize those. English Wikipedia alone is **127.418 GB**: its theoretical download time is about 2.83 hours at sustained 100 Mbps, 5.66 hours at 50 Mbps, and 14.16 hours at 20 Mbps, before hashing/export/indexing and contention. Measure actual throughput at H0; require a projected source-ready time by H6. Do not let Wikipedia or the 114.856 GB Stack Overflow source starve small high-value downloads.

Targets such as 40 GB Gutenberg, 100 GB Survivor, 90 GB Khan, and 60 GB direct editions are editorial storage allocations. Count complete selected works and coverage, not quota fulfillment. Record compressed input, extracted output, retained cache, search, scratch and reserve separately. The existing large-profile peak budgets already exceed their nominal drive sizes; rerun the actual CLI plan instead of claiming that resolving all catalog rows guarantees a fitting drive.

A twelve-hour **acquisition-resolution** result is separate from downloading and indexing the whole full-1tb selection. Final QA should build/verify a bounded selection of new ordinary assets and any small archives whose complete indexing benchmark fits, reporting unfinished full-drive jobs separately. Run a small-source import/build benchmark by H4. Current extra-catalog derivatives require their parent ZIM to remain selected, and the builder then indexes that ZIM; narrowing only the derivative manifest does not avoid full source indexing. A tested per-asset archive indexing policy or supported source-bound direct edition would be needed to change that behavior. Do not add such a feature in the final QA window or assume full Wikipedia indexing fits the last two hours.

## Delivery checklist at H12

- Per resource: original requirement, selected/acquired/failed counts, exact unresolved gap, source evidence, tested devices, actual bytes, and honest ready/partial/unresolved status.
- Versioned selection manifests, reproducible acquisition/conversion commands, per-file hashes, notices and retry checkpoints; large content stays on the SSD, outside Git.
- Updated `catalog/library.yaml` and `catalog/resources.yaml` only for accepted portable acquisitions, plus explicit local manifests for local-only outputs.
- Regenerated content documentation and `SELECT.html`, with no falsely enabled direct/compact editions.
- Run `python scripts/validate_catalog.py`, `python scripts/build_selector.py --check`, `python scripts/build_content_docs.py --check`, relevant exporter/selection/extra-catalog tests if code changed, a bounded import/build, and `python scripts/verify.py` for that completed build. Demonstrate resume once for each newly added acquisition mechanism.
- List every unfinished item with its next concrete action; preserve checkpoints. Do not use `--allow-incomplete` as evidence that the declared scope is complete.

Two inputs remain necessary for tailored coverage: the home region/corridors for maps and the desired non-English reading languages. Device-specific claims require access to those devices. Those dependencies do not prevent work on the other collections.
