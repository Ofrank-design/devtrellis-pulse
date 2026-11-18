"""Run level limits: operation budget, wall clock and change volume."""

from __future__ import annotations

import time

from devtrellis_pulse.core.errors import BudgetExceeded


class Budget:
    """Operation count and wall clock limits for one run. An upper bound, never a target."""

    def __init__(self, max_operations: int, max_seconds: float) -> None:
        self.max_operations = max_operations
        self.used = 0
        self.deadline = time.monotonic() + max_seconds

    def remaining_seconds(self) -> float:
        return self.deadline - time.monotonic()

    def spend(self, count: int = 1) -> None:
        if self.used + count > self.max_operations:
            raise BudgetExceeded(f"operation budget of {self.max_operations} exhausted")
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded("run time budget exhausted")
        self.used += count


class ChangeTracker:
    """Caps how many files and bytes a run may change (limits.max_changed_*)."""

    def __init__(self, max_files: int, max_bytes: int) -> None:
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.files: dict[str, int] = {}

    def record(self, rel: str, size: int) -> None:
        files = dict(self.files)
        files[rel] = size
        if len(files) > self.max_files:
            raise BudgetExceeded(f"limits.max_changed_files_per_run ({self.max_files}) exceeded")
        if sum(files.values()) > self.max_bytes:
            raise BudgetExceeded(f"limits.max_changed_bytes_per_run ({self.max_bytes}) exceeded")
        self.files = files
