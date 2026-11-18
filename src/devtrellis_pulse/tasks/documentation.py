"""Documentation Guardian: finds documentation drift, writes only a marked generated section."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from devtrellis_pulse.app.commands import (
    CLI_REFERENCE_END,
    CLI_REFERENCE_START,
    cli_reference_markdown,
)
from devtrellis_pulse.core.config import validate
from devtrellis_pulse.core.errors import ConfigError, PolicyError
from devtrellis_pulse.core.models import NO_CHANGES, Finding, TaskResult
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_MAX_FILES = 500
_MAX_BYTES = 1_000_000


def split_fences(text: str) -> tuple[list[tuple[int, str]], bool]:
    """Return (lines outside code fences with numbers, whether the fences were balanced)."""
    outside: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            outside.append((number, line))
    return outside, fence is None


def headings(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    found = []
    for _, line in lines:
        match = _HEADING_RE.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2)))
    return found


def render_section(path: str) -> str:
    return f"{CLI_REFERENCE_START}\n{cli_reference_markdown()}\n{CLI_REFERENCE_END}"


def replace_generated_section(existing: str) -> str | None:
    """Swap the marked section for fresh content. None when the markers are missing."""
    start = existing.find(CLI_REFERENCE_START)
    end = existing.find(CLI_REFERENCE_END)
    if start == -1 or end == -1 or end < start:
        return None
    end += len(CLI_REFERENCE_END)
    return existing[:start] + render_section("") + existing[end:]


class DocumentationGuardian(Task):
    task_id = "documentation"
    name = "Documentation Guardian"
    description = "Required files, local links, code fences, headings and the generated CLI reference"
    retry_safe = True
    default_timeout_seconds = 60
    commit_summary = "update generated CLI reference"

    def write_scope(self, cfg: dict[str, Any]) -> tuple[str, ...]:
        task = cfg["tasks"]["documentation"]
        if task["mode"] == "write" and task["generated_cli_reference"]:
            return (task["generated_cli_reference"],)
        return ()

    # ---- individual checks ------------------------------------------------------------

    def _markdown_files(self, repo: Path) -> list[Path]:
        files = sorted(repo.glob("*.md")) + sorted((repo / "docs").glob("**/*.md"))
        return [p for p in files if p.is_file() and not p.is_symlink()][:_MAX_FILES]

    def _check_file(
        self, ctx: TaskContext, md: Path, cfg: dict[str, Any], findings: list[Finding]
    ) -> dict[str, int]:
        counts = {"broken_links": 0, "fence_problems": 0, "marker_hits": 0, "heading_jumps": 0}
        rel = str(md.relative_to(ctx.repo))
        if md.stat().st_size > _MAX_BYTES:
            findings.append(Finding("info", "file too large to inspect, skipped", rel))
            return counts
        text = md.read_text(encoding="utf-8", errors="replace")
        outside, balanced = split_fences(text)
        if not balanced:
            counts["fence_problems"] += 1
            findings.append(Finding("error", "unbalanced code fence", rel))
        previous = 0
        for level, title in headings(outside):
            if previous and level > previous + 1:
                counts["heading_jumps"] += 1
                findings.append(
                    Finding("warning", f"heading level jumps from {previous} to {level}: {title}", rel)
                )
            previous = level
        for _, line in outside:
            for match in _LINK_RE.finditer(line):
                link = match.group(1).split("#", 1)[0]
                if not link or _SCHEME_RE.match(link) or link.startswith("/"):
                    continue
                resolved = (md.parent / link).resolve()
                inside = resolved == ctx.repo or ctx.repo in resolved.parents
                if not inside or not resolved.exists():
                    counts["broken_links"] += 1
                    findings.append(Finding("error", f"broken local link: {link}", rel))
        for marker in cfg["forbidden_markers"]:
            hits = text.count(marker)
            if hits:
                counts["marker_hits"] += hits
                findings.append(Finding("error", f"forbidden marker {marker!r} found {hits} time(s)", rel))
        return counts

    def _check_example_config(self, ctx: TaskContext, findings: list[Finding]) -> bool:
        checked = False
        for name in ("pulse.example.yml", "pulse.yml"):
            path = ctx.repo / name
            if not path.is_file():
                continue
            checked = True
            try:
                validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            except (ConfigError, yaml.YAMLError) as exc:
                findings.append(Finding("error", f"configuration does not parse: {exc}", name))
        return checked

    def _generated_reference(self, ctx: TaskContext, cfg: dict[str, Any], findings: list[Finding]):
        ref = cfg["generated_cli_reference"]
        if not ref:
            return "not configured", False
        try:
            target = ctx.policy.paths.check_read(ref)
        except PolicyError as exc:
            findings.append(Finding("error", str(exc), ref))
            return "blocked", False
        writing = cfg["mode"] == "write"
        if not target.exists():
            if not writing:
                findings.append(Finding("warning", "generated CLI reference is missing", ref))
                return "missing", False
            header = "# CLI reference\n\nThis section is generated by Pulse.\n\n"
            changed = ctx.write_file(ref, header + render_section(ref) + "\n")
            return "created", changed
        existing = target.read_text(encoding="utf-8")
        updated = replace_generated_section(existing)
        if updated is None:
            findings.append(
                Finding("error", f"markers {CLI_REFERENCE_START} and {CLI_REFERENCE_END} not found", ref)
            )
            return "markers missing", False
        if updated == existing:
            return "up to date", False
        if not writing:
            findings.append(
                Finding("warning", "generated CLI reference is out of date (use mode: write)", ref)
            )
            return "out of date", False
        return "updated", ctx.write_file(ref, updated)

    # ---- execution --------------------------------------------------------------------

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        cfg = ctx.task_config
        findings: list[Finding] = []
        present = 0
        for name in cfg["required_files"]:
            ctx.check()
            try:
                target = ctx.policy.paths.check_read(name)
            except PolicyError as exc:
                findings.append(Finding("error", str(exc), name))
                continue
            if target.is_file():
                present += 1
            else:
                findings.append(Finding("error", "required file is missing", name))

        if cfg["required_readme_sections"]:
            readme = ctx.repo / "README.md"
            if readme.is_file():
                outside, _ = split_fences(readme.read_text(encoding="utf-8", errors="replace"))
                have = {title.lower() for _, title in headings(outside)}
                for section in cfg["required_readme_sections"]:
                    if section.lower() not in have:
                        findings.append(Finding("error", f"README section missing: {section}", "README.md"))

        totals = {"broken_links": 0, "fence_problems": 0, "marker_hits": 0, "heading_jumps": 0}
        files = self._markdown_files(ctx.repo)
        for md in files:
            ctx.check()
            for key, value in self._check_file(ctx, md, cfg, findings).items():
                totals[key] += value
        example_checked = self._check_example_config(ctx, findings)
        reference_state, wrote = self._generated_reference(ctx, cfg, findings)

        summary = (
            f"{present}/{len(cfg['required_files'])} required files, {len(files)} Markdown files "
            f"checked, {totals['broken_links']} broken links, CLI reference {reference_state}"
        )
        metrics = {
            "required_present": present,
            "required_total": len(cfg["required_files"]),
            "markdown_files": len(files),
            "example_config_checked": example_checked,
            "cli_reference": reference_state if not wrote else "current",
            **totals,
        }
        status = None
        if not any(f.severity == "error" for f in findings) and not ctx.changed_paths and cfg["mode"] == "write":
            status = NO_CHANGES
        result = finalize(self, summary, findings, status=status, metrics=metrics)
        result.changed_paths = list(ctx.changed_paths)
        return result
