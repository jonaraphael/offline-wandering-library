# Bounded 7z acquisition and local QA

Build recipes can declare pinned 7z archives under `build_inputs` and exact,
reviewed XML members under `build_input_extractions`. The archive remains a
temporary build input. Its members require whole-file SHA-256 and size pins;
originals, expanded members, work space, and retained caches have separate
capacity accounting. Required publisher notices stay in the retained library.

The extraction helper lists the complete archive within explicit byte and file
bounds, rejects unsafe paths, links, encryption, and collisions, then streams
only allowlisted members into owned partial files. It enforces exact output
sizes, timeouts, whole-file hashes, and live free-space checks before writes.
Interrupted files never become completed inputs. `observe_members` records
unapproved review evidence when a member pin has not yet been established.

Run the real-format checks offline after obtaining a local development tool:

```sh
.venv/bin/python scripts/check_sevenzip.py \
  --export-evidence catalog/acquisition/sevenzip-real-evidence.json
```

On macOS, the optional first-run preparation downloads only the official pinned
7-Zip 26.03 console bundle into ignored `.owl/tools/sevenzip-26.03/`. It reuses
the normal downloader, verifies the GitHub-published archive SHA-256, extracts
the executable and notices within finite bounds, and changes no global setup:

```sh
.venv/bin/python scripts/check_sevenzip.py --prepare-official-macos \
  --export-evidence catalog/acquisition/sevenzip-real-evidence.json
```

Use `--executable /path/to/7zz` to test another already installed executable.
For a build or capture preview, prepend the local tool directory to that
command's `PATH`; the build preflight still requires an available extractor.

The portable evidence records seven actual-format checks: extraction, reuse and
observation; traversal rejection; whole-archive limits; encryption and changed
member rejection; interrupted write recovery; and a normal synthetic library
build with offline reuse; and a source capture with one shared XML expansion
reused by two independently owned previews. This evidence covers the recorded macOS arm64 binary.
Other platforms and large production source archives still require their own
validation. No library bodies are downloaded by these checks.

Official provenance: [7-Zip download page](https://www.7-zip.org/download.html),
[release metadata](https://api.github.com/repos/ip7z/7zip/releases/tags/26.03), and
[26.03 macOS console bundle](https://github.com/ip7z/7zip/releases/download/26.03/7z2603-mac.tar.xz).
