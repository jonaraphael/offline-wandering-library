# Offline full-text search

Open `SEARCH.html` in a browser, choose `SEARCH/library.owl` using the file picker,
and enter search words. Selection grants the page access to that file. The page
does not fetch neighboring files, use a server, execute archive readers, or make
network requests. It contains its own script and styles. If your viewer does not
execute JavaScript or offer a usable picker, use `INDEX/categories.html`,
`INDEX/critical.html`, and the alphabetical pages instead.

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

A temporary SQLite database sorts the inverted index on disk. It uses a 16 MiB
page-cache budget; neither the corpus nor the vocabulary is collected into one
Python list. Ordinary text, HTML and EPUB members stream in bounded chunks.
`pypdf` and `libzim` have their own working memory requirements: a complex PDF
page or decompressed ZIM cluster can still consume substantial memory. The ZIM
entry-size guard prevents allocating entries known to exceed 64 MiB, but is not
a hard process-memory limit. Use a computer with adequate RAM and scratch space
for large builds, preferably with scratch on a fast local SSD.

Full Wikipedia indexing may take many hours or days and considerable temporary
storage. The final index duplicates extracted text and adds postings; it can be
larger than the compressed source archive. Profile space budgets are planning
allowances, not measured bounds. A corpus containing highly compressible data
can exceed any fixed source-size multiplier. Keep additional space available and
check the actual build. An interrupted index build is rebuilt from the existing,
verified content; index construction itself does not resume. The old final index
remains until its replacement is complete.

The builder reports each asset's start and completion, including extraction
warnings, and reports major index-writing stages. During extraction it checks
progress every 1,000 passages and prints at most every five seconds; posting-list
and lexicon output are also periodically reported. One unusually slow PDF page
can still delay progress while the extraction library processes that page.

## Browser queries

Tokens are Unicode letters/numbers, normalized with NFKC and lowercased. There is
no stemming, stop-word removal, prefix matching, quoted-phrase operator, or
language-specific segmentation. Titles receive weight 5, category and tags weight
2, and other metadata/body words weight 1. BM25 uses these weighted frequencies
and document lengths, with `k1=1.2` and `b=0.75`. IDF is computed over passages.
Queries consider passages matching any query word. Use up to 32 distinct words;
longer queries are rejected with an explanation.

The browser binary-searches the sorted lexicon using `File.slice()`. For each
query word it streams postings in blocks of at most 4,096 records (48 KiB).
Sorted posting lists are merged and scored, retaining only the best 50 results
in a bounded heap. This is exact top-K ranking for the implemented query model,
not a fixed candidate cutoff that loses later matches. Only those result records
are read for snippets. It never loads the entire index or scans the corpus text.
Memory for postings is at most approximately 1.5 MiB for 32 query words, plus the
small lexicon cache and result records. Common words may still require reading
large posting lists, so queries can be slow on very large corpora. Progress and
cancellation remain available while processing.

Result text is assigned using DOM `textContent`; imported snippets are never
interpreted as HTML. Links are validated as relative paths. PDF links include
`#page=N` where supported. ZIM results provide the archive location and internal
article title/path; there is no portable file URL that opens an individual ZIM
article in an arbitrary reader. Open the archive in the bundled reader and locate
the article there. EPUB chapter names likewise identify the source but are not
guaranteed to deep-link into a reader.

## Platforms and testing

| Platform | Expected behavior |
| --- | --- |
| Windows, macOS, Linux, Raspberry Pi desktop | Modern Chrome/Chromium, Edge, Firefox and Safari expose the required File API when the page is opened in a full browser. File permissions and local policy can still prevent use. |
| Android / Pixel | Browser and file-manager dependent. Some viewers disable scripts, cannot launch local HTML in a full browser, or copy the chosen index into internal storage. Test your exact combination. |
| iPhone / iPad | Files/Quick Look commonly previews local HTML without the needed JavaScript/browser access. Direct search is not guaranteed. Use the static pages and ordinary PDF/text documents. Offline installation of Kiwix from the SSD is not assumed. |

No real-phone, drive-provider, or browser-version compatibility matrix is claimed.
Automated tests execute the actual page's JavaScript engine under Node using the
same Blob range-read contract, including BM25 ranking, Unicode, high-frequency
multi-block postings, snippets, safe links and corrupt-file rejection. Python
tests cover HTML/TXT, real PDF/EPUB fixtures and a small real ZIM when the optional
dependency is installed. These tests do not simulate an operating system's
external-drive file picker. Always test the completed SSD on the actual devices
you intend to use before an emergency.

A direct local-page smoke test was also attempted during development, but the
available automated browser's URL policy blocks `file://` navigation. That
restriction was not bypassed; the automated evidence remains the cross-language
engine and extraction tests above.

## Durable file format: OWLIDX1

All integer records use little endian. The first 4,096 bytes are reserved for a
header: eight-byte `OWLIDX1\n` magic, a uint32 JSON length, then UTF-8 JSON. The
header includes document/term counts, average weighted length, offset-table
locations, tokenizer identity, and final file size. It has no timestamps.

Document records are variable-length UTF-8 JSON. Their table contains one
`uint64 offset, uint32 length` pair per passage ID. Each term has a contiguous
posting list of `uint32 passage_id, uint32 weighted_frequency, uint32 length`
records ordered by passage ID. Lexicon records are JSON arrays
`[term, posting_offset, posting_count]`, sorted by UTF-8 bytes; a second fixed-width
offset table permits random-access binary search. The browser validates ranges
before reading and refuses any individual read over 1 MiB. The format supports
up to 2^32 passages and browser-safe integer byte offsets (below 2^53).

The Python source and readable JavaScript are the format reference. SQLite is
only a build-time implementation detail. SHA-256 verification covers the
finished index alongside the other managed drive files.

Extractor API references: [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[python-libzim reader API](https://python-libzim.readthedocs.io/en/latest/api_reference/libzim.reader/),
and [python-libzim's reader type stubs](https://github.com/openzim/python-libzim/blob/main/libzim/reader.pyi).
The Python binding currently exposes numeric entry iteration through
`_get_entry_by_id`; OWL pins the supported major version and tests this with a real
archive. Upgrading that dependency requires re-running the archive test.
