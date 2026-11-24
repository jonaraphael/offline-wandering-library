# Changelog

## Unreleased

- **Pause** stops new downloads and pauses at the next save point. When that is more than 5 seconds away, the button offers **Save progress first** with the time it takes and pauses after 5 seconds without a choice. While waiting, **Pause now** stops at once, as Pause did before.
- Show whether archives download on the **Fast route** (the download relay) or the **Slow route** (the Kiwix mirror), with the download speed. When the relay stops answering, a card names the likely daily limit and its reset in local time. Sync returns to the relay by itself once it answers, and a relay that fails partway through an archive no longer costs every piece a failed request.
- Show progress while checking files already on the drive ("Checked 92 GB of 181 GB · 25 min left"). Checksums run in a worker, once per file, so the check runs about twice as fast and leaves the page and other OWL windows responsive.
- Sync several drives at once, one per window. Each window remembers its own drive, a folder can sync in only one window at a time, and every finished drive keeps a working **Try it** link.
- Keep files finished before a pause in the drive record when Sync resumes. A first sync paused twice forgot them, and the next Sync downloaded them again under new names. Sync now finds such files by checksum and keeps them. After **Pause**, opening the drive no longer rereads every finished file.
- Offer **Choose a different drive** on the ready, up-to-date, paused and problem screens, including after the page reopens a remembered drive.

## 0.2.0 (2026-11-22)

- Identify Pages mirror downloads with the project name and repository URL, as Wikimedia requires.
- Retry job status reads during Windows file sharing conflicts.
- Count damaged critical files in browser builds and report checksum failures in reader and search support.
- Direct Python builds to a new folder when the destination already contains a browser library.
- Document the publisher relay's purpose, the owner's decision and how to request removal.
- Count selected files from verified drive contents and report ignored OS metadata.
- Confirm publisher denials with a browser probe, escalate inconclusive sources after three weeks, and close the tracking issue after a passing run.
- Pass through pinned whole-file relay responses and return a readable range error when a publisher ignores a sub-range.
- Lock Pages copies of the GNU Bash, Coreutils and Make manuals, the Organic Seed Alliance seed-saving guide, Siyavula grades 4–5 and two Book Dash titles. Recover matching copies from the prior deployment when publishers change their URLs or bytes.
- Check browser routes against the Pages network policy and fetch representative routes in Chrome before publishing.
- Publish a usable Python library when some downloads fail, resume FAT32 ZIM downloads at verified part boundaries, and print a smaller build command when the requested capacity exceeds available space.
- Lower the publisher relay's per-IP limit and document its Workers Free request budget.
- Report missing Kiwix apps as support gaps in Python builds and strict verification.
- Retry status and state writes on Windows when a reader briefly holds the destination open.
- Report reader, search and WikiMed phone support separately during strict verification. Store large ZIMs in verified 1 GiB parts on FAT32 with the Python builder.
- Require the publisher relay and verify the production Pages recommendations before deployment. Load hosted scripts from same-origin files and limit network requests to published source and search origins.
- Re-pin three PhET simulations, refresh publisher and browser route evidence, and check every publisher source each week.
- Count only selected essentials as missing after browser Sync and show essentials removed in Manage. Show archives kept in parts and preserve verified parts when a join cannot finish.
- Improve emergency search ranking and check it with held-out queries across the 16 GB, 128 GB and 1 TB presets.
- Report checksum integrity and selection completeness separately. Strict verification fails on missing selected files or an empty library unless incomplete content was explicitly accepted.
- Try pinned mirrors when a Python download fails its SHA-256 check.
- Fit the Python library to the free space in an existing destination, with reduced recommendations down to 8 GB.
- Create drive files and folders with POSIX permissions suitable for other readers.
- Use the production offline reader and search in the device test kit.
- Publish Pages from `main` after tests pass for the same commit. Add the browser regressions to CI.
- Check publisher sizes, live Pages mirrors and relay routes, and report failed checks in a GitHub issue.
- Include pinned Kiwix source links on the drive and document publishing, rollback and troubleshooting.
