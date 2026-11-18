"""Task registry. Order is stable and dependencies must come first."""

from __future__ import annotations

from devtrellis_pulse.tasks.base import Task
from devtrellis_pulse.tasks.code_hygiene import CodeHygiene
from devtrellis_pulse.tasks.dependency_inventory import DependencyInventory
from devtrellis_pulse.tasks.documentation import DocumentationGuardian
from devtrellis_pulse.tasks.report_snapshot import ActivityReport
from devtrellis_pulse.tasks.repository_health import RepositoryHealth
from devtrellis_pulse.tasks.tests import TestRunner

_ORDER: tuple[Task, ...] = (
    DocumentationGuardian(),
    TestRunner(),
    CodeHygiene(),
    RepositoryHealth(),
    DependencyInventory(),
    ActivityReport(),
)

REGISTRY: dict[str, Task] = {task.task_id: task for task in _ORDER}

# Tasks that appear in the `tasks:` section of the configuration.
CONFIGURABLE = tuple(t for t in REGISTRY if t != "activity_report")

# The activity report runs after everything else so it can describe the whole run.
REGISTRY["activity_report"].depends_on = tuple(CONFIGURABLE)


def _check_order() -> None:
    seen: set[str] = set()
    for task_id, task in REGISTRY.items():
        missing = [d for d in task.depends_on if d not in seen]
        if missing:
            raise RuntimeError(f"task {task_id} depends on later tasks: {missing}")
        seen.add(task_id)


_check_order()
