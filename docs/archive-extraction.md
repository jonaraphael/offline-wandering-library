# Pinned ZIP documentation packages

The normal drive builder can fetch a pinned publisher ZIP once and unpack reviewed,
individually pinned members into ordinary readable files. This capability runs only
during a requested future build; creating or validating a recipe does not acquire
content. Tests use tiny synthetic local archives.

## Catalog contract

The source is an ordinary resolved asset with `format: zip`, exact `size_bytes` and
`sha256`, and `supporting_file: true`. Each output is another resolved asset with its
own destination, exact uncompressed size and SHA-256, and this additional mapping:

```yaml
archive_member:
  source_asset_id: docs_example_zip
  path: example-docs/index.html
  document: true
```

Member `source_url` and `mirrors` must exactly match the source asset; they identify
the publisher ZIP, not a separate request for each output. A member is never
downloaded directly. Archive members may have a zero-byte size if that exact empty
file is pinned. Ordinary downloaded assets must still have positive sizes.

Use `document: false` and `supporting_file: true` for CSS, JavaScript, images used by
pages, font/data files, redirects and auxiliary navigation pages. These dependencies
remain in machine inventory, locked catalog, checksum verification and drive copy.
They do not become titles in reading navigation, full-text search, atlas routes or
learning-coverage counts. A substantive image intended to be a standalone reading
item can instead be explicitly reviewed as a document. Source ZIPs are dependencies,
not independent reading entries.

Select the source ZIP and every needed member in the same resource. Omission of a
member's source fails selection/planning before files are written. The builder
orders ZIP sources before members regardless of profile priority. It does not
silently reverse an explicit source exclusion. Each catalog fragment must include
its source records so it can validate independently; a source existing only in a
separate base catalog is insufficient for a member-only `--extra-catalog`.

For a complete publisher package, retain every member and the original directory
structure, including notices, indexes and dependencies. For example,
`example-docs/index.html` and `example-docs/style.css` become
`REFERENCE/COMPUTING/example-docs/index.html` and
`REFERENCE/COMPUTING/example-docs/style.css`. The destination is always the explicit
reviewed catalog path, never a path selected implicitly from untrusted ZIP contents.
Package completeness is a manifest-review responsibility; this feature does not
discover missing assets on the web or change collection status automatically.

## Safety, storage and restart behavior

The source and each output are independently size- and SHA-256-checked. Source
identity is checked while an open source is reused for multiple members. A bounded
central-directory preflight runs before ZIP metadata allocation, followed by an
audit of every entry, including entries not selected for extraction.

Only ordinary single-disk ZIPs with stored or deflated regular files are supported.
The reader rejects traversal, absolute and nonportable paths, ambiguous casing,
duplicate paths, file/directory conflicts, symlinks and special files, encryption,
ZIP64 end records, split archives, and prefixed self-extracting wrappers. Limits are
128 MiB compressed input, 20,000 entries, 64 MiB per file, 512 MiB total expanded
size, and a 1,000:1 member compression ratio. These conservative limits cover the
reviewed Python and SQLite packages; larger archives require a separate reviewed
design or ordinary assets.

Members stream into builder-owned partial files on the destination filesystem.
Output is promoted only after ZIP CRC, exact byte count, SHA-256 and readback checks.
No archive code is executed. Interrupted member extraction restarts that member;
completed files use the normal verified reuse path. Search checkpoints and locked
catalog rebuilds use the same document selection. Standalone atlas rebuilds keep
dependencies hidden and accept valid empty members.

Capacity planning counts the retained ZIP and all expanded files as disk content,
but only ZIP bytes as downloads. Supporting bytes are reported separately and do
not inflate pinned knowledge or directly readable byte totals. With an external
download cache, only the ZIP is staged there; extracted outputs stay on the target.
The normal root lock, ownership checks, mount guards and checksum publication still
apply. Neither rebuilding nor changing selection deletes unrelated or older files.

## Current package recipes

`catalog/acquisition/programming-zip-members.yaml` contains full Python and SQLite
packages prepared from already-preserved publisher bytes. See
[the package acquisition note](acquisition-programming-zip.md). Activate complete
packages through resource membership; they are not direct-edition declarations.
The direct-edition registry currently requires ordinary document formats for every
record, so it does not accept a ZIP dependency.

When an upstream moving URL changes, the old pin fails safely. Review the new
publisher package, regenerate and review every member pin and title, preserve
notices, and update the source and member records together. Do not weaken hash
checks or silently accept a newer archive under an older manifest.
