"""Process-lifetime locks and cooperative command-line interruption."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import stat
import threading

from .safety import SafetyError, reject_symlinks


@contextmanager
def file_lock(path: Path):
    """Fail fast on a live writer; the OS releases the lock even after a crash.

    Keep the lock file: unlinking it could let another process lock a different
    inode while an existing waiter still refers to the original one.
    """
    reject_symlinks(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b", buffering=0) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SafetyError(f"Unsafe lock file: {path}")
        if not info.st_size:
            handle.write(b"\0")  # Windows locks an existing byte.
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SafetyError(f"Another OWL process is using {path}, or this filesystem cannot lock it: {error}") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def interrupt_signals():
    """Let terminal close/termination use the same checkpoint cleanup as Ctrl-C.

    Only CLI entry points install these handlers. Library callers retain control
    of their process's signal policy. A second signal waits for cleanup instead
    of interrupting a filesystem flush; forced kill remains an OS operation.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    names = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")
    previous = {}

    def stop(signum, frame):
        for number in previous:
            signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt

    try:
        for name in names:
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.getsignal(number)
                signal.signal(number, stop)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
