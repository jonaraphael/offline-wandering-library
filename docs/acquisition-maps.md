# New England map selection evidence

The original proposal freezes **75 USGS sheets, 2,107,297,354 bytes** against a
30 GB topographic allowance. Default discovery now uses it only for the compact
and standard presets; the [detailed 1 TB selection](acquisition-detailed-maps.md)
has its own registered 80 GB recipe. The original proposal contains 64 historical 1:100,000 sheets
and 11 current-series 1:24,000 sheets that close the Vermont boundary strip north
of 45° latitude. It is a metadata selection, not a ready collection: all 75
whole-file SHA-256 pins and PDF reviews remain pending.

The national overview source is now selected: **USGS product 112764**, General
Reference, National Atlas of the United States, at **1:5,000,000**. Its 2001
edition, printed in 2002, covers all 50 states according to the publisher. HEAD
confirms **19,527,583 bytes**. The combined sheet and overview proposal is
**2,126,824,937 bytes**, within the existing 30 GB allowance. Its whole-file
SHA-256 and actual PDF review remain pending. This historical overview supplies
national geographic context; it is not current local route coverage.

The recipe records this unpinned identity under `overview_candidates`, separate
from the strict overview selection. Candidate bytes are reserved before selecting
the finest complete topographic set. The frozen manifest keeps sheet bytes,
overview candidate bytes and the combined total separate; a candidate cannot make
a plan complete or create a catalog asset.

The full 1:24,000 set needs roughly 71.7 GB, exceeding the allowance. The new
selector considers complete base scales in detail order, retains the latest
edition of every relevant sheet at that scale, and supplements exact holes with
finer sheets. It does not truncate a fine-scale set to make its bytes fit or add
unused sheets to fill the budget. Editions span 1983–2024. Historical road,
structure, and shoreline information must remain visibly dated.

Coverage uses the exact Census state polygons for CT, MA, ME, NH, RI, and VT.
The original apparent Cape Cod hole lies entirely in a Census areal-hydrography
feature named Atlantic Ocean, classified `H2053`, with `AREALAND=0`. The recipe
explicitly subtracts this one evidenced ocean polygon; it does not remove lakes,
rivers, islands, or arbitrary coastal buffers. Polygon holes inside an ocean
feature remain land. The result has no positive-area gaps, with zero area
tolerance and no simplification. This proves publisher bounding-box coverage;
the actual PDF map frames still need build-time inspection.

The Census `USLandmass` response was also investigated. It was byte-identical to
the state-boundary response, so its service name was not treated as proof of a
shoreline-clipped boundary. Generalized 500K state boundaries remove coastal
water, but the accepted proposal uses the detailed boundary and explicit ocean
evidence instead, avoiding loss of small islands during generalization.

The metadata inventory supplies 1,818 candidate editions. HEAD-only verification
found all 75 selected URLs available, but **65 sizes differed from USGS inventory
metadata**. The manifest records both sizes and uses the exact HEAD sizes for
capacity. None of the responses supplied a whole-file SHA-256. Multipart ETags
were not used as hashes. One ScienceBase metadata sample likewise provided
download links and the older size, without a content checksum. No map PDFs or
other library bodies were downloaded during this investigation.

Portable records:

- `catalog/acquisition/regional-maps-proposal.yaml`: the pending, source-bound
  discovery recipe, including the exact official water query.
- `catalog/acquisition/regional-map-selection.json`: every selected sheet ID,
  publication date, scale, publisher ID, footprint, exact URL, size evidence,
  and remaining pin/review requirements.
- `catalog/acquisition/regional-map-source-probes.json` and
  `regional-map-source-probe-evidence.json`: reproducible HEAD requests and
  publisher response evidence.
- `catalog/acquisition/usa-overview-candidate.json` and its source-probe records:
  the selected overview identity, historical edition, exact size and pending
  whole-file pin/review requirements.

With the optional acquisition dependency installed, reproduce using cached
metadata, then pass the discovery detail path printed by the first command:

```sh
python scripts/acquire_content.py discover --resource regional-maps --profile full-1tb --recipes catalog/acquisition/regional-maps-proposal.yaml --offline --json
python scripts/probe_source_pins.py --help
python scripts/freeze_map_selection.py --discovery PATH_TO_DISCOVERY_DETAIL --source-probes catalog/acquisition/regional-map-source-probe-evidence.json --output .owl/acquisition/regional-map-selection.json
```

`freeze_map_selection.py` never fetches the network. It rejects truncated
inventories, unresolved geographic gaps, duplicate sheets/probes, malformed
hashes, and corrected sizes exceeding the original allowance. Unpinned outputs
remain explicitly pending and cannot promote the resource or the preset.

Primary references: [USGS programmatic map access](https://www.usgs.gov/the-national-map-data-delivery/topographic-map-access-points),
[Census detailed state layer](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0),
and [Census areal hydrography](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Hydro/MapServer/1).
