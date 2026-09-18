# Programming references and Low-tech Magazine

Verified on 2026-09-18. Exact file records and evidence are preserved in
[`catalog/acquisition/reference.yaml`](../catalog/acquisition/reference.yaml)
and incorporated into the active catalog. No downloaded content is in Git.

Ten complete official documents were downloaded and SHA-256 hashed:

| Publication | Version | Ordinary file |
| --- | --- | --- |
| Bash Reference Manual | 5.3 | Single-page HTML |
| GNU Coreutils | 9.12 | Single-page HTML |
| GNU Make | 4.4.1 | Single-page HTML |
| Using GCC | 16.2.0 | PDF, 1,241 pages |
| C Preprocessor | 16.2.0 | PDF, 90 pages |
| GNU Binary Utilities | 2.47 | PDF, 115 pages |
| GNU Linker | 2.47 | PDF, 168 pages |
| GNU C Library | 2.44 | PDF, 1,290 pages |
| Pro Git | 2.1.450 | Illustrated PDF, 501 pages |
| Python documentation | 3.14, EPUB built 2026-09-10 | EPUB, needs reader support |

These files total **41,537,243 bytes**. PDF structure, title and license pages,
EPUB structure/notices, and HTML manual text were checked. Pro Git PDF page 17 was rendered and visually checked for its labeled version-control diagram. The GNU one-page
manuals contain all their text and section links; an optional remote stylesheet
is cosmetic, so the documents remain readable without network access.

Download links came from the projects' own documentation pages:
[GNU Bash](https://www.gnu.org/software/bash/manual/),
[Coreutils](https://www.gnu.org/software/coreutils/manual/),
[Make](https://www.gnu.org/software/make/manual/),
[GCC](https://gcc.gnu.org/onlinedocs/),
[Binutils](https://sourceware.org/binutils/docs/),
[glibc](https://sourceware.org/glibc/manual/),
[Pro Git](https://git-scm.com/book/en/v2), and
[Python](https://docs.python.org/3/download.html).

GNU manuals retain GFDL notices, including invariant sections and cover texts
where specified. Pro Git is CC BY-NC-SA 3.0. Python retains PSF and historical
licenses; documentation code examples are additionally available under
Zero-Clause BSD. Mutable source URLs remain pinned to the inspected bytes;
later changes fail verification until the catalog is deliberately updated.

Resource #31 remains **partial**: Linux man-pages, SQLite, OpenSSH,
networking/filesystem utilities and systemd are not yet pinned, and Python's
direct HTML edition is not supplied. No permission for restricted POSIX
publications is invented.

The [published Kiwix Low-tech archive](https://download.kiwix.org/zim/zimit/)
`solar.lowtechmagazine.com_mul_all_2025-01.zim` is pinned at **700,555,670 bytes**.
Its whole-file SHA-256 comes from the upstream `.meta4` file; an HTTP HEAD
request independently matched the exact length. The large archive body was
not downloaded. This is a personal-use source, with `redistributable: false`
because no blanket grant for every article/image has been established.
The [publisher's offline editions](https://solar.lowtechmagazine.com/offline-reading/)
are distinct offerings; no purchase or account access is assumed.

Resource #18 remains **partial** until its requested ordinary HTML/image
edition is exported and visually reviewed. The general ZIM exporter is now
available, but dynamic Zimit pages are not guaranteed to become complete
static pages merely by removing scripts.
