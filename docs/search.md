# Offline search

Open **Search offline** on the drive’s start page. Search covers the catalog and
adds PDF passages, HTML sections and ZIM entries for sources with precomputed
shards. PDF results open at the physical page. Archive results give the
archive’s drive path and the entry’s title and internal path. Open the archive
in Kiwix and find the title there.

The start page, topic atlas, sections page and phone shelf work without
JavaScript. When iPhone Files withholds neighboring links, use the printed
drive paths to open the files directly. See [device tests](device-matrix.md).

## What the search covers

The catalog index includes every completed document, its reviewed topics and
any reviewed chapter locations. Shards supply text fields, weighted stemmed
postings, vectors and locators for the exact source edition. New PDF shards
index passages on individual physical pages and carry forward outline headings.
New HTML shards segment visible text by headings and use the source’s existing
anchors where present. Sources with image-only pages still supply page locators.
A restricted source’s text contributes word postings and vectors. The stored
records carry its headings and locators. New archive shards index article titles
and paths, and selected archives also contribute lead paragraphs or accepted
answers. Archive coverage varies by source. [ZIM coverage](zim-search-coverage.md)

Editorial concept groups add common terms, spelling variants and question
wording at indexing time. At search time, the ranker removes common question
wrappers and handles audience phrases separately. It uses offline phrase groups
to connect everyday wording with clinical and practical vocabulary. A relevant
passage or article lead earns more than a title-only match. For health, water
and survival intents, matching CRITICAL sources receive additional weight.
Discussion results receive less weight unless a marked accepted-answer excerpt
or its postings match. Older discussion shards lack per-record answer markers
and receive the title penalty. The ranker also uses similarity to quantized
vectors where present. The shared model is a
32-component, signed 8-bit conversion of Minish Lab’s MIT-licensed
Potion-base-2M. OWL pools tokens from each passage body before quantization.
New title-only archive records store up to four bytes of vector data as the
signs of those components. Shared Wikipedia title records store eight signs
in one byte. These vectors help rank term matches.
The model table and license are copied once per drive. [Pinned model](https://huggingface.co/minishlab/potion-base-2M/tree/389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da)

Browser search loads classic scripts and inflates gzip chunks with
DecompressionStream. It runs with local files and a network-denying CSP.
Catalog results appear while the article and passage index loads. The ranker
reads chunks based on query terms and the presence of passage or lead vectors,
then updates results as chunks arrive. For emergency intents it reads matching
passage chunks from relevant CRITICAL sources first. The catalog remains available if the
viewer can load the catalog script and blocks the larger index.

## Precompute and verify

```sh
python scripts/build_search_shards.py --model-input "$MODEL_INPUT" \
  --cache "$VERIFIED_SOURCE_CACHE" --directories "$ZIM_RECEIPTS"
python scripts/search_benchmark.py --check
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
ordered chunks and aggregate digest. English Wikipedia editions can refer to
the same stored title chunks. Their logical shards refer to only the chunks
that match each edition’s directory. A lead from the pinned mini edition can
serve another edition when its title and internal path match exactly. Each builder selects shards after source
verification. Python reads and copies one chunk at a time. The browser fetches
and verifies only selected shard files. The Pages workflow serves its small
manifest from Pages and uses the workflow’s exact commit on Raw GitHub for the
payload. A local Pages build can copy search assets into its output for testing.

The search catalog is limited to 900 MB with files no larger than 50 MB.
The default 16 GB plan reserves 160 MB for search. Larger plans can allocate up
to 900 MB by assigning a portion of their on-drive reserve to search. The
planner leaves at least 125 MB in that reserve. The
benchmark checks chunk digests and runs the original 100 probes plus body-only
PDF queries with expected physical page locations. It reports the two query sets
at 16 GB, 128 GB and 1 TB. The optional task export records the first three
results for each natural-language task in `tests/search/task-queries.json`,
with the title, source, locator and any displayable excerpt for grading.
