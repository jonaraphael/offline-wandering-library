"""Read the destination filesystem without creating anything on it."""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import sys


FAT_FILE_LIMIT = (1 << 32) - 1


def filesystem_type(path: Path) -> str:
    path = path.resolve()
    while not path.exists() and path.parent != path:
        path = path.parent
    try:
        if sys.platform == "darwin":
            mount = path
            while not os.path.ismount(mount) and mount.parent != mount:
                mount = mount.parent
            data = subprocess.check_output(
                ["/usr/sbin/diskutil", "info", "-plist", str(mount)], stderr=subprocess.DEVNULL, timeout=5)
            return plistlib.loads(data).get("FilesystemType", "").lower()
        if sys.platform.startswith("linux"):
            return subprocess.check_output(["stat", "-f", "--format=%T", str(path)],
                                           stderr=subprocess.DEVNULL, timeout=5, text=True).strip().lower()
        if os.name == "nt":
            from ctypes import WinDLL, create_unicode_buffer
            kernel = WinDLL("kernel32", use_last_error=True)
            volume = create_unicode_buffer(32768)
            system = create_unicode_buffer(64)
            if (kernel.GetVolumePathNameW(str(path), volume, len(volume)) and
                    kernel.GetVolumeInformationW(volume, None, 0, None, None, None, system, len(system))):
                return system.value.lower()
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        return ""
    return ""


def fat_file_limit(fs: str) -> int | None:
    return FAT_FILE_LIMIT if fs in {"fat", "fat32", "msdos", "vfat"} else None
