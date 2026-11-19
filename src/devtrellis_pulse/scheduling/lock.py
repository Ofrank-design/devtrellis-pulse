"""Run lock scoped to a repository identity. Stale locks are verified, never guessed from age."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

from devtrellis_pulse.core.clock import iso_utc
from devtrellis_pulse.core.errors import LockError

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def _windows_pid_alive(pid: int) -> bool:
    """Ask Windows directly. os.kill(pid, 0) must never be used there: signal 0 is Ctrl+C."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_start_ticks(pid: int) -> int | None:
    """Process start time from /proc (Linux). Detects a reused pid. None where unavailable."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


class RunLock:
    def __init__(self, path: Path, wait_seconds: float = 0) -> None:
        self.path = Path(path)
        self.wait_seconds = wait_seconds
        self._held = False

    def _is_stale(self) -> bool:
        """True only when the recorded owner is provably gone. An old lock is not a stale lock."""
        try:
            info = json.loads(self.path.read_text())
            pid = int(info["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return True  # unreadable or malformed lock files carry no live owner
        if info.get("hostname") != socket.gethostname():
            return False  # cannot verify a process on another machine: treat as active
        if not _pid_alive(pid):
            return True
        recorded = info.get("start_ticks")
        return recorded is not None and process_start_ticks(pid) not in (None, recorded)

    def _try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self._is_stale():
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                return self._try_acquire()
            return False
        info = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "start_ticks": process_start_ticks(os.getpid()),
            "started_at": iso_utc(),
        }
        with os.fdopen(fd, "w") as handle:
            json.dump(info, handle)
        self._held = True
        return True

    def acquire(self) -> None:
        deadline = time.monotonic() + self.wait_seconds
        while not self._try_acquire():
            if time.monotonic() >= deadline:
                raise LockError(f"another Pulse run is active (lock: {self.path})")
            time.sleep(0.2)

    def release(self) -> None:
        if self._held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._held = False

    def holder(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
