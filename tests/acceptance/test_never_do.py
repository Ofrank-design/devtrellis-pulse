"""Appendix M: what Pulse must never do, encoded as tests."""

import ast
import re
import time
from pathlib import Path

import pytest

from devtrellis_pulse.core.errors import PolicyError
from tests.helpers import commit_count, execute, git, head, make_cfg

SRC = Path(__file__).resolve().parents[2] / "src" / "devtrellis_pulse"
SOURCES = {p: p.read_text() for p in SRC.rglob("*.py")}


def string_literals(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


@pytest.mark.parametrize(
    "token",
    ["--force", "--force-with-lease", "--amend", "--hard", "--date", "clean", "--allow-empty", "-A"],
)
def test_forbidden_git_arguments_never_appear_as_arguments(token):
    # Only modules that talk to git are in scope; the CLI's own `init --force` is unrelated.
    for path, text in SOURCES.items():
        if path.parent.name not in {"repository", "commits", "execution", "tasks", "policy"}:
            continue
        for value in string_literals(ast.parse(text)):
            if value == token:
                pytest.fail(f"{path.name} passes {token!r} to git")


def test_no_network_libraries_are_imported():
    banned = {"requests", "urllib3", "httpx", "aiohttp", "socket", "http", "ftplib", "smtplib"}
    for path, text in SOURCES.items():
        for node in ast.walk(ast.parse(text)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            found = banned & set(names)
            if path.name == "lock.py":
                found -= {"socket"}  # only used to read the host name for lock identity
            assert not found, f"{path.name} imports {found}"


def test_no_shell_true_and_no_add_all():
    for path, text in SOURCES.items():
        assert not re.search(r"shell\s*=\s*True", text), path.name
        for value in string_literals(ast.parse(text)):
            assert value not in {"add -A", "add --all", "--all"}, path.name


def test_unchanged_content_never_makes_a_commit(repo, commit_cfg):
    # Items 1 to 3: no empty or no-op commits. A run that writes nothing commits nothing.
    quiet = make_cfg(runtime={"mode": "standard"}, commit={"enabled": True})
    before = commit_count(repo)
    run = execute(quiet, repo)
    assert run.commits == [] and commit_count(repo) == before


def test_commits_use_the_configured_identity_and_real_dates(repo, commit_cfg):
    execute(commit_cfg, repo)
    line = git(repo, "log", "-1", "--format=%an|%at|%ct").strip().split("|")
    assert line[0] == "DevTrellis Pulse" and line[1] == line[2]
    assert abs(int(line[1]) - time.time()) < 120


def test_preexisting_user_changes_are_not_committed(repo, commit_cfg):
    (repo / "README.md").write_text("# Edited by the user\n")
    with pytest.raises(PolicyError):
        execute(commit_cfg, repo)
    assert "README.md" in git(repo, "status", "--porcelain")
    assert commit_count(repo) == 1


def test_failures_are_never_reported_as_success(repo):
    (repo / "LICENSE").unlink()
    git(repo, "commit", "-qam", "drop license")
    run = execute(make_cfg(), repo)
    assert run.exit_code != 0 and run.status != "success"


def test_disabled_tasks_are_reported_as_skipped_not_passed(repo):
    run = execute(make_cfg(), repo)
    assert next(t for t in run.tasks if t.task_id == "tests").status == "skipped"


def test_a_clean_run_leaves_head_alone(repo):
    before = head(repo)
    execute(make_cfg(), repo)
    assert head(repo) == before
