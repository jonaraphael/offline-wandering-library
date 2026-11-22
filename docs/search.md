# Offline search

Open **Search** from `START_HERE.html`. Search shows one card per matching
document, with the best passage and other matching locations when available.
When the query matches an urgent task, its guide appears first. Documents
that open directly appear before matches in encyclopedias. Use **Options** to
search within a category. PDF matches open at the physical page. **How to
open** on an encyclopedia match shows the article to find in Kiwix and the
file's location on the drive. Search labels low-confidence suggestions.

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
The search page loads the weights on its first indexed query.
It uses classic local scripts, DecompressionStream for compressed shards and a
network-denying CSP. Word postings retrieve literal matches and Bloom filters
route them to chunks. Hamming distance admits additional passage and lead
candidates. The ranker compares each compact code with the full query vector
and combines similarity, word matches and source priority. Emergency queries
prefer matching critical sources. Childhood symptoms and childbirth receive
different ranking treatment. Among similar matches in directly readable files,
essential documents and first-aid chapters move up. Precomputed
token-pair filters and vector centroids order the chunks likely to yield
relevant hits. The compact term dictionary adds weighted chunk candidates,
using stronger field matches first. A query loads only its term buckets, then
opens candidate chunks. An approximately 40 MB read allowance covers the term
buckets and chunks for the first pass. The page shows those preliminary hits,
then automatically scores the remaining eligible chunks and refreshes the
results. Larger drives can take longer to finish the second pass. Submitting
a different query cancels the previous one between chunk reads.

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
benchmark checks chunk digests and runs the original 100 probes plus body-only
PDF queries with expected physical page locations. It reports the two query sets
at 16 GB, 128 GB and 1 TB. The experimental `--quick` measurement evaluates
just the first 28 MB of candidate chunks and can return fewer relevant hits.
The `--bounded` run measures the initial shortlist without completion or MiniLM.
The optional task export records the first three
results for each natural-language task in `tests/search/task-queries.json`,
with the title, source, locator and any displayable excerpt for grading.

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
