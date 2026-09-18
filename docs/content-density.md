# Useful content within a real drive budget

Every preset starts with the same acquired ordinary-format foundation: medical
and WASH manuals, food preservation, agriculture, shelter, navigation, 20 complete
OpenStax math/science textbooks, two electrical textbooks, Pro Git, illustrated
children's EPUBs and practical computing manuals. Critical documents remain PDFs
or HTML. Original figures and photographs are preserved.

The small presets are exact file selections. The larger presets use named
collections and explicit `default_editions`. These select real, SHA-256-pinned
archive editions where direct-file curation is still unfinished. An explicit
`--edition RESOURCE=published|direct|compact` overrides the preset; inclusion and
exclusion still work. Selection locks preserve the chosen edition independently
of future defaults.

| Preset | Pinned sources, including readers | Planning peak, including scratch and reserve |
| --- | ---: | ---: |
| 16 GB | 9.696 GB | 15.713 GB |
| 64 GB | 40.273 GB | 58.289 GB |
| 256 GB | 195.141 GB | 240.939 GB |
| 512 GB | 261.614 GB | 462.342 GB |
| 1 TB | 393.589 GB | 925.969 GB |

Decimal GB are used throughout. The last three planning peaks reserve space for
still-unresolved collection scope; their numbers are **not** acquired byte totals.
Optional caches duplicate sources and are additional, as are retained old
versions. A build on a small drive should omit `--cache-dir`; its default in-place
partials already resume. Full-sized index measurements for the larger presets
are still outstanding.

The 16 GB selection supplements the foundation with WikEM, iFixit, Appropedia,
CD3WD and Low-tech Magazine. The 64 GB version adds WikiMed, the eight LibreTexts
STEM libraries, Wikibooks, Wiktionary, Wikiversity, Wikivoyage and World Factbook.
Their four bundled readers cover Windows, Linux, macOS and Android. Ordinary
medical PDFs remain usable on an iPhone without Kiwix.

The 256 GB preset now reaches its 190–210 GB source target. It includes full
illustrated English Wikipedia, four Gutenberg nonfiction classes and Gutenberg
juvenile literature alongside the foundation. Standard adds twelve practical
Stack Exchange sites; full also includes mathematics, physics, biology and
chemistry. Historical Gutenberg books and community answers are references,
not reviewed current clinical protocols. Their classifications select published
collections, not question-level safety or quality ratings.

The 512 GB and 1 TB presets still lack enough acquired content to meet their
390–420 GB and 750–820 GB targets. Survivor's checked category ZIP links returned
404, but individual PDF downloads work; title curation and complete-file hashes
remain unfinished. Durable Stack Overflow filtering, Khan STEM-only acquisition,
local topo selection and curated direct exports remain unfinished. OWL neither
adds unrelated languages/videos as filler nor counts those missing collections
as present. See [source evidence](acquisition-enrichment.md).

The selector leads with real downloadable knowledge bytes, shows readers
separately, and identifies unresolved space. A default selection below its
minimum knowledge target cannot complete without explicit `--allow-incomplete`.
User-customized smaller selections bypass this editorial floor. The build still
records any incomplete collection scopes. Tests protect minimum useful bytes,
medical/textbook coverage, nested small presets, inclusion/exclusion, exact
edition locks and nominal in-place planning peaks.

Search uses independently compressed text records and delta-coded postings.
Whitespace from source layout is normalized for indexing; the original illustrated
documents stay intact. A verified, durable raw-index checkpoint permits extraction
files to be removed before browser packaging, reducing peak temporary space.
The in-place peak reserves raw assembly plus the larger of extraction workspace
or published search output, rather than adding both nonconcurrent phases.

Published search output and temporary raw-index writes have explicit byte
limits. Extraction work and free-space reserves are checked at checkpoints;
SQLite transactions can grow between checks, so this is not a filesystem quota.
An exceeded allowance stops the build with resumable checkpoints. Increasing an
allowance still requires a plan that fits the device; the builder does not move
work onto the computer or silently skip selected text.
