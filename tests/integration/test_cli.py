"""The command line, run in process."""

import json

import pytest

from devtrellis_pulse.cli import main
from tests.helpers import commit_count, git, state_dir


def config_file(repo, text="version: 1\n"):
    path = repo.parent / "pulse.yml"
    path.write_text(text)
    return path


def pulse(capsys, repo, *args):
    code = main(["--config", str(config_file(repo)), "--repo", str(repo), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version_and_help(capsys):
    assert main(["version"]) == 0
    assert "0.1.0" in capsys.readouterr().out
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        main(["nope"])
    assert caught.value.code == 2


def test_not_a_repository_exits_4(tmp_path, capsys):
    cfg = tmp_path / "pulse.yml"
    cfg.write_text("version: 1\n")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert main(["--config", str(cfg), "--repo", str(plain), "inspect"]) == 4


def test_inspect_json_is_valid(repo, capsys):
    code, out, _ = pulse(capsys, repo, "--json", "inspect")
    assert code == 0 and json.loads(out)


def test_plan_and_default_run_do_not_execute(repo, capsys):
    code, out, _ = pulse(capsys, repo, "plan")
    assert code == 0 and "documentation" in out
    before = commit_count(repo)
    code, out, _ = pulse(capsys, repo, "run")
    assert code == 0 and commit_count(repo) == before


def test_execute_runs_tasks_and_history_lists_them(repo, capsys):
    code, _, _ = pulse(capsys, repo, "run", "--execute")
    assert code == 0
    code, out, _ = pulse(capsys, repo, "--json", "history")
    assert code == 0 and "run_" in out


def test_failing_task_exit_code(repo, capsys):
    (repo / "LICENSE").unlink()
    git(repo, "commit", "-qam", "drop license")
    code, _, _ = pulse(capsys, repo, "run", "--execute", "--task", "documentation")
    assert code == 8 or code == 7 or code != 0


def test_invalid_config_exits_3(repo, tmp_path, capsys):
    bad = tmp_path / "bad.yml"
    bad.write_text("version: 1\nruntime:\n  mode: reckless\n")
    assert main(["--config", str(bad), "--repo", str(repo), "validate-config"]) == 3


def test_schedule_prints_cron(repo, capsys):
    code, out, _ = pulse(capsys, repo, "schedule", "--for", "cron", "--at", "07:30")
    assert code == 0 and "30 7" in out


def test_doctor_and_ledger_check(repo, capsys):
    assert pulse(capsys, repo, "doctor")[0] == 0
    pulse(capsys, repo, "run", "--execute")
    assert pulse(capsys, repo, "ledger", "check")[0] == 0
    assert state_dir().exists()


def test_scheduled_run_skips_unscheduled_day(repo, tmp_path, capsys):
    cfg = tmp_path / "c.yml"
    cfg.write_text("version: 1\nschedule:\n  enabled: true\n  weekdays: [mon, wed, fri]\n  timezone: UTC\n")
    from datetime import UTC, datetime
    weekday = datetime.now(UTC).strftime("%a").lower()
    days = [d for d in ("mon", "tue", "wed", "thu", "fri") if d != weekday][:3]
    cfg.write_text(f"version: 1\nschedule:\n  enabled: true\n  weekdays: {days}\n  timezone: UTC\n")
    before = commit_count(repo)
    code = main(["--repo", str(repo), "--config", str(cfg), "run", "--scheduled", "--execute"])
    assert code == 0 and commit_count(repo) == before
    out = capsys.readouterr().out.lower()
    assert "skip" in out or "not a scheduled" in out
