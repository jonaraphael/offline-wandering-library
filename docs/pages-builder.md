# Build a library in your browser

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in desktop Chrome or Edge. Connect a drive and choose its root or an empty folder
on it. Confirm the drive's label size when the page asks. Choose a preset or
enter a size in decimal GB. The recommendation uses the same capacity ladder
as the Python builder and fills spare space with files that have browser
routes. The meter shows selected download bytes, including reader packages.

Edit by collection, file or topic. Each collection has **Show files**.
An unavailable file stays unchecked and its collection links to the desktop
tool instructions. Use the [standalone selector](../SELECT.html) to include
those files in a desktop build. Expand **Storage details** to see the planning
allowances.

Choose **Build library**. Keep the tab open, the computer awake and the drive
attached. A 1 TB transfer takes about 44–111 hours at 50–20 Mbps, before
retries and verification. The page requests Screen Wake Lock while visible.
If the connection drops, it waits, probes with increasing delays and continues
automatically when it can connect. Pause or choose **Resume** after reopening
the page or reconnecting the drive. Resume uses the original selection,
archive layout and search allowance. It accepts a newer catalog when each
saved file retains its original pin, size and destination.

After the build, open `START_HERE.html` on the drive. The emergency directory takes you to the available guide for each task. The build report lists unavailable files. The start page also links to shelves, the topic atlas and book contents. Paths are printed for file viewers that block links.
The browser build’s atlas uses catalog topic assignments. Offline search uses
the available precomputed shards and catalog index. The browser writes a whole-file inventory, a
per-file or per-part checksum listing, and the standalone Python verifier.

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

In single-file mode, the browser writes the largest archives first so their
checkpoints fit. In split mode, it downloads in priority order, with readers first. If a write
reports a full drive and the drive remains accessible, the builder reclaims
the current unfinished file and tries later files. Free space and choose
**Resume** to retry the omitted files.

Kiwix ZIMs over 4 MiB start with six concurrent 4 MiB range requests. The
builder adds another request when throughput improves, up to eight. It reduces
concurrency after errors and retries missing ranges. A 16-piece window holds
up to 64 MiB of archive payload for ordered hashing. Each piece passes the
publisher’s SHA-1 check before writing. The whole archive must match its
SHA-256 pin before it appears in the offline library. The two published
SHA-256 part manifests add a check for the matching editions. Other files
use their whole-file SHA-256. **Verify and repair files** rehashes installed
files on the drive. [Transfer evidence](browser-delivery.md)

On exFAT or NTFS, leave **Save each archive as one file** selected. When
the drive has room for two copies of the current archive, OWL saves verified
pieces on the drive, commits them into 1 GiB parts, then joins those parts.
A paused or closed tab can reuse every saved, intact piece. At most 64 MiB
of the current transfer window can be in flight or awaiting a commit. If the
drive fills while joining, the verified parts remain readable. Resume can
try the join again after space is freed.

With less working space, OWL still downloads ranges in parallel. The
single-file writer uses the last committed prefix it can fit beside the
on-drive swap. Closing the tab can lose everything after that prefix,
or the entire unfinished archive if no prefix fits. For split mode,
piece-by-piece checkpoints need space for one additional part. With less
space, committed 1 GiB parts are the resume points. Existing browser-build
records keep their selection and layout. A saved single-file prefix can
be reused directly or imported to verified parts when space allows.

Turn off the single-file option for FAT32. Split builds can resume after each
committed part. The first part is `.zimaa`. Desktop Kiwix supports split
archives. A single archive avoids split-reader requirements on Android and
iPhone. Opening external archives in place on phones remains unverified.
[Reader and filesystem tests](device-matrix.md) ·
[Chromium swap writer](https://chromium.googlesource.com/chromium/src/+/b694dcb617f6ed6a9e738461017c48cb0de0ba4a/content/browser/file_system_access/file_system_access_file_handle_impl.cc)

## Publish to GitHub Pages

Under **Settings → Pages → Build and deployment → Source**, choose **GitHub
Actions**. The Pages workflow runs on a push to `main` or
`t3/council-offline-library-audit`. If the repository already restricts the
`github-pages` environment to particular branches, include the deployment branch.
The separate Pages build job generates `index.html`, `catalog.json`,
`chunk-manifests.json` and the same-origin copies, then uploads the site artifact
for the deploy job. [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

Sources with recorded browser access go direct, including the Kiwix CORS mirror.
Recorded byte-identical CORS alternates follow the direct route. A publisher
relay can serve configured non-archive files. Archive relay sampling is
separately opt-in. [Relay guide](../relay/README.md) The site can
serve eligible redistributable files whose primary sources lack CORS. The build
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
node --test tests/browser-builder.test.mjs
```

Use `--fetch-mirrors --cache /tmp/owl-mirror-cache` to publish the exact editions
in [the Pages mirror lock](../web/pages-mirrors.json). Pages reuses verified
cached bytes when available. If a required copy is unavailable or mismatched,
the build fails before artifact upload and the current deployment stays live.
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

Open **Set up an iPhone for offline reading** to scan the App Store QR code
while online. The start page on the drive links to critical files readable in
Files and lists the exact folders and names. The bundled Android APK can
install from the drive. Use the [device test kit](device-matrix.md) to check
file access and native ZIM reading on your devices.
