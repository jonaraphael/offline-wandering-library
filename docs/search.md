# Offline full-text search

Open `START_HERE.html` and enter words in **Search this library**. The same controls
are available on `SEARCH.html`. Search automatically loads its manifest and small
index chunks from the neighboring `SEARCH/` directory. There is no index-file
selection, installation, server, account, or network connection. The two pages
share one local runtime and widget. If your viewer blocks local JavaScript or
neighboring script files, use `INDEX/categories.html`, `INDEX/critical.html`, and
the alphabetical pages instead. The start page's static navigation also works
without JavaScript.

Keep the HTML entry pages and the entire `SEARCH/` directory together. Opening an
isolated copy of just one HTML page cannot provide search. Loading failures show
a retry control and links to static indexes; they do not fall back to a file
picker or a network service. A drive built only with the topic-atlas command
clearly reports that full-text search has not been built and has no search widget
or dangling runtime references.

The **Search in** selector offers **All resources**, **Textbooks**, and
**Illustrated guides**. The two learning collections include ordinary readable
files whose catalog metadata identifies them as textbooks or illustrated guides;
an illustrated textbook belongs to both. Specialized archives, software, and
files marked as needing a reader are excluded from these two collections even
if another catalog label calls them a textbook. They remain available under All
resources. Textbook/guide and illustration labels also appear beside results and
are searchable words. There is no ranking boost merely for belonging to a shelf.

Diagrams, photographs, and illustrations remain in the original PDF/HTML/image
files. Open a result to see them. Text snippets do not reproduce figures, and
filtering for illustrated guides does not imply image understanding or OCR.

## Coverage is measured, not assumed

Every build writes `SEARCH/coverage.json`; its information is also included in
the inventory and build metadata. Each asset has a status:

| Status | Meaning |
| --- | --- |
| `full_text` | All supported text units yielded extractable text; all extracted text was indexed. |
| `partial` | Some units were empty or a documented extraction limit excluded content. |
| `metadata_only` | No document text was extracted; catalog metadata and description are searchable. |

`full_text` describes extraction coverage, not a guarantee that a PDF's text layer
accurately represents every visible word. Text within images, diagrams, embedded
video, or scripts is not extracted. There is no OCR. A PDF page containing both
text and scanned images may have unsearchable words even when its status is
`full_text`. Warnings are counted; the first 20 examples per asset are retained
(each bounded to 2 KiB of text) so reports remain manageable. PDF/font-decoder
warnings are captured per asset instead of flooding the terminal. A document
with such warnings is marked `partial` even when its pages produced text.

Supported extraction:

- HTML: visible text and headings, excluding scripts, styles and templates.
- TXT and Markdown: streamed UTF-8 text. Set the optional `text_encoding` catalog
  field when a source uses another encoding. Invalid encoded bytes are replaced
  rather than executed; check original content if a passage looks garbled.
- PDF: `pypdf` extracts the text layer one page at a time. Empty pages are reported
  and page numbers are retained for result links.
- EPUB: every HTML, XHTML, and TXT archive member is streamed, without extracting
  archive paths onto disk. Member names are shown in results. DRM is unsupported.
- ZIM: the optional `libzim` build dependency visits archive entries and extracts
  HTML, XHTML, plain text and Markdown. Redirect targets are indexed once. PDF
  attachments and text entries above 64 MiB are explicitly reported as partial
  coverage. Archive media, application code and binary indexes are not text.
- Other formats: catalog title, description, category, source, filename and tags.
  Images, raster maps and installer binaries are explicitly metadata-only.

Missing required PDF/ZIM extraction dependencies fail before downloading. A
corrupt or encrypted document that cannot be extracted fails the build rather
than silently receiving a `full_text` label. Extraction is not a sandbox for
hostile documents; use approved, pinned sources and current extraction libraries.

## Index construction

The builder stores complete extracted text in passages of roughly 8 KiB. Normal
words are preserved at boundaries. Pathological uninterrupted strings longer
than 8 KiB are divided into segments. Passages retain document title, category,
source, destination and, where applicable, page or archive-entry identity.
Repeated passages from the same document can appear separately in results.
Resource type, illustration status, license, and attribution are retained on
every passage. Attribution and license notices are displayed beneath each search
snippet as ordinary text, including publisher-required notices such as
“Access for free at openstax.org.” The original source's licensing conditions
still apply to text incorporated into the search index and its displayed results.

A persistent, checkpointed SQLite database orders the inverted index on disk. It uses a 16 MiB
page-cache budget; neither the corpus nor the vocabulary is collected into one
Python list. Ordinary text, HTML and EPUB members stream in bounded chunks.
`pypdf` and `libzim` have their own working memory requirements: a complex PDF
page or decompressed ZIM cluster can still consume substantial memory. The ZIM
entry-size guard prevents allocating entries known to exceed 64 MiB, but is not
a hard process-memory limit. Use a computer with adequate RAM. By default the build database, rollback
journal, extracted records, and unfinished index all stay on the destination
SSD. `--work-dir` optionally relocates database/record storage, but is not
required. Serialization walks primary-key order without temporary sorting
B-trees; SQLite does not spill large sort files into the computer's OS temporary
directory. The finished library needs neither SQLite nor the scratch files.

Full Wikipedia indexing may take many hours or days and considerable temporary
storage. The final index duplicates extracted text and adds postings; it can be
larger than the compressed source archive. Profile space budgets are planning
allowances, not measured bounds. A corpus containing highly compressible data
can exceed any fixed source-size multiplier. Keep additional space available and
check the actual build. Peak space includes extracted records, postings in the
checkpoint database, a temporary serialized binary index, and the published
script chunks. Base64 increases the binary index size by roughly one third, plus
small script wrappers. The profile's search budget covers this **published output**,
not a raw-binary quota. The scratch allowance includes temporary binary assembly
on the SSD even when `--work-dir` moves the database elsewhere. An existing final
index remains until its replacement is complete. The default plans fit nominal capacities with explicit per-profile scratch allowances, but final-corpus sizing for the larger presets is still unproven. Building in place is supported,
but a final-content target alone does not guarantee enough temporary space. Raw serialization writes and exact script-pack sizes are checked before exceeding their allowances; the full generated search output is checked before completion. Extraction scratch and free-space reserves are monitored at checkpoint/progress boundaries. A SQLite transaction can grow between checks, so this is not a filesystem quota. Budget failures retain checkpoints for a reviewed retry.

Extraction checkpoints store the current asset, page/member/raw-entry cursor,
coverage report, passage count, and durable record-file offset together with
postings in a SQLite transaction. Records are flushed before committing the
transaction. On restart, SQLite rolls back unfinished transactions and the record
file is truncated to the last committed offset. Checkpoints occur every 50 units
or five seconds at a unit boundary, plus every completed asset. PDF pages, EPUB
members, and ZIM raw entries resume within the current archive; the current plain
HTML/TXT file restarts. Very slow individual units can delay a checkpoint.

Final index assembly restarts from the retained records and postings after an
interruption, without extracting the corpus again. On success, only registered
scratch files are removed; unrelated files in a workspace are preserved. Search
workspace ownership markers and OS-held locks prevent conflicting writers.

Actual source SHA-256 values, catalog metadata, extractor code, Python/Unicode,
and extraction dependencies form a build fingerprint. Changes invalidate the
extraction job deliberately. An unchanged completed index is reused only after
checking the fingerprint and the completed index's SHA-256. Space preflight can credit a complete unchanged index only after verifying every source and search chunk. It then reserves just UI/coverage rewrites, metadata and free-space reserve, without a second index/workspace allocation. Search rechecks this proof after locking and refuses fallback extraction if it changed. Integrity hashing repeats on restart and can take substantial time; hashing itself is not
checkpointed. Keep the same work directory and target path to retain an unfinished
extraction job. See the [pause/resume guide](usage.md#pause-and-resume).

The builder reports each asset's start and completion, including extraction
warnings, and reports major index-writing stages. During extraction it checks
progress every 1,000 passages and prints at most every five seconds; posting-list
and lexicon output are also periodically reported. One unusually slow PDF page
can still delay progress while the extraction library processes that page.

## Browser queries

Tokens are Unicode letters/numbers, normalized with NFKC and lowercased. There is
no stemming, stop-word removal, prefix matching, quoted-phrase operator, or
language-specific segmentation. Titles receive weight 5, category, tags and
resource labels weight 2, and other metadata/body words weight 1. BM25 uses these weighted frequencies
and document lengths, with `k1=1.2` and `b=0.75`. IDF is computed over passages.
Queries consider passages matching any query word. Use up to 32 distinct words;
longer queries are rejected with an explanation.

The browser binary-searches the sorted lexicon through a range-read interface
backed by local script chunks. For each query word it streams postings in blocks
of at most 4,096 records (48 KiB).
Sorted posting lists are merged and scored, retaining only the best 50 results
in a bounded heap. This is exact top-K ranking for the implemented query model,
not a fixed candidate cutoff that loses later matches. Only those result records
are read for snippets. It never loads the entire index or scans the corpus text.
For a selected learning collection, a separate table supplies one byte of flags
per passage. The browser reads this table through a single 64 KiB cache. Candidate
IDs increase during posting-list merging, so each relevant flag block is read at
most once per query. The collection filter applies **before** top-K selection;
textbooks outside the unfiltered top 50 are therefore still considered, without
decoding every candidate's document record. BM25 statistics continue to describe
the entire corpus, making filtered ranking the same ordering restricted to the
selected collection.
Memory for postings is at most approximately 1.5 MiB for 32 query words, plus the
small lexicon cache, at most 64 KiB of collection flags, and result records. The
transport additionally caches up to eight decoded 1 MiB chunks; script loading
and base64 decoding use temporary memory, and the browser may have its own caches.
This is not an 8 MiB bound on the entire browser process. Common words may still require reading
large posting lists, so queries can be slow on very large corpora. Progress and
cancellation remain available while processing.

Result text is assigned using DOM `textContent`; imported snippets are never
interpreted as HTML. Links are validated as relative paths. PDF links include
`#page=N` where supported. ZIM results provide the archive location and internal
article title/path; there is no portable file URL that opens an individual ZIM
article in an arbitrary reader. Open the archive in the bundled reader and locate
the article there. EPUB chapter names likewise identify the source but are not
guaranteed to deep-link into a reader.

## Automatic local loading

The finished drive contains:

```text
SEARCH/
├── search.js
├── manifest.js
├── coverage.json
└── chunks/<index-sha256>/
    ├── 00000000.js
    ├── 00000001.js
    └── ...
```

Both entry pages load `SEARCH/search.js` as an ordinary deferred script. The
runtime loads `manifest.js`, then requests only the chunk files needed for index
headers, lexicon lookups, postings, and results. Each script supplies a bounded
base64 payload through a registration callback. The final chunk may be shorter
than 1 MiB. The manifest fixes the index identity, decoded size, and chunk count;
the runtime rejects mismatched generations, IDs, sizes, and malformed payloads.
Decoded chunks are retained in an eight-entry least-recently-used cache. The
reader can assemble small ranges crossing a chunk boundary.

The transport uses classic script loading because browsers commonly restrict
`fetch()` of neighboring `file://` data. It needs no `fetch`, XMLHttpRequest,
JavaScript modules, service worker, file picker, or local server. The entry pages'
Content Security Policy permits local script files and prohibits network
connections. No source document or archive is scanned when someone types a query.

A fresh completed library contains the chunked output, not a second standalone
binary index. The binary OWLIDX2 layout below describes the decoded byte stream.
Chunk generation and the manifest are covered by the drive's checksum manifest.
Updates retain previously managed search files rather than automatically deleting
them; the new manifest selects only the current generation. Allow room for
retained generations or build into a fresh dedicated destination.

Very large Wikipedia indexes and common-word searches have not been benchmarked
at production scale with this transport. Small local chunks avoid a single huge
file read, but loading many chunks can still be slow and consume browser memory.

## Platforms and testing

| Platform | Expected behavior |
| --- | --- |
| Windows, macOS, Linux, Raspberry Pi desktop | Use a full browser that permits local JavaScript and neighboring classic script files. File permissions and local policy can still prevent use; test the chosen browser. |
| Android / Pixel | Browser and file-manager dependent. Some viewers disable scripts or expose only a single document without access to neighboring files. Test your exact combination. |
| iPhone / iPad | Files/Quick Look commonly previews local HTML without the needed JavaScript/browser access. Direct search is not guaranteed. Use the static pages and ordinary PDF/text documents. Offline installation of Kiwix from the SSD is not assumed. |

No real-phone, drive-provider, or browser-version compatibility matrix is claimed.
Automated tests execute the actual shared JavaScript engine under Node using its
range-read contract, including BM25 ranking, Unicode, high-frequency
multi-block postings, snippets, safe links and corrupt-file rejection. Collection
tests cover exact filtered top-K ranking, overlapping illustrated textbooks,
reader/archive exclusions, and bounded flag reads across distant passage IDs.
The actual result-rendering event handler is also exercised with a minimal DOM
test double to verify that attribution notices and resource labels are rendered
as text; this does not replace a real-browser layout and local-script test. Python
tests cover HTML/TXT, real PDF/EPUB fixtures and a small real ZIM when the optional
dependency is installed. These tests do not certify a phone's external-storage
permissions or file-provider behavior. Always test the completed SSD on the actual devices
you intend to use before an emergency.

The [validation record](validation.md) distinguishes historical engine and
file-selection checks from the automatic transport. Evidence for one browser or
headless fixture does not establish compatibility with an in-app preview or a
physical phone. If HTML links or local scripts are unavailable, browse the SSD's
folders and open ordinary PDF or text files with a compatible viewer.

## Durable file format: OWLIDX2

All integer records use little endian. The first 4,096 bytes are reserved for a
header: eight-byte `OWLIDX2\n` magic, a uint32 JSON length, then UTF-8 JSON. The
header includes document/term counts, average weighted length, offset-table
locations, tokenizer identity, and final file size. It has no timestamps.

Document records are variable-length UTF-8 JSON. Their table contains one
`uint64 offset, uint32 length` pair per passage ID. Immediately after that table,
`flags_offset` locates one byte per passage: bit 0 means textbook and bit 1 means
illustrated guide; both bits may be set. Other bits are reserved and rejected.
Each term has a contiguous
posting list of `uint32 passage_id, uint32 weighted_frequency, uint32 length`
records ordered by passage ID. Lexicon records are JSON arrays
`[term, posting_offset, posting_count]`, sorted by UTF-8 bytes; a second fixed-width
offset table permits random-access binary search. The browser validates ranges
before reading and refuses any individual read over 1 MiB. The format supports
up to 2^32 passages and browser-safe integer byte offsets (below 2^53).

The Python source and readable JavaScript are the format reference. SQLite is
only a build-time implementation detail. SHA-256 verification covers the
finished chunk scripts and manifest alongside the other managed drive files.
Keep `START_HERE.html`, `SEARCH.html`, and `SEARCH/` from the same completed build;
an index with a different format is rejected with instructions to rebuild the drive.

Extractor API references: [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[python-libzim reader API](https://python-libzim.readthedocs.io/en/latest/api_reference/libzim.reader/),
and [python-libzim's reader type stubs](https://github.com/openzim/python-libzim/blob/main/libzim/reader.pyi).
The Python binding currently exposes numeric entry iteration through
`_get_entry_by_id`; OWL pins the supported major version and tests this with a real
archive. Upgrading that dependency requires re-running the archive test.
