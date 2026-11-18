"""Code Hygiene: configured linters as checks, optional formatter write mode with a re-check."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import BLOCKED, TIMED_OUT, Finding, TaskResult
from devtrellis_pulse.policy.paths import glob_to_regex
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext


class CodeHygiene(Task):
    task_id = "code_hygiene"
    name = "Code Hygiene"
    description = "Run configured linters, and formatters when write mode is enabled"
    enabled_by_default = False  # executes repository tooling
    requires_subprocess = True
    retry_safe = False
    idempotent = True
    default_timeout_seconds = 120
    commit_summary = "apply formatter changes"

    def write_scope(self, cfg: dict[str, Any]) -> tuple[str, ...]:
        task = cfg["tasks"]["code_hygiene"]
        return tuple(task["paths"]) if task["mode"] == "write" else ()

    def command_lists(self, cfg: dict[str, Any]) -> list[list[str]]:
        task = cfg["tasks"]["code_hygiene"]
        return task["commands"] + (task["write_commands"] if task["mode"] == "write" else [])

    def operations(self, cfg: dict[str, Any]) -> int:
        task = cfg["tasks"]["code_hygiene"]
        checks, writes = len(task["commands"]), len(task["write_commands"])
        tools = len({c[0] for c in self.command_lists(cfg)})
        if task["mode"] == "write":
            return 1 + tools + writes + 2 * checks  # version probes, formatters, check, re-check
        return 1 + tools + checks

    def prerequisite_problem(self, cfg: dict[str, Any]) -> str | None:
        task = cfg["tasks"]["code_hygiene"]
        return None if task["commands"] else "no commands configured"

    # ---- helpers ----------------------------------------------------------------------

    def _versions(self, ctx: TaskContext, commands: list[list[str]]) -> dict[str, str | None]:
        versions: dict[str, str | None] = {}
        for exe in sorted({c[0] for c in commands}):
            probe = ctx.run_command([exe, "--version"], 10)
            first = probe.output.strip().splitlines()[0] if probe.ok and probe.output.strip() else None
            versions[exe] = ctx.redact(first) if first else None
        return versions

    def _run_checks(self, ctx: TaskContext, label: str, findings: list[Finding]) -> tuple[int, int]:
        failed = timed_out = 0
        for argv in ctx.task_config["commands"]:
            result = ctx.run_command(argv, ctx.task_config["timeout_seconds"])
            if result.ok:
                continue
            failed += 1
            timed_out += result.timed_out
            reason = "timed out" if result.timed_out else f"exit code {result.returncode}"
            tail = ctx.output_tail(result.output)
            findings.append(
                Finding("error", f"{label} `{ctx.redact(' '.join(argv))}` failed ({reason})"
                        + (f"\n{tail}" if tail else ""))
            )
        return failed, timed_out

    # ---- execution --------------------------------------------------------------------

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        cfg = ctx.task_config
        findings: list[Finding] = []
        versions = self._versions(ctx, self.command_lists(ctx.config))
        formatted = 0
        status = None

        if cfg["mode"] == "write":
            before = {e.path for e in ctx.git.status()}
            for argv in cfg["write_commands"]:
                result = ctx.run_command(argv, cfg["timeout_seconds"])
                if not result.ok:
                    findings.append(Finding("error", f"formatter `{ctx.redact(' '.join(argv))}` failed"))
            changed = sorted({e.path for e in ctx.git.status()} - before)
            scope = [glob_to_regex(p) for p in cfg["paths"]]
            outside = [p for p in changed if not any(rx.match(p) for rx in scope)]
            for rel in changed:
                size = (ctx.repo / rel).stat().st_size if (ctx.repo / rel).is_file() else 0
                ctx.changes.record(rel, size)
            ctx.changed_paths.extend(p for p in changed if p not in ctx.changed_paths)
            formatted = len(changed)
            if outside:
                status = BLOCKED
                findings.append(
                    Finding(
                        "error",
                        f"formatter changed files outside tasks.code_hygiene.paths: {outside}. "
                        "Changes were left in place for inspection; nothing will be committed.",
                    )
                )

        failed, timed_out = self._run_checks(ctx, "check" if cfg["mode"] == "check" else "re-check", findings)
        if status is None and timed_out and timed_out == failed:
            status = TIMED_OUT
        summary = (
            f"{len(cfg['commands']) - failed}/{len(cfg['commands'])} checks passed"
            + (f", {formatted} file(s) reformatted" if cfg["mode"] == "write" else "")
        )
        result = finalize(
            self,
            summary,
            findings,
            status=status,
            metrics={"checks_run": len(cfg["commands"]), "checks_failed": failed, "reformatted": formatted},
            details={"tool_versions": versions},
        )
        result.changed_paths = list(ctx.changed_paths)
        return result
