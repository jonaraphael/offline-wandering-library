# Offline search

Open **Search** from `START_HERE.html`. Search shows one card per matching
document, with the best passage and other matching locations when available.
When the query matches a reviewed emergency route, search shows an **Urgent**
card for the guide. Documents that open directly appear
before matches in encyclopedias in ordinary search. Use **Options** to
search within a category. PDF matches open at the physical page. **How to
open** on an encyclopedia match shows the article to find in Kiwix and the
file's location on the drive. When the emergency is uncertain, search can
show up to three related sections or passages under “No reviewed guide
matched. These passages may help.” **Browse Home** opens the Urgent shelf
and categories.

The static start page shows the urgent tasks, categories, file locations and
device instructions. When a file preview withholds local links or scripts,
use the printed paths in your file manager. [Device tests](device-matrix.md)

## What the search covers

The catalog index includes every completed document, its reviewed topics and
any reviewed chapter locations. Shards supply text fields, weighted stemmed
postings, vectors and locators for the exact source edition. New PDF shards
index passages on individual physical pages and carry forward outline headings.
New HTML shards segment visible text by headings and use the source’s existing
anchors where present. Sources with image-only pages still supply page locators.
A restricted source’s text contributes word postings and vectors. Result
titles use the book or source title for unnamed PDF pages, with the physical
page shown separately. Restricted text excerpts are suppressed. New archive
shards index article titles and paths. For filename-like HTML titles, the
extractor checks the HTML title and first usable heading. Existing CD3WD
shards carry title overrides recovered from the pinned archive. When the
source has no readable heading, the result uses the collection title and
keeps the archive path visible. Selected archives also contribute lead paragraphs, body passages and
accepted answers. Archive coverage varies by source. [ZIM coverage](zim-search-coverage.md)

Editorial concept groups add common terms, spelling variants and question
wording at indexing time. At search time, the ranker removes common question
wrappers and handles audience phrases separately. It uses offline phrase groups
to connect everyday wording with clinical and practical vocabulary. A relevant
passage or article lead earns more than a title-only match. For health, water
and survival intents, matching CRITICAL sources receive additional weight.
Discussion results receive less weight unless a marked accepted-answer excerpt
or its postings match. Older discussion shards lack per-record answer markers
and receive the title penalty. The ranker also uses similarity to quantized
vectors where present. The MIT-licensed Potion-retrieval-32M model uses its
first 256 components, with signed 8-bit token weights and the pinned WordPiece
vocabulary. Python and JavaScript use the same text normalization and token
lookup. Each passage or lead code stores 256 sign bits in 32 bytes before
script packaging. Its input combines the title, any displayable excerpt and
terms from the passage or lead postings. This lets the catalog refresh derived
vectors from preserved search data while keeping restricted excerpts redacted.
Title-directory entries use word postings reconstructed from their titles.
[Model revision](https://huggingface.co/minishlab/potion-retrieval-32M/tree/6fc8051fab2a1e0ee76689cf08c853792ac285e7)

The same generated composition plan supplies source order, physical paths,
pins and ranker metadata to both builders. The reader loads its own search
manifest and shares content-addressed shards and model files across builds.
The search page loads the weights on its first query that needs semantic
routing or indexed ranking. A reviewed lexical match can open without loading
the weights.
It uses classic local scripts, DecompressionStream for compressed shards and a
network-denying CSP. Word postings retrieve literal matches and Bloom filters
route them to chunks. Hamming distance admits additional passage and lead
candidates. The ranker compares each compact code with the full query vector
and combines similarity, word matches and source priority. Emergency queries
prefer matching critical sources. Childhood symptoms and childbirth receive
different ranking treatment. Among similar matches in directly readable files,
essential documents and first-aid chapters move up. Precomputed token-pair
filters and vector centroids order the chunks likely to yield relevant hits.
The compact term dictionary adds weighted chunk candidates, using stronger
field matches first. Title signatures and short references get dedicated
portions of the read allowance. The reader can show a lexical preview from
up to 350 KB of record chunks while the model and relevant term buckets load.
If final ranking opens a preview chunk, it reuses the parsed records.

The base ranker uses a 16 MB allowance for emergency intents when running
with the term index. The reader uses the smaller emergency fallback below
for descriptions it classifies as health or safety. Libraries with
up to 125 MB of record chunks use a 20 MB allowance for simple one- and
two-term lookups. Other searches preview results within a 39.7 MB allowance,
then score the remaining eligible chunks. That second pass can take longer,
especially on large libraries. Submitting a different query cancels the
previous one between chunk reads.

When the build fits the 46.6 MB MiniLM bundle in its search allocation,
desktop search preserves the top three indexed hits and uses MiniLM to
reorder subsequent results from the first 50 indexed hits. The all-MiniLM-L6-v2 model runs through single-threaded ONNX Runtime
Web WASM using local classic scripts. Potion and term postings supply the
shortlist. The model reads only excerpts that the index already permits
displaying. Its results follow the initial lexical and Potion matches. The
base index remains available if MiniLM cannot load or the search budget
prevents its installation. [MiniLM revision](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)
[ONNX Runtime Web](https://onnxruntime.ai/docs/tutorials/web/env-flags-and-session-options.html)

## Precompute and verify

```sh
python scripts/build_search_shards.py --model-input "$MODEL_INPUT" \
  --cache "$VERIFIED_SOURCE_CACHE" --directories "$ZIM_RECEIPTS"
node scripts/build_search_routes.cjs catalog/search catalog/search/routes.json
node --max-old-space-size=7000 scripts/build_impact_routes.cjs catalog/search catalog/search/impact
python scripts/search_benchmark.py --check
python scripts/search_benchmark.py --bounded --tasks
python scripts/search_benchmark.py --tasks > search-task-results.json
```

Store source files in the cache under their catalog SHA-256. The indexing
command checks file length and hashes the complete source before inspection.
It reuses the PDF outline importer and extracts PDF page text with PyMuPDF
when available, with pypdf as its fallback. Indexing leads from local ZIMs
requires the optional libzim package and a separate `--directories` path for
extraction receipts. `--replace` updates a source’s existing shard. For an
archive that needs a lead limit, `--lead-limit N` selects HTML entries with the
most direct redirect aliases. Ties use archive directory order. The model input
directory takes
`potion-model.safetensors`, `potion-tokenizer.json` and `potion-license.txt`.
Their digests are pinned in the conversion and build scripts. The
`--packed-model catalog/search` option reuses the repository’s pinned model and
license.

Run one remote edition with `--range-zim --asset ASSET_ID` and a
`--directories` path to create a reusable range receipt. The range path checks
HTTP 206, exact Content-Range, unchanged ETag and catalog byte count. Each range
has its own SHA-256 receipt. A range receipt identifies the observed edition
through those checks. Whole-file SHA-256 verification applies when the full
source is available and when the asset is built onto the drive.

The manifest keys each logical shard by source SHA-256 and pins its schema,
ordered chunks and aggregate digest. New chunks live under their own content
SHA-256. The generator reuses an identical chunk and retires unreferenced
paths after updating the manifest. Existing numbered chunks stay readable.
Routing descriptions are keyed by chunk digest and reused on regeneration.
English Wikipedia editions can refer to
the same stored title chunks. Their logical shards refer to only the chunks
that match each edition’s directory. A lead from the pinned mini edition can
serve another edition when its title and internal path match exactly. Each builder selects shards after source
verification. Python reads and copies one chunk at a time. The browser fetches
and verifies only selected shard files. The Pages workflow serves its small
manifest from Pages and uses the workflow’s exact commit on Raw GitHub for the
payload. A local Pages build can copy search assets into its output for testing.

The search catalog is limited to 900 MB with files no larger than 50 MB.
The default 16 GB plan reserves 200 MB for search and the WikiMed phone volumes. Larger plans can allocate up
to 900 MB by assigning a portion of their on-drive reserve to search. The
planner leaves at least 125 MB in that reserve. The
benchmark checks chunk digests and runs the original 100 probes, 10 body-only
PDF queries with expected physical page locations, and 10 held-out emergency
queries. It grades the first ten results at 16 GB, 128 GB and 1 TB using the
reader's chunk selection and base ranker. `--check` enforces the original probe
totals at each capacity, a hit for “signs of dehydration” at all three, and
retention of every previously passing probe. `--quick`, `--bounded`
and `--exhaustive` compare a 28 MB heuristic route, a 39.7 MB term-index route,
and all eligible chunks. Benchmark scoring stops at the base ranker.
The optional task export records the first three
results for each natural-language task in `tests/search/task-queries.json`,
with the title, source, locator and any displayable excerpt for grading.

## Reviewed emergency routes

The section review covers **189 destinations in 137 situations** from the
default 16 GB editions of *Where There Is No Doctor*, *A Book for Midwives*,
FEMA CERT, *Basic Emergency Care*, the MSF clinical and obstetric guides,
FEMA *Are You Ready?*, and WikiMed. The review records the edition digest,
physical PDF page or WikiMed path, heading, and everyday terms for each
situation.
[Section review](../catalog/emergency-sections.json)

The route compiler reads the default selection and verifies each destination
against its edition and its existing indexed locators. The reader matches
section names and everyday synonyms. Descriptions that depend on several
clues require each clue, such as a fall, hip pain, and the affected body
part. Existing time-critical routes keep precedence where clues overlap.
Matching sections open immediately from the installed catalog and respect
the optional category filter. Multiple locations in the same book share a
card. [Reader implementation](../src/owl/templates/search.js)

The expanded review includes the following destinations in the standard
16 GB selection.

| Situation | Destination |
| --- | --- |
| Stroke signs | *Basic Emergency Care*, pp. 139 and 147 |
| Blood in vomit or stool | MSF clinical guide, p. 122 |
| A blow or scratch to the eye | *Where There Is No Doctor*, chapter 16, p. 2 |
| A child with fever and a seizure | MSF clinical guide, p. 23 |
| Cold-water exposure and numb extremities | FEMA CERT, p. 114, and WikiMed’s *Non-freezing cold injury* |
| Prolonged exposure in wet shoes | WikiMed’s *Trench foot* |
| Penetrating injury or stab wound | *Where There Is No Doctor*, chapter 10, p. 16 |
| A fall from height | *Basic Emergency Care*, p. 58 |
| Mold in a flooded building | WikiMed’s *Mold health issues* |
| House fire and indoor smoke | FEMA CERT, pp. 173 and 30 |
| Evacuation as floodwaters rise | FEMA *Are You Ready?*, pp. 11 and 12 |

### Semantic matching and emergency fallback

Each situation, including the 35 established routes, has three plain-language
descriptions of symptoms, events, or hazards. Alternative locations for
the same situation share those descriptions. The compiler encodes each
description separately with the pinned 256-component Potion model and
stores its normalized vector as 256 signed bytes. The **182,218-byte**
generated table ships inside `rank.js`, so it adds no separate request.
Metadata-only builds omit the ranker. The reader uses the same locally
installed model as passage ranking.
[Situation descriptions](../catalog/emergency-descriptions.json)

The reader tries reviewed lexical matches first. Otherwise it embeds the
query and scores each situation by the highest approximate cosine similarity
to any of its descriptions. Injury mechanisms, danger signs, and hazard
terms can independently trigger emergency routing and constrain candidates
to health or safety. The calibrated recognition floor is **0.48**. A
specific route at or above that floor earns the Urgent label with a lead of
at least **0.08**, or a score of at least **0.55**. Generic assessment guides
and ambiguous similarities are shown as related sections. Straightforward
reference and prevention wording bypasses semantic emergency inference,
as do single-word searches without a reviewed name.

Calibration compared the new emergency descriptions with similar wording
from ordinary searches. “Yellow marks on a spider plant” scored about 0.47
against the spider-bite description, below the recognition floor. “Book
about art and smoke” scored about 0.53 against indoor smoke and is handled
by the reference filter. Flashes and a dark curtain in one eye scored
about 0.43 against retinal detachment. The vision danger sign allows the
section to appear as a related result at that score.

An emergency recognized from words or meaning gets an installed Urgent
guide while the reader looks for passages. If no reviewed route qualifies,
the reader can show up to three related sections or passages from different
documents. Nearby sections need a score of at least **0.42** and must be
within **0.13** of the strongest match. The reader can fill open slots with
matching body passages from up to 1.2 MB of existing index chunks in the
applicable categories. If no passage qualifies, it keeps an installed
urgent guide or offers **Browse Home** in the results. Ordinary searches
continue through the catalog, term index, and base ranker.

For a new edition, start with the pinned PDFs on an installed default
16 GB library and install the PDF extra. Candidate extraction verifies
the PDFs against the catalog and emits a list
from bookmarks, tables of contents and visually marked headings. The
first column on each candidate is the physical page where the text was
found. A contents entry may name a different printed page.

~~~sh
python scripts/build_search_emergency.py --candidates /path/to/LIBRARY > "$scratch/headings.tsv"
python scripts/build_search_emergency.py
python scripts/build_search_emergency.py --check
~~~

Review the relevant headings and check the cited sections and their physical
page numbers. Record the destination and add three to six short descriptions
of the situation, using a mix of wording a caregiver or bystander might use.
Check unusual paraphrases, reviewed routes that share symptoms, and unrelated
searches that use the same words. The compiler writes the reviewed locations
and vectors into the reader script. CI checks the generated table against
the review and exercises the displayed results in the offline reader.

The reader also retains the following previously reviewed routes. Named
WikiMed articles use the archive paths in the pinned manifest.
[WikiMed manifest](../catalog/wikimed-phone/manifest.json)

Page numbers in the table are physical PDF pages. The standard 16 GB
selection contains every listed source.

| Situation | Wording the route recognizes | Destination |
| --- | --- | --- |
| Severe bleeding | Blood gushing or a wound that keeps bleeding | FEMA CERT, p. 101 |
| Burns | Scalds, blisters after a spill, burned skin | MSF Clinical Guidelines, p. 339 |
| Choking | Food stuck in the throat, inability to speak while eating | WHO/ICRC Basic Emergency Care, p. 155 |
| CPR | No pulse, stopped breathing, gasping after collapse | WikiMed, Cardiopulmonary resuscitation |
| Unresponsive person | Fainted, passed out, won't wake or respond | Hesperian Where There Is No Doctor, chapter 10, p. 4 |
| Drowning | Fell into a pool, river, or well, fell overboard, gasping after a rescue | WikiMed, Drowning |
| Electric shock | Live wire, shock from a cord or socket | WikiMed, Electrical injury |
| Heart attack | Chest pressure, chest pain with arm or jaw pain | WHO/ICRC Basic Emergency Care, p. 203 |
| Stroke | Facial droop, one-sided weakness, slurred speech | WHO/ICRC Basic Emergency Care, p. 139 |
| Anaphylaxis | Tight throat after a sting, lip swelling after a meal | MSF Clinical Guidelines, p. 14 |
| Poisoning | Swallowed cleaner, pills from an open bottle | WikiMed, Poisoning |
| Swallowed objects | Gulped a coin, ate a battery, put missing magnets in the mouth | WikiMed, Foreign body |
| Chemical eye injury | Cleaning fluid or battery liquid in an eye | WikiMed, Chemical eye injury |
| Carbon monoxide | CO alarm, a generator indoors, exhaust and headache | WikiMed, Carbon monoxide poisoning |
| Gas leak | Smell of gas, hissing near a stove | FEMA CERT, p. 176 |
| House fire | Smoke filling a hallway, fire in a home | FEMA CERT, p. 173 |
| Electrical fire | Smoking plug, sparking socket | FEMA CERT, p. 175 |
| Flood | Rising floodwater, a flooded road, trapped in a vehicle | FEMA Are You Ready?, p. 11 |
| Earthquake | Shaking ground, falling objects | FEMA Are You Ready?, p. 10 |
| Heat illness | Confusion or collapse in the heat | FEMA Are You Ready?, p. 10 |
| Cold exposure | Shivering and confusion in freezing conditions | FEMA CERT, p. 114 |
| Frostbite | White, numb fingers or toes in the cold | FEMA CERT, p. 114 |
| Fractures | Crooked limb, exposed bone, broken wrist | FEMA CERT, p. 110 |
| Puncture wounds | Stepped on a nail, a shard or wire went through the skin, tetanus booster | Hesperian Where There Is No Doctor, chapter 10, p. 15 |
| Animal bites | A dog bite, a stray cat breaking the skin | MSF Clinical Guidelines, p. 258 |
| Insect bites and stings | Wasps, bees, insect bites | WikiMed, Arthropod bites and stings |
| Snakebite | Fang marks or a snake slithering away | MSF Clinical Guidelines, p. 355 |
| Newborn fever | A newborn with a temperature | MSF Essential Obstetric and Newborn Care, p. 221 |
| Young infant fever | A young baby with fever or a high thermometer reading | MSF Clinical Guidelines, p. 35 |
| Diarrhea and dehydration | Watery stools, reduced urination, inability to keep water down | Hesperian Where There Is No Doctor, chapter 13, p. 1 |
| Childbirth | A baby coming before reaching the hospital | Hesperian A Book for Midwives, chapter 12, p. 14 |
| Postpartum bleeding | Heavy bleeding after the baby is born | Hesperian A Book for Midwives, chapter 13, p. 3 |
| Drinking water | Dirty tap water, disinfection, whether creek, lake, or rain water is safe to drink | EPA Emergency Disinfection of Drinking Water, pp. 1–2 |
| Food in an outage | Warm refrigerator, thawed freezer, outage and meat | FEMA Are You Ready?, p. 26 |
| Emergency sanitation | Toilets that will not flush, nowhere to dispose of human waste | Hesperian A Community Guide to Environmental Health, chapter 7, p. 2 |

## Held-out emergency queries

The original ten probes were fixed before tuning. The additional
[30 everyday emergency queries](../tests/search/everyday-emergency-queries.json)
were fixed before adding the reviewed routes. The browser test submits each
query to the assembled 16 GB reader in offline Chromium and checks the titles
of the first three displayed cards, with floors of 8/10 and 24/30. A further
[15 paraphrases](../tests/search/emergency-paraphrases.json) were fixed before
the follow-up routing changes. Each must show the expected reviewed guide as
its first card. The browser test also checks both fallback states.

A fourth set contains 40 new everyday queries across 39 situations. Six
situations overlap the old route table. This set was fixed before the
section routes were implemented. The offline reader grades the first three
cards as good when a reviewed guide or named first-aid reference covers the
expected topic, partial for an adjacent topic or a weaker source, and poor
otherwise. CI requires at least 32 good and no empty emergency results.
[40-query section benchmark](../tests/search/section-emergency-queries.json)

The new semantic routing fixture contains 40 independently worded queries
across 32 situations. It was frozen and run against the baseline reader
before routing changes. It includes symptoms, injury mechanisms, approaching
hazards, and descriptions from bystanders. It grades the first three
displayed cards, with **34 good** and **zero empty** required in CI.
[40-query semantic benchmark](../tests/search/semantic-emergency-queries.json)

- Smoke is coming from the outlet where the heater was plugged in.
- My friend touched a live wire and fell to the floor.
- A dog we do not know bit my hand and broke the skin.
- Cleaning spray got in my eye and it will not stop burning.
- A swimmer was pulled from the water and is barely breathing.
- Someone woke up with sudden chest pressure and pain down one arm.
- My friend has hives and cannot breathe after a bee sting.
- The power has been out all night and the meat in the fridge feels warm.
- We smell gas next to the stove and the burner is off.
- Floodwater is rising around the car and we cannot drive out.

## Measured relevance

The 16 GB reader scored **10/10** on the original held-out set, **30/30** on
the everyday set, and **15/15** first reviewed cards on the paraphrase set.
The 40-query section benchmark used the same grading rules before and after
the change.

| Reader | Good in top three | Partial | Poor | Empty |
| --- | ---: | ---: | ---: | ---: |
| At 772a1dba | 0 | 2 | 38 | 22 |
| With section routes and emergency fallback | 37 | 2 | 1 | 0 |

The object-in-nose and object-in-ear cases still retrieve only adjacent
topics. The jellyfish sting case shows the general emergency assessment
guide.

The new 40-query set uses mutually exclusive grades. An empty result counts
only as empty. A good result includes a section or article on the expected
situation among the first three displayed cards. A partial result finds a
related topic or a less specific reference.

| Reader | Good in top three | Partial | Poor | Empty |
| --- | ---: | ---: | ---: | ---: |
| At `8e41895a` | 0 | 8 | 12 | 20 |
| With lexical and semantic routing | 40 | 0 | 0 | 0 |

The older browser floors still pass at 10/10 held out, 30/30 everyday,
15/15 first-card paraphrases, and 37/40 section cases with zero empty.
Separate timing probes exercise health and safety descriptions with no
lexical trigger.

The base-ranker benchmark retained all probes that passed
at `fde71516`, including “signs of dehydration” at all three capacities.

| Library size | Original probes, top ten | PDF body probes, top ten | Base ranker held-out probes, top ten |
| --- | ---: | ---: | ---: |
| 16 GB | 92/100 | 9/10 | 3/10 |
| 128 GB | 96/100 | 9/10 | 3/10 |
| 1 TB | 96/100 | 8/10 | 2/10 |

## Offline timing and reads

```sh
scratch=$(mktemp -d "${TMPDIR:-/tmp}/owl-search.XXXXXX")
NODE_PATH=/path/to/node_modules PYTHONPATH=src python scripts/search_benchmark.py --assemble "$scratch/16" --check-reader
PYTHONPATH=src python scripts/search_benchmark.py --assemble "$scratch/1000" --capacity 1000
NODE_PATH=/path/to/node_modules node scripts/search_timing.cjs "$scratch/16/START_HERE.html" --check
NODE_PATH=/path/to/node_modules node scripts/search_timing.cjs "$scratch/1000/START_HERE.html"
```

The assembler uses only the checked-in search data and shipped reader files.
The checks use `playwright-core` with an installed Chromium. The timing harness also
accepts an existing `START_HERE.html`, repeated `--query` arguments, and
`CHROMIUM_EXECUTABLE_PATH` for a browser outside Playwright's cache.

Measurements used Chromium 145.0.7632.6 and an Apple M5 Pro local SSD. Each
query opens a fresh browser context with 4× CPU throttling, offline network
emulation and browser cache disabled. First-result time runs from form
submission to the first reviewed, fallback or indexed result card. Complete time ends when
the reader publishes its final results and status, including MiniLM where
installed. Byte counts sum the sizes of local file requests during each
query, including cold model and reranker loads. They exclude reader startup
and in-memory scripts and measure requested file bytes on the SSD run.

| Query | 16 GB first card | 16 GB complete | 16 GB requested bytes |
| --- | ---: | ---: | ---: |
| Signs of dehydration | 21.2 ms | 21.2 ms | 0 |
| Chest compressions | 23.3 ms | 23.3 ms | 0 |
| Snake bite | 23.0 ms | 23.0 ms | 0 |
| Make water safe to drink | 22.5 ms | 22.6 ms | 0 |
| We are stuck outside overnight in heavy rain without a tent | 20.4 ms | 147.5 ms | 1,199,596 |
| My neighbor is lying still on the floor and I can't tell if he's breathing | 23.2 ms | 213.3 ms | 1,199,798 |

The 16 GB run passed the limits of 300 ms to the first card and 3 s to
finish. The four reviewed routes requested zero additional file bytes.
The last two queries both used the emergency fallback. The timing check
requires the last query to read index chunks and show the fallback label.
Ordinary searches can read more index chunks and take longer to complete.
The selected 16 GB library contains 110.5 MB of record chunks and 155.9 MB
of search files overall. At 1 TB, those figures are 723.9 MB and 853.5 MB.
USB and phone I/O were outside these measurements.

With semantic routing, Chromium 158.0.8127.36 measured a maximum of
**95.3 ms to the first card** and **289.9 ms to completion** across eight
cold 16 GB queries at 4× CPU throttling. The two queries that had no
lexical trigger but found a reviewed guide took 93.0 and 95.3 ms. Both
read the existing 21.54 MB model and no record chunks. Lexical matches
still requested zero additional bytes. Node measured about **0.21 ms per
query** for embedding and scoring with the model already loaded, averaged
over 4,000 queries without throttling.

| Emergency fallback | Baseline first card | Current first card | Baseline complete | Current complete |
| --- | ---: | ---: | ---: | ---: |
| Stuck outside in heavy rain | 17.1 ms | 18.0 ms | 158.7 ms | 238.8 ms |
| Lying still with uncertain breathing | 17.6 ms | 18.8 ms | 212.3 ms | 289.9 ms |

The fallback draws its first guide before loading the model, then adds the
nearby sections or indexed passages. On these cold runs the first-card time
increased by 0.9 to 1.2 ms and completion time by 77.6 to 80.1 ms. No
additional model reads are needed on subsequent queries in the same view.

## Precomputed term index

Each term appears in one dictionary bucket shared by all selected resources.
Its postings name the physical chunks where the term is likely to be useful.
Score bands run from high to low. Within a band, ascending chunk identifiers
use delta integers with variable-length encoding. The compiler bounds each
band and the runtime limits term-bucket and candidate-chunk reads. Title
postings, archive sections and detailed scores are recovered from the
verified source chunks. The ranker also reserves part of the read allocation
for shorter references and candidates from token-pair and vector routing.
At smaller or unusual capacities the builders include the index when its
complete payload fits after selected source shards.

Append new edition-pinned body data with
`python scripts/build_archive_passages.py --cache CACHE --directories RECEIPTS ASSET_ID`.
This retains original title and lead rows and writes new content-addressed
passage chunks. The build chooses article candidates by redirect popularity
and deterministic sampling. Regenerate routing after appending chunks.
For Stack Exchange, marked accepted answers supply the body text. Whole-file
verification and publisher-piece samples have distinct coverage receipts.
