"""Diff helpers used by validation and reports."""

from __future__ import annotations

from devtrellis_pulse.repository.git_cli import GitCli


def staged_names(git: GitCli, paths: list[str]) -> list[str]:
    raw = git.run("diff", "--cached", "--name-only", "-z", "--", *paths)
    return [n for n in raw.split("\0") if n]


def staged_added_text(git: GitCli, paths: list[str]) -> str:
    """Only the added lines of the staged diff, which is what could introduce a secret."""
    diff = git.run("diff", "--cached", "-U0", "--", *paths)
    return "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )


def diff_stat(git: GitCli, paths: list[str]) -> str:
    if not paths:
        return ""
    return git.run("diff", "--stat", "HEAD", "--", *paths, check=False).strip()


def change_summary(git: GitCli, paths: list[str]) -> str:
    """One line per changed file: added and removed lines. Works for new, untracked files too."""
    if not paths:
        return ""
    tracked = set(git.tracked_files())
    lines = []
    for rel in paths:
        if rel in tracked:
            raw = git.run("diff", "--numstat", "HEAD", "--", rel, check=False).strip()
            if raw:
                added, removed, _ = raw.split("\t", 2)
                lines.append(f"{rel} | +{added} -{removed}")
                continue
        target = git.root / rel
        if target.is_file():
            count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
            lines.append(f"{rel} | +{count} (new file)")
    return "\n".join(lines)
