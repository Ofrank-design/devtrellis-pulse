"""The only handle a task gets on the world: policy checked file writes and subprocesses."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.errors import PolicyError, TaskTimeout
from devtrellis_pulse.execution.cancellation import CancellationToken
from devtrellis_pulse.execution.limits import Budget, ChangeTracker
from devtrellis_pulse.execution.timeout import effective_timeout
from devtrellis_pulse.platform.files import atomic_write_text
from devtrellis_pulse.platform.process import CommandResult, run_command
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.policy.paths import glob_to_regex, normalize_relative
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.validation.output_validator import sanitize_output
from devtrellis_pulse.validation.secret_scan import redact

if TYPE_CHECKING:
    from devtrellis_pulse.tasks.base import Task


@dataclass
class TaskContext:
    repo: Path
    config: dict[str, Any]
    task: Task
    task_config: dict[str, Any]
    git: GitCli
    policy: PolicyEngine
    budget: Budget
    changes: ChangeTracker
    cancel: CancellationToken
    run_id: str = ""
    run_snapshot: Callable[[], dict[str, Any]] | None = None
    changed_paths: list[str] = field(default_factory=list)
    deadline: float = 0.0

    def __post_init__(self) -> None:
        self.deadline = time.monotonic() + self.config["runtime"]["max_task_runtime_seconds"]

    # ---- cooperative limits -----------------------------------------------------------

    def check(self) -> None:
        """Call regularly inside long loops: stops the task on cancellation or timeout."""
        if self.cancel.is_set():
            raise TaskTimeout("cancelled")
        if time.monotonic() > self.deadline:
            raise TaskTimeout("task exceeded runtime.max_task_runtime_seconds")

    # ---- output handling --------------------------------------------------------------

    def redact(self, text: str) -> str:
        return redact(text, self.config["reports"]["redact_patterns"])

    def output_tail(self, text: str) -> str:
        """Redacted tail of command output, or nothing unless reports.include_task_output."""
        if not self.config["reports"]["include_task_output"]:
            return ""
        return sanitize_output(text, self.config["reports"]["redact_patterns"])

    # ---- subprocesses -----------------------------------------------------------------

    def run_command(self, argv: list[str], timeout: float | None = None) -> CommandResult:
        if not self.task.requires_subprocess or not self.config["policy"]["allow_subprocesses"]:
            raise PolicyError("subprocesses are not allowed for this task")
        self.check()
        self.budget.spend(1)
        limit = effective_timeout(timeout, self.config, self.budget)
        max_bytes = self.config["runtime"]["max_output_kilobytes_per_task"] * 1024
        return run_command(argv, self.repo, limit, max_bytes, self.cancel)

    # ---- file writes ------------------------------------------------------------------

    def write_file(self, rel: str, text: str) -> bool:
        """Write a file inside the task's declared scope and the policy allowlist.

        Returns False (and writes nothing) when the content is already identical, so repeated
        runs never produce a diff.
        """
        rel = normalize_relative(rel)
        if self.config["runtime"]["mode"] != "standard":
            raise PolicyError("writes are blocked because runtime.mode is safe")
        scope = self.task.write_scope(self.config)
        if not any(glob_to_regex(p).match(rel) for p in scope):
            raise PolicyError(f"{rel} is outside the declared write scope of {self.task.task_id}")
        target = self.policy.paths.check_write(rel)
        data = text.encode("utf-8")
        if target.is_file() and target.read_bytes() == data:
            return False
        self.changes.record(rel, len(data))
        atomic_write_text(target, text)
        if rel not in self.changed_paths:
            self.changed_paths.append(rel)
        return True
