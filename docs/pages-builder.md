# Build a library in your browser

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in Chrome, Edge or Arc on a computer. The page has three steps.

1. **Choose your drive.** Pick the drive's root or an empty folder on it. The
   page measures the free space. When it cannot, it asks for the size printed
   on the drive; picking a size is the confirmation. Without a drive, the size
   buttons preview what each size would hold.
2. **Review the library.** The recommendation uses the same capacity ladder as
   the Python builder and fills spare space with files that have browser
   routes while preserving the field allocations that the reviewed ladder
   protects. The summary shows the selected download bytes by theme, including
   the reader packages. The list shows what is on the drive, grouped by theme;
   a theme or collection unfolds to show what is inside.
3. **Build.** The build screen shows progress in bytes, speed, time left and
   the file in hand, with **Pause**.

**Customize** switches the list to editing: every collection appears with a
checkbox, a search field, an on-drive / not-included switch and a priority
filter. A collection unfolds to its files and, where one exists, its editions
(the recommended edition is marked). A file the browser cannot download stays
unchecked and is labeled for the desktop builder. Use the
[standalone planner](../SELECT.html) to include those files in a desktop build;
its **Storage details** lists the planning allowances. **Reset to recommended**
discards the changes.

Choose **Build library**. Keep the tab open, the computer awake and the drive
attached. A 1 TB transfer takes about 44–111 hours at 50–20 Mbps, before
retries and verification. The page requests Screen Wake Lock while visible.
If the connection drops, it waits, probes with increasing delays and continues
automatically when it can connect. Pause, or choose **Resume build** after
reopening the page or reconnecting the drive; a remembered drive with an
unfinished library opens on that screen. Resume uses the original selection,
archive layout and search allowance. It accepts a newer catalog when each
saved file retains its original pin, size and destination.

After the build, open `START_HERE.html` on the drive. It starts with search,
then "Need help right now?" cards that open the guide for each emergency task,
subjects, shelves and help for each kind of device. Every page carries the same
tabs: Home, Search, Essentials, Subjects, Books, All files and Help. A book
published as one file per chapter appears once, with its chapters inside. The
build report lists unavailable files. In a viewer that cannot run the search
script (an iPhone file preview, for example) the start page prints each item's
folder path and unfolds its full file list; where the script runs, the paths
are hidden and the lists fold.
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

When single-file output is selected, the browser writes the largest archives
first to leave more room for joining. Split-only builds download in priority
order, with readers first. If the drive fills, verified archive pieces and
parts stay available for **Resume**. The builder can reclaim an unfinished
ordinary file and try later files.

Kiwix ZIMs over 4 MiB start with six concurrent 4 MiB range requests. The
builder adds another request when throughput improves, up to eight. It reduces
concurrency after errors and retries missing ranges. A 16-piece window holds
up to 64 MiB of archive payload for ordered hashing. Each piece passes the
publisher’s SHA-1 check before writing. The whole archive must match its
SHA-256 pin before it appears in the offline library. The two published
SHA-256 part manifests add a check for the matching editions. Other files
use their whole-file SHA-256. **Check and repair every file** rehashes installed
files on the drive. [Transfer evidence](browser-delivery.md)

On exFAT or NTFS, leave **Save each archive as one file** selected. OWL
closes each verified 4 MiB piece on the drive, assembles it into a 1 GiB part,
then joins the verified parts when there is temporary space for a second
copy. Without room for the join, the split archive remains available in the
library. Free space and choose **Resume** to retry the join using those parts.

Closing the tab can repeat at most the 64 MiB window being downloaded for a
publisher-pinned archive. Interrupted joins can repeat local copying. The
piece files need up to one extra split part's space while a part is being
written. Resume can import a prefix saved by the previously deployed builder.
Turn off single-file output for FAT32. Keep the resulting files together and
open the `.zimaa` part in a compatible reader. Opening external archives in
place on phones remains unverified.
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
