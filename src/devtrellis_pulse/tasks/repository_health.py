"""Repository Health Snapshot: factual metadata only. No opaque score, no transmitted content."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import NO_CHANGES, Finding, TaskResult
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext

_MAX_STAT = 20000
_LARGE = 1_000_000

# (metric name, human label, candidate paths). Missing optional files are information, never
# presented as vulnerabilities.
_PRESENCE = (
    ("has_readme", "README", ("README.md", "README.rst", "README.txt", "README")),
    ("has_license", "License file", ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")),
    ("has_security_policy", "Security policy", ("SECURITY.md", ".github/SECURITY.md")),
    ("has_contributing", "Contributing guide", ("CONTRIBUTING.md", ".github/CONTRIBUTING.md")),
    ("has_code_of_conduct", "Code of conduct", ("CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md")),
    ("has_changelog", "Changelog", ("CHANGELOG.md", "CHANGELOG", "HISTORY.md")),
    ("has_gitignore", ".gitignore", (".gitignore",)),
)


def _exists_any(repo: Path, names: tuple[str, ...]) -> bool:
    return any((repo / n).exists() for n in names)


def _has_ci(repo: Path) -> bool:
    workflows = repo / ".github" / "workflows"
    return (workflows.is_dir() and any(workflows.glob("*.y*ml"))) or (repo / ".gitlab-ci.yml").exists()


def _has_tests(repo: Path) -> bool:
    if (repo / "tests").is_dir() or (repo / "test").is_dir():
        return True
    pyproject = repo / "pyproject.toml"
    return pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="replace")


def render_snapshot(metrics: dict[str, Any]) -> str:
    """Deterministic Markdown: stable facts only, so unchanged facts produce no diff."""
    lines = [
        "# Repository health snapshot",
        "",
        "Facts gathered by DevTrellis Pulse. There is no combined score.",
        "",
        "| Fact | Value |",
        "|---|---|",
    ]
    skip = {"uncommitted_paths", "untracked_paths"}
    for key in sorted(metrics):
        if key not in skip:
            lines.append(f"| {key} | {metrics[key]} |")
    lines.append("")
    return "\n".join(lines)


class RepositoryHealth(Task):
    task_id = "repository_health"
    name = "Repository Health Snapshot"
    description = "Factual repository snapshot"
    retry_safe = True
    default_timeout_seconds = 60
    commit_summary = "update repository health snapshot"

    def write_scope(self, cfg: dict[str, Any]) -> tuple[str, ...]:
        if cfg["tasks"]["repository_health"]["write_snapshot"]:
            return (cfg["reports"]["output_directory"].strip("/") + "/health.md",)
        return ()

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        out = ctx.config["reports"]["output_directory"].strip("/")
        owned = lambda p: p == out or p.startswith(out + "/")  # noqa: E731
        tracked = [p for p in ctx.git.tracked_files() if not owned(p)]
        large = []
        for rel in tracked[:_MAX_STAT]:
            ctx.check()
            path = ctx.repo / rel
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_size > _LARGE:
                    large.append(rel)
            except OSError:
                continue
        entries = [e for e in ctx.git.status() if not owned(e.path)]
        findings: list[Finding] = []
        metrics: dict[str, Any] = {
            "tracked_files": len(tracked),
            "uncommitted_paths": len(entries),
            "untracked_paths": sum(1 for e in entries if e.untracked),
            "large_files": len(large),
        }
        for key, label, names in _PRESENCE:
            metrics[key] = _exists_any(ctx.repo, names)
            if not metrics[key]:
                findings.append(Finding("info", f"{label} not found (optional)"))
        metrics["has_ci_workflows"] = _has_ci(ctx.repo)
        metrics["has_tests"] = _has_tests(ctx.repo)
        for rel in large[:20]:
            findings.append(Finding("warning", "tracked file larger than 1 MB", rel))

        status = None
        if ctx.task_config["write_snapshot"]:
            changed = ctx.write_file(out + "/health.md", render_snapshot(metrics))
            if not changed:
                status = NO_CHANGES
        details = {"branch": ctx.git.branch(), "head": ctx.git.head(), **ctx.git.recent_commits()}
        summary = (
            f"{len(tracked)} tracked files, {len(entries)} uncommitted paths, {len(large)} large files"
        )
        result = finalize(self, summary, findings, status=status, metrics=metrics, details=details)
        result.changed_paths = list(ctx.changed_paths)
        return result
