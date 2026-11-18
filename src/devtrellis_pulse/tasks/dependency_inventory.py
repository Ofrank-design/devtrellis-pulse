"""Dependency Manifest Inspector: counts declared packages. Makes no vulnerability claims."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from devtrellis_pulse.core.models import Finding, TaskResult
from devtrellis_pulse.tasks.base import Task, TaskPlan, finalize

if TYPE_CHECKING:
    from devtrellis_pulse.execution.context import TaskContext


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _pyproject(path: Path) -> int:
    data = _toml(path)
    project = data.get("project", {})
    count = len(project.get("dependencies", []))
    count += sum(len(v) for v in project.get("optional-dependencies", {}).values())
    poetry = data.get("tool", {}).get("poetry", {})
    count += len([k for k in poetry.get("dependencies", {}) if k.lower() != "python"])
    return count


def _requirements(path: Path) -> int:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith(("#", "-")))


def _package_json(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))


def _pipfile(path: Path) -> int:
    data = _toml(path)
    return len(data.get("packages", {})) + len(data.get("dev-packages", {}))


def _cargo(path: Path) -> int:
    data = _toml(path)
    return len(data.get("dependencies", {})) + len(data.get("dev-dependencies", {}))


def _go_mod(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    block = sum(
        len([ln for ln in m.group(1).splitlines() if ln.strip() and not ln.strip().startswith("//")])
        for m in re.finditer(r"require\s*\((.*?)\)", text, re.S)
    )
    single = len(re.findall(r"^require[ \t]+[^\s(]\S*[ \t]+\S+", text, re.M))
    return block + single


def _gemfile(path: Path) -> int:
    return len(re.findall(r"^\s*gem\s+['\"]", path.read_text(encoding="utf-8", errors="replace"), re.M))


def _composer(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    names = list(data.get("require", {})) + list(data.get("require-dev", {}))
    return len([n for n in names if n != "php" and not n.startswith("ext-")])


# manifest -> (parser, lockfiles that satisfy it or None when no lockfile is expected)
_PARSERS: dict[str, tuple[Callable[[Path], int], tuple[str, ...] | None]] = {
    "pyproject.toml": (_pyproject, None),
    "requirements.txt": (_requirements, None),
    "Pipfile": (_pipfile, ("Pipfile.lock",)),
    "package.json": (_package_json, ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")),
    "go.mod": (_go_mod, ("go.sum",)),
    "Cargo.toml": (_cargo, ("Cargo.lock",)),
    "Gemfile": (_gemfile, ("Gemfile.lock",)),
    "composer.json": (_composer, ("composer.lock",)),
}
_UNPARSED = ("setup.py", "setup.cfg", "pom.xml", "build.gradle", "environment.yml")


class DependencyInventory(Task):
    task_id = "dependency_inventory"
    name = "Dependency Manifest Inspector"
    description = "Dependency manifests, declared package counts and lockfiles"
    retry_safe = True
    default_timeout_seconds = 30

    def execute(self, ctx: TaskContext, plan: TaskPlan) -> TaskResult:
        repo = ctx.repo
        findings: list[Finding] = []
        counts: dict[str, int | None] = {}
        locks: list[str] = []
        candidates = list(_PARSERS) + sorted(p.name for p in repo.glob("requirements-*.txt"))
        for name in candidates:
            ctx.check()
            path = repo / name
            if not path.is_file() or path.is_symlink():
                continue
            parser = _PARSERS.get(name, (_requirements, None))[0]
            try:
                counts[name] = parser(path)
            except (ValueError, OSError, tomllib.TOMLDecodeError):
                counts[name] = None
                findings.append(Finding("info", "could not parse; no count reported", name))
                continue
            wanted = _PARSERS.get(name, (None, None))[1]
            if wanted:
                present = [n for n in wanted if (repo / n).is_file()]
                locks.extend(present)
                if not present:
                    findings.append(Finding("warning", f"no lockfile found (expected {wanted[0]})", name))
        for name in _UNPARSED:
            if (repo / name).is_file():
                counts[name] = None
                findings.append(Finding("info", "manifest format not parsed by Pulse; no count reported", name))
        parsed = {k: v for k, v in counts.items() if v is not None}
        summary = (
            f"{len(counts)} dependency manifest(s), {sum(parsed.values())} declared package(s)"
            if counts
            else "no dependency manifests"
        )
        return finalize(
            self,
            summary,
            findings,
            metrics={"manifests": dict(sorted(counts.items())), "lockfiles": sorted(locks)},
        )
