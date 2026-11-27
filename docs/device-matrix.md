# Offline reading device matrix

Record the device model, OS version, reader version, filesystem, build ID and
result for each test. Use airplane mode on phones and disconnect desktop
networking before opening the fixtures. Keep the single-file and split copies
in separate folders if a reader treats them as the same publication.

## Make the drive

```sh
python -m pip install -e '.[zim]'
python scripts/build_device_test_kit.py --folder /tmp/owl-device-fixture
python scripts/build_device_test_kit.py --image /tmp/owl-device-test.dmg
```

The second command creates a fresh exFAT image on macOS. Mount the image or
copy the folder contents to the root of an existing exFAT USB-C drive.
`--readers-from /Volumes/OWL` copies `LIBRARY/SOFTWARE` from a built library.
Use that option to test the packaged programs and the offline APK install.
Both commands require a new output path.

Open `START_HERE.html`. With scripts disabled the page lists every title
with the folders that lead to it. Open `LIBRARY/BOOKS/phone-test.pdf` and read the fixture sentence.
With this test fixture, open **Search** in the reader and enter **weather vane**.
The expected first result is **Weather vane**, linked to
the PDF’s first physical page. The bundled fixtures show the same marker
article in `LIBRARY/ZIM/reader-test.zim` and in the two split parts
`split-test.zimaa` and `split-test.zimab`.

## Archive policy and reader support

In a computer browser, choose **Open** on an encyclopedia in
`START_HERE.html`. Chrome and Edge ask to read the drive and can remember
the folder for later visits. In Firefox and Safari, select `LIBRARY/ZIM`
and keep the page open to reuse the selection. Keep all parts of a split
ZIM together. The reader shows an article in the page or offers the file
location and the bundled Kiwix app when an archive cannot be displayed.


Browser downloads checkpoint in split parts. On drives that accept large
files, the builder attempts an optional on-drive join. Check free space for
the temporary second copy. If the join cannot fit, keep the split set
together. On detected FAT32 volumes, Python writes pinned ZIMs that exceed
the single-file limit as verified 1 GiB parts. Keep the parts together and
open the first one, ending in `.zimaa`, in a compatible reader.

Windows and Linux Kiwix Desktop explicitly accepts `.zimaa`. Android
external storage support depends on the reader variant and the file provider.
Published reports show split-opening failures in Android 3.8.1/3.9.0 and in
the 4.0.0 local-library flow. [Desktop file picker](https://github.com/kiwix/kiwix-desktop/blob/main/src/kiwixapp.cpp#L171-L189) ·
[Android external storage issue](https://github.com/kiwix/kiwix-android/issues/3605) ·
[Android local split issue](https://github.com/kiwix/kiwix-android/issues/4510)

Apple grants directory-wide access when an app opens the directory through its
document picker. Opening one external file grants access through that file’s
security-scoped URL. Kiwix Apple 3.14.0 uses a one-file importer for the
ZIM type and bookmarks the file’s URL. Split playback from USB remains
unconfirmed. The Kiwix JS PWA
documents selecting all pieces together. Test in-place playback and look for
new phone-local storage use. [Apple directory access](https://developer.apple.com/documentation/uikit/providing-access-to-directories) ·
[Apple external document access](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/DocumentPickerProgrammingGuide/AccessingDocuments/AccessingDocuments.html) ·
[Kiwix Apple importer](https://github.com/kiwix/kiwix-apple/blob/3.14.0/Views/ViewModifiers/FileImport.swift#L39-L45) ·
[Kiwix Apple file bookmark](https://github.com/kiwix/kiwix-apple/blob/3.14.0/Model/ZimFileService/ZimFileService.swift#L106-L123) ·
[Kiwix JS PWA](https://kiwix.github.io/kiwix-js-pwa/dist/)

On exFAT or NTFS the browser joins verified parts when the single-file
option is selected and temporary space allows it. For FAT32, keep split
output selected.
A single file avoids dependence on split-reader support. USB access, phone
provisioning and in-place playback still depend on the individual device.

## Platform checks

| Test | Procedure and expected result | Physical result |
| --- | --- | --- |
| Windows 10 or 11, x64 | On exFAT, unpack the portable reader ZIP into an OWL software folder or a local folder. Run `kiwix-desktop.exe` and open the single ZIM. Then give the reader the first split part with its sibling beside it. Record whether both display the marker and whether the file dialog needs **All files**. | Pending |
| macOS | Open the bundled Kiwix DMG while offline, launch the app, and record any Gatekeeper message. Open the single ZIM and the first split part separately. Record whether the app reads the files in place and keeps bookmarks after unplug and reconnect. | Pending |
| Linux x86-64 | Copy the AppImage to a filesystem where you can set the execute bit, run `chmod +x <file>`, then launch it. Keep the ZIMs on exFAT. Open the single ZIM and the first split part separately. If FUSE is unavailable as part of the tested system, record the alternate launch method used. | Pending |
| Android with USB OTG | In airplane mode, connect the drive and open the standalone APK under `LIBRARY/SOFTWARE/ANDROID` in Files. Allow that app to install unknown apps if Android prompts. Open the standalone Kiwix build, choose its file picker, select the USB volume through the Storage Access Framework, and open the single ZIM. Repeat with both split parts beside each other. Verify the reported storage location stays on USB and confirm what happens after reconnect. | Pending |
| USB-C iPhone, Files | In airplane mode, open Files → Browse → Locations and select the drive. Open `START_HERE.html` first, then the PDF path directly. Open a WikiMed PDF using the checklist below. Record whether Files follows sibling links. | 2026-11-22, owner's iPhone, browser-built exFAT drive: nothing opened when the drive was plugged in; Files previewed `START_HERE.html` as the static page, a plain list of titles and paths, with the scripts not run. On November 26 the category link prompted to leave Files and **Open** dismissed it. See the updated catalog checks below. |
| USB-C iPhone, native Kiwix | While online, scan the builder’s App Store QR code and install Kiwix. In airplane mode, try the Kiwix document picker with the USB single ZIM, then its split copy. Record in-place playback or any import and storage growth. | Pending |
| USB-C iPhone, Kiwix JS PWA | In Safari while online, open the Kiwix PWA, add it to the Home Screen and wait for caching. Relaunch from the Home Screen in airplane mode. Use **Select Storage** or the file picker to open the USB ZIM. Record whether the app itself loads, USB appears, the marker renders, and the same steps work with split parts. | Pending |

Windows and Linux Kiwix Desktop rely on libzim. A local libzim fixture can
establish split decoding. The app dialog and physical disk check are separate.
The Kiwix Android full variant provides the file picker and its issue tracker
records split-archive behavior that varies by edition and storage location.
Record the standalone APK version, Android build and provider for every result.
[Kiwix Desktop](https://github.com/kiwix/kiwix-desktop)
[libzim multipart changes](https://github.com/openzim/libzim/blob/main/ChangeLog)
[Apple reader 3.14 dependencies](https://github.com/kiwix/kiwix-apple/blob/main/CHANGELOG.md#3140)
[Android variants](https://github.com/kiwix/kiwix-android#important-notes)
[Android split issue](https://github.com/kiwix/kiwix-android/issues/4510)
[Android external split issue](https://github.com/kiwix/kiwix-android/issues/3605)

iPhone installs Kiwix while online through the App Store. Files can open
the directly readable layer without Kiwix. Apple documents exFAT and notes
that some external drives require a powered adapter. Check Kiwix's file
picker separately from Files. [Apple external drives](https://support.apple.com/guide/iphone/external-storage-devices-iph95baac91f/ios)
[Kiwix for iPhone](https://apps.apple.com/us/app/kiwix/id997079563)
[Kiwix JS PWA](https://github.com/kiwix/kiwix-js-pwa)

## START_HERE in the iPhone Files preview

Files opens `START_HERE.html` in Quick Look. Scripts do not run there, styles
written in the file apply, files beside the page do not load, and a link to
another file on the drive asks to open and then opens nothing. Safari cannot
open a local file, and iOS offers no built-in app that can. A link to an
`https://` address opens Safari after a confirmation. Plugging the drive in
triggers nothing: iOS has no autorun and no notification an app or a drive
can use. Files shows a generic icon for an `.html` file and hides the
extension, so the entry appears as `START_HERE` after `LIBRARY`.
[Apple external storage](https://support.apple.com/guide/iphone/external-storage-devices-iph95baac91f/ios) ·
[Quick Look link handling](https://developer.apple.com/documentation/quicklook/qlpreviewcontrollerdelegate/previewcontroller(_:shouldopen:for:)) ·
[Local HTML in Files](https://developer.apple.com/forums/thread/710001)

A web page cannot stand in for an app here. Safari's folder picker
(`webkitdirectory`, iOS 18.4 and later) copies the whole chosen folder into
the phone's temporary storage before the page sees a file, and iOS Safari has
no `showDirectoryPicker`.
[WebKit upload panel](https://github.com/WebKit/WebKit/blob/main/Source/WebKit/UIProcess/ios/forms/WKFileUploadPanel.mm) ·
[Safari 18.4 notes](https://developer.apple.com/documentation/safari-release-notes/safari-18_4-release-notes)

On the reported KINGSTON drive, even a same-page category link triggered the
leave-Files prompt and **Open** dismissed it. Files also returned no matches for
the exact WHO filename with KINGSTON selected. The screenshots establish the
failed lookup. They do not identify how iOS indexed that USB volume.

After refreshing the indexes, test both entry files in airplane mode.

1. In the HTML preview, expand **Health**, then expand a book with **Show chapters**.
   Touch and hold a filename and copy it. Paste it into Files search and select
   the drive scope. If it returns no matches, open the displayed folders.
2. From Files, open **START_HERE_FOR_IPHONES.pdf** in Preview. Tap the
   magnifying glass and search for `splint`, then for a title and a filename.
   This searches the PDF's text on the phone. Record whether the yellow mark is
   in view or under Preview's top bar.
3. Tap **Home** at the top left, then a red urgent tile, then **Open** in "Leave
   Preview and open this link?". Record whether the guide opens in Preview.
   Repeat from **Browse by subject** with a book title and with a chapter of a
   multi-part book. If the drive is missing in Preview's Browse screen, start
   from Files using **Open With → Preview**. Record the OS, drive format, and
   viewer for each result.

Each blue title is a Files link:
`shareddocuments:///private/var/mobile/Library/LiveFiles/com.apple.filesystems.userfsd/<volume UUID>/LIBRARY/…pdf?open`.
With `?open`, Files hands the book to Preview to open in place. Preview does
not follow a PDF link to another file (`GoToR`), and a relative link opens
nothing after its prompt. In the iOS 27.2 simulator on 2026-11-26, the Files
link opened the linked book in Preview after one confirmation. The `GoToR` link
did nothing, and the relative link showed the prompt and then nothing.

iOS names a USB drive's folder by its volume UUID, not its label. On
2026-11-26 an iPhone running iOS 27 opened `OWL-link-test/1_Link_test.pdf` from
the FAT32 drive KINGSTON. 3 of 3 links built on the UUID
`D8CE3C96-2155-39B9-ACA4-EA1CF1876615` worked: the book with `?open` from
`/private/var/…` and from `/var/…`, and the drive's top folder. 0 of 4 built on
the label `KINGSTON` worked, including a `file://` link. A bare
`shareddocuments://` link opened Files.
macOS reports the same UUID as `VolumeUUID` in `diskutil info -plist`. For FAT,
Apple derives it from the boot sector's volume ID and total sector count
([msdosfs `generateVolumeUuid`](https://github.com/apple-oss-distributions/msdosfs/blob/main/msdos_appex/utils.m)),
so renaming the drive keeps it and reformatting changes it.

The Python builder reads the UUID with `diskutil` when it writes to a drive
under `/Volumes`. A browser cannot read a volume UUID or a boot sector, and
neither can the Python builder on Linux or Windows without raw device access.
It saves the location in `LIBRARY/.owl/iphone-drive.json` as
`{"path": "<UUID>[/folders]", "folder": "<name of the folder holding LIBRARY>"}`.
A builder that cannot read the UUID reuses that record. The file sits beside
the builders' private records, outside `SHA256SUMS.txt`, so a browser Sync
reads it without owning it and `owl copy` leaves it behind. A builder ignores
the record when the folder's name differs, so a library copied by hand to a
differently named drive stops linking to the original. A Windows drive root has
no name to compare. Without a location, each title links to a bare
`shareddocuments://`, which switches to Files, and the page says to follow the
folders under the title. In that case an urgent tile jumps to its guide's
folders inside the PDF, and the filename stands alone above them.

In the iOS 27.2 simulator on 2026-11-26, the start page filled one iPhone 17
screen. A search for `splint` reported 3 matches and jumped to the chapter
lists that carry the word, with the yellow mark under Preview's top bar in 2 of
2 matches looked at. The **Stop severe bleeding** tile showed the prompt and
**Open** opened chapter 10 of *Where There Is No Doctor*. Preview's sidebar
showed page thumbnails, not the PDF's outline. A title that is not a PDF links
to its folder in Files, a form the phone test covered only for the drive's top
folder.
[Preview search](https://support.apple.com/guide/iphone/iph7a0cdad0c/ios)
· [PDFKit remote-open delegate](https://developer.apple.com/documentation/pdfkit/pdfviewdelegate/pdfviewopenpdf%28_%3Aforremotegotoaction%3A%29)
· [Files search scopes](https://support.apple.com/guide/iphone/iphe4bff8827/ios)

## WikiMed in Files

1. Use a drive build that includes the April 2026 WikiMed archive. Put the
   iPhone in airplane mode. In Files, open **Browse** and select the drive
   under **Locations**.
2. Open **Help** in `START_HERE.html` and look for **WikiMed PDFs**. If Files
   shows a preview, use the listed locations or browse directly to
   `LIBRARY/CRITICAL/MEDICAL/WIKIMED-PHONE`.
3. Open `wikimed-emergencies.pdf`. Tap **Choking** in the contents and check
   that it jumps to the article. Open the viewer's outline if offered, then
   look up “abdominal thrusts” with the viewer’s text search. Try selecting text.
4. Open `wikimed-family-health.pdf` and find **Postpartum bleeding** in the
   contents. Disconnect and reconnect the drive, then repeat one open. Record
   the iPhone model, iOS version, drive format, and which contents links,
   outline, and find controls worked while offline.

Twelve volumes cover emergencies, common symptoms, infections, chronic
disease, pregnancy, childhood, mental health, medicines and prevention. Each
has selectable text, linked contents, article outlines, and Wikipedia
revision links for attribution. The export omits illustrations,
infoboxes and reference lists. Each volume carries the CC BY-SA 4.0 notice.
The browser builder downloads the 35.4 MB of prebuilt files from the same
Pages origin and verifies each SHA-256 before adding them to Health and Help.
The Python builder installs the same volumes from the repository and can
regenerate them from the catalog-pinned ZIM with libzim and ReportLab:

```sh
python scripts/build_wikimed_phone.py /path/to/wikipedia_en_medicine_maxi_2026-04.zim OUTPUT
```

The volumes are sized within the drive's existing discovery allowance.
In iPhone Quick Look, use Kiwix for the encyclopedia archive. [Apple Files and Quick Look](https://support.apple.com/guide/iphone/find-and-view-files-and-folders-iph4bff8827/ios)

## Local checks

A macOS-generated exFAT disk image contains both fixtures and the static
start page. libzim reads the marker in both copies. The downloaded Kiwix
macOS 3.14 app passed code signature and notarization ticket validation. Chrome 158 returned the expected PDF page from `file://` with
DevTools networking disabled. Firefox 160.0.1 and a local system WebKit
view returned the same PDF location. Safari WebDriver requires a developer
setting on this Mac, so the WebKit result records the engine fixture. The
upstream Kiwix JS 4.4.0 bundle attempted
to fetch local decompressor WebAssembly files in Chrome and failed to open
both ZIM fixtures. Firefox also failed to display the fixture article with
the upstream bundle. These upstream checks predate the on-page OWL reader. [Kiwix JS documentation](https://github.com/kiwix/kiwix-js)
