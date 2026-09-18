# Building, carrying, and maintaining an OWL drive

## Prepare

1. Use a dependable SSD and cable. Format it with your operating system’s ordinary disk tools if needed; OWL does not format drives. exFAT is the intended cross-platform filesystem.
2. Identify the SSD’s mount location carefully. Use a dedicated `EMERGENCY_LIBRARY` directory so the library is easy to find.
3. Install Python 3.11+ and OWL on the build computer. Install the `.[zim]` extra for profiles containing ZIM archives; the minimal installation is sufficient for the directly readable critical profile.
4. Review the catalog and sources. Every production profile includes required core textbooks and illustrated guides alongside directly readable emergency material. Use a profile that fits the actual available space. Reserve space for search output and build scratch storage as well as downloads.
5. Run a plan and inspect its selected files, source sizes, and warnings.

```bash
python scripts/validate_catalog.py
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb --plan
```

Mount locations differ by operating system. Typical roots include `/Volumes/` on macOS, `/media/` or `/run/media/` on Linux, and a drive letter such as `E:\` on Windows. These are examples; confirm the real destination yourself.

## Build and resume

```bash
python scripts/build_drive.py /media/SSD/EMERGENCY_LIBRARY \
    --profile standard-512gb \
    --cache-dir /path/to/cache \
    --work-dir /path/to/build-scratch
```

The cache and scratch directories should have sufficient free space; putting them on the build computer can reduce removable-drive I/O. Scratch storage is used to construct search, including a build-time SQLite database. No database service or server is required, and the finished drive does not need SQLite to run search.

Capacity planning uses decimal drive capacity, the profile’s reserve, content sizes, a search budget, and build overhead. Free-space checks additionally allow for search scratch storage; external scratch storage is checked separately. Caching needs another copy of downloaded content, including when the cache and target share a physical disk. Estimates cannot predict exact compressed archive extraction costs or future changes to unpinned sources.

If a connection fails, rerun the same command. Downloads stream to partial files and request HTTP byte ranges where supported. A source that ignores the range is downloaded from the beginning instead of blindly appending bytes. Files are accepted only after the builder’s checks and then renamed into place. Checksum failures are errors, not successful builds.

The cache stores downloaded bytes, not an alternative authoritative catalog. Hashes are rechecked before reuse. Drive files already present and verified can be reused. The builder preserves unrelated files and refuses unsafe paths or output collisions. Do not rename or edit the managed library while a build is running. A target lock prevents concurrent builds. Remove a stale lock only after confirming no builder is running; do not remove a lock to bypass an active build.

Custom recipes use `--catalog /path/to/catalog.yaml` and `--profiles-dir /path/to/profiles`. Use versioned, immutable URLs and known SHA-256 hashes where possible. `--allow-local` explicitly permits local test assets; it is useful for tiny demonstration builds and is not needed for ordinary public-source builds.

## Find textbooks and illustrated guides

`START_HERE.html` links directly to the textbook shelf and illustrated-guide shelf, showing each shelf’s total and critical-resource count. Both pages work without JavaScript. The textbook shelf contains ordinary, directly readable textbooks. The illustrated shelf includes illustrated textbooks and practical guides; reader-dependent archives, EPUBs, and software packages are excluded from these shelves.

The critical-content index spans folders. A core textbook stored under `BOOKS/TEXTBOOKS/` still appears in `INDEX/critical.html` and carries a Critical label in the other indexes. You do not need to know its folder to find it. The inventory shows resource-type and illustration labels alongside source, license, integrity, and search-coverage information.

Open the original PDFs to see diagrams, photographs, charts, and figures. Downloads retain the original file bytes and embedded illustrations. Search indexes extractable text; it does not interpret images or provide OCR. A diagram or scanned page can be useful even when its contents are absent from search results.

## Verify and practice

```bash
python scripts/verify.py /media/SSD/EMERGENCY_LIBRARY
# Or use the independent verifier copied to the drive:
python /media/SSD/EMERGENCY_LIBRARY/VERIFY.py /media/SSD/EMERGENCY_LIBRARY
```

Read the report:

| Status | Meaning | Action |
| --- | --- | --- |
| `OK` | File matches its recorded SHA-256 | No action needed |
| `MISSING` | Expected file is absent | Rebuild or restore it from the verified backup |
| `FAILED` | Hash mismatch, unreadable file, or unsafe manifest entry | Investigate; replace from a trusted source and verify again |
| `UNKNOWN` | File has no entry in the checksum manifest | Review whether it is your file or intentionally unmanaged material |

Keep a trusted copy of `SHA256SUMS.txt`, `INVENTORY.json`, `BUILD_INFO.json`, `LOCKED_CATALOG.yaml`, and the original catalog away from the drive. A checksum manifest stored beside its files cannot detect an attacker replacing both. OWL’s build timestamps and metadata may differ between builds even when the knowledge assets are identical.

Before storing the SSD, disconnect network access and try each intended device:

1. Attach the SSD with the necessary adapter and power source; find it in the file manager.
2. Open `START_HERE.html`, follow a category link, and open a critical PDF or text file.
3. If HTML links do not work, open a critical document directly from its folder.
4. Open a core textbook and an illustrated guide from their dedicated shelves. Navigate between pages and zoom into a diagram to confirm it is readable on the device.
5. Open `SEARCH.html` in an actual browser, select `SEARCH/library.owl`, and search for a known phrase. Verify the resulting document link. Treat this as optional on devices whose file previews restrict JavaScript.
6. Open the textbook, illustrated-guide, category, critical, and alphabetical indexes with JavaScript disabled. Confirm critical textbooks are reachable through the critical index even when their files are in `BOOKS/`.
7. On platforms that permit offline installation, check that the matching bundled reader can open a ZIM. The builder does not install or run it for you.
8. Safely eject the SSD before unplugging it.

An iPhone’s Files preview is useful for ordinary documents but is not a general-purpose browser for a local web application. A bundled APK or desktop executable cannot provide an offline iOS installation path. Android storage access also varies by file manager and browser. Keep direct document access as the primary path on phones.

## Update without losing a working copy

Keep one verified SSD untouched while building or updating the other. Review changed source licenses, URLs, versions, and expected hashes before accepting a new catalog. Plan the update, build it, verify it, and repeat the device checks before replacing the previous working copy. Replacements are atomic per file, but a failed update can leave files from different builds; an incomplete build is not a verified snapshot.

Rebuilding is safe to repeat, but it does not guarantee an old source remains downloadable. A mutable URL can change or disappear. Retain a cache for the exact approved catalog and build records for repeatability. Files removed from a newer recipe are not automatically deleted from an older drive; a fresh dedicated destination provides the clearest snapshot.

Build two identical SSDs, verify both, and store the backup separately. Keep required cables, adapters, and power equipment with them. Periodically verify all files and read a few important documents on the actual target devices. Investigate checksum changes before copying data between the drives so a bad copy does not replace a good one.
