# Archive acquisition evidence

Checked on **2026-09-18**. [The acquisition fragment](../catalog/acquisition/archives.yaml)
contains 23 exact file records and merge instructions for 16 named resources. It
does not contain the datasets. Resource status describes the requested collection's
scope; a pinned, downloadable archive can still leave a collection partial.

For every file, the check read the dated source URL's `.meta4` document from
`https://download.kiwix.org/zim/`. The recorded size is its `file/size`; the SHA-256
is the **direct child** `file/hash[@type="sha-256"]`, which hashes the whole file.
No MD5 conversion, estimated checksum, or piece hash was used. All 23 source URLs
also returned HTTP 200 to HEAD, after Kiwix's mirror redirect, with Content-Length
equal to the Metalink size. Evidence records include the observed mirror URL and
the SHA-256 of the small metadata document itself. The latter records the research
response; mirror ordering in a later Metalink response may differ.

No large archive was downloaded to establish these pins. The builder must stream
and verify each complete download against its pinned size and SHA-256. A successful
HEAD response verifies availability and byte count, not the contents or usability
of the archive. Whole-corpus extraction and device playback have not been tested
as part of this source-resolution pass.

| Resource | Pinned edition | Exact archive bytes | Collection status |
| --- | --- | ---: | --- |
| WikEM | 2026-07, all-maxi | 374,632,362 | Ready |
| North America OSM | 2026-08 | 22,652,513,201 | Regional maps remain partial: local topography needs a location |
| CD3WD Project | 2025-11 | 581,165,229 | Partial: ordinary PDF/HTML exports remain |
| LibreTexts, eight subjects | 2025-01 and 2026-01 | 9,088,921,656 | Eight-archive baseline ready |
| English Wikiversity | 2026-05, all-maxi | 2,459,209,431 | Ready |
| English Wikivoyage | 2026-09, all-maxi | 1,071,168,673 | Ready |
| World Factbook | 2026-02 | 407,350,139 | Historical archive ready |
| English Wikisource | 2026-05, all-maxi | 19,663,666,206 | Ready |
| TED-Ed topic collection | 2026-09, multilingual | 6,380,955,947 | Partial: bounded TED topic collection |
| Spanish Wikipedia | 2026-05, all-maxi | 40,766,243,832 | Ready |
| French Wikipedia | 2026-05, all-maxi | 55,438,794,004 | Ready |
| Chinese Wikipedia | 2026-08, all-maxi | 26,601,056,121 | Ready |
| Arabic Wikipedia | 2026-05, all-maxi | 19,095,710,684 | Ready |
| Portuguese Wikipedia | 2026-05, all-maxi | 20,641,394,954 | Ready |
| Italian Wikipedia | 2026-08, all-maxi | 31,788,251,774 | Ready |
| World OSM | 2026-06 | 77,731,456,103 | Ready; replaces only North America OSM |

These are actual file sizes, not the collection planning targets. In particular,
the world map, North America map and Spanish Wikipedia exceed their old rounded
planning figures. Profiles must account for exact selected bytes, search space,
temporary build space and free-space reserve. This fragment does not select all
six optional Wikipedia languages by default.

## Rights, scope and readers

**WikEM and Wikimedia collections.** [WikEM's copyright page](https://wikem.org/wiki/WikEM:Copyrights)
specifies CC-BY-SA-4.0. [Wikimedia's terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use)
and the project policies for [Wikiversity](https://en.wikiversity.org/wiki/Wikiversity:Copyrights),
[Wikivoyage](https://en.wikivoyage.org/wiki/Wikivoyage:Copyleft) and
[Wikisource](https://en.wikisource.org/wiki/Wikisource:Copyright_policy) require
preserving applicable authorship and license notices. Individual media or source
works can have different terms. Wikisource's historical texts are not necessarily
public domain in every jurisdiction. The full illustrated Wikipedia editions are
ZIM archives, not ordinary HTML exports. Medical and travel snapshots can become
outdated; the latter's external map links do not establish offline map coverage.

**Maps.** [OpenStreetMap permits copying and distribution under ODbL](https://www.openstreetmap.org/copyright)
with attribution and applicable share-alike obligations. [Kiwix's maps2zim project](https://github.com/openzim/maps)
describes offline map archives including city search. Keep the data attribution
and all bundled software notices. These are interactive map packages requiring a
compatible JavaScript-capable ZIM reader; they are not ordinary image/PDF maps.
No routing, GPS support, universal reader compatibility or street-level
completeness is claimed. The world package replaces the North America package,
while local GeoPDF/topographic selections remain independently necessary.

**CD3WD.** The [current CD3WD Project](https://www.cd3wdproject.org/) offers free
access and encourages dissemination. Its [publication index](https://www.cd3wdproject.org/CD3WD/INDEX.HTM)
describes HTML, images and some PDFs. This pin is Kiwix's 581 MB website snapshot,
not the historical multi-DVD collection. Original publication rights vary. The
asset therefore records `redistributable: false` because a collection-wide
redistribution grant has not been established; that flag does **not** claim that
personal downloading from the offered public archive is prohibited. Personal
offline archive acquisition is resolved. The requested ordinary-file exports
remain separate work, with original credits and notices retained.

**LibreTexts.** [Publisher terms](https://libretexts.org/terms-conditions) permit
downloads consistent with the individual material's license and describe the
collection as openly licensed. There is no single CC-BY license for every page:
preserve each book/page's attribution, license and any [stacked license obligations](https://commons.libretexts.org/insight/license-stacks).
The eight pins cover biology, chemistry, engineering, geosciences, mathematics,
medicine, physics and statistics. They do not add the business, humanities or
social-science libraries. Ordinary PDF editions, where suitable, remain a
separate acquisition or export task.

**World Factbook.** CIA [discontinued the publication on February 4, 2026](https://www.cia.gov/stories/story/spotlighting-the-world-factbook-as-we-bid-a-fond-farewell/).
The pinned February 2026 Kiwix archive preserves historical information; the
edition date does not make all underlying statistics current. US government
content and retained individual credits/notices apply. This acquisition uses the
preserved Kiwix file and does not assume the retired CIA download endpoint works.

**TED-Ed.** [TED's licensing guidance](https://help.ted.com/hc/en-us/articles/360004233294-How-do-I-license-TED-or-TEDx-content)
includes TED-Ed under attribution, noncommercial and no-derivatives conditions;
the current [usage policy](https://www.ted.com/about/our-organization/our-policies-terms/ted-talks-usage-policy)
identifies CC-BY-NC-ND-4.0. Preserve intact talks, their attribution and source
links. OWL uses an already-published Kiwix archive, not a YouTube or TED.com
scraper. The pinned file is the Kiwix TED scraper's **TED-Ed topic collection**;
it is not a claim to cover every animation, lesson page or interactive exercise
on ed.ted.com. [TED's lesson FAQ](https://help.ted.com/hc/en-us/articles/360005308974-General-TED-Ed-lessons-FAQ)
also distinguishes YouTube-hosted material and its terms. Broader lesson coverage
and ordinary-file video exports are unresolved, so the resource remains partial.

All 23 files require reader software. None is marked critical, and none satisfies
a directly readable textbook or illustrated-guide requirement. No claim is made
that an iPhone without a previously installed compatible reader can open them.
