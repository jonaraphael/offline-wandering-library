# Complete source-review trial for Stack Overflow

The four publisher archives are captured once with
`catalog/acquisition/stackoverflow-capture.json`. Capture verifies the frozen
publisher checksums and records complete SHA-256 values. It remains separate
from the production library and does not approve content.

After capture completes, expose the local 7-Zip executable to the command and
inspect the actual archive inventories:

```sh
PATH="$PWD/.owl/tools/sevenzip-26.03:$PATH" .venv/bin/python scripts/prepare_stackoverflow.py inspect \
  --staging-root "$STAGING_ROOT" --output .owl/acquisition/stackoverflow-inspection.json
```

Inspection requires all four capture receipts, verifies the whole archives,
and confirms exactly one expected XML member per archive. It records measured
XML bytes, finite per-member timeouts, and source/allowlist identities. It
does not extract. Allocate a phase budget only after comparing these measured
bytes, scratch, retained previews, reserve, and other concurrent work with the
shared drive's free space.

`prepare_stackoverflow.py expand` requires explicit `--expanded-bytes`,
`--scratch-bytes`, `--preview-bytes`, `--budget-bytes`, and `--reserve-bytes`.
The total includes the captured archives and bounded control metadata. The
command keeps one independently owned expansion under
`previews/stackoverflow-shared-xml-v1/expanded/`, records per-member whole-file
hashes, checks free space before every write, and resumes completed members.
The expanded byte allowance includes 131072 control bytes per archive.

Use `prepare_stackoverflow.py select --shared-expansion PATH --cache-dir PATH
--output PATH` to produce deterministic, bounded candidate metadata from those
verified XML files. The default is at most 100000 scored candidates and 100000
ambiguous-version review records. Candidate limits are explicit trial bounds;
they never imply full collection coverage or fulfillment of its content target.
Metadata caches avoid reparsing unchanged sources; whole-file pin verification
still runs. Age alone never determines legacy classification.

Each durable or legacy `acquire_content.py preview` uses
`--shared-expansion PATH` pointing to the shared `expanded-receipt.json` and
the exact frozen `build_input_extractions` recorded there. Preview and review
verify ownership, source receipts, allowlists, and all XML hashes before reuse.
They retain no second XML copy. Their expanded/scratch/output phase allowances
must cover all retained sibling previews.

Corpus transformation/checkpoint version 2 preserves every distinct publisher
duplicate edge. It resolves only selected question chains. Unrelated ambiguity
does not block generation; selected multiple-target or cyclic chains remain
explicit review blockers with affected IDs and targets. No target is silently
chosen. Reviewed selection, per-post attribution and licenses, illustrations,
comments, complete static output review, and content-target accounting remain
required before admission or a claim of complete coverage.

The actual canonical question is classified again using the frozen selection
rules. A durable selection that resolves to an explicitly legacy or ambiguous
version question is blocked with its canonical ID and classification reasons;
it requires recorded review and reclassification before an output can be frozen.
