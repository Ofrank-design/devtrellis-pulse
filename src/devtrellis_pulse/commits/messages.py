"""Commit messages describe what actually changed. They never claim checks that did not pass."""

from __future__ import annotations

from devtrellis_pulse.commits.grouping import ChangeGroup
from devtrellis_pulse.core.models import PASSED, TaskResult
from devtrellis_pulse.tasks import REGISTRY


def build_message(
    prefix: str, group: ChangeGroup, results: list[TaskResult], run_id: str
) -> tuple[str, str]:
    by_id = {r.task_id: r for r in results}
    if len(group.task_ids) == 1:
        task = REGISTRY.get(group.task_ids[0])
        summary = task.commit_summary if task else "update files"
        subject = f"{prefix}: {summary}"
        if group.task_ids[0] == "activity_report":
            subject += f" {run_id}"
    else:
        subject = f"{prefix}: apply changes from {len(group.task_ids)} maintenance tasks"

    body = ["Changed files:"]
    body += [f"- {p}" for p in group.paths[:20]]
    if len(group.paths) > 20:
        body.append(f"- and {len(group.paths) - 20} more")
    body += ["", "Task results (as recorded in this run):"]
    for task_id in group.task_ids:
        body.append(f"- {task_id}: {by_id[task_id].summary}")
    # Only mention a check when it really ran and passed in this same run.
    for check in ("tests", "code_hygiene"):
        result = by_id.get(check) or next((r for r in results if r.task_id == check), None)
        if result is not None and result.status == PASSED:
            body.append(f"- {check} passed in this run")
    body += ["", f"Run: {run_id}"]
    return subject, "\n".join(body)
