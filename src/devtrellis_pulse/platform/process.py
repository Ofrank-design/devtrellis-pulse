"""Subprocess runner: no shell, hard timeout, bounded memory, cooperative cancellation."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from devtrellis_pulse.execution.cancellation import CancellationToken

_SENSITIVE = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY", "CREDENTIAL", "PRIVATE")


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    output: str
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


def scrubbed_env() -> dict[str, str]:
    """The process environment minus anything that looks like a credential."""
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE)
    }


def _kill(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # taskkill /T ends the whole process tree, not only the direct child.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    proc.wait()


def run_command(
    argv: list[str],
    cwd: Path,
    timeout: float,
    max_bytes: int,
    cancel: CancellationToken | None = None,
) -> CommandResult:
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("argv must be a non empty list of strings")
    started = time.monotonic()
    env = scrubbed_env()
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is None:
        return CommandResult(argv, 127, f"executable not found: {argv[0]}")
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        [executable, *argv[1:]],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        shell=False,
        **group,
    )
    buffer = bytearray()
    total = [0]
    fd = proc.stdout.fileno()  # type: ignore[union-attr]

    def drain() -> None:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            total[0] += len(chunk)
            buffer.extend(chunk)
            if len(buffer) > max_bytes:  # keep only the tail, memory stays bounded
                del buffer[: len(buffer) - max_bytes]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = started + max(timeout, 0.1)
    timed_out = cancelled = False
    while True:
        try:
            proc.wait(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            pass
        if cancel is not None and cancel.is_set():
            cancelled = True
            _kill(proc)
            break
        if time.monotonic() > deadline:
            timed_out = True
            _kill(proc)
            break
    reader.join(timeout=2)
    return CommandResult(
        argv=argv,
        returncode=proc.returncode if proc.returncode is not None else -1,
        output=bytes(buffer).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        cancelled=cancelled,
        truncated=total[0] > max_bytes,
        duration_seconds=round(time.monotonic() - started, 3),
    )
