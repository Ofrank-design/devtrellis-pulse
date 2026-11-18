"""Group changed paths into coherent commits. A path belongs to the first task that produced it."""

from __future__ import annotations

from dataclasses import dataclass, field

from devtrellis_pulse.core.models import TaskResult


@dataclass
class ChangeGroup:
    task_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def group_changes(results: list[TaskResult], mode: str) -> list[ChangeGroup]:
    claimed: set[str] = set()
    groups: list[ChangeGroup] = []
    for result in results:
        paths = [p for p in result.changed_paths if p not in claimed]
        if not paths:
            continue
        claimed.update(paths)
        groups.append(ChangeGroup([result.task_id], sorted(paths)))
    if mode == "run" and len(groups) > 1:
        merged = ChangeGroup()
        for group in groups:
            merged.task_ids.extend(group.task_ids)
            merged.paths.extend(group.paths)
        merged.paths.sort()
        return [merged]
    return groups
