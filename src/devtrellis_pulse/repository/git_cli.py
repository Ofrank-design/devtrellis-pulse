"""Git through the command line: argument lists only, never a shell, bounded by timeouts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from devtrellis_pulse.core.errors import DependencyError, GitError, NotARepositoryError
from devtrellis_pulse.core.models import RepoSnapshot, StatusEntry
from devtrellis_pulse.repository.status import detect_operation, parse_porcelain_z, sanitize_remote


class GitCli:
    def __init__(self, root: Path, timeout: int = 30) -> None:
        self.root = Path(root)
        self.timeout = timeout

    # ---- low level --------------------------------------------------------------------

    def run(self, *args: str, check: bool = True, input_text: str | None = None) -> str:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_") or k in {"GIT_SSH_COMMAND", "GIT_SSH"}
        }
        env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"})
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                input=input_text,
                shell=False,
            )
        except FileNotFoundError:
            raise DependencyError("git executable not found") from None
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} timed out after {self.timeout}s") from None
        if check and proc.returncode != 0:
            message = (proc.stderr or proc.stdout).strip().splitlines()
            raise GitError(f"git {args[0]} failed: {message[0] if message else proc.returncode}")
        return proc.stdout

    # ---- inspection -------------------------------------------------------------------

    def version(self) -> str:
        return self.run("--version", check=False).strip()

    def is_repository(self) -> bool:
        try:
            return self.run("rev-parse", "--is-inside-work-tree", check=False).strip() == "true"
        except GitError:
            return False

    def toplevel(self) -> Path:
        return Path(self.run("rev-parse", "--show-toplevel").strip()).resolve()

    def git_dir(self) -> Path:
        raw = self.run("rev-parse", "--absolute-git-dir").strip()
        return Path(raw)

    def branch(self) -> str | None:
        out = self.run("symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
        return out or None

    def head(self) -> str | None:
        out = self.run("rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        return out or None

    def remote_url(self) -> str | None:
        names = self.run("remote", check=False).split()
        if not names:
            return None
        name = "origin" if "origin" in names else names[0]
        return sanitize_remote(self.run("remote", "get-url", name, check=False))

    def is_shallow(self) -> bool:
        return self.run("rev-parse", "--is-shallow-repository", check=False).strip() == "true"

    def is_sparse(self) -> bool:
        return self.run("config", "--get", "core.sparseCheckout", check=False).strip() == "true"

    def submodules(self) -> list[str]:
        raw = self.run("ls-files", "--stage", "-z", check=False)
        found = []
        for item in raw.split("\0"):
            if item.startswith("160000"):
                found.append(item.split("\t", 1)[-1])
        return found

    def status(self) -> list[StatusEntry]:
        raw = self.run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return parse_porcelain_z(raw)

    def tracked_files(self) -> list[str]:
        return [p for p in self.run("ls-files", "-z").split("\0") if p]

    def snapshot(self) -> RepoSnapshot:
        if not self.root.exists():
            raise NotARepositoryError(f"path does not exist: {self.root}")
        if not self.is_repository():
            raise NotARepositoryError(f"not a Git repository: {self.root}")
        return RepoSnapshot(
            root=str(self.toplevel()),
            branch=self.branch(),
            head=self.head(),
            remote=self.remote_url(),
            entries=self.status(),
            operation=detect_operation(self.git_dir()),
            shallow=self.is_shallow(),
            sparse=self.is_sparse(),
            submodules=self.submodules(),
        )

    def recent_commits(self, days: int = 30) -> dict[str, object]:
        count = self.run("rev-list", "--count", f"--since={days}.days", "HEAD", check=False).strip()
        last = self.run("log", "-1", "--format=%cI%x09%s", check=False).strip()
        stamp, _, subject = last.partition("\t")
        return {
            f"commits_last_{days}_days": int(count) if count.isdigit() else 0,
            "last_commit_date": stamp or None,
            "last_commit_subject": subject or None,
        }

    # ---- mutation (used only by the commit manager) -----------------------------------

    def stage(self, paths: list[str]) -> None:
        self.run("add", "--", *paths)  # explicit paths only, never `add -A`

    def unstage(self, paths: list[str]) -> None:
        self.run("reset", "-q", "--", *paths, check=False)  # index only, working tree untouched

    def commit(self, paths: list[str], subject: str, body: str, name: str, email: str) -> str:
        args = [
            "-c", f"user.name={name}",
            "-c", f"user.email={email}",
            "commit", "--only", "-m", subject,
        ]
        if body:
            args += ["-m", body]
        self.run(*args, "--", *paths)
        sha = self.head()
        if not sha:
            raise GitError("commit succeeded but HEAD could not be read")
        return sha

    def push(self, remote: str, branch: str) -> None:
        self.run("push", remote, f"HEAD:refs/heads/{branch}")  # never forced
