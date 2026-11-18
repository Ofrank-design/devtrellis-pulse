"""Decide whether a task is selected, skipped or blocked, and say why (DSC-001 to DSC-004)."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.core.models import BLOCKED, PLANNED, SKIPPED
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.tasks.base import Task


def task_enabled(task: Task, cfg: dict[str, Any]) -> bool:
    if task.task_id == "activity_report":  # driven by reports.write_to_repository
        return True
    return bool(cfg["tasks"][task.task_id]["enabled"])


def evaluate(
    task: Task, cfg: dict[str, Any], policy: PolicyEngine, only: list[str] | None
) -> tuple[str, str]:
    if only and task.task_id not in only:
        return SKIPPED, "not selected"
    if not task_enabled(task, cfg):
        return SKIPPED, "disabled in configuration"
    problem = task.prerequisite_problem(cfg)
    if problem:
        return SKIPPED, problem
    blocked = policy.task_block_reason(task)
    if blocked:
        return BLOCKED, blocked
    return PLANNED, task.description
