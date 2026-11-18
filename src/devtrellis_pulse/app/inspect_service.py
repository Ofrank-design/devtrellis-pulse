"""Read only repository inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devtrellis_pulse.repository.git_cli import GitCli


def inspect(repo: Path) -> dict[str, Any]:
    git = GitCli(repo)
    snap = git.snapshot()
    staged = sorted(snap.staged_paths)
    untracked = sorted(e.path for e in snap.entries if e.untracked)
    modified = sorted(
        e.path for e in snap.entries if not e.untracked and e.worktree not in (" ", "?")
    )
    return {
        "root": snap.root,
        "branch": snap.branch,
        "head": snap.head,
        "remote": snap.remote,
        "git_version": git.version(),
        "clean": not snap.dirty,
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
        "operation_in_progress": snap.operation,
        "shallow": snap.shallow,
        "sparse": snap.sparse,
        "submodules": snap.submodules,
    }
