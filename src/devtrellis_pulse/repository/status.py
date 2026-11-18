"""Parsing of Git status output and detection of special repository states."""

from __future__ import annotations

import re
from pathlib import Path

from devtrellis_pulse.core.models import StatusEntry

_CRED_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")


def sanitize_remote(url: str | None) -> str | None:
    """Strip embedded credentials from a remote URL."""
    if not url:
        return None
    return _CRED_RE.sub(r"\1", url.strip())


def parse_porcelain_z(raw: str) -> list[StatusEntry]:
    """Parse `git status --porcelain=v1 -z` output (paths may contain spaces or Unicode)."""
    entries: list[StatusEntry] = []
    parts = raw.split("\0")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        index, worktree, path = item[0], item[1], item[3:]
        orig = None
        if index in "RC" or worktree in "RC":
            orig = parts[i] if i < len(parts) else None
            i += 1
        entries.append(StatusEntry(path=path, index=index, worktree=worktree, orig_path=orig))
    return entries


_OPERATION_MARKERS = (
    ("MERGE_HEAD", "merge"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
)


def detect_operation(git_dir: Path) -> str | None:
    """Detect an in progress merge, rebase, cherry-pick or revert."""
    for marker, name in _OPERATION_MARKERS:
        if (git_dir / marker).exists():
            return name
    return None
