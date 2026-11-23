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
  ([Open Copyright Policy](https://hesperian.org/open-copyright-policy/))
- International Federation of Red Cross and Red Crescent Societies
- John Wiley & Sons, Inc., New York / Chapman & Hall, Limited, London; scan hosted by Survivor Library
- Kiwix / openZIM
- Libre Pathology
  ([copyright policy](https://librepathology.org/wiki/Libre_Pathology:Copyrights))
- Low-tech Magazine; archived by Kiwix/openZIM
- Medecins Sans Frontieres
  ([medical guidelines disclaimer](https://medicalguidelines.msf.org/en/node/1338))
- Montana State University Extension
- National Center for Home Food Preservation / University of Georgia
- North Central Food Safety Extension Network / NDSU Extension
- Project Gutenberg contributors; Kiwix/openZIM
  ([permissions](https://www.gutenberg.org/policy/permission) and
  [license](https://www.gutenberg.org/policy/license))
- Skat / Rural Water Supply Network (RWSN)
- Southern African Development Community Groundwater Management Institute (SADC-GMI)
- Sphere Association
  ([intellectual property policy](https://spherestandards.org/intellectual-property/))
- Sustainable Agriculture Research and Education (SARE)
- University of Alaska Fairbanks Cooperative Extension
- University of California, Davis, Postharvest Technology Research and Information Center
- University of Georgia Cooperative Extension
- University of Georgia Extension
- University of Maryland Extension
- World Health Organization
  ([terms of use](https://www.who.int/about/policies/terms-of-use))
- World Health Organization / WEDC

For Kiwix archives, the catalog also records the original publishers' terms.
[Wikimedia](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) ·
[Khan Academy](https://www.khanacademy.org/about/docs/khan-academy-terms-of-service) ·
[Energypedia](https://energypedia.info/wiki/Energypedia:Copyrights) ·
[Gardenology](https://gardenology.org/wiki/Gardenology.org:Copyrights) ·
[MedlinePlus](https://medlineplus.gov/copyright.html) ·
[Stack Overflow](https://stackoverflow.com/help/licensing) ·
[PhET](https://phet.colorado.edu/en/licensing) ·
[Mutopia](https://www.mutopiaproject.org/legal.html) ·
[Folgerpedia](https://folgerpedia.folger.edu/Folgerpedia:Copyrights) ·
[OpenStreetMap Wiki](https://wiki.openstreetmap.org/wiki/Wiki_content_license)

### Why the owner operates the relay

The owner runs the relay as a pass-through. When a user's browser asks for a
file, the relay fetches the publisher's original for that user's personal
offline copy. The relay stores and caches nothing and serves only the exact
publisher URLs in its fixed [allowlist](allowlist.json).

The owner accepts the remaining legal risk and will remove a publisher's
routes on request. Publishers can request removal by opening a
[GitHub issue](https://github.com/jonaraphael/offline-wandering-library/issues/new)
with the affected URLs or catalog IDs.

## Cloudflare plan and publisher terms

The relay runs on Workers Free (confirmed by the owner, 2026-11-22). Free
allows 100,000 requests per day across the account and 10 ms of CPU per
invocation.

Archive relay is off (`OWL_ARCHIVE_RELAY=false`, set 2026-11-22). Kiwix
archives download from `mirror.download.kiwix.org` directly, and the relay
carries only the whole-file publisher routes. A 16 GB browser build then
sends about 320 relay requests, so Free covers roughly 300 such builds a
day. The owner will revisit the plan and the archive flag when the number
of users grows well beyond a handful.
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
