# Offline search

Open **Search offline** on the drive’s start page. Search covers the catalog and
adds PDF sections, HTML pages and ZIM entries for sources with precomputed
shards. PDF results open at the physical page. Archive results give the
archive’s drive path and the entry’s title and internal path. Open the archive
in Kiwix and find the title there.

The start page, topic atlas, sections page and phone shelf work without
JavaScript. When iPhone Files withholds neighboring links, use the printed
drive paths to open the files directly. See [device tests](device-matrix.md).

## What the search covers

The catalog index includes every completed document, its reviewed topics and
any reviewed chapter locations. Shards supply text fields, weighted stemmed
postings, and locators for the exact source edition. PDF text is indexed in
publisher outline sections or ranges of up to five physical pages. Image-only
PDFs supply navigation and any extractable text. HTML indexing extracts visible
text from the pinned file. Archive coverage varies by source. [ZIM coverage](zim-search-coverage.md)

Editorial concept groups add common terms, spelling variants and question
wording at indexing time. The runtime combines the resulting lexical scores
with similarity to quantized vectors where present. The shared model is a
32-component, signed 8-bit conversion of Minish Lab’s MIT-licensed
Potion-base-2M. OWL uses its WordPiece vocabulary and normalized pooled vectors.
The model table and license are copied once per drive. [Pinned model](https://huggingface.co/minishlab/potion-base-2M/tree/389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da)

Browser search loads classic scripts and inflates gzip chunks with
DecompressionStream. It runs with local files and a network-denying CSP.
If the viewer blocks the chapter and article index, catalog search remains
available in browsers that can load the smaller catalog script.

## Precompute and verify

```sh
python scripts/build_search_shards.py --model-input "$MODEL_INPUT" \
  --cache "$VERIFIED_SOURCE_CACHE" --directories "$ZIM_RECEIPTS"
python scripts/search_benchmark.py --check
```

Store source files in the cache under their catalog SHA-256. The indexing
command checks file length and hashes the complete source before inspection.
It reuses the PDF outline importer and extracts PDF page text with PyMuPDF
when available, with pypdf as its fallback. Indexing sampled leads from local
ZIMs requires the optional libzim package. The model input directory takes
`potion-model.safetensors`, `potion-tokenizer.json` and `potion-license.txt`.
Their digests are pinned in the conversion and build scripts.

Run one remote edition with `--range-zim --asset ASSET_ID` and a
`--directories` path to create a reusable range receipt. The range path checks
HTTP 206, exact Content-Range, unchanged ETag and catalog byte count. Each range
has its own SHA-256 receipt. A range receipt identifies the observed edition
through those checks. Whole-file SHA-256 verification applies when the full
source is available and when the asset is built onto the drive.

The manifest keys each logical shard by source SHA-256 and pins its schema,
ordered chunks and aggregate digest. Each builder selects shards after source
verification. Python reads and copies one chunk at a time. The browser fetches
and verifies only selected shard files. The Pages workflow serves its small
manifest from Pages and uses the workflow’s exact commit on Raw GitHub for the
payload. A local Pages build can copy search assets into its output for testing.
