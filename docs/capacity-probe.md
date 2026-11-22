# Measuring free space on a selected drive

OWL tests allocation on a temporary file on the selected volume. It tries a
64 MiB write-length change, then a length just above 4 GiB, then 2 TiB.
A binary search estimates a repeatable boundary to within 1 MiB. OWL discards
the temporary file. A sparse filesystem, a slow or ambiguous answer, or a
file-size limit prompts the user to confirm the label size.

Chromium calls `FileSystemAccessFileWriterImpl::Truncate` on the volume-local
swap, followed by `NativeFileUtil::Truncate` and `base::File::SetLength`.
POSIX uses `ftruncate`. Windows seeks and calls `SetEndOfFile`. The native
utility collapses failed length changes to a generic error, so the browser
often sees `InvalidStateError` for either ENOSPC or EFBIG.
[Chromium writer](https://github.com/chromium/chromium/blob/main/content/browser/file_system_access/file_system_access_file_writer_impl.cc#L199-L224) ·
[Native file utility](https://github.com/chromium/chromium/blob/main/storage/browser/file_system/native_file_util.cc#L277-L295) ·
[POSIX implementation](https://github.com/chromium/chromium/blob/main/base/files/file_posix.cc#L419-L425) ·
[Windows implementation](https://github.com/chromium/chromium/blob/main/base/files/file_win.cc) ·
[Blink error mapping](https://github.com/chromium/chromium/blob/main/third_party/blink/renderer/core/fileapi/file_error.cc#L138-L165)

`node scripts/probe_capacity.mjs <disposable-volume-path> <filesystem>` runs
the same binary search against native truncate operations. It records the
volume's raw free bytes, logical file length, change in allocated bytes,
native error code and timing. `Capacity probe` CI runs the script on a Linux
loop device and a Windows VHD. Each matrix job uploads its JSON.

| System and volume | Native allocation result | Total probe time |
| --- | --- | ---: |
| macOS exFAT, 1 TB partition on a physical USB drive (2026-11-22) | 959,040,368,640 bytes estimated from 959,050,285,056 bytes available (9.92 MB, 0.001% low) in 26 attempts. The first 64 MiB allocation took 364–418 ms while the drive woke, later ones 0.1 ms; 100 GiB took 0.75 s; 2,000 GiB returned ENOSPC in 2.7 s.  Two later runs saw free space shrink by about 1 MB during the search (macOS indexing and event logs), so the boundary recheck now backs off 64 MiB: 958,972,213,248 bytes in both runs (0.008% low). | 6.5–13.2 s |
| macOS exFAT, 6 GiB disk image | 6,439,303,168 bytes estimated from 6,440,255,488 bytes available. Larger requests returned ENOSPC. | 169 ms |
| macOS FAT32, 6 GiB disk image | 64 MiB allocated. At 4 GiB + 1, EFBIG. | 71 ms |
| macOS APFS, local temporary directory | All length changes through 2 TiB succeeded with zero allocated bytes. Manual confirmation required. | 0.92 ms |
| Windows exFAT VHD (`windows-latest`) | Measured: 6,437,210,112 bytes. | CI |
| Windows NTFS VHD (`windows-latest`) | Measured: 6,411,046,912 bytes. | CI |
| Windows FAT32 VHD (`windows-latest`) | File-size limit detected; manual confirmation. | CI |
| Linux exFAT loop volume (`ubuntu-latest`) | Extension rejected with a file-limit error; manual confirmation. | CI |
| Linux NTFS (ntfs-3g) loop volume | Oversized length accepted (sparse); manual confirmation. | CI |
| Linux FAT32 (vfat) loop volume | FAT32 detected; manual confirmation. | CI |

The Windows and Linux rows come from the `Capacity probe` workflow run on commit
`cb2e222` (one run per volume). The browser therefore probes on macOS and
Windows (`probesCapacity` in `web/builder-ui.mjs`) and asks Linux users to
confirm the label size.

These macOS measurements describe one host run. Device throughput and
filesystem drivers affect timings. The native measurements and a test with a
browser-picked USB drive establish different parts of the capacity story.
