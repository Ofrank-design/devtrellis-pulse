"""Task permission checks: does policy grant a task what it declares it needs?"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.config import pattern_covered

if TYPE_CHECKING:
    from devtrellis_pulse.tasks.base import Task


def task_block_reason(task: Task, cfg: dict[str, Any]) -> str | None:
    """Return why policy blocks a task, or None when it may be planned."""
    policy = cfg["policy"]
    if task.requires_subprocess and not policy["allow_subprocesses"]:
        return "subprocesses are not allowed by policy"
    if task.requires_network and not policy["allow_network"]:
        return "network access is not allowed by policy"
    scope = task.write_scope(cfg)
    if scope:
        if cfg["runtime"]["mode"] != "standard":
            return "task writes files but runtime.mode is safe"
        for pattern in scope:
            if not pattern_covered(pattern, policy["allowed_write_paths"]):
                return f"write scope {pattern!r} is not in policy.allowed_write_paths"
    return None
