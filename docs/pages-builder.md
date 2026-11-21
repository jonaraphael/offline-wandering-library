# Build a library in your browser

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in desktop Chrome or Edge. Connect a drive and choose its root or an empty folder
on it. Confirm the drive's label size when the page asks. Choose a preset or
enter a size in decimal GB. The recommendation uses the same capacity ladder
as the Python builder and fills spare space with files that have browser
routes. The meter shows deliverable bytes and the size of the selected files
available through Python.

Edit the plan by collection, file or topic. The meter shows the files the browser
can build and whether they fit. Expand **Storage details** for the planner's
estimates. The editor flags collections and individual files that need Python. The build section names the affected critical topics. You can build the available selection after accepting the omissions.
Use **Python build instructions** for a command that retains the original
selection, or use the [standalone selector](../SELECT.html) in your checkout.

Choose **Build library**. Keep the tab open, the computer awake and the drive
attached. A 1 TB transfer takes about 44–111 hours at 50–20 Mbps, before
retries and verification. The page requests Screen Wake Lock while visible. Pause, close the tab
or reconnect the drive and choose **Resume** to continue from saved parts. The
browser remembers the last drive folder when its storage permissions permit it.
You can also choose the folder again. Resume uses the original selection. It
accepts a newer catalog when each saved file retains its original pin, size and
destination.

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

On macOS, OWL tries a temporary truncate-and-abort probe. Windows and Linux
ask for the size on the label. See the native-filesystem methodology, results,
and Chromium call path. [Capacity probe](capacity-probe.md)

### How files are written and verified

The browser downloads in priority order, with readers first. If a write
reports a full drive and the drive remains accessible, the builder reclaims
the current unfinished file and tries later files. Free space and choose
**Resume** to retry the omitted files.

ZIMs over 1 GiB download in consecutive 1 GiB parts. Chromium’s write swap is
on the destination volume. If a tab closes, the current uncommitted part
downloads again. Routine resume checks saved sizes and restores the recorded
digest state. Choose **Verify and repair files** to re-read and hash installed
payloads and retry damaged files. The standalone verifier on the drive
offers independent read-only verification.

The publisher’s 4 MiB SHA-1 piece digests cover all 117 cataloged Kiwix ZIMs
and catch wrong bytes during each transfer. SHA-256 pins protect the entire
archive. The two locally generated SHA-256 part manifests provide another
check for their matching editions. Every other asset also has a whole-file
SHA-256 pin. [Transfer evidence](browser-delivery.md)

On exFAT or NTFS, leave **Join archive parts into single files when space
permits** selected. The builder verifies the assembled ZIM on the drive
before removing its parts. Joining can temporarily require a second copy of
that archive. If it cannot fit, the verified parts remain usable with a
compatible reader. Clear this option for FAT32. A resumed build keeps its
original setting. [Reader and filesystem tests](device-matrix.md) ·
[Chromium swap writer](https://github.com/chromium/chromium/blob/main/content/browser/file_system_access/file_system_access_file_handle_impl.cc#L681-L714)

## Publish to GitHub Pages

Under **Settings → Pages → Build and deployment → Source**, choose **GitHub
Actions**. The Pages workflow runs on a push to `main` or
`t3/council-offline-library-audit`. If the repository already restricts the
`github-pages` environment to particular branches, include the deployment branch.
The separate Pages build job generates `index.html`, `catalog.json`,
`chunk-manifests.json` and the same-origin copies, then uploads the site artifact
for the deploy job. [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

Sources with recorded browser access go direct, including the Kiwix CORS mirror.
Recorded byte-identical CORS alternates follow the direct route. The site can
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

Use `--fetch-mirrors --cache /tmp/owl-mirror-cache` on the generator to include
pinned same-origin content. The generator validates checked-in archive part pins
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
