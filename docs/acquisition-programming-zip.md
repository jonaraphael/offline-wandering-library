# Python and SQLite build-time package recipes

Prepared from temporary publisher archives already acquired before the user
clarified link/catalog-only scope. Preparing these recipes performed local reads
and metadata writes only: no additional network calls, resource-body downloads,
real-content extraction, drive builds or SSD writes. Synthetic tests exercise the
future build behavior without real library content.

The portable fragment is
[`catalog/acquisition/programming-zip-members.yaml`](../catalog/acquisition/programming-zip-members.yaml).
It contains the two source ZIPs and every one of their 1,655 ordinary output files.
The parent collection remains **partial**: these packages complete the bounded
Python/SQLite documentation additions, not the whole Linux/programming collection.

| Package | ZIP download | Expanded files | Expanded bytes | Reading documents | Supporting members |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python 3.14.7 publisher documentation build | 12,857,046 B | 628 | 67,588,241 B | 538 | 90 |
| SQLite 3.53.4 documentation | 11,820,412 B | 1,027 | 37,345,103 B | 835 | 192 |
| Total | 24,677,458 B | 1,655 | 104,933,344 B | 1,373 | 282 |

Keeping source ZIPs and outputs requires 129,610,802 content bytes before search,
generated navigation and reserve. The 1,373 documents are HTML pages with original
publisher `<title>` text, prefixed by Python or SQLite. Redirect pages without titles,
generated Python alphabetical/module/search/help pages, and non-HTML package files
remain reachable on disk but do not clutter reading navigation or full-text search.

## Sources and reproducibility

- [Python publisher documentation ZIP](https://docs.python.org/3/archives/python-3.14-docs-html.zip):
  SHA-256 `f0945099f00a6b078e0101b8a7bee14364698f8ecce4bb1a26d5c2e47c8203cf`.
  The inspected HTML identifies Python 3.14.7. This URL follows the release line and
  can change. No immutable archive URL was established by the saved evidence.
  A future changed response must fail the pin; refresh the source and complete
  member manifest together after review.
- [SQLite publisher documentation ZIP](https://www.sqlite.org/2026/sqlite-doc-3530400.zip):
  SHA-256 `a1d0f5de57485d062796ed7e67daff0758b50d00001a0f233a2c15aaf40bbdc8`.
  Its versioned source URL identifies 3.53.4.

The fragment retains publisher archives, original file bytes, exact relative
structure and all shipped copyright/license pages. Python's documented PSF/historical
notices and example-code terms remain in the package; SQLite's public-domain
documentation notices remain in its package. Bundled third-party assets keep their
own included licenses and notices; Python's PSF terms do not relabel those assets.
Linked third-party content keeps its own rights and is not pulled into this recipe.

Each source ZIP was rehashed and audited locally with the new bounded reader. Each
manifest member was compared to its original bytes for size and SHA-256. This
verified exact package coverage without unpacking a new copy. The existing earlier
offline browser evidence covers representative pages and local dependencies, not
every hyperlink or every page in both packages.

## Future build and remaining limits

Select both source IDs and all member IDs under `linux-programming-docs`. The new
[archive extraction contract](archive-extraction.md) makes a future build download
each ZIP once, verify it, and produce directly readable files with independent pins.
Useful entry points will be:

- `REFERENCE/COMPUTING/python-3.14-docs-html/index.html`
- `REFERENCE/COMPUTING/sqlite-doc-3530400/index.html`

Source archives, CSS/JavaScript/images and other support files stay in inventory and
verification while reading navigation and search include substantive HTML documents.
The fragment is portable HTTPS metadata; it has no `file:` URLs or dependency on the
temporary evidence directory. It does not require a browser or Python process for
reading the static documentation after a build.

The publisher HTML is preserved unchanged. Optional analytics, online feedback and
search links remain external; Python's 404 page references online resources, and
SQLite's `whynotgit.html` references an external XKCD cartoon. Core technical pages
retain the package's local CSS, JavaScript and illustrations. This is a full manifest
of the publisher ZIPs, not a claim that external websites linked by them are offline.

Still outside this package completion: verified OpenBSD 7.9 ssh-keygen, sftp-server,
ssh-keyscan and ssh-keysign pages, automatic rendering of the complete OpenSSH 10.5p1
manual sources, and local closure of external cross-references/cosmetic resources
on the selected systemd/OpenBSD/Debian pages. Per-file source/notice accompaniment
for separately pinned man-page PDFs/HTML remains absent where redistribution is
unverified. A real authorized drive build with whole-package link and offline smoke
checks remains future work.
