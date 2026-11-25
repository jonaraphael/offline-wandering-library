# Build a library in your browser

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in Chrome, Edge or Arc on a computer. Plug in a USB drive or SD card and
choose **Choose drive**. Select the drive's folder in the browser dialog.
OWL measures free space where the filesystem allows it and asks for the
label size when a measurement is unavailable. The category bar shows the
recommended library and the space left.

Choose **Sync** to download and verify files directly on the drive. **Pause**
waits until the download in progress is saved, then keeps completed files and
verified archive pieces; **Pause immediately** stops at once and discards the
unsaved part of that download. Open the page again and
choose **Reconnect** if the browser needs permission. **Sync** continues from
the drive's record. If the connection drops, the page waits and continues
when it returns. Keep the drive connected and the tab open during Sync. OWL
requests Screen Wake Lock while the tab is visible.

To build several drives at once, open the builder in a new window for each
drive. Each window remembers its own drive. A folder syncs in one window at
a time: another window that picks it shows **This drive is syncing in
another window**. Libraries in two folders of the same drive each plan for
the whole drive's free space, so give each library its own drive.

Choose **Manage what goes on it** and drag **Space for the library** to set
how much space OWL may use, including search and the reader. The category
sizes and bar update as you drag. The hatched portion stays free. The default
uses all available space up to 1 TB. At 1 GB and 8 GB, OWL keeps as many
higher-priority files from its 16 GB recommendation as fit. Reader apps are
included when the library contains an encyclopedia file.

Search eight categories, turn collections on or off, compare editions and
choose individual files. Your edits carry over when the limit moves.
**Reset to recommended** restores the default for the current limit.
**Make it fit** removes the lowest-priority selections when the choice
exceeds the limit. Advanced holds the FAT32 option, bulk actions, storage
accounting and diagnostics. **See what goes on a drive** opens a preview
with drive size buttons. The [standalone planner](../SELECT.html) also
generates commands for a Python build.

The drive stores its choice, storage limit and verified content. A later Sync applies that
choice to the latest available files. It verifies additions and replacements
before removing dropped files recorded by OWL. A replacement that needs
space beside the original waits for more room or an explicit **Replace in
place** choice in Manage. Files outside OWL's record stay on the drive.
**Check every file** rereads the selected files and downloads replacements
for failed checks.
If the drive record lost files that OWL wrote, Sync finds them by their
SHA-256 and keeps them. On a large drive the page shows **Checking the
files already on the drive** while it reads them.
After **Pause**, or an error that leaves the drive connected, the next Sync
trusts the drive record and starts at once. After a closed tab, a crash or an
unplugged drive, it rereads only the files written in the 10 minutes before
the sync last saved its record, since only those can have data the drive had
not yet stored.

Sync writes the new reader and updates `START_HERE.html` before clearing the
older reader files listed in the drive record. When Sync finishes, choose **Try it**
to open `START_HERE.html` in a new tab and read from the connected drive.
On another device, open `START_HERE.html` directly from the drive.
The build report lists any files that could not be downloaded.

### Add files with the Python builder

If the browser cannot download files you selected, run the Python builder in
a new folder on the same drive, such as `OWL Python`. Keep the two libraries
in separate folders and open `START_HERE.html` in the one you want to read.
If the browser library is at the top of the drive, close the builder and move
its `START_HERE.html` and `LIBRARY` together into a folder such as `OWL Browser`.
Choose that folder the next time you Sync.

For a single combined library, select the files you want from both builds in
the Python planner. To reuse a whole file you already downloaded, copy it to
the matching catalog path under the new folder's `LIBRARY/` before building.
Python checks the file's SHA-256 against the selected edition and creates a
new start page and search index for the combined selection. [Python build instructions](../README.md#build-with-python)

## Drives and readers

Use exFAT for a drive shared across Windows, macOS, Linux and phones. Android
USB and filesystem access depend on the device and storage provider. Phones
may have limited access to APFS or NTFS drives. Format drives with your
operating system's disk tool if needed. The browser builder runs on desktop.
Chromium uses the phone's app cache for Android content-URI writes, so those
writes cannot meet the direct-to-drive requirement. Firefox and Safari users
can use the Python build.

The browser copies the pinned Windows, Linux x86-64, macOS and Android Kiwix
packages from the publisher. Set up a compatible iPhone reader while online and
check it with your drive before taking it offline. To open split ZIMs, keep all
parts together and open the `.zimaa` part in a reader that supports them. Kiwix
Desktop uses libzim. Android split results vary with the app variant and
storage provider. See the device matrix for the current evidence and checks. [Kiwix Desktop file picker](https://github.com/kiwix/kiwix-desktop/blob/main/src/kiwixapp.cpp#L171-L189) ·
[Kiwix Android split archive issue](https://github.com/kiwix/kiwix-android/issues/4510) ·
[Kiwix JS split archives](https://github.com/kiwix/kiwix-js/issues/1496)

### How capacity is estimated

On macOS and Windows, OWL tries a temporary truncate-and-abort probe; exFAT and
NTFS volumes return a measured free-space estimate, and FAT32 or an inconclusive
result falls back to the label size. Linux asks for the size on the label,
because its exFAT driver rejects the probe and ntfs-3g allocates sparsely. See
the native-filesystem methodology, results, and Chromium call path.
[Capacity probe](capacity-probe.md)

### How files are written and verified

Sync writes files in priority order: essential files first, then the Kiwix
reader apps, then the rest. On a tight drive, an encyclopedia that needs room
to verify its incoming pieces can come before the apps. Verified archive
parts and pieces stay on the drive for the next Sync after a pause. When an
ordinary file runs out of space, Sync can release the unfinished copy and
try later files.

Kiwix ZIMs over 4 MiB start with six concurrent 4 MiB range requests. The
builder adds another request when throughput improves, up to eight. It reduces
concurrency after errors and retries missing ranges. A 16-piece window holds
up to 64 MiB of archive payload for ordered hashing. Each piece passes the
publisher’s SHA-1 check before writing. The whole archive must match its
SHA-256 pin before it appears in the offline library. The two published
SHA-256 part manifests add a check for the matching editions. Other files
use their whole-file SHA-256. **Check every file** rehashes installed
files on the drive. [Transfer evidence](browser-delivery.md)

On exFAT or NTFS, leave **Split large files for FAT32** off in Manage. OWL
closes each verified 4 MiB piece on the drive, assembles it into a 1 GiB part,
then joins the verified parts after every download in the sync is done, when
there is temporary space for a second copy. The page shows "combining *title*,
*n* of *total* parts" while it copies. Without room for the join, the split
archive remains available in the library. A later **Sync** joins the existing parts once there is room for the
second copy, without downloading the archive again.

Closing the tab can repeat at most the 64 MiB window being downloaded for a
publisher-pinned archive. Interrupted joins can repeat local copying. The
piece files need up to one extra split part's space while a part is being
written. Sync can import a prefix saved by an earlier browser build.
Turn on **Split large files for FAT32** for FAT32 drives. Keep the resulting files together and
open the `.zimaa` part in a compatible reader. Opening external archives in
place on phones remains unverified.
[Reader and filesystem tests](device-matrix.md) ·
[Chromium swap writer](https://chromium.googlesource.com/chromium/src/+/b694dcb617f6ed6a9e738461017c48cb0de0ba4a/content/browser/file_system_access/file_system_access_file_handle_impl.cc)

## Publish to GitHub Pages

Under **Settings → Pages → Build and deployment → Source**, choose **GitHub
Actions**. A push to `main` or a manual run of **tests** on `main` publishes
that commit without waiting for the test jobs; its pull request passed the
`pages` job before the merge. Set the `github-pages`
environment to allow deployments from `main` and set the `OWL_RELAY_BASE`
repository variable to the approved publisher relay origin.
The Pages build job generates `index.html`, `catalog.json`,
`chunk-manifests.json` and the same-origin copies, then uploads the site artifact
for the deploy job. [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

Sources with recorded browser access go direct, including the Kiwix CORS mirror.
Recorded byte-identical CORS alternates follow the direct route. A publisher
relay can serve configured non-archive files. Archive relay sampling is
separately opt-in. [Relay guide](../relay/README.md) The site can
serve eligible redistributable files whose primary sources lack CORS or use
mutable download URLs. The build
verifies their size and whole-file SHA-256 before publishing them and preserves
source credits. For selected ZIP members it verifies the ZIP source and each
named member before publishing, so the browser writes the original member bytes.
Unavailable or unlicensed copies stay in the Python path. Pages artifacts are
limited to 950 MB in this build, with published mirror pieces at most 80 MB.
[GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

Generate the site in a fresh directory and run the local fixtures.

```sh
python scripts/build_pages.py /tmp/owl-pages
python -m http.server --directory /tmp/owl-pages 8000
node --test tests/browser-builder.test.mjs tests/sync-reconcile.test.mjs
```

Use `--fetch-mirrors --cache /tmp/owl-mirror-cache` to publish the exact editions
in [the Pages mirror lock](../web/pages-mirrors.json). Pages reuses verified
cached bytes when available. With `--published-base`, it can recover a copy
from the prior deployment after a publisher source fails. It verifies the
reassembled SHA-256 before reusing the copy. If both routes and the cache lack
the exact bytes, the build fails before artifact upload and the current
deployment stays live.

The lock includes the publisher PDFs for GNU Bash, Coreutils and Make, the
Organic Seed Alliance seed-saving guide, and Siyavula’s grade 4–5 English
Natural Sciences learner books and teacher guides. It also includes the Book
Dash titles *Amazing Daisy* and *Come Back, Cat*. The grade 6 and grade
10–12 Siyavula books and OpenStax PDFs still depend on their publisher URLs.
The combined copies exceed the Pages artifact limit.

Update the lock deliberately when changing published copies. The generator validates checked-in archive part pins
against their catalog entries. To create a record from a downloaded split-bound
ZIM, run `python scripts/build_pages.py --archive-pins ASSET_ID FILE`.
The command emits JSON only after verifying the whole SHA-256.

## Search and phone reading

The build copies the precomputed search files for completed selected sources
and publishes the local search page, model and static shelves. The workflow
pins its shard URLs to the same Git commit used to build the site. Retrying a
search download reuses any verified chunks on the drive. See
[offline search](search.md).

Scan the **Reading on an iPhone?** card during Sync to install Kiwix while online. The start page on the drive links to critical files readable in
Files and lists the exact folders and names. The bundled Android APK can
install from the drive. Use the [device test kit](device-matrix.md) to check
file access and native ZIM reading on your devices.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| The drive is full | Free space or choose a larger drive. In **Manage what goes on it**, lower **Space for the library** and, if the selection still exceeds the limit, choose **Make it fit**. Then choose **Sync**. |
| The browser refused folder permission | Choose **Reconnect** or **Choose drive**, pick the drive folder and grant access when the browser asks. If the browser refuses the root, choose a folder on the drive that your account can write to. |
| The browser is unsupported | Open the builder in Chrome, Edge or Arc on a computer. You can also use the [Python builder](usage.md). |
| OWL asks for the drive size on Linux or FAT32 | Choose the size printed on the drive. Reduce **Space for the library** if other files already use some of it. For FAT32, keep **Split large files for FAT32** on. |
| An archive was kept in parts | Keep the parts together and open `.zimaa` in a compatible reader. On exFAT or NTFS, free room for a second copy and choose **Sync** to retry joining. |
| Items are missing after Sync | Open **Show details** or the drive’s build report to see the source errors. Reconnect the drive, check free space and the connection, then choose **Try those again**. |
| The verifier says `INCOMPLETE` or `SUPPORT INCOMPLETE` | Check the build report for missing titles and choose **Sync** or **Try those again**. Rerun `python -I LIBRARY/VERIFY.py --strict` from the drive. Use `--accept-partial` only when you intend to accept missing content or support files. Checksum errors still fail verification. |
