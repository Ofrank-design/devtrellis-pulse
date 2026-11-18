"""Commit manager behaviour against disposable repositories."""

import pytest

from devtrellis_pulse.core.errors import PolicyError
from tests.helpers import commit_count, execute, git, head, make_cfg


def test_commit_mode_off_means_no_commit_even_with_reports(repo):
    cfg = make_cfg(runtime={"mode": "standard"}, reports={"write_to_repository": True})
    run = execute(cfg, repo)
    assert run.commits == [] and commit_count(repo) == 1


def test_a_report_commit_contains_only_report_files(repo, commit_cfg):
    run = execute(commit_cfg, repo)
    assert run.commit_status == "committed" and len(run.commits) == 1
    files = git(repo, "show", "--name-only", "--format=").split()
    assert files and all(f.startswith("reports/pulse/") for f in files)
    assert git(repo, "log", "-1", "--format=%an <%ae>").strip().startswith("DevTrellis Pulse")
    assert git(repo, "status", "--porcelain").strip() == ""


def test_commit_message_is_plain_and_names_the_run(repo, commit_cfg):
    run = execute(commit_cfg, repo)
    message = git(repo, "log", "-1", "--format=%B")
    assert message.startswith("chore(pulse): ") and run.run_id in message


def test_staged_user_changes_are_never_swept_in(repo, commit_cfg):
    # Staged work from the user blocks the clean start rule, so nothing is committed.
    (repo / "mine.txt").write_text("work\n")
    git(repo, "add", "mine.txt")
    before = head(repo)
    with pytest.raises(PolicyError, match="uncommitted"):
        execute(commit_cfg, repo)
    assert head(repo) == before
    assert git(repo, "diff", "--cached", "--name-only").split() == ["mine.txt"]


def test_failing_commit_hook_preserves_the_files(repo, commit_cfg):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho rejected >&2\nexit 1\n")
    hook.chmod(0o755)
    run = execute(commit_cfg, repo)
    assert run.commit_status == "failed" and run.exit_code == 9
    assert commit_count(repo) == 1
    assert (repo / "reports" / "pulse").exists()  # nothing was discarded


def test_push_goes_to_a_local_bare_remote(repo, tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    cfg = make_cfg(
        runtime={"mode": "standard"},
        policy={"allow_network": True},
        reports={"write_to_repository": True},
        commit={"enabled": True, "push": True, "remote": "origin", "branch": "main"},
    )
    run = execute(cfg, repo)
    assert run.commits and run.commits[0].pushed
    assert git(bare, "rev-parse", "main").strip() == head(repo)


def test_push_failure_is_reported_not_hidden(repo, tmp_path):
    git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    cfg = make_cfg(
        runtime={"mode": "standard"},
        policy={"allow_network": True},
        reports={"write_to_repository": True},
        commit={"enabled": True, "push": True, "remote": "origin", "branch": "main"},
    )
    run = execute(cfg, repo)
    assert run.commits and not run.commits[0].pushed
    assert run.exit_code != 0
