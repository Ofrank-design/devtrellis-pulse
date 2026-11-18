"""The repository contract the rest of Pulse depends on. GitCli is the only implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from devtrellis_pulse.core.models import RepoSnapshot, StatusEntry


class Repository(Protocol):
    root: Path

    def is_repository(self) -> bool: ...

    def snapshot(self) -> RepoSnapshot: ...

    def status(self) -> list[StatusEntry]: ...

    def tracked_files(self) -> list[str]: ...

    def head(self) -> str | None: ...

    def branch(self) -> str | None: ...

    def stage(self, paths: list[str]) -> None: ...

    def commit(self, paths: list[str], subject: str, body: str, name: str, email: str) -> str: ...
