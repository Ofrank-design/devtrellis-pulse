"""Locations of Pulse runtime state. State never lives inside the target repository."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path

APP_DIR = "devtrellis-pulse"


def default_state_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the state directory: PULSE_STATE_DIR, then XDG_STATE_HOME, then ~/.local/state."""
    env = os.environ if environ is None else environ
    explicit = env.get("PULSE_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = env.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / APP_DIR


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def repo_fingerprint(root: Path) -> str:
    """Stable identifier for a repository location. Does not expose the path itself."""
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def short_fingerprint(fingerprint: str) -> str:
    return fingerprint.split(":")[-1][:12]


def is_writable_dir(path: Path) -> bool:
    try:
        ensure_private_dir(path)
    except OSError:
        return False
    return os.access(path, os.W_OK)
