from pathlib import Path

import pytest
import yaml

from devtrellis_pulse.core.config import DEFAULTS, load_config, starter_yaml, validate
from devtrellis_pulse.core.errors import ConfigError
from devtrellis_pulse.tasks import CONFIGURABLE

ROOT = Path(__file__).resolve().parents[2]


def test_defaults_are_safe():
    cfg = validate({"version": 1})
    assert cfg["runtime"]["mode"] == "safe"
    assert cfg["runtime"]["dry_run_by_default"] is True
    assert cfg["commit"]["enabled"] is False
    assert cfg["commit"]["push"] is False
    assert cfg["policy"]["allow_network"] is False
    assert cfg["policy"]["allow_deleting_files"] is False
    assert cfg["policy"]["allow_symlinks"] is False
    assert cfg["tasks"]["tests"]["enabled"] is False  # runs repository code


def test_version_is_required():
    with pytest.raises(ConfigError, match="version"):
        validate({})


def test_unknown_key_is_a_warning_not_an_error():
    cfg = validate({"version": 1, "commit": {"enabeld": True}})
    assert any("commit.enabeld" in w for w in cfg.warnings)
    assert cfg["commit"]["enabled"] is False


def test_unknown_task_id_is_an_error():
    with pytest.raises(ConfigError, match="unknown task id"):
        validate({"version": 1, "tasks": {"mystery": {"enabled": True}}})


def test_config_tasks_match_the_registry():
    assert set(DEFAULTS["tasks"]) == set(CONFIGURABLE)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"commit": {"enabled": "yes"}}, "expected bool"),
        ({"runtime": {"max_runtime_seconds": True}}, "expected integer"),
        ({"runtime": {"max_operations_per_run": 0}}, "between 1 and 100"),
        ({"runtime": {"max_operations_per_run": 101}}, "between 1 and 100"),
        ({"runtime": {"max_task_runtime_seconds": 0}}, "between"),
        ({"runtime": {"mode": "yolo"}}, "one of"),
        ({"tasks": {"tests": {"commands": ["pytest -q"]}}}, "shell strings"),
        ({"tasks": {"tests": {"commands": [[]]}}}, "non empty list"),
        ({"schedule": {"weekdays": ["mon", "mon"]}}, "unique"),
        ({"schedule": {"weekdays": ["funday"]}}, "unrecognized"),
        ({"schedule": {"timezone": "Mars/Base"}}, "IANA"),
        ({"project": {"timezone": "nope"}}, "IANA"),
        ({"reports": {"output_directory": "../outside"}}, "relative path"),
        ({"reports": {"output_directory": "/etc"}}, "relative path"),
        ({"reports": {"redact_patterns": ["("]}}, "regular expression"),
        ({"reports": {"format": []}}, "reports.format"),
        ({"policy": {"denied_paths": ["../x"]}}, "inside the repository"),
        ({"policy": {"allowed_write_paths": ["/abs"]}}, "relative"),
        ({"repository": {"require_git": False}}, "not supported"),
    ],
)
def test_invalid_values_are_rejected(data, message):
    with pytest.raises(ConfigError, match=message):
        validate({"version": 1, **data})


def test_commit_needs_standard_mode():
    with pytest.raises(ConfigError, match="runtime.mode: standard"):
        validate({"version": 1, "commit": {"enabled": True}})


def test_repository_reports_need_standard_mode():
    with pytest.raises(ConfigError, match="runtime.mode: standard"):
        validate({"version": 1, "reports": {"write_to_repository": True}})


def test_commit_allowlist_must_be_inside_write_allowlist():
    with pytest.raises(ConfigError, match="not covered"):
        validate({"version": 1, "commit": {"allow_paths": ["src/**"]}})
    cfg = validate(
        {
            "version": 1,
            "policy": {"allowed_write_paths": ["docs/**"]},
            "commit": {"allow_paths": ["docs/generated/**"]},
        }
    )
    assert cfg["commit"]["allow_paths"] == ["docs/generated/**"]


@pytest.mark.parametrize(
    "commit, policy, message",
    [
        ({"push": True}, {}, "requires commit.enabled"),
        ({"push": True, "enabled": True}, {}, "remote and commit.branch"),
        ({"push": True, "enabled": True, "remote": "origin", "branch": "main"}, {}, "allow_network"),
    ],
)
def test_push_needs_explicit_policy(commit, policy, message):
    data = {"version": 1, "runtime": {"mode": "standard"}, "commit": commit, "policy": policy}
    with pytest.raises(ConfigError, match=message):
        validate(data)


def test_push_accepted_when_fully_declared():
    cfg = validate(
        {
            "version": 1,
            "runtime": {"mode": "standard"},
            "policy": {"allow_network": True},
            "commit": {"enabled": True, "push": True, "remote": "origin", "branch": "main"},
        }
    )
    assert cfg["commit"]["push"] is True


def test_write_modes_need_matching_scope():
    base = {"version": 1, "runtime": {"mode": "standard"}}
    with pytest.raises(ConfigError, match="generated_cli_reference"):
        validate({**base, "tasks": {"documentation": {"mode": "write"}}})
    with pytest.raises(ConfigError, match="allowed_write_paths"):
        validate(
            {
                **base,
                "tasks": {"documentation": {"mode": "write", "generated_cli_reference": "docs/x.md"}},
            }
        )
    with pytest.raises(ConfigError, match="write_commands and paths"):
        validate({**base, "tasks": {"code_hygiene": {"mode": "write"}}})


def test_schedule_requires_days_and_warns_outside_the_recommended_range():
    with pytest.raises(ConfigError, match="weekdays"):
        validate({"version": 1, "schedule": {"enabled": True, "weekdays": []}})
    cfg = validate({"version": 1, "schedule": {"enabled": True, "weekdays": ["mon"]}})
    assert any("three to five" in w for w in cfg.warnings)
    quiet = validate({"version": 1, "schedule": {"enabled": True, "weekdays": ["mon", "tue", "wed"]}})
    assert not quiet.warnings


def test_timezone_from_the_spec_example_is_valid():
    cfg = validate({"version": 1, "schedule": {"timezone": "Africa/Accra"}})
    assert cfg["schedule"]["timezone"] == "Africa/Accra"


def test_fingerprint_tracks_content():
    a = validate({"version": 1})
    b = validate({"version": 1})
    c = validate({"version": 1, "project": {"name": "other"}})
    assert a.fingerprint == b.fingerprint != c.fingerprint


# ---- loading and precedence -------------------------------------------------------------


def test_starter_yaml_parses_back_to_the_defaults():
    parsed = validate(yaml.safe_load(starter_yaml()))
    assert dict(parsed) == dict(validate({"version": 1}))
    assert not parsed.warnings


def test_example_file_matches_the_generated_starter():
    assert (ROOT / "pulse.example.yml").read_text() == starter_yaml()


def test_load_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yml")
    bad = tmp_path / "bad.yml"
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(bad)
    empty = tmp_path / "empty.yml"
    empty.write_text("")
    with pytest.raises(ConfigError, match="empty"):
        load_config(empty)
    listy = tmp_path / "list.yml"
    listy.write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(listy)


def test_environment_beats_the_file(tmp_path):
    path = tmp_path / "pulse.yml"
    path.write_text("version: 1\nruntime:\n  max_operations_per_run: 10\n")
    assert load_config(path, {})["runtime"]["max_operations_per_run"] == 10
    cfg = load_config(path, {"PULSE_MAX_OPERATIONS": "55"})
    assert cfg["runtime"]["max_operations_per_run"] == 55
    assert cfg.env_applied == ["PULSE_MAX_OPERATIONS"]


def test_environment_values_are_validated(tmp_path):
    path = tmp_path / "pulse.yml"
    path.write_text("version: 1\n")
    with pytest.raises(ConfigError, match="PULSE_MAX_OPERATIONS"):
        load_config(path, {"PULSE_MAX_OPERATIONS": "lots"})
    with pytest.raises(ConfigError, match="between 1 and 100"):
        load_config(path, {"PULSE_MAX_OPERATIONS": "500"})


def test_environment_can_never_enable_commits_or_network(tmp_path):
    path = tmp_path / "pulse.yml"
    path.write_text("version: 1\n")
    env = {"PULSE_COMMIT": "1", "PULSE_COMMIT_ENABLED": "true", "PULSE_ALLOW_NETWORK": "1"}
    cfg = load_config(path, env)
    assert cfg["commit"]["enabled"] is False
    assert cfg["policy"]["allow_network"] is False
    assert cfg.env_applied == []


@pytest.mark.parametrize("bad", ["/etc", "\\windows", "C:/x", "c:\\x", "../out", "a/../../b", "  "])
def test_unsafe_paths_are_caught_on_every_platform(bad):
    from devtrellis_pulse.core.config import is_unsafe_relative

    assert is_unsafe_relative(bad)


@pytest.mark.parametrize("good", ["reports/pulse", "docs", "a/b.md", "./x"])
def test_ordinary_relative_paths_are_fine(good):
    from devtrellis_pulse.core.config import is_unsafe_relative

    assert not is_unsafe_relative(good)
