# Optional publisher relay

The Worker is prepared for an explicit owner decision. The default Pages
build never emits relay routes. The supplied configuration also disables
Workers.dev, previews and all origins.

Generate the exact URL map from the catalog at the same revision as Pages.

```sh
python scripts/build_pages.py --relay-allowlist relay/allowlist.json
```

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

Set the Worker’s `ALLOWED_ORIGIN` to the exact Pages origin and configure a
Worker custom domain or route. Set up the rate-limit binding with a namespace
unique to your account. Once approved and configured, deploy from the
`relay/` directory with Wrangler. Turn off cache rules on the relay route and
leave browser caching disabled. The Worker validates Range, serves the pinned
URL, declines publisher redirects, strips cookies and streams without
retaining a copy. Large publisher redirects or changed files require a
catalog review. Publisher 403 responses remain request failures.

Generate a Pages artifact with relay routes using the corresponding origin.

```sh
python scripts/build_pages.py /tmp/owl-pages --relay-base https://relay.example.org \
    --archive-relay --search-commit <full-git-commit>
```

The client checks each response against the existing catalog SHA-256. The
rate limiter counts requests per IP and Cloudflare location.
[Workers rate limits](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/) ·
[Cloudflare cache behavior](https://developers.cloudflare.com/workers/reference/how-the-cache-works/)


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
