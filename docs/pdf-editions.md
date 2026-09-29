# Finished PDF editions

Use an existing publisher PDF or a faithful mirror of that original file. Active builds do not convert EPUB, HTML or source manuscripts into PDFs. The authoritative admitted types and requirements are in `src/owl/content_policy.json`.

The optional children's collection includes original illustrated Book Dash PDFs mirrored by Wikimedia Commons, with a published juvenile-literature ZIM in its own separately selectable collection. It has no title-count target. Original illustrations and credits remain unchanged; the former 61 EPUB-derived editions and their build inputs are no longer selectable.

The optional computing collection keeps the publisher's 37 Python 3.14.0 PDFs, extracted unchanged from its pinned ZIP. This does not claim the coverage of newer EPUB/HTML releases. Bash, Coreutils and Make use the publisher's finished PDFs. No generation recipe is active.

New source evidence, original failures, alternatives and coverage limits are recorded in `catalog/content-review.json`. PDF downloads were hashed and parsed; all pages of the newly admitted PDFs were rendered for a technical integrity check, with representative illustrated pages visually inspected. This is not a complete editorial review of their contents.

See [current selections](content-selection.md) for the school and practical manuals. The optional `pdf` development dependency supports historical acquisition tooling; it is not required to convert content during a current build.
