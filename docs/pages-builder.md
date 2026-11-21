# Build a library in your browser

Open the [OWL library builder](https://jonaraphael.github.io/offline-wandering-library/)
in desktop Chrome or Edge. Connect a drive and choose its root or an empty folder
on it. Confirm the drive's label size when the page asks. Choose a preset or
enter a size in decimal GB. The recommendation uses the same capacity ladder
as the Python builder.

Edit the plan by collection, file or topic. The meter shows the files the browser
can build and whether they fit. Expand **Storage details** for the planner's
estimates. Expand the omitted-files list to see which files need the Python
builder. You can build the available selection after accepting the omissions.
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

After the build, open `START_HERE.html` on the drive. It links to shelves, a
topic atlas and the files. Paths are printed for file viewers that block links.
The browser build's atlas uses catalog topic assignments. Search shards are
planned for a later round. The browser writes a whole-file inventory, a
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
Desktop uses libzim. Kiwix Android supports opening split archives from storage,
with application variant and platform differences in storage access. Kiwix JS
groups the parts and may require selecting them together. Its reader
installation is separate. [Kiwix Desktop file picker](https://github.com/kiwix/kiwix-desktop/blob/main/src/kiwixapp.cpp#L171-L189) ·
[Kiwix Android split archive issue](https://github.com/kiwix/kiwix-android/issues/4510) ·
[Kiwix JS split archives](https://github.com/kiwix/kiwix-js/issues/1496)

### How capacity is estimated

File System Access supplies a folder handle. On macOS, OWL attempts to estimate
available bytes by truncating and aborting a temporary writable on the selected
drive. A quick 64 MiB check precedes attempts above 4 GiB. If the filesystem
accepts 2 TiB, the drive could be sparse or larger than the probe's range. A
4 GiB + 1 byte rejection can indicate FAT32 or too little free space. Both cases
fall back to a drive-size confirmation. A repeatable allocation boundary
above 4 GiB yields an estimate rounded down within 1 MiB of that boundary.
Windows and Linux use manual confirmation in this release.

Chromium truncates a swap file through `NativeFileUtil::Truncate`,
`base::File::SetLength`, and `ftruncate` on POSIX. Chromium converts a failed
`SetLength` to `FILE_ERROR_FAILED`, which Blink reports as
`InvalidStateError`, so the probe cannot identify ENOSPC and EFBIG by
exception name there. Operations that preserve `FILE_ERROR_NO_SPACE` report
`QuotaExceededError`. The macOS exFAT allocation and FAT32 limit were measured
with `ftruncate` on disk images. APFS, HFS+, Linux and Windows filesystem
behavior and browser measurements on removable hardware remain unverified.
[Chromium writer](https://github.com/chromium/chromium/blob/main/content/browser/file_system_access/file_system_access_file_writer_impl.cc#L199-L224) ·
[Native truncate](https://github.com/chromium/chromium/blob/main/storage/browser/file_system/native_file_util.cc#L277-L295) ·
[POSIX SetLength](https://github.com/chromium/chromium/blob/main/base/files/file_posix.cc#L419-L425) ·
[Blink error mapping](https://github.com/chromium/chromium/blob/main/third_party/blink/renderer/core/fileapi/file_error.cc#L138-L165)

### How files are written and verified

The browser downloads files in priority order, with readers first. When a
write reports a full drive, it reclaims an unfinished file's space, records the
omission and tries the remaining files. The start page lists omissions. Use
**Resume** after freeing space or to retry an upstream download failure. Committed parts are
re-read on resume to check their SHA-256 and reconstruct the whole-file digest.

OWL writes ZIMs over 1 GiB as consecutive parts with a maximum of 1 GiB each.
Chromium places a swap file beside the destination and replaces it on close.
Its after-write checks can read and hash the swap again before close completes.
OWL bounds swap work per part and uses a fresh swap for each piece. A tab close
can require re-downloading the current, uncommitted part. Source files stream
directly into the selected drive. [Chromium swap writer](https://github.com/chromium/chromium/blob/main/content/browser/file_system_access/file_system_access_file_handle_impl.cc#L681-L714) ·
[Chromium after-write checks](https://github.com/chromium/chromium/blob/main/content/browser/file_system_access/file_system_access_safe_move_helper.cc#L169-L219)

Single-file downloads are checked against their catalog SHA-256 before close.
For split ZIMs, separately published SHA-256 part pins are compared when
available. Other ZIMs use SHA-256 checks recorded on the drive for each part
during transfer and the catalog's whole-file pin before the archive can
appear in the offline index. Same-origin copies have a published SHA-256 for
each hosted piece. Hashing uses the pinned vendored noble-hashes implementation.
[Vendor record](../web/vendor/noble-hashes/README.md)

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
