"""Run synthetic Python tools as real subprocesses on every supported OS."""
from contextlib import contextmanager
import os
import subprocess
import sys
from unittest.mock import patch


@contextmanager
def python_script_tool(script):
    """Use Python explicitly; Windows cannot execute a Unix shebang script."""
    popen = subprocess.Popen

    def launch(arguments, *args, **kwargs):
        if str(arguments[0]) == str(script):
            arguments = [sys.executable, *arguments]
        return popen(arguments, *args, **kwargs)

    with patch.object(subprocess, "Popen", side_effect=launch):
        yield


def wait_for_windows_process_exit(pid, timeout=12):
    """Wait past lock release until Windows releases the worker's cwd handle."""
    if os.name != "nt" or pid is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the process already exited.
            return
        raise ctypes.WinError(error)
    try:
        result = kernel.WaitForSingleObject(handle, int(timeout * 1000))
        if result == 258:  # WAIT_TIMEOUT
            raise TimeoutError(f"Worker {pid} did not exit within {timeout} seconds")
        if result != 0:  # WAIT_OBJECT_0
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
