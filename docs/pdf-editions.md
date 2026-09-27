# PDF reading editions

The reading collection should open with the PDF support already available on a
phone or computer. It must not require downloading an EPUB reader before an
offline trip. On iPhone, browse to a PDF in Files and open it; if an app chooser
appears, use **Preview with Quick Look**.

Use a matching publisher PDF when it preserves the selected title, language,
illustrations and scope. When that edition is unavailable, a reviewed conversion
can produce an ordinary PDF from a pinned EPUB. Keep the source EPUB on the
external drive under `LIBRARY/REFERENCE/SOURCE_PACKAGES/EPUB/`; it is a build input,
excluded from reading shelves and search. The PDF belongs in the book's reading folder.

PDF pages have fixed layouts. Text remains searchable and illustrations remain
embedded, but readers may need to zoom instead of changing an EPUB font size.
An HTML start page still cannot overcome iPhone Files' restrictions on scripting
or local HTML links; its inline catalog supplies the paths to open manually.

## Included editions

All production presets include 61 Book Dash PDF editions: 38 English, 16 isiXhosa
and seven French editions. These preserve the selected publisher EPUBs' complete
text, illustrations and credits. They are OWL format adaptations, not publisher
PDFs. Each original EPUB stays on the external drive as the pinned supporting
source; source bytes are never copied to the build computer.

The Python documentation collection instead uses all 37 original PDFs from the
[publisher's Python 3.14.0 archive](https://www.python.org/ftp/python/doc/3.14.0/python-3.14.0-docs-pdf-a4.zip),
dated **October 7, 2025**. These are extracted unchanged from the pinned ZIP.
Read them under `LIBRARY/REFERENCE/COMPUTING/PYTHON_PDF/`; `library.pdf` is the
Library Reference. The source ZIP stays under
`LIBRARY/REFERENCE/SOURCE_PACKAGES/PYTHON/`.
The newer September 2026 EPUB snapshot is retained separately as a supporting
source package. It was not converted into these PDFs, and the PDF collection
does not claim the newer snapshot's coverage. Titles and inventory metadata
identify the older stable release explicitly.

## Building a converted edition

Install the build-time renderer with `python -m pip install -e '.[zim,pdf]'`.
The finished PDFs need none of these Python dependencies. Sources, download
partials, conversion outputs and any page previews stay on the external drive.
The repository may retain metadata and generated search indexes.

Each converted PDF has its own `epub_pdf` acquisition recipe, pinned source hash,
renderer version, layout policy and output hash. Selecting or rebuilding one
book does not force conversion of the rest. A matching output is reused; an
unexpected output hash stops the build. Search uses the normal per-asset index
cache, so unchanged assets retain their extracted indexes.

The Book Dash recipes pin PyMuPDF/MuPDF 1.28.2, a 600 by 800 point layout at
fontsize 16, and `bookdash-pages-v1`. That policy groups each existing illustration
with its following story paragraphs in memory and starts the next illustration
on a new page. Longer text can continue onto another page. It keeps the original
credits and a proportional publisher logo. An image-only cover is cropped to its
complete illustration only when the cover has exactly one page and one image.
The original ZIP remains unchanged. Book Dash recipes permit no renderer warnings.

Before approving new output pins, check every spine chapter, source text,
embedded illustrations, bookmarks and page bounds. Render representative pages
including covers, credits, tables and code, and compare two independent
conversions for identical hashes. A successful conversion command alone does not
establish complete content or readable layout. Document any fixed, reviewed
renderer diagnostic exception instead of ignoring warnings generally.
When reviewing cropped covers with Poppler, use `pdftoppm -cropbox`; its default
MediaBox rendering includes the original page margins outside the visible CropBox.

Preserve the original publisher and creator credits and license. Mark the format
adaptation in edition metadata without changing the work's title or implying the
publisher authored the converted PDF. Converted PDFs also identify OWL and the
pinned renderer in their producer metadata and append a format-adaptation note
to their subject metadata.
