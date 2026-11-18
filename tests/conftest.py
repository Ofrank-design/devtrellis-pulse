from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import git, make_cfg


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep every test away from the real state directory and from the caller's environment."""
    monkeypatch.setenv("PULSE_STATE_DIR", str(tmp_path / "state"))
    for name in (
        "PULSE_CONFIG",
        "PULSE_REPO",
        "PULSE_MAX_OPERATIONS",
        "PULSE_MAX_RUNTIME_SECONDS",
        "PULSE_MAX_TASK_RUNTIME_SECONDS",
        "PULSE_TIMEZONE",
        "NO_COLOR",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "user.name", "Dev Person")
    (root / "README.md").write_text("# Demo\n\nA small project.\n")
    (root / "LICENSE").write_text("license text\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial commit")
    return root


@pytest.fixture
def commit_cfg():
    """Standard mode, reports written into the repository, commits on."""
    return make_cfg(
        runtime={"mode": "standard"},
        commit={"enabled": True},
        reports={"write_to_repository": True},
    )
