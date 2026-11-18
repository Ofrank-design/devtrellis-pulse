"""Policy engine: path rules, task permissions and repository precondition checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devtrellis_pulse.core.errors import PolicyError
from devtrellis_pulse.core.models import RepoSnapshot
from devtrellis_pulse.policy.commit_policy import clean_start_required
from devtrellis_pulse.policy.paths import PathPolicy
from devtrellis_pulse.policy.permissions import task_block_reason


class PolicyEngine:
    def __init__(self, cfg: dict[str, Any], repo_root: Path) -> None:
        self.cfg = cfg
        p = cfg["policy"]
        self.paths = PathPolicy(
            repo_root,
            p["allowed_write_paths"],
            p["denied_paths"],
            p["allow_symlinks"],
            p["allowed_read_paths"],
        )

    def task_block_reason(self, task: Any) -> str | None:
        return task_block_reason(task, self.cfg)

    def _user_changes(self, snap: RepoSnapshot) -> list[str]:
        """Dirty paths, ignoring Pulse's own report folder when reports go into the repository."""
        paths = sorted(snap.dirty_paths)
        if not self.cfg["reports"]["write_to_repository"]:
            return paths
        out = self.cfg["reports"]["output_directory"].strip("/")
        return [p for p in paths if not (p == out or p.startswith(out + "/"))]

    def check_preconditions(self, snap: RepoSnapshot, will_write: bool) -> list[str]:
        """Raise PolicyError when the repository state forbids this run; else return warnings.

        Read only runs are allowed in most states. Anything that writes or commits is blocked
        when the repository is mid operation, off the expected branch, or has user changes.
        """
        cfg = self.cfg
        repo = cfg["repository"]
        warnings: list[str] = []
        user_changes = self._user_changes(snap)

        expected = repo["expected_branch"]
        if expected and snap.branch != expected:
            raise PolicyError(
                f"expected branch {expected!r} but the repository is on {snap.branch!r}"
            )
        if snap.shallow and not repo["allow_shallow_clone"]:
            raise PolicyError("shallow clone and repository.allow_shallow_clone is false")
        if snap.sparse:
            warnings.append("sparse checkout detected: some files may not be present")
        if snap.submodules:
            warnings.append(
                f"{len(snap.submodules)} submodule(s) detected; Pulse does not inspect their contents"
            )

        if snap.operation:
            message = f"a {snap.operation} is in progress"
            if will_write:
                raise PolicyError(f"{message}; finish or abort it before writing or committing")
            warnings.append(message)
        if snap.detached and not repo["allow_detached_head"]:
            if will_write:
                raise PolicyError("HEAD is detached and repository.allow_detached_head is false")
            warnings.append("HEAD is detached")
        if will_write and clean_start_required(cfg) and user_changes:
            raise PolicyError(
                "the working tree has uncommitted changes and a clean start is required for "
                "write or commit runs (repository.require_clean_start); commit or stash them first"
            )
        return warnings
