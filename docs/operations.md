# Operations

## GitHub Pages

The `tests` workflow runs on pushes, pull requests and manual dispatches. Pushes
and pull requests run the browser and site tests (the `pages` job), the only
check required to merge. Its two search checks, the search benchmark and
emergency search in the offline reader, run only when a change touches a path
outside `web/`, `docs/`, `relay/`, the JavaScript tests in `tests/`, root
Markdown files and `SELECT.html`; without them the job takes about 1.5
minutes instead of 7 to 11. The Python matrix and optional-dependency tests run
only from a manual run of **tests**. A push to `main` or a manual run of
**tests** with branch **main** publishes that commit at once, in about 3
minutes. Set the `OWL_RELAY_BASE` repository variable to the approved
publisher relay before deploying. The Pages build verifies the locked mirrors
and pins the search paths to the publishing commit. Before uploading the
artifact, the build runs the browser plan suite against it and checks that both
the 16 GB and 64 GB recommendations contain every CRITICAL file in the
corresponding Python profile. Keep the `github-pages` environment restricted to
`main` and set the Pages source to **GitHub Actions**. [Workflow](../.github/workflows/pages.yml)

The hosted builder loads scripts from its own origin. Its Content Security
Policy derives `connect-src` from the HTTPS origins in the generated catalog's
direct and relay routes, the configured archive relay routes and the search
base. Production uses `raw.githubusercontent.com` for commit-pinned search data.
The site origin serves its own catalog, mirrors, and bundled support files.
The standalone `SELECT.html` embeds its scripts and disables network access.

If a deployment regresses, use the **github-pages** environment's deployment
history to identify the last working commit. Revert the offending change on
`main` using the normal review and merge process. The reverted content goes
through the same test and deployment jobs. Confirm that Pages serves the new
commit, then reload the builder to pick up its versioned modules. A failed
artifact build leaves the existing deployment live. [Pages build guide](pages-builder.md)

## Publisher relay

The Cloudflare account owner deploys `owl-publisher-relay` from `relay/`.
Record the Git commit and previous Worker version before deploying. After a
rollback, check that the active Pages catalog uses relay IDs available in the
restored allowlist. The relay guide has the commands and probe. [Relay guide](../relay/README.md)

## Catalog pins

1. Find the publisher's finished release and confirm redistribution rights.
   Update the source URL, version, exact byte count and SHA-256 together.
   Record where the hash came from. If the publisher has no verified SHA-256,
   hash the complete file and record the provenance. Repeat the full hash
   check before adding a mirror.
2. Update `catalog/library.yaml` and the affected resource sizes and editions.
   For Kiwix, refresh the matching piece pins with `scripts/build_kiwix_pins.py`.
   Run `scripts/build_pages.py --archive-pins ASSET_ID FILE` for any affected
   split-bound archive with a published part manifest. Update the Pages mirror
   lock when a mirrored pin changes. Any relay allowlist change needs the
   owner's review and a coordinated relay deploy.
3. Run the catalog and selection policy checks, regenerate the capacity ladder,
   selector and content docs, and confirm their `--check` results. If the source
   changed, rebuild and validate its search shards before publishing the new pin.
   [Catalog maintenance](catalog.md) · [Search maintenance](search.md)

The weekly source check probes every publisher URL and samples browser direct
and relay routes. It counts streamed bytes for small responses without a length.
After an HTTP 403 or 429 from a publisher, it retries without an Origin header
and with a browser user agent. A retry that reports the pinned length is listed
under **Blocked for this checker** in the tracking issue. HTTP 404 or 410 and
size drift fail the check when every alternate is unavailable. An asset whose
publisher URLs are all inconclusive fails on the third consecutive week. A
passing run updates and closes the issue, retaining the counts for the next run.

The November 2026 pins for PhET Forces and Motion: Basics, Build an Atom,
and Area Builder use PhET's origin and alternate host. The principal PhET
domain sometimes adds an analytics tag to the HTML, changing the exact bytes.
Pages republishes the verified CC BY-NC 4.0 files with their attribution.
All 18 offline screen and viewport checks passed against the new pins using
the existing [PhET screen checks](../catalog/acquisition/phet-required-screen-checks-20260927.json).

## Release tag

1. Set matching versions in `pyproject.toml` and `src/owl/__init__.py` and date
   the release section in `CHANGELOG.md`. Merge the release changes to `main`.
2. Run **tests** by hand on the release commit, which adds the Python matrix
   and optional-dependency tests, and wait for the Pages deployment. Check
   that the live builder and relay routes work. Tag the reviewed commit.

   ```sh
   git tag -a v0.2.0 <release-commit> -m 'OWL 0.2.0'
   git push origin v0.2.0
   ```

3. Publish a GitHub release from the tag with the changelog and the build
   instructions. Pages deploys through the tested `main` workflow.

## Ownership

| Area | Owner |
| --- | --- |
| GitHub Pages settings, production releases and rollbacks | Repository maintainer with environment access |
| Worker deployments, rollback, account settings and allowlist decisions | Cloudflare Worker account owner |
| Asset pins, rights and selection policy | Catalog reviewers |
| Reader, search and drive-build changes | Maintainers of the respective code paths, reviewed through pull requests |
| Scheduled catalog-check issue | Catalog reviewers and the Pages or relay owner for the failing route |
