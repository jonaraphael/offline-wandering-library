# Optional publisher relay

The Worker is prepared for an explicit owner decision. The default Pages
build never emits relay routes. The supplied configuration also disables
Workers.dev, previews and all origins.

Generate the exact URL map from the catalog at the same revision as Pages.

```sh
python scripts/build_pages.py --relay-allowlist relay/allowlist.json
```

The map includes 320 resolved critical files that lack a browser route and
have redistribution disabled in the catalog. Confirm the applicable
publisher terms and deployment authorization before enabling any of these
routes. Review the generated map with the approver before deployment.

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
    --search-commit <full-git-commit>
```

The client checks each response against the existing catalog SHA-256. The
rate limiter counts requests per IP and Cloudflare location.
[Workers rate limits](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/) ·
[Cloudflare cache behavior](https://developers.cloudflare.com/workers/reference/how-the-cache-works/)
