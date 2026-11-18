"""Single writer, append only JSON Lines ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from devtrellis_pulse.core.clock import utc_now
from devtrellis_pulse.core.errors import PersistenceError
from devtrellis_pulse.ledger.schema import LEDGER_ROTATED, make_event
from devtrellis_pulse.validation.secret_scan import redact_obj

try:  # POSIX advisory locking; other platforms rely on the per repository run lock
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class LedgerWriter:
    def __init__(
        self, path: Path, max_megabytes: int = 25, redact_patterns: list[str] | None = None
    ) -> None:
        self.path = Path(path)
        self.max_bytes = max_megabytes * 1024 * 1024
        self.patterns = redact_patterns or []

    def _rotate_if_needed(self) -> dict[str, Any] | None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return None
        if size < self.max_bytes:
            return None
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        archived = self.path.with_name(f"{self.path.stem}-{stamp}{self.path.suffix}")
        os.replace(self.path, archived)  # rotation by rename: nothing is rewritten or lost
        return make_event(LEDGER_ROTATED, None, archived_as=archived.name, bytes=size)

    def _write_line(self, record: dict[str, Any]) -> None:
        line = json.dumps(redact_obj(record, self.patterns), sort_keys=True, default=str) + "\n"
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            size = os.fstat(fd).st_size
            if size:
                os.lseek(fd, size - 1, os.SEEK_SET)
                if os.read(fd, 1) != b"\n":  # a previous write was cut off mid record
                    os.write(fd, b"\n")
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)  # closing also releases the lock

    def append(self, record: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            rotated = self._rotate_if_needed()
            if rotated:
                self._write_line(rotated)
            self._write_line(record)
        except OSError as exc:
            raise PersistenceError(f"cannot write ledger {self.path}: {exc}") from None
