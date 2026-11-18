"""Task contract (specification 7.1). Tasks only touch the world through their TaskContext."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import (
    PASSED,
    Finding,
    RepoSnapshot,
    TaskResult,
    ValidationResult,
)
from devtrellis_pulse.policy.paths import glob_to_regex

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext


@dataclass
class PlanContext:
    """What a task may know while planning: configuration and repository facts, nothing live."""

    config: dict[str, Any]
    snapshot: RepoSnapshot | None = None


@dataclass
class TaskPlan:
    operations: int = 1
    write_paths: list[str] = field(default_factory=list)
    summary: str = ""


class Task(ABC):
    task_id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1"
    enabled_by_default: bool = True
    read_paths: tuple[str, ...] = ("**",)
    requires_network: bool = False
    requires_subprocess: bool = False
    retry_safe: bool = False
    idempotent: bool = True
    default_timeout_seconds: int = 60
    depends_on: tuple[str, ...] = ()
    commit_summary: str = "update files"  # used to describe this task's commits

    # ---- planning ---------------------------------------------------------------------

    def write_scope(self, cfg: dict[str, Any]) -> tuple[str, ...]:
        """Glob patterns this task may write. Empty means the task is read only."""
        return ()

    def command_lists(self, cfg: dict[str, Any]) -> list[list[str]]:
        """Commands this task would run (used for budgeting and duplicate detection)."""
        return []

    def operations(self, cfg: dict[str, Any]) -> int:
        return 1

    def prerequisite_problem(self, cfg: dict[str, Any]) -> str | None:
        """A reason this task has nothing to do, or None when it is eligible."""
        return None

    def plan(self, pctx: PlanContext) -> TaskPlan:
        cfg = pctx.config
        return TaskPlan(self.operations(cfg), list(self.write_scope(cfg)), self.description)

    # ---- execution --------------------------------------------------------------------

    @abstractmethod
    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult: ...

    def validate(self, ctx: TaskContext, result: TaskResult) -> ValidationResult:
        """Check the result before the engine accepts it. Default: write scope was respected."""
        scope = [glob_to_regex(p) for p in self.write_scope(ctx.config)]
        outside = [p for p in result.changed_paths if not any(rx.match(p) for rx in scope)]
        return ValidationResult(
            ok=not outside, messages=[f"changed outside declared write scope: {p}" for p in outside]
        )


def finalize(
    task: Task,
    summary: str,
    findings: list[Finding],
    *,
    status: str | None = None,
    **extra: Any,
) -> TaskResult:
    """Build a TaskResult. Any error finding makes the task fail unless a status is given."""
    if status is None:
        status = "failed" if any(f.severity == "error" for f in findings) else PASSED
    return TaskResult(
        task_id=task.task_id, name=task.name, status=status, summary=summary, findings=findings, **extra
    )
