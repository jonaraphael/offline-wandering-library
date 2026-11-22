# Changelog

## 0.2.0 (unreleased)

- Show missing essential files and archives kept in parts after browser Sync. Preserve verified parts when a join cannot finish.
- Improve emergency search ranking and check it with held-out queries across the 16 GB, 128 GB and 1 TB presets.
- Report checksum integrity and selection completeness separately. Strict verification fails on missing selected files or an empty library unless incomplete content was explicitly accepted.
- Try pinned mirrors when a Python download fails its SHA-256 check.
- Fit the Python library to the free space in an existing destination, with reduced recommendations down to 8 GB.
- Create drive files and folders with POSIX permissions suitable for other readers.
- Use the production offline reader and search in the device test kit.
- Publish Pages from `main` after tests pass for the same commit. Add the browser regressions to CI.
- Check publisher sizes, live Pages mirrors and relay routes, and report failed checks in a GitHub issue.
- Include pinned Kiwix source links on the drive and document publishing, rollback and troubleshooting.
