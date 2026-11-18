"""Markdown report, readable without a renderer (specification 6.6 and 29)."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.reports.summary import build_summary
from devtrellis_pulse.validation.secret_scan import redact


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def _commit_outcome(run: dict[str, Any]) -> list[str]:
    status = run.get("commit_status", "disabled")
    commits = run.get("commits", [])
    if status == "committed":
        lines = []
        for c in commits:
            if c["status"] == "committed":
                push = "pushed" if c.get("pushed") else "not pushed"
                lines.append(f"- `{(c['sha'] or '')[:12]}` {c['subject']} ({push})")
        return lines
    reasons = {
        "disabled": "No commit created. Commit mode is disabled.",
        "no_changes": "No commit created. Nothing changed that Pulse owns.",
        "skipped": "No commit created. " + "; ".join(c.get("reason", "") for c in commits if c.get("reason")),
        "failed": "Commit failed. See warnings. Changes were left in place for inspection.",
        "pending": "Commit outcome is recorded in the ledger once the run completes.",
    }
    return [reasons.get(status, f"Commit status: {status}").strip()]


def to_markdown(run: dict[str, Any], patterns: list[str] | None = None) -> str:
    summary = build_summary(run)
    repo = run.get("repo", {})
    dry = run.get("dry_run", False)
    lines = ["# DevTrellis Pulse Run Report", ""]
    lines.append(f"- Run: `{run['run_id']}`")
    lines.append(f"- Started: {run['started_at']}")
    lines.append(f"- Finished: {run.get('finished_at') or 'not finished'}")
    lines.append(f"- Repository: `{repo.get('name', 'unknown')}`")
    if repo.get("remote"):
        lines.append(f"- Remote: `{repo['remote']}`")
    lines.append(f"- Branch: `{repo.get('branch') or 'detached HEAD'}`")
    lines.append(f"- Starting HEAD: `{(repo.get('head') or 'none')[:12]}`")
    lines.append(f"- Overall status: `{run['status']}`")
    if dry:
        lines += ["", "**Dry run: this is a plan. Nothing was executed or changed.**"]

    lines += ["", "## Summary", ""]
    lines.append(f"- Operations planned: {summary['operations_planned']}")
    if not dry:
        lines.append(f"- Operations completed: {summary['operations_completed']}")
        lines.append(f"- Passed: {summary['passed']}")
        lines.append(f"- Failed: {summary['failed']}")
        lines.append(f"- Skipped: {summary['skipped']}")
        lines.append(f"- Files changed: {summary['files_changed']}")
        lines.append(f"- Commits created: {summary['commits_created']}")
        lines.append(f"- Pushes: {summary['pushes']}")
        lines.append(f"- Operations used: {summary['operations_used']}")
        lines.append(f"- Runtime: {summary['runtime_seconds']}s")

    if dry:
        lines += ["", "## Planned work", "", "| Task | Status | Reason |", "|---|---|---|"]
        for item in run.get("plan", []):
            lines.append(f"| {item['task_id']} | {item['status']} | {_cell(item['reason'])} |")
    else:
        lines += ["", "## Tasks", "", "| Task | Status | Duration | Summary |", "|---|---|---:|---|"]
        for task in run.get("tasks", []):
            seconds = f"{task.get('duration_ms', 0) / 1000:.1f}s"
            lines.append(
                f"| {task['task_id']} | {task['status']} | {seconds} | {_cell(task['summary'])} |"
            )
        if not run.get("tasks"):
            lines.append("| none | no_changes | 0.0s | No eligible tasks, so no work was done |")

        findings = [(t["task_id"], f) for t in run.get("tasks", []) for f in t.get("findings", [])]
        if findings:
            lines += ["", "## Findings", ""]
            for task_id, finding in findings:
                where = f" (`{finding['path']}`)" if finding.get("path") else ""
                first, *rest = finding["message"].splitlines() or [""]
                lines.append(f"- **{finding['severity']}** [{task_id}] {first}{where}")
                lines.extend(f"    {extra}" for extra in rest)

        lines += ["", "## Changes", ""]
        if summary["changed_paths"]:
            lines.extend(f"- `{p}`" for p in summary["changed_paths"])
        else:
            lines.append("No files were changed by this run.")
        if run.get("diff_stat"):
            lines += ["", "```text", run["diff_stat"], "```"]

        validation = run.get("validation", {})
        lines += ["", "## Validation", ""]
        if validation.get("messages"):
            lines.extend(f"- {m}" for m in validation["messages"])
        else:
            lines.append("No validation problems." if validation.get("ok", True) else "Validation failed.")

        lines += ["", "## Commit outcome", ""]
        lines.extend(_commit_outcome(run))

    if run.get("warnings"):
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {w}" for w in run["warnings"])
    if run.get("operator_actions"):
        lines += ["", "## Recommended operator action", ""]
        lines.extend(f"- {a}" for a in run["operator_actions"])
    lines.append("")
    return redact("\n".join(lines), patterns) + "\n"
