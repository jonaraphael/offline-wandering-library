# Source-pin discovery for the 1 TB plan

`scripts/probe_source_pins.py` checks exact source identities using HEAD requests
and explicitly declared checksum sidecars. It never reads a library file body,
including error and redirect responses. HEAD remains HEAD across redirects;
both the pin probe and metadata fetcher stop after five redirects. Sidecar reads
use the existing metadata-only fetcher with a 64 KiB bound. A manifest can contain
at most 200 probes.

```sh
python scripts/probe_source_pins.py \
  catalog/acquisition/full-1tb-source-probes.json \
  --output .owl/acquisition/source-pin-report.json
python scripts/probe_source_pins.py \
  catalog/acquisition/regional-map-source-probes.json \
  --offline --output .owl/acquisition/map-pin-report.json
```

Repeat `--id` to filter requests. `--refresh` rechecks publisher metadata;
ordinary reruns reuse local evidence. Summary output is concise JSON. Detailed
reports preserve exact URLs, response dates, selected headers, observed byte
counts and actionable blockers. The cache defaults to
`.owl/acquisition/source-pins/` and is not committed.

A request has `id` and `url`, optionally `checksum_url`,
`expected_size_bytes` and `expected_sha256`. A checksum sidecar must identify
the exact filename; a bare hexadecimal SHA-256 is accepted only from that
filename's `.sha256` URL. Conflicting checksums and changed sizes remain pending.
ETags, MD5, SHA-1, composite S3 checksums and a digest of an empty HEAD response
never become whole-file SHA-256 pins. HTTP errors do not contribute their error
page sizes as source sizes.

`proposed` means publisher metadata contains an exact byte count and a
whole-file SHA-256. This status does not select the file, approve its content or
mark a resource ready. Normal build verification must still validate the whole
download against its pin. `pending` records are evidence and must not be staged
as ready catalog assets.

## Observed sources

- All 75 proposed New England map objects returned HTTP 200. Their exact HEAD
  total is **2,107,297,354 bytes**; 65 API size values were stale, with a total
  difference of 1,470,212 bytes. The [map probe evidence](../catalog/acquisition/regional-map-source-probe-evidence.json)
  preserves both the observed size and a changed-size blocker. These S3 objects
  expose no qualifying whole-file SHA-256; multipart ETags are retained only as
  evidence.
- The exact 2026 Hesperian midwives back-matter URL returned HTTP 404. The
  [source report](../catalog/acquisition/full-1tb-source-probe-evidence.json)
  records the unavailable file; a different edition is not substituted.
- The publisher's [Stack Exchange archive metadata](https://archive.org/metadata/stackexchange)
  identifies separate Posts, Comments, Users and PostLinks archives totaling
  **31,166,034,729 bytes**. HEAD confirms all four sizes. The
  [candidate manifest](../catalog/acquisition/stackoverflow-input-candidates.json)
  freezes their identities, metadata hash, expected XML members and correctly
  labeled publisher MD5/SHA-1/CRC32 values. Whole-file SHA-256, safe 7z extraction,
  unpacked XML pins, per-post metadata and illustration review remain required.
  The four shared inputs serve both durable and legacy selections and must not
  be counted twice. `stackoverflow_input_candidates()` in the pin module
  reproduces this freeze from cached publisher metadata.
- The [Kiwix directory observation](../catalog/acquisition/khan-source-discovery.json)
  lists only the whole English Khan archive. That collection is excluded from
  the declared 90 GB subject subset, so it has not been selected as a substitute
  for course and lesson manifests.

The [USA overview candidate](../catalog/acquisition/usa-overview-candidate.json)
now identifies USGS product **112764**, a 2001 General Reference map printed in
2002. The [publisher product metadata](https://store.usgs.gov/product/112764)
declares all 50 states, including Alaska and Hawaii, at a common 1:5,000,000 scale.
The exact linked PDF returns HTTP 200 with **19,527,583 bytes**. Its identity,
dates, scale, metadata checksum and header evidence are frozen. No SHA-256 or
checksum sidecar is provided in the inspected metadata, so the PDF remains
pending acquisition and review. It supplements the New England topographic
selection as a historical national overview; it does not establish current
road, trail or evacuation-route coverage.

The HTTP observations were made September 22, 2026 US Eastern time. No new
whole-file pins were supplied by these publishers, and no library bodies were
downloaded. These records narrow the remaining work without enabling a falsely
complete 1 TB preset.
