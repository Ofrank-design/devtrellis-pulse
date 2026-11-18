"""Build a deterministic plan from configuration, policy and repository facts (DSC-001 to 014)."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.core.config import pattern_covered
from devtrellis_pulse.core.errors import ConfigError
from devtrellis_pulse.core.models import BLOCKED, PLANNED, SKIPPED, PlannedTask
from devtrellis_pulse.discovery.deduplication import duplicate_of
from devtrellis_pulse.discovery.eligibility import evaluate
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.tasks import REGISTRY
from devtrellis_pulse.tasks.base import Task


def _overlaps(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    return any(pattern_covered(x, [y]) or pattern_covered(y, [x]) for x in a for y in b)


def build_plan(
    cfg: dict[str, Any],
    policy: PolicyEngine,
    only: list[str] | None = None,
    estimates: dict[str, float] | None = None,
) -> list[PlannedTask]:
    """Plan in registry order. Identical inputs always produce an identical plan.

    `estimates` are historical median seconds per task. They are hints, never guarantees, and the
    planner never promises any number of commits.
    """
    if only:
        unknown = [name for name in only if name not in REGISTRY]
        if unknown:
            raise ConfigError(f"unknown task(s): {', '.join(unknown)}")
    estimates = estimates or {}
    limit = cfg["runtime"]["max_operations_per_run"]
    spent = 0
    selected: list[Task] = []
    write_owners: list[tuple[str, tuple[str, ...]]] = []
    plan: list[PlannedTask] = []

    for task in REGISTRY.values():
        status, reason = evaluate(task, cfg, policy, only)
        cost = task.operations(cfg)
        scope = task.write_scope(cfg)
        if status == PLANNED:
            twin = duplicate_of(task, cfg, selected)
            if twin:
                status, reason = SKIPPED, f"duplicate of {twin}"
        if status == PLANNED:
            missing = [d for d in task.depends_on if not any(p.task_id == d for p in plan)]
            if missing:
                status, reason = BLOCKED, f"depends on tasks that are not registered first: {missing}"
        if status == PLANNED and scope:
            for owner, owned_scope in write_owners:
                if _overlaps(scope, owned_scope):
                    status, reason = BLOCKED, f"write scope conflicts with task {owner}"
                    break
        if status == PLANNED and spent + cost > limit:
            status, reason = SKIPPED, "operation budget would be exceeded"
        if status == PLANNED:
            spent += cost
            selected.append(task)
            if scope:
                write_owners.append((task.task_id, scope))
        plan.append(
            PlannedTask(
                task_id=task.task_id,
                name=task.name,
                status=status,
                reason=reason,
                read_paths=list(task.read_paths),
                write_paths=list(scope),
                subprocess=task.requires_subprocess,
                operations=cost,
                estimated_seconds=estimates.get(task.task_id),
            )
        )
    return plan
