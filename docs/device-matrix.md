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

## Platform checks

| Test | Procedure and expected result | Physical result |
| --- | --- | --- |
| Windows 10 or 11, x64 | On exFAT, unpack the portable reader ZIP into an OWL software folder or a local folder. Run `kiwix-desktop.exe` and open the single ZIM. Then give the reader the first split part with its sibling beside it. Record whether both display the marker and whether the file dialog needs **All files**. | Pending |
| macOS | Open the bundled Kiwix DMG while offline, launch the app, and record any Gatekeeper message. Open the single ZIM and the first split part separately. Record whether the app reads the files in place and keeps bookmarks after unplug and reconnect. | Pending |
| Linux x86-64 | Copy the AppImage to a filesystem where you can set the execute bit, run `chmod +x <file>`, then launch it. Keep the ZIMs on exFAT. Open the single ZIM and the first split part separately. If FUSE is unavailable as part of the tested system, record the alternate launch method used. | Pending |
| Android with USB OTG | In airplane mode, connect the drive and open the standalone APK under `LIBRARY/SOFTWARE/ANDROID` in Files. Allow that app to install unknown apps if Android prompts. Open the standalone Kiwix build, choose its file picker, select the USB volume through the Storage Access Framework, and open the single ZIM. Repeat with both split parts beside each other. Verify the reported storage location stays on USB and confirm what happens after reconnect. | Pending |
| USB-C iPhone, Files | In airplane mode, open Files → Browse → Locations and select the drive. Open `START_HERE.html` first, then the PDF path directly. Verify that the PDF text appears. Record whether Files follows sibling links. | Pending |
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
