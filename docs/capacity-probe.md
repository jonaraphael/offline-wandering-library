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
| macOS exFAT, 6 GiB disk image | 6,439,303,168 bytes estimated from 6,440,255,488 bytes available. Larger requests returned ENOSPC. | 169 ms |
| macOS FAT32, 6 GiB disk image | 64 MiB allocated. At 4 GiB + 1, EFBIG. | 71 ms |
| macOS APFS, local temporary directory | All length changes through 2 TiB succeeded with zero allocated bytes. Manual confirmation required. | 0.92 ms |
| Linux exFAT, FAT32, NTFS loop volumes | CI result pending. Browser uses manual confirmation. | Pending |
| Windows exFAT, FAT32, NTFS VHDs | CI result pending. Browser uses manual confirmation. | Pending |

These macOS measurements describe one host run. Device throughput and
filesystem drivers affect timings. The native measurements and a test with a
browser-picked USB drive establish different parts of the capacity story.
