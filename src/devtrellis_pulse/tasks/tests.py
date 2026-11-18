"""Test Runner: runs configured commands, never claims success it did not observe."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import TIMED_OUT, Finding, TaskResult
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext


class TestRunner(Task):
    __test__ = False  # not a pytest class

    task_id = "tests"
    name = "Test Runner"
    description = "Run the configured test commands"
    enabled_by_default = False  # executes repository code
    requires_subprocess = True
    retry_safe = False
    default_timeout_seconds = 240

    def command_lists(self, cfg: dict[str, Any]) -> list[list[str]]:
        return cfg["tasks"]["tests"]["commands"]

    def operations(self, cfg: dict[str, Any]) -> int:
        return 1 + len(self.command_lists(cfg))

    def prerequisite_problem(self, cfg: dict[str, Any]) -> str | None:
        return None if self.command_lists(cfg) else "no commands configured"

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        commands = ctx.task_config["commands"]
        timeout = ctx.task_config["timeout_seconds"]
        findings: list[Finding] = []
        details: list[dict[str, Any]] = []
        failed = timed_out = 0
        for argv in commands:
            result = ctx.run_command(argv, timeout)
            shown = ctx.redact(" ".join(argv))
            details.append(
                {
                    "command": shown,
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                    "seconds": result.duration_seconds,
                }
            )
            if result.ok:
                continue
            failed += 1
            timed_out += result.timed_out
            reason = "timed out" if result.timed_out else f"exit code {result.returncode}"
            tail = ctx.output_tail(result.output)
            findings.append(Finding("error", f"`{shown}` failed ({reason})" + (f"\n{tail}" if tail else "")))
        summary = f"{len(commands) - failed}/{len(commands)} commands succeeded"
        status = TIMED_OUT if timed_out and timed_out == failed else None
        return finalize(
            self,
            summary,
            findings,
            status=status,
            metrics={"commands_run": len(commands), "commands_failed": failed},
            details={"commands": details},
        )
