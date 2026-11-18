"""Generated Activity Report: writes the run report into the repository when explicitly enabled.

It reports only what actually happened and never presents a scheduled invocation as maintenance.
It is planned only when reports.write_to_repository is true, and always runs last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import Finding, TaskResult
from devtrellis_pulse.reports.json_report import to_json
from devtrellis_pulse.reports.markdown import to_markdown
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext


class ActivityReport(Task):
    task_id = "activity_report"
    name = "Generated Activity Report"
    description = "Write the activity report into the repository"
    retry_safe = True
    default_timeout_seconds = 30
    commit_summary = "record run report"

    def write_scope(self, cfg: dict[str, Any]) -> tuple[str, ...]:
        return (cfg["reports"]["output_directory"].strip("/") + "/**",)

    def prerequisite_problem(self, cfg: dict[str, Any]) -> str | None:
        return None if cfg["reports"]["write_to_repository"] else "reports.write_to_repository is false"

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        if ctx.run_snapshot is None:
            return finalize(self, "no run data available", [Finding("error", "run data missing")])
        run = ctx.run_snapshot()
        patterns = ctx.config["reports"]["redact_patterns"]
        out = ctx.config["reports"]["output_directory"].strip("/")
        written = 0
        for fmt in ctx.config["reports"]["format"]:
            ext, text = ("md", to_markdown(run, patterns)) if fmt == "markdown" else (
                "json",
                to_json(run, patterns),
            )
            written += ctx.write_file(f"{out}/{run['run_id']}.{ext}", text)
        result = finalize(self, f"{written} report file(s) written", [], metrics={})
        result.changed_paths = list(ctx.changed_paths)
        return result
