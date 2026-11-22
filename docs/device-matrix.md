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

Open `START_HERE.html`. The HTML page prints paths and works with scripts
disabled. Open `LIBRARY/BOOKS/phone-test.pdf` and read the fixture sentence.
Open `LIBRARY/SEARCH.html` in a desktop browser and search for **weather vane
wind direction**. The expected first result is **Weather vane**, linked to
the PDF’s first physical page. The bundled fixtures show the same marker
article in `LIBRARY/ZIM/reader-test.zim` and in the two split parts
`split-test.zimaa` and `split-test.zimab`.

## Archive policy and reader support

Browser downloads checkpoint in split parts. On drives that accept large
files, the builder attempts an optional on-drive join. Check free space for
the temporary second copy. If the join cannot fit, keep the split set
together. Python writes a single file and rejects archives that exceed its
detected FAT32 file limit.

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

New browser builds use single-file archives on exFAT or NTFS when the
single-file option is selected. The FAT32 option writes split files.
A single file avoids dependence on split-reader support. USB access, phone
provisioning and in-place playback still depend on the individual device.

## Platform checks

| Test | Procedure and expected result | Physical result |
| --- | --- | --- |
| Windows 10 or 11, x64 | On exFAT, unpack the portable reader ZIP into an OWL software folder or a local folder. Run `kiwix-desktop.exe` and open the single ZIM. Then give the reader the first split part with its sibling beside it. Record whether both display the marker and whether the file dialog needs **All files**. | Pending |
| macOS | Open the bundled Kiwix DMG while offline, launch the app, and record any Gatekeeper message. Open the single ZIM and the first split part separately. Record whether the app reads the files in place and keeps bookmarks after unplug and reconnect. | Pending |
| Linux x86-64 | Copy the AppImage to a filesystem where you can set the execute bit, run `chmod +x <file>`, then launch it. Keep the ZIMs on exFAT. Open the single ZIM and the first split part separately. If FUSE is unavailable as part of the tested system, record the alternate launch method used. | Pending |
| Android with USB OTG | In airplane mode, connect the drive and open the standalone APK under `LIBRARY/SOFTWARE/ANDROID` in Files. Allow that app to install unknown apps if Android prompts. Open the standalone Kiwix build, choose its file picker, select the USB volume through the Storage Access Framework, and open the single ZIM. Repeat with both split parts beside each other. Verify the reported storage location stays on USB and confirm what happens after reconnect. | Pending |
| USB-C iPhone, Files | In airplane mode, open Files → Browse → Locations and select the drive. Open `START_HERE.html` first, then the PDF path directly. Open a WikiMed PDF using the checklist below. Record whether Files follows sibling links. | Pending |
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

## WikiMed in Files

1. Use a drive build that includes the April 2026 WikiMed archive. Put the
   iPhone in airplane mode. In Files, open **Browse** and select the drive
   under **Locations**.
2. Open **Critical files for phones** from `START_HERE.html`. If Files
   restricts the link, browse directly to
   `LIBRARY/CRITICAL/MEDICAL/WIKIMED-PHONE`.
3. Open `wikimed-emergencies.pdf`. Tap **Choking** in the contents and check
   that it jumps to the article. Open the viewer's outline if offered, then
   look up “abdominal thrusts” with the viewer’s text search. Try selecting text.
4. Open `wikimed-family-health.pdf` and find **Postpartum bleeding** in the
   contents. Disconnect and reconnect the drive, then repeat one open. Record
   the iPhone model, iOS version, drive format, and which contents links,
   outline, and find controls worked while offline.

The four volumes have selectable text, linked contents, article outlines, and
Wikipedia revision links for attribution. The export omits illustrations,
infoboxes and reference lists. Each volume carries the CC BY-SA 4.0 notice.
The browser builder streams the small prebuilt files from the same Pages
origin and verifies each SHA-256 before publishing its shelf links.
The Python builder installs the same volumes from the repository and can
regenerate them from the catalog-pinned ZIM with libzim and ReportLab:

```sh
python scripts/build_wikimed_phone.py /path/to/wikipedia_en_medicine_maxi_2026-04.zim OUTPUT
```

The volumes are sized within the drive's existing discovery allowance.
The archive itself still uses Kiwix. [Apple Files and Quick Look](https://support.apple.com/guide/iphone/find-and-view-files-and-folders-iph4bff8827/ios)

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
the upstream bundle. The native reader packages remain the path for ZIMs on
finished libraries. [Kiwix JS documentation](https://github.com/kiwix/kiwix-js)
