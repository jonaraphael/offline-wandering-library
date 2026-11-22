# Release OWL v0.2.0

Use a local clone, Git, Python 3.11 or later and a current Node.js LTS with npm.

1. Open [the GitHub repository](https://github.com/jonaraphael/offline-wandering-library).
   Click **Settings → Pages** and confirm **Source** is **GitHub Actions**.
   Under **Settings → Environments → github-pages**, confirm that `main`
   can deploy. Record the last working commit from the `github-pages`
   deployment history. Open **Settings → Secrets and variables → Actions →
   Variables** and confirm `OWL_RELAY_BASE` is set to the owner's approved
   Worker origin, `https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev`.

2. Open the release pull request under **Pull requests**. Click the source
   branch link above the conversation and open `pyproject.toml` and
   `src/owl/__init__.py`. Both should specify `0.2.0`.
   If the [changelog](../CHANGELOG.md) still says `0.2.0 (unreleased)`, replace
   `unreleased` with the planned release date on the PR branch. On the
   **Conversation** tab, wait for approval and green checks, then click the
   enabled merge button and confirm.
   Copy the full commit SHA from the resulting commit link on `main`. Use
   that SHA for the rest of the checklist.

3. Click **Actions → tests**. Open the run for the merge commit on `main`.
   Check the commit SHA at the top of the run. Watch the Python matrix,
   `zim` and `pages` jobs, followed by `publish / build` and
   `publish / deploy`. If a job fails, open the first failed step for its
   log. Retry a transient failure with **Re-run jobs → Re-run failed jobs**.
   For a code or settings failure, correct it and use the successful run
   and SHA of the corrected release commit. If the PR adds relay IDs, start
   step 4 while the tests run. The live Pages catalog must keep working
   with the updated Worker during the cutover.

4. Prepare the relay deploy from the release commit. Open a Bash terminal
   (Git Bash on Windows). From a clean local copy of the repository, run
   the following. Paste the full SHA when prompted. Continue once the
   allowlist comparison and relay tests pass.

   ```sh
   read -r -p 'Full release commit SHA: ' release_commit
   git fetch origin
   git switch --detach "$release_commit"
   python -m pip install -e .
   relay_allowlist=$(mktemp)
   python scripts/build_pages.py --relay-allowlist "$relay_allowlist"
   diff -u relay/allowlist.json "$relay_allowlist"
   node --test tests/relay.test.mjs
   ```

5. Sign in to the Cloudflare dashboard as the owner of the Worker. Open
   [My Profile → API Tokens](https://dash.cloudflare.com/profile/api-tokens),
   then click **Create Token**. Choose **Edit Cloudflare Workers** as the
   permission template and scope it to the account that owns
   `owl-publisher-relay`. Review the summary, click **Create Token** and copy
   the secret into your password manager. On the Cloudflare account's
   **Workers & Pages** page, copy the **Account ID**.
   [Cloudflare token instructions](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)

6. In the same Bash terminal, enter the account ID and token when prompted.

   ```sh
   read -r -p 'Cloudflare account ID: ' CLOUDFLARE_ACCOUNT_ID
   read -r -s -p 'Cloudflare API token: ' CLOUDFLARE_API_TOKEN
   printf '\n'
   export CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN
   cd relay
   npx wrangler whoami
   npx wrangler deployments list
   ```

   Confirm that Wrangler reports the correct account. Copy the previous
   working Worker **version ID** from the deployments list, then run
   the deploy command.

   ```sh
   npx wrangler deploy
   ```

   Record the newly deployed Worker version and the Git commit. Probe the
   relay by requesting headers for a one-byte range. Expect HTTP `206`,
   a `Content-Range` starting with `bytes 0-0/` and
   `Access-Control-Allow-Origin: https://jonaraphael.github.io`.

   ```sh
   curl --fail --head -H 'Origin: https://jonaraphael.github.io' \
     -H 'Range: bytes=0-0' \
     https://owl-publisher-relay.snapandshop-jonaraphael.workers.dev/assets/wikipedia_en_top
   ```

7. After **publish / deploy** is green, open the deployment URL from that
   job in Chrome or Edge and reload. Check that **See what goes on a drive**
   opens Manage and displays the recommended collections. Connect a spare
   drive, open **Manage what goes on it** and use **Advanced → Exclude filtered
   files** with an empty search. Search for a small PDF and include just that
   file. Click **Done → Sync**. Confirm the stage says **Ready** and open
   `START_HERE.html` from the drive to verify the PDF opens. If Pages or the
   relay fails the check, fix it or follow step 10 before tagging.

8. Tag the tested commit from the same Bash terminal. The release SHA
   captured in step 4 is still in `release_commit`.

   ```sh
   git tag -a v0.2.0 "$release_commit" -m 'OWL 0.2.0'
   git push origin refs/tags/v0.2.0
   git show --no-patch v0.2.0
   ```

9. In the GitHub repository, click **Releases → Draft a new release**. Under
   **Choose a tag**, choose the existing `v0.2.0`. Use **OWL v0.2.0** as
   the title. Paste the dated `0.2.0` section from the changelog at the
   tagged commit into the description. Add the [live builder](https://jonaraphael.github.io/offline-wandering-library/)
   and [desktop build instructions](https://github.com/jonaraphael/offline-wandering-library/blob/v0.2.0/docs/usage.md).
   Review the preview, then click **Publish release**. Open the published
   release and check its tag and links.
   [GitHub release instructions](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

10. If the release needs to be rolled back, use the last working Pages
    commit and Worker version ID you recorded.

    - For Pages, open the merged PR on GitHub and click **Revert → Create
      pull request**. Review and merge the revert PR into `main`. Watch
      **Actions → tests** through `publish / deploy`, then repeat the live
      check in step 7.
      [GitHub revert instructions](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/reverting-a-pull-request)
    - For the Worker, authenticate as in step 6 and run the command below
      from `relay/`. Enter the recorded version UUID, then confirm the
      rollback. If the older Worker lacks IDs used by the current Pages
      catalog, restore the compatible Pages deployment first. Repeat the
      one-byte relay probe and live Sync check after rollback.
      [Cloudflare rollback instructions](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)

      ```sh
      read -r -p 'Previous working Worker version ID: ' previous_worker_version
      npx wrangler rollback "$previous_worker_version"
      npx wrangler deployments list
      ```

    - If `v0.2.0` was published, edit its release notes to point readers to
      the last good version. Keep `v0.2.0` attached to its original commit.
      Use a new version for the next release.
