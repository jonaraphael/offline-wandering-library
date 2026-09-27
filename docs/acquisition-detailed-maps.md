# Detailed New England maps for the 1 TB preset

The pending full-preset selection retains all 1,433 latest relevant US Topo 1:24,000 sheets, adds 14 explicitly historical 1:100,000 coastal supplements, and includes the all-50-state USGS national overview. The exact HEAD-verified download total is **72,124,080,891 bytes** within the new 80 GB allowance. The ordinary source-review capture reserves **72,164,924,091 bytes**, including metadata and receipts. PDFs are neither expanded nor duplicated in this accounting. Review images require a later separately reserved preview phase.

`catalog/acquisition/regional-maps-detailed-1tb.yaml` is the standalone discovery recipe, mirrored in the default pending registry `catalog/acquisition/recipes.yaml`. Default audit/discovery selects it for `full-1tb`; the original coarse recipe is limited to compact/standard allowances. `regional-maps-detailed-selection.json` freezes sheet identifiers, publisher URLs, editions, scales, extents, exact lengths and required reviews. `regional-maps-detailed-acquisition.json` supplies 1,448 source records to the acquisition build workflow; it remains outside the active library catalog. The existing 75-sheet compact/standard proposal is unchanged.

Exact headers corrected 88 stale API byte counts. All source SHA256 values remain null because the inspected USGS headers supply no whole-file SHA256. Multipart ETags are not checksums. Fine editions are 2023–2026; the coastal supplements are 1983–1994 and the overview is the 2001 edition printed in 2002. Navigation must keep these publication dates and the historical warning visible.

The selected publisher bounding boxes cover the Census target after the existing evidenced zero-land Atlantic Ocean exclusion. This is **complete mixed-scale footprint coverage**, not verified complete 1:24,000 land coverage or an evacuation-route guarantee. Fine-scale gaps remain explicit: CT 2, MA 10, ME 12, NH 1 and RI 3; Vermont has none against this geometry. These may include territorial water, but no unverified mask, geometry repair, buffer or positive-area tolerance removes them. Actual PDF map frames, usable detail, legends, notices and those coverage gaps still require review. Both manifests keep `content_ready: false`.

Reproduce using a Python environment with the optional Shapely dependency for real-state geometry:

```sh
python scripts/acquire_content.py discover --resource regional-maps --profile full-1tb --recipes catalog/acquisition/regional-maps-detailed-1tb.yaml --offline --json
python scripts/prepare_map_capture.py --discovery .owl/acquisition/reports/discover-ba5bcd3f7e87c2ce.json --request-output catalog/acquisition/regional-maps-detailed-source-probes.json
python scripts/probe_source_batches.py catalog/acquisition/regional-maps-detailed-source-probes.json --output catalog/acquisition/regional-maps-detailed-source-probe-evidence.json --offline
python scripts/freeze_map_selection.py --discovery .owl/acquisition/reports/discover-ba5bcd3f7e87c2ce.json --source-probes catalog/acquisition/regional-maps-detailed-source-probe-evidence.json --output catalog/acquisition/regional-maps-detailed-selection.json
python scripts/prepare_map_capture.py --discovery .owl/acquisition/reports/discover-ba5bcd3f7e87c2ce.json --source-probes catalog/acquisition/regional-maps-detailed-source-probe-evidence.json --overview catalog/acquisition/usa-overview-candidate.json --overview-metadata-cache .owl/acquisition/overview-metadata --output catalog/acquisition/regional-maps-detailed-acquisition.json
```

Use the discovery detail path printed by the first command if the recipe changes. Metadata caches are local and not committed. The HEAD batch command validates every request before networking, uses at most four workers, spaces request starts by 150 ms, checkpoints every 100 records, and reuses per-URL evidence. Omit `--offline` only to acquire missing headers; it never reads PDF bodies. The capture-preparation command is always offline and binds each source identity to its original verified publisher metadata page. See [the source-review build workflow](acquisition-capture.md) for the explicit body-acquisition phase.

The request-preparation command deterministically freezes every selected sheet URL before probing. Review changed selections before replacing their portable manifests. Missing exact HEAD sizes, changed metadata, missing publisher identities, duplicate inputs, mixed-up overview identity, or capacity overflow prevent generation of a capture manifest.
# Captured PDF inspection

`scripts/inspect_map_capture.py` inspects originals captured by the source-review
build without changing the source directory or active catalog. It accepts an
in-progress capture, labels missing receipts as pending, and reports the whole
manifest's source count even when `--limit` selects a diagnostic subset.

```sh
.venv/bin/python scripts/inspect_map_capture.py \
  --staging '/Volumes/General Backup/OWL-acquisition/maps-detailed-1tb' \
  --output '/Volumes/General Backup/OWL-acquisition/maps-review-1tb' \
  --render --output-budget-bytes 14000000000 \
  --follow-job .owl/jobs/maps-detailed-1tb \
  --production-root /Volumes/OWL --reserve-bytes 10000000000
```

Each separate worker rechecks the whole-file SHA256 and receipt identity, opens
at most 96 MiB of source PDF, inspects at most eight pages, and has a 120-second
timeout. It records scale/date text, publisher-bound corner-label candidates,
page dimensions and geospatial viewports, then renders every page plus a legend
detail. Output is bounded to 64 MiB per source and to the declared aggregate
allowance. Unchanged evidence and rendered files are reused only after source
hash verification; damaged renders are regenerated. Failures have bounded
excerpts in the local report, and normal command output is a compact summary.
The review root has a manifest-bound owner and fixed byte allowance. Every write
rechecks that owner and the live filesystem reserve; an unrelated populated
directory cannot be adopted. Source capture and review use sibling directories,
so concurrent capture accounting does not absorb unregistered derivatives.

The optional follower waits for newly completed receipts from the matching
already-running capture, with an eight-hour deadline. It never starts or retries
that acquisition; failure, loss of its worker, or the deadline produces an
explicitly incomplete report. It inspects each newly captured original once.

The 14 GB review allowance plus the frozen 72,164,924,091-byte capture peak
reserves 86,164,924,091 bytes. PDF images and detailed review evidence live in
the separately owned staging sibling; only small local summaries remain under
`.owl`. `scripts/relocate_map_review.py` can preserve a prior local pass there,
verifying every copied file before removing its exact former local copy. The
checker never marks content ready. A printed
year is only a locator for edition review. GeoPDF registration may cover paper
margins and locator insets, so registration coordinates do not resolve the
explicit fine-scale coastal gaps. Full map-frame, label, contour, notice and
coverage review remains required even after every PDF parses and renders.
