# Browser source and transfer evidence

The 117 Kiwix `.meta4` records each supplied a matching catalog SHA-256 and
size, with 347,529 publisher SHA-1 pieces at 4 MiB each. Recreate the compact
receipt from the repo root.

```sh
python scripts/build_kiwix_pins.py /tmp/kiwix-pieces.json --mirrors /tmp/kiwix-mirrors.json
cmp /tmp/kiwix-pieces.json web/kiwix-pieces.json
```

The builder checks these pieces as bytes arrive. Whole-file SHA-256 remains
the acceptance check. The drive journal saves hash state for committed split
parts and single-file prefixes. Routine resume checks sizes before using that
state. Full verification reads the installed bytes again.

On 2026-11-21 a single-byte ranged GET with the Pages Origin confirmed the
pinned total and exposed Content-Range on 6/6 Kiwix project mirror responses for
the largest six ZIMs. The same check found 31/49 alternate URLs accepted a
range. Zero of those 49 satisfied the full browser test. The candidates
included publisher-listed US and European peers, the Wikimedia host and
the Kiwix archive service. The project mirror remains the default browser
route. Six exact editions also have a publisher-listed NLUUG route under
the optional relay configuration. The relay serves bounded byte ranges when
configured and authorized. The browser tries the direct route first. [Kiwix download infrastructure](https://github.com/kiwix/operations/wiki/Downloads)

During an active build, transfer transport failures try alternate sources,
check the Pages connection and wait with exponential backoff during an
outage. The browser’s online event prompts a new probe. Search payloads use
the same wait and resume logic. An HTTP error or a pin mismatch from a source
can fail that source while other files continue.

A synthetic 20 GiB Chrome headless fixture used a test picker backed by a
dedicated Chromium profile. The browser was killed during parts starting
at 2, 8 and 15 GiB. It resumed at each of those offsets and verified all
20 parts against whole-file SHA-256. Runs took 44.72, 128.88, 154.36 and
107.67 seconds on the test host. This exercises the builder and browser
persistence with loopback data. See the device matrix for hardware status.

Run the scale fixture with a fresh scratch directory, a locally installed
Chromium and the path to an installed `playwright-core` module.

```sh
node scripts/check_browser_resume.cjs <scratch-dir> <chrome> <playwright-core>
node scripts/check_browser_resume.cjs <scratch-dir> <chrome> <playwright-core> disk-full
```

The disk-full fixture injects a `QuotaExceededError` after 256 KiB of one
file. Chromium then builds and verifies the following file. This took 0.12 s
on the test host. An OS disk-full trial put Chromium’s profile and its
test drive on the same 512 MiB image. The profile could no longer read the
journal at exhaustion and the run stopped. Physical external-drive
recovery remains unverified. The Python unplug fixture replaces the
transfer directory at the same path. The downloader rejects that directory
and writes no files into it.
