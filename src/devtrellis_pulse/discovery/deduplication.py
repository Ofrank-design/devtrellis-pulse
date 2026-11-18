"""Equivalent maintenance opportunities are run once (DSC-006)."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.tasks.base import Task


def _signature(commands: list[list[str]]) -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(c) for c in commands)


def duplicate_of(task: Task, cfg: dict[str, Any], planned: list[Task]) -> str | None:
    """Return the id of an earlier planned task that already runs exactly these commands."""
    mine = _signature(task.command_lists(cfg))
    if not mine:
        return None
    for earlier in planned:
        theirs = _signature(earlier.command_lists(cfg))
        if theirs and mine <= theirs:
            return earlier.task_id
    return None
