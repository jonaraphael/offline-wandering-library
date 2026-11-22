# Operations

## GitHub Pages

The `tests` workflow runs on pushes, pull requests and manual dispatches. A
push to `main` or a manual run of **tests** with branch **main** publishes
that commit after the Python matrix, optional-dependency tests and browser
tests pass. The Pages build verifies the locked mirrors, pins the search
paths to that commit, and publishes the artifact to the `github-pages`
environment. Keep the environment restricted to `main` and set the Pages
source to **GitHub Actions**. [Workflow](../.github/workflows/test.yml)

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

## Release tag

1. Set matching versions in `pyproject.toml` and `src/owl/__init__.py` and date
   the release section in `CHANGELOG.md`. Merge the release changes to `main`.
2. Wait for **tests** and the Pages deployment for the release commit. Check
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
