# Publisher relay

`owl-publisher-relay` runs at
`https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev` and allows
requests from `https://jonaraphael.github.io`. It is a pass-through for a fixed
allowlist of catalog IDs and exact URLs. It stores nothing. The Worker
validates ranges, declines publisher redirects, strips cookies and streams
with caching disabled. Browser clients check the returned bytes against the
catalog SHA-256. The rate limiter allows 1,800 requests per minute per IP
and Cloudflare location. Sync uses up to eight concurrent 4 MiB archive
requests. Use 600 requests per minute as a conservative ceiling for the
observed Sync rate. Three times that ceiling is 1,800 requests per minute.

## Deploy and roll back

The Cloudflare account owner deploys from the reviewed revision used by Pages.
Check that the generated allowlist matches the checked-in copy before deploy.

```sh
python scripts/build_pages.py --relay-allowlist /tmp/owl-relay-allowlist.json
diff -u relay/allowlist.json /tmp/owl-relay-allowlist.json
node --test tests/relay.test.mjs
cd relay
npx wrangler whoami
npx wrangler deployments list
npx wrangler deploy
```

Record the previous working Worker version and the deploy commit. Use the
owner's Wrangler login or credentials supplied outside the repository.
To roll back, run `npx wrangler rollback <previous-version-id>` from `relay/`
and probe a known relay ID. Use a bounded range for an archive route.
Check that the restored allowlist contains the IDs in the live Pages catalog.
[Cloudflare rollback guide](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)

```sh
curl --head -H 'Origin: https://jonaraphael.github.io' \
  -H 'Range: bytes=0-0' \
  https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev/assets/wikipedia_en_top
```

## Pages integration

Set the repository variable `OWL_RELAY_BASE` to the Worker HTTPS origin.
The map includes critical publisher files and exact archive peers from
[`web/archive-relay.json`](../web/archive-relay.json). The English Wikipedia
and Survivor Library pins include FAU and Dotsrc URLs. The Worker accepts
only single, closed archive ranges of at most 64 MiB. Pages keeps Kiwix’s
CORS mirror as the default. Pass `--archive-relay` along with `--relay-base`,
or set `OWL_ARCHIVE_RELAY=true` in the Pages workflow, to sample approved
archive routes. The client compares the same verified 4 MiB range on each
route and switches when a peer is at least 25% faster or the direct sample
fails. If a peer fails
during transfer, the current archive returns to the direct route.

For ordinary publisher files, a request for the full file (`bytes=0-` or a
range covering the entire file) can receive HTTP 200 when the publisher
ignores Range and declares the pinned length. For an ignored sub-range, the
relay returns HTTP 416 and exposes `X-OWL-Reason: publisher-ignores-range`
through CORS. Clients can retry with a whole-file GET without a Range header.
Archive peers still require a bounded range and a matching HTTP 206 response.

Generate a Pages artifact with relay routes using the corresponding origin.

```sh
python scripts/build_pages.py /tmp/owl-pages \
    --relay-base https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev \
    --archive-relay --search-commit <full-git-commit>
```

[Workers rate limits](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/) ·
[Cloudflare cache behavior](https://developers.cloudflare.com/workers/reference/how-the-cache-works/)

## Publishers with restricted files

The [catalog](../catalog/library.yaml) marks one or more files from each
publisher below `redistributable: false`. This is a per-file flag. The relay's
separate allowlist governs the exact routes it can serve.

- CD3WD Project and original publication authors
- Centers for Disease Control and Prevention
- D. Van Nostrand Company, New York; scan hosted by Survivor Library
- David Williams Company, New York; scan hosted by Survivor Library
- Eawag / Sandec
- Food and Agriculture Organization of the United Nations
- Hesperian Health Guides
- International Federation of Red Cross and Red Crescent Societies
- John Wiley & Sons, Inc., New York / Chapman & Hall, Limited, London; scan hosted by Survivor Library
- Kiwix / openZIM
- Libre Pathology
- Low-tech Magazine; archived by Kiwix/openZIM
- Medecins Sans Frontieres
- Montana State University Extension
- National Center for Home Food Preservation / University of Georgia
- North Central Food Safety Extension Network / NDSU Extension
- Project Gutenberg contributors; Kiwix/openZIM
- Skat / Rural Water Supply Network (RWSN)
- Southern African Development Community Groundwater Management Institute (SADC-GMI)
- Sphere Association
- Sustainable Agriculture Research and Education (SARE)
- University of Alaska Fairbanks Cooperative Extension
- University of California, Davis, Postharvest Technology Research and Information Center
- University of Georgia Cooperative Extension
- University of Georgia Extension
- University of Maryland Extension
- World Health Organization
- World Health Organization / WEDC

## Cloudflare plan and publisher terms

Assume Workers Free until the owner confirms the account plan. Free allows
100,000 requests per day across the account and 10 ms of CPU per invocation.
For an archive transfer entirely through the relay, divide decimal bytes by
4,194,304 (4 MiB) and round up.

| Transfer | Calculation | Requests |
| --- | ---: | ---: |
| 16 GB | ⌈16,000,000,000 ÷ 4,194,304⌉ | 3,815 |
| 64 GB | ⌈64,000,000,000 ÷ 4,194,304⌉ | 15,259 |
| 256 GB | ⌈256,000,000,000 ÷ 4,194,304⌉ | 61,036 |
| 1 TB | ⌈1,000,000,000,000 ÷ 4,194,304⌉ | 238,419 |

These estimates exclude retries, route samples and rounding for separate
archives. Direct publisher downloads and Pages mirrors use no Worker
requests. A 1 TB transfer entirely through the relay needs more than two
full Free daily allowances. The per-IP limit applies separately.

To check the plan, sign in to the Cloudflare dashboard, select the account
that owns the relay and open **Workers & Pages → Plans**. To upgrade, select
**Workers Paid** and confirm billing for that account. [Cloudflare dashboard](https://dash.cloudflare.com/)

Workers Paid starts at USD 5 per month. It removes the Free daily request
cap and includes 10 million requests per month, with USD 0.30 per additional
million. The default CPU time limit rises to 30 seconds per request. Workers
charges no per-byte egress fee. Both plans have 128 MB of Worker memory and
stream response bodies without an enforced size limit. Cloudflare's CDN
cache limits are 512 MB on Free, Pro and Business and 5 GB on Enterprise.
The relay disables caching. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) ·
[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)

Cloudflare’s Free, Pro and Business CDN terms require an eligible paid
service to serve large files through its CDN. The Developer Platform terms
also allow Cloudflare to restrict disproportionately burdensome requests
and require compliance with applicable third-party terms. Use a paid Worker
for bulk archive relay traffic under those terms and confirm the publisher
or mirror’s terms allow this access before enabling archive routes.
[CDN terms](https://www.cloudflare.com/service-specific-terms-application-services/) ·
[Developer Platform terms](https://www.cloudflare.com/service-specific-terms-developer-platform/)
