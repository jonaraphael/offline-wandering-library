# Programming documentation: metadata handoff

Prepared 2026-09-19 UTC. The user clarified that this pass should resolve links and
catalog/build-time acquisition, not download library content yet. Temporary
acquisitions had already occurred before that clarification. Acquisition stopped;
the existing temporary files were preserved as verification evidence. **No SSD
writes, library build, or shared-catalog changes were performed by this worker.**

The proposed fragment is
[`catalog/acquisition/hour-programming.yaml`](../catalog/acquisition/hour-programming.yaml).
It contains **50 ordinary-file records, 13,124,479 bytes**, and separately records
four archive inputs. All proposed active URLs are HTTPS; no temporary `file:` URLs
are proposed as portable assets. The parent resource remains **partial**.

The subsequent local-only implementation adds a separate complete Python/SQLite
recipe in [`programming-zip-members.yaml`](../catalog/acquisition/programming-zip-members.yaml).
It contains two ZIP inputs and all 1,655 output-member pins, including 1,373 substantive
HTML reading documents and 282 supporting members. The normal builder now supports
verified build-time extraction and hides dependencies from search/navigation while
preserving them in inventory/checksums. This adds 24,677,458 download bytes and
104,933,344 expanded bytes to a future selected build. No real-content build was run.
See [package details and remaining limits](acquisition-programming-zip.md).

| Added portable records | Count | Scope |
| --- | ---: | --- |
| Linux man-pages 6.19 | 1 | Canonical 4,118-page publisher PDF |
| systemd 259.6 | 20 | Service/unit/journal/network administration and configuration manuals |
| Linux networking/filesystem commands | 13 | ip, ss, ping, mount, umount, lsblk, findmnt, fsck, blkid, fdisk, e2fsck, mke2fs, tune2fs |
| OpenSSH/OpenBSD 7.9 | 8 | ssh, sshd, client/server configuration, agent/add, sftp and scp |
| Original license companions | 8 | Upstream/package notices and applicable license texts |

The existing ten programming manuals are retained in the proposed resource
membership. Downloaded bodies were hashed completely; existing evidence, rather
than new requests after the clarification, supplies the exact sizes and SHA-256s.
Publisher URLs that change in place must fail against these pins rather than
silently updating the documents.

## Source and verification details

The [Linux man-pages book directory](https://www.kernel.org/pub/linux/docs/man-pages/book/)
publishes the canonical 6.19 PDF and a whole-file SHA-256. The downloaded PDF
matched `cba8dda2b7cb0cbe732cb31538d1a37abb201d45b752b36bc2df6a3d9c00fffa`.
PDF structure, complete extracted text, title page and a middle technical
table/code page were checked; this is not visual review of all 4,118 pages.
The separate source archive retains individual page notices and the project's
mixed license texts, but remains a `source_inputs` record and is not part of the
active build. The PDF points readers to the source headers for authorship and
copyright. Its `redistributable: false` flag therefore remains conservative until
those source/notices are an actual delivered dependency. A single uniform license
is not assigned to the book.

The [systemd versioned manuals](https://www.freedesktop.org/software/systemd/man/259/systemctl.html)
all identify themselves as **259.6**, despite the major-version URL. Their bodies,
inline styling and technical material are static. Optional jQuery and navigation
scripts remain remote/missing when opened locally, and references to unselected
manuals remain. The accompanying general source license files are from tag
**v259**, explicitly not represented as v259.6 source files.

The [Debian stable manual service](https://manpages.debian.org/trixie/iproute2/ip.8.en.html)
provides complete rendered upstream manuals with exact package versions in their
footers: iproute2 6.15.0-1, iputils-ping 3:20240905-3, util-linux/mount/fdisk 2.41-5,
and e2fsprogs 1.47.2-3+b11. These are distribution-release manuals, not generic
unversioned development documentation. Copyright companions were acquired for
iproute2, iputils and e2fsprogs; util-linux's tagged upstream licensing overview
was acquired when the exact Debian metadata URL returned 404. The overview lists possible
project licenses, not each manual's copyright and permission notice. The seven
util-linux-family manuals (mount, umount, lsblk, findmnt, fsck, blkid and fdisk)
therefore have `redistributable: false` until matching file-specific notices or
source companions are delivered. Personal offline acquisition remains possible.
Preserve individual notices and source/license companions when distributing.

[OpenSSH's manual index](https://www.openssh.org/manual.html) points by default to
development manuals. This fragment instead pins successful **OpenBSD 7.9**
release-manual URLs. ssh-keygen, sftp-server, ssh-keyscan and ssh-keysign timed out
twice and were not admitted as verified file records. The eight HTML manuals
retain their author sections, but complete release-matched copyright preservation
was not established for this rendered subset; their conservative
`redistributable: false` flag does not prohibit personal offline acquisition.

An isolated Chrome session with network disabled opened nine representative
files through `file://`: systemctl, bootup, ssh, mount, ip, Python control flow,
Python sqlite3, SQLite SELECT and SQLite CLI. All contained substantial readable
document text and no page-script errors. SQLite's SQL syntax diagram and Python's
styled tutorial were visually checked. Failures were recorded rather than hidden:
systemd's optional scripts, OpenBSD's stylesheet, Debian's decorative logo and
online-search links, and Python's analytics request. This does not claim zero
network attempts, complete cross-reference closure, or phone compatibility.

## Archive inputs and supported ZIP package recipes

The fragment's **`source_inputs`** section is separate from **`assets`** and must
not be merged by itself as if archives already satisfy ordinary-file reading.
Python and SQLite now have a separate complete source-plus-member recipe supported
by the builder. The OpenSSH and Linux source tar inputs remain evidence-only;
automatic tar extraction/rendering has not been implemented.

| Input | Exact bytes | Existing temporary inspection |
| --- | ---: | --- |
| Python HTML documentation, 3.14.7 | 12,857,046 | 628 extracted files, 67,588,241 bytes; 579 HTML files |
| SQLite documentation, 3.53.4 | 11,820,412 | 1,027 extracted files, 37,345,103 bytes; 837 HTML files |
| OpenSSH portable 10.5p1 source | 2,333,659 | All 15 principal release manuals and original sources/notices available |
| Linux man-pages 6.19 source | 1,908,136 | Per-page source notices and LICENSES directory available |

[Python's official download page](https://docs.python.org/3/download.html) supplies
the HTML archive. Its existing extracted files passed path traversal, symlink,
case-collision and size checks and have per-file hashes. Ordinary technical pages
had their active local dependencies; the web-only 404 page retains absolute
website paths, and analytics/version links remain online. The original bundle
was not rewritten.

[SQLite's download page](https://www.sqlite.org/download.html) supplies a static
HTML bundle whose downloaded SHA3-256 matched the publisher's value, independently
of the newly computed SHA-256 pin. The inspected bundle had no missing local
HTML image/script/style dependencies. It contains one external cartoon in
`whynotgit.html`; the technical SELECT and CLI pages rendered offline with no
failed requests. Do not generalize the SQLite public-domain statement to that
linked third-party cartoon.

The [official OpenSSH portable release](https://www.openssh.org/portable.html)
contains 15 principal manual sources and preformatted originals. Before the
clarification, a temporary experiment rendered all 15 sources with the local
`mandoc`, retained each complete original manual source, and linked the original
release license. Those 31 local files are **supplementary evidence**, not portable
catalog assets or an implemented build-time transformation. They are a separate
10.5p1 edition and must not be mislabeled as the OpenBSD 7.9 HTML set.

The implemented ZIP recipe verifies source and output pins, rejects unsafe
paths/links and excessive expansion, retains complete directory structure/notices,
and integrates ordinary-file navigation/search. Meaningful synthetic tests cover
extraction, interruption/reuse, corrupt pins and CRCs, path/link/collision limits,
external cache accounting, locked rebuilds and subsequent atlas publication.
The two preserved publisher ZIPs also pass read-only source/member audits. Python
documentation terms do not relabel bundled third-party assets: their own included
licenses/notices are retained. The mutable Python archive URL fails safely when
the publisher replaces it; a complete reviewed repin is then required.

## Remaining gap and handoff

Keep `linux-programming-docs` **partial**. The four OpenBSD 7.9 manuals ssh-keygen,
sftp-server, ssh-keyscan and ssh-keysign still lack verified records, and selected
systemd/OpenBSD/Debian pages retain external cross-references or cosmetic resources.
The complete OpenSSH 10.5p1 source-to-HTML experiment remains evidence only.
Python/SQLite packaging is now build-supported, but a complete offline-navigation
audit and an authorized real-content build remain future verification work.
No restricted POSIX publication was introduced.

All temporary evidence remains under `/tmp/owl-one-hour/programming`, including
`download-log.json`, archive member/hash manifests, `html-dependency-report.json`,
`offline-check.json`, screenshots and the original files. The later failed
systemd patch-tag license lookup is recorded in the raw log; the proposed fragment
correctly references the earlier successful v259 license downloads. Nothing was
deleted or copied to the SSD. No further source requests were made after the
metadata-only clarification.

Independent local review matched all 50 admitted records against the preserved
temporary bodies by exact length and SHA-256. Linux man-pages and the seven
util-linux-family redistribution flags were corrected as described above; no new
network requests, body acquisition, shared-catalog edits or library build occurred.
