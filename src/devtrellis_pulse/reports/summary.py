"""Derive the headline numbers of a run from its record. Reports never invent work."""

from __future__ import annotations

from typing import Any

EXECUTED = {"passed", "failed", "timed_out", "no_changes", "cancelled"}


def build_summary(run: dict[str, Any]) -> dict[str, Any]:
    tasks = run.get("tasks", [])
    plan = run.get("plan", [])
    changed: list[str] = []
    for task in tasks:
        for path in task.get("changed_paths", []):
            if path not in changed:
                changed.append(path)
    commits = [c for c in run.get("commits", []) if c.get("status") == "committed"]
    return {
        "operations_planned": sum(1 for p in plan if p.get("status") == "planned"),
        "operations_completed": sum(1 for t in tasks if t["status"] in EXECUTED),
        "operations_used": run.get("operations_used", 0),
        "passed": sum(1 for t in tasks if t["status"] in ("passed", "no_changes")),
        "failed": sum(1 for t in tasks if t["status"] in ("failed", "timed_out")),
        "skipped": sum(1 for t in tasks if t["status"] in ("skipped", "blocked", "cancelled")),
        "files_changed": len(changed),
        "changed_paths": changed,
        "commits_created": len(commits),
        "pushes": sum(1 for c in commits if c.get("pushed")),
        "runtime_seconds": run.get("runtime_seconds", 0.0),
    }
