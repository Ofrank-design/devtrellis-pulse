"""Whole runs through the engine against disposable repositories."""

import json

import pytest

from devtrellis_pulse.core.errors import PolicyError
from devtrellis_pulse.execution.cancellation import CancellationToken
from tests.helpers import commit_count, execute, git, head, ledger_path, make_cfg, task


def ledger_events():
    return [json.loads(line) for line in ledger_path().read_text().splitlines() if line.strip()]


def test_default_run_changes_nothing_in_the_repository(repo):
    before = (head(repo), git(repo, "status", "--porcelain"))
    run = execute(make_cfg(), repo)
    assert (head(repo), git(repo, "status", "--porcelain")) == before
    assert run.exit_code == 0 and run.commits == []


def test_dry_run_runs_no_tasks(repo):
    run = execute(make_cfg(), repo, dry_run=True)
    assert run.dry_run and run.tasks == []
    assert run.exit_code == 0


def test_every_run_is_recorded_in_the_ledger(repo):
    run = execute(make_cfg(), repo)
    events = ledger_events()
    assert events and all(e.get("event_id") and e.get("schema_version") for e in events)
    assert any(run.run_id in json.dumps(e) for e in events)


def test_failing_task_gives_a_nonzero_exit_and_keeps_going(repo):
    (repo / "LICENSE").unlink()
    git(repo, "commit", "-qam", "remove license")
    run = execute(make_cfg(), repo)
    assert task(run, "documentation").status == "failed"
    assert task(run, "repository_health").status == "passed"
    assert run.exit_code != 0


def test_cancellation_stops_before_any_task_runs(repo):
    token = CancellationToken()
    token.cancel()
    run = execute(make_cfg(), repo, cancel=token)
    assert run.exit_code == 130


def test_dirty_working_tree_blocks_a_writing_run(repo, commit_cfg):
    (repo / "scratch.txt").write_text("user work\n")
    with pytest.raises(PolicyError, match="uncommitted changes"):
        execute(commit_cfg, repo)
    assert commit_count(repo) == 1
    assert (repo / "scratch.txt").read_text() == "user work\n"
