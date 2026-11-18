"""Shared helpers for the test suite."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from devtrellis_pulse.core.config import Config, validate
from devtrellis_pulse.execution.cancellation import CancellationToken
from devtrellis_pulse.execution.engine import RunEngine


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def commit_count(repo: Path) -> int:
    return int(git(repo, "rev-list", "--count", "HEAD").strip())


def make_cfg(**sections: Any) -> Config:
    return validate({"version": 1, **sections})


def state_dir() -> Path:
    return Path(os.environ["PULSE_STATE_DIR"])


def ledger_path() -> Path:
    return state_dir() / "activity.jsonl"


def execute(
    cfg: Config,
    repo: Path,
    *,
    dry_run: bool = False,
    only: list[str] | None = None,
    cancel: CancellationToken | None = None,
):
    engine = RunEngine(cfg, repo, state_dir(), ledger_path(), cancel)
    return engine.execute(dry_run=dry_run, only=only)


def task(run, task_id: str):
    return next(t for t in run.tasks if t.task_id == task_id)
