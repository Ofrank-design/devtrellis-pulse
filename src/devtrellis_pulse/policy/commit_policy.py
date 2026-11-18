"""Commit policy: what must be true before Pulse may create or publish a commit."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.core.models import RepoSnapshot
from devtrellis_pulse.policy.paths import PathPolicy, glob_to_regex, normalize_relative


def path_in_commit_scope(rel: str, cfg: dict[str, Any], policy: PathPolicy) -> bool:
    """A path may be committed only if it is allowlisted for commits and not denied."""
    if policy.is_denied(rel):
        return False
    return any(glob_to_regex(p).match(rel) for p in cfg["commit"]["allow_paths"])


def commit_scope_problems(paths: list[str], cfg: dict[str, Any], policy: PathPolicy) -> list[str]:
    problems = []
    for raw in paths:
        try:
            rel = normalize_relative(raw)
        except Exception:
            problems.append(f"invalid path: {raw!r}")
            continue
        if not path_in_commit_scope(rel, cfg, policy):
            problems.append(f"outside commit.allow_paths or denied: {rel}")
    return problems


def push_blockers(cfg: dict[str, Any], snapshot_branch: str | None) -> list[str]:
    commit = cfg["commit"]
    blockers = []
    if not commit["push"]:
        blockers.append("commit.push is false")
        return blockers
    if not cfg["policy"]["allow_network"]:
        blockers.append("policy.allow_network is false")
    if snapshot_branch != commit["branch"]:
        blockers.append(
            f"current branch {snapshot_branch!r} is not the configured commit.branch "
            f"{commit['branch']!r}"
        )
    return blockers


def clean_start_required(cfg: dict[str, Any]) -> bool:
    return bool(cfg["repository"]["require_clean_start"] or cfg["commit"]["require_clean_start"])


def overlap_with_user_changes(produced: list[str], snapshot: RepoSnapshot) -> list[str]:
    return sorted(set(produced) & snapshot.dirty_paths)
