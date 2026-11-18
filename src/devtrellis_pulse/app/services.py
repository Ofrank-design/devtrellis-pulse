"""Wiring: resolve settings with the documented precedence and build what commands need.

Precedence for every setting that has more than one source, highest first:
explicit CLI option, documented environment variable, configuration file, built in default.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from devtrellis_pulse.core.config import Config, load_config, resolve_repo_path
from devtrellis_pulse.core.errors import NotARepositoryError
from devtrellis_pulse.platform.paths import default_state_dir, repo_fingerprint

DEFAULT_CONFIG_NAME = "pulse.yml"


@dataclass
class Environment:
    cfg: Config
    config_path: Path
    repo: Path
    state_dir: Path
    ledger_path: Path

    @property
    def fingerprint(self) -> str:
        return repo_fingerprint(self.repo)


def resolve_config_path(explicit: str | None, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(explicit or env.get("PULSE_CONFIG") or DEFAULT_CONFIG_NAME)


def resolve_environment(
    config: str | None,
    repo: str | None,
    state_dir: str | None,
    environ: Mapping[str, str] | None = None,
) -> Environment:
    env = os.environ if environ is None else environ
    config_path = resolve_config_path(config, env)
    cfg = load_config(config_path, env)
    repo_choice = repo or env.get("PULSE_REPO")
    repo_path = resolve_repo_path(cfg, config_path, repo_choice)
    if not repo_path.is_dir():  # never fall back to a different repository
        raise NotARepositoryError(f"repository path does not exist: {repo_path}")
    if state_dir:
        state = Path(state_dir).expanduser()
    else:
        state = default_state_dir(env)
    ledger = Path(cfg["ledger"]["path"]).expanduser() if cfg["ledger"]["path"] else state / "activity.jsonl"
    return Environment(cfg, config_path, repo_path, state, ledger)
