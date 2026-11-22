# Publisher relay

`owl-publisher-relay` runs at
`https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev` and allows
requests from `https://jonaraphael.github.io`. It is a pass-through for a fixed
allowlist of catalog IDs and exact URLs. It stores nothing. The Worker
validates ranges, declines publisher redirects, strips cookies and streams
with caching disabled. Browser clients check the returned bytes against the
catalog SHA-256. The rate limiter counts requests per IP and Cloudflare
location.

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

A decimal 1 TB transfer in 4 MiB requests takes about 238,419 Worker
invocations before retries. Workers Free allows 100,000 requests per day
and 10 ms CPU per invocation. Workers Paid currently starts at USD 5 per
month with 10 million standard requests included, 30 seconds of CPU per
invocation by default and no per-byte egress charge. Both plans have
128 MB of Worker memory and no enforced response-body size limit for
streaming. Cloudflare’s CDN cache limits are 512 MB on Free, Pro and
Business and 5 GB on Enterprise. The relay disables caching and streams
the response. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) ·
[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)

Cloudflare’s Free, Pro and Business CDN terms require an eligible paid
service to serve large files through its CDN. The Developer Platform terms
also allow Cloudflare to restrict disproportionately burdensome requests
and require compliance with applicable third-party terms. Use a paid Worker
for bulk archive relay traffic under those terms and confirm the publisher
or mirror’s terms allow this access before enabling archive routes.
[CDN terms](https://www.cloudflare.com/service-specific-terms-application-services/) ·
[Developer Platform terms](https://www.cloudflare.com/service-specific-terms-developer-platform/)
