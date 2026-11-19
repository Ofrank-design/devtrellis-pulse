"""Configuration: defaults, loading, strict validation and documented environment overrides.

Precedence, highest first (specification 9.4): explicit CLI option, documented environment
variable, selected configuration file, built in safe default. There are no hidden rules.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

import yaml

from devtrellis_pulse.core.clock import get_zone
from devtrellis_pulse.core.errors import ConfigError
from devtrellis_pulse.platform.files import canonical_json, sha256_text

SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "project": {"name": "repository", "description": "", "timezone": "UTC"},
    "repository": {
        "path": ".",
        "expected_branch": None,
        "require_git": True,
        "require_clean_start": True,
        "allow_detached_head": False,
        "allow_shallow_clone": True,
    },
    "runtime": {
        "mode": "safe",
        "dry_run_by_default": True,
        "fail_fast": False,
        "max_runtime_seconds": 900,
        "max_operations_per_run": 40,
        "max_task_runtime_seconds": 180,
        "max_output_kilobytes_per_task": 128,
        "lock_wait_seconds": 0,
    },
    "limits": {
        "max_retries_per_task": 0,
        "max_changed_files_per_run": 25,
        "max_changed_bytes_per_run": 1048576,
    },
    "schedule": {
        "enabled": False,
        "weekdays": ["mon", "wed", "fri"],
        "timezone": "UTC",
        "missed_run_policy": "skip",
    },
    "tasks": {
        "documentation": {
            "enabled": True,
            "mode": "check",
            "required_files": ["README.md", "LICENSE"],
            "required_readme_sections": [],
            "forbidden_markers": [],
            "generated_cli_reference": "",
        },
        "tests": {
            "enabled": False,
            "commands": [["python", "-m", "pytest", "-q"]],
            "timeout_seconds": 240,
        },
        "code_hygiene": {
            "enabled": False,
            "mode": "check",
            "commands": [["ruff", "check", "."]],
            "write_commands": [],
            "paths": [],
            "timeout_seconds": 120,
        },
        "repository_health": {"enabled": True, "write_snapshot": False},
        "dependency_inventory": {"enabled": True},
    },
    "policy": {
        "allowed_read_paths": ["**"],
        "allowed_write_paths": ["reports/pulse/**"],
        "denied_paths": [
            ".git/**",
            ".env",
            ".env.*",
            "**/*.pem",
            "**/*.key",
            "**/id_rsa*",
        ],
        "allow_subprocesses": True,
        "allow_network": False,
        "allow_deleting_files": False,
        "allow_symlinks": False,
    },
    "commit": {
        "enabled": False,
        "push": False,
        "remote": None,
        "branch": None,
        "author_name": "DevTrellis Pulse",
        "author_email": "pulse-bot@example.invalid",
        "message_prefix": "chore(pulse)",
        "group_by": "task",
        "require_validation": True,
        "require_clean_start": True,
        "allow_paths": ["reports/pulse/**"],
        "max_file_kilobytes": 512,
    },
    "ledger": {"path": "", "retention_days": 90, "max_file_megabytes": 25},
    "reports": {
        "format": ["markdown", "json"],
        "output_directory": "reports/pulse",
        "write_to_repository": False,
        "include_diff_stat": True,
        "include_task_output": False,
        "redact_patterns": ["(?i)token=[^& ]+"],
    },
}

SECTION_COMMENTS = {
    "version": "Configuration schema version.",
    "project": "Project identity used in reports.",
    "repository": "Target repository and the state it must be in.",
    "runtime": "Execution mode and resource limits. mode: safe (read only) or standard.",
    "limits": "Bounds on retries and on how much a run may change.",
    "schedule": "Used by `pulse schedule` and `pulse run --scheduled`. Pulse has no daemon.",
    "tasks": "Built in tasks. Tasks that run repository code are disabled by default.",
    "policy": "Path and capability permissions. Denied paths always win.",
    "commit": "Commit and push controls. Off by default and never forced.",
    "ledger": "Activity ledger. Empty path means the default state directory.",
    "reports": "Report outputs. Written to the state directory unless write_to_repository is true.",
}

_ENUMS = {
    ("runtime", "mode"): ("safe", "standard"),
    ("schedule", "missed_run_policy"): ("skip",),
    ("commit", "group_by"): ("task", "run"),
}
_RANGES = {
    ("runtime", "max_runtime_seconds"): (1, 86400),
    ("runtime", "max_operations_per_run"): (1, 100),
    ("runtime", "max_task_runtime_seconds"): (1, 3600),
    ("runtime", "max_output_kilobytes_per_task"): (1, 10240),
    ("runtime", "lock_wait_seconds"): (0, 3600),
    ("limits", "max_retries_per_task"): (0, 5),
    ("limits", "max_changed_files_per_run"): (1, 1000),
    ("limits", "max_changed_bytes_per_run"): (1, 104857600),
    ("commit", "max_file_kilobytes"): (1, 10240),
    ("ledger", "retention_days"): (0, 36500),  # 0 means keep forever
    ("ledger", "max_file_megabytes"): (1, 1024),
}
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_FORMATS = ("markdown", "json")

# Scalar settings that environment variables may override. Policy and commit settings are
# deliberately absent: the environment can never switch on writes, commits, push or network.
ENV_OVERRIDES: dict[str, tuple[str, str, type]] = {
    "PULSE_MAX_OPERATIONS": ("runtime", "max_operations_per_run", int),
    "PULSE_MAX_RUNTIME_SECONDS": ("runtime", "max_runtime_seconds", int),
    "PULSE_MAX_TASK_RUNTIME_SECONDS": ("runtime", "max_task_runtime_seconds", int),
    "PULSE_TIMEZONE": ("schedule", "timezone", str),
}


class Config(dict):
    """A validated configuration. Behaves as a plain dict and carries load metadata."""

    warnings: list[str]
    source: str | None
    env_applied: list[str]

    def __init__(self, data: dict[str, Any], warnings: list[str] | None = None) -> None:
        super().__init__(data)
        self.warnings = warnings or []
        self.source = None
        self.env_applied = []

    @property
    def fingerprint(self) -> str:
        return sha256_text(canonical_json(dict(self)))


# ---- glob helpers -----------------------------------------------------------------------


def is_unsafe_relative(path: str) -> bool:
    """True for empty, absolute or parent escaping paths, whatever the host operating system.

    Checked by hand so `/etc` and `C:\\x` are caught on every platform. On Windows, a path
    like `/etc` has no drive letter and Path.is_absolute() would call it relative.
    """
    text = path.strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return True
    return ".." in text.split("/")


def validate_glob(pattern: Any, where: str) -> str:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ConfigError(f"{where}: glob patterns must be non empty strings")
    if "\0" in pattern or "\\" in pattern:
        raise ConfigError(f"{where}: invalid characters in pattern {pattern!r}")
    if is_unsafe_relative(pattern):
        raise ConfigError(f"{where}: pattern must be relative and inside the repository: {pattern}")
    return pattern


def pattern_covered(pattern: str, parents: list[str]) -> bool:
    """True when every path matched by `pattern` is also matched by one of `parents`."""
    for parent in parents:
        if parent == pattern or parent == "**":
            return True
        if parent.endswith("/**") and pattern.startswith(parent[:-2]):
            return True
    return False


def _path_allowed(path: str, patterns: list[str]) -> bool:
    from devtrellis_pulse.policy.paths import glob_to_regex

    return any(glob_to_regex(p).match(path) for p in patterns)


# ---- merging and type checks ------------------------------------------------------------


def _check_type(path: str, default: Any, value: Any) -> None:
    if default is None:
        ok = value is None or isinstance(value, str)
        expected = "string or null"
    elif isinstance(default, bool):
        ok, expected = isinstance(value, bool), "bool"
    elif isinstance(default, int):
        ok, expected = isinstance(value, int) and not isinstance(value, bool), "integer"
    elif isinstance(default, str):
        ok, expected = isinstance(value, str), "string"
    elif isinstance(default, list):
        ok, expected = isinstance(value, list), "list"
    else:
        ok, expected = True, ""
    if not ok:
        raise ConfigError(f"{path}: expected {expected}, got {type(value).__name__}")


def _merge(
    defaults: dict[str, Any], user: dict[str, Any], prefix: str, warnings: list[str]
) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in user.items():
        where = f"{prefix}{key}"
        if key not in defaults:
            if prefix == "tasks.":
                raise ConfigError(f"{where}: unknown task id (known: {', '.join(defaults)})")
            warnings.append(f"unknown configuration key ignored: {where}")
            continue
        default = defaults[key]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{where}: expected a mapping")
            merged[key] = _merge(default, value, where + ".", warnings)
        else:
            _check_type(where, default, value)
            merged[key] = value
    return merged


def _validate_commands(where: str, commands: Any) -> None:
    if not isinstance(commands, list):
        raise ConfigError(f"{where}: expected a list of argument lists")
    for command in commands:
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ConfigError(
                f"{where}: each command must be a non empty list of strings "
                "(shell strings are not supported)"
            )


def _validate_timezone(where: str, name: str) -> None:
    try:
        get_zone(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ConfigError(f"{where}: {name!r} is not a valid IANA timezone") from None


def validate(data: Any) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a mapping")
    if "version" not in data:
        raise ConfigError("version: required")
    warnings: list[str] = []
    cfg = _merge(DEFAULTS, data, "", warnings)
    if cfg["version"] != SCHEMA_VERSION:
        raise ConfigError(f"version: only version {SCHEMA_VERSION} is supported")

    for (section, key), (low, high) in _RANGES.items():
        value = cfg[section][key]
        if not low <= value <= high:
            raise ConfigError(f"{section}.{key}: must be between {low} and {high}")
    for (section, key), allowed in _ENUMS.items():
        if cfg[section][key] not in allowed:
            raise ConfigError(f"{section}.{key}: must be one of {list(allowed)}")

    if not cfg["repository"]["require_git"]:
        raise ConfigError("repository.require_git: false is not supported in this release")
    for name in (cfg["project"]["name"],):
        if not name.strip():
            raise ConfigError("project.name: must not be empty")

    days = cfg["schedule"]["weekdays"]
    bad_days = [d for d in days if d not in _WEEKDAYS]
    if bad_days:
        raise ConfigError(f"schedule.weekdays: unrecognized values {bad_days}")
    if len(set(days)) != len(days):
        raise ConfigError("schedule.weekdays: values must be unique")
    if cfg["schedule"]["enabled"] and not days:
        raise ConfigError("schedule.weekdays: required when schedule.enabled is true")
    if cfg["schedule"]["enabled"] and not 3 <= len(days) <= 5:
        warnings.append("schedule.weekdays: three to five days per week is the recommended profile")
    _validate_timezone("project.timezone", cfg["project"]["timezone"])
    _validate_timezone("schedule.timezone", cfg["schedule"]["timezone"])

    formats = cfg["reports"]["format"]
    if not formats or any(f not in _FORMATS for f in formats):
        raise ConfigError(f"reports.format: must be a non empty list drawn from {list(_FORMATS)}")
    for pattern in cfg["reports"]["redact_patterns"]:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"reports.redact_patterns: invalid regular expression: {exc}") from None

    for name in ("tests", "code_hygiene"):
        task = cfg["tasks"][name]
        _validate_commands(f"tasks.{name}.commands", task["commands"])
        if not 1 <= task["timeout_seconds"] <= 3600:
            raise ConfigError(f"tasks.{name}.timeout_seconds: must be between 1 and 3600")
    hygiene = cfg["tasks"]["code_hygiene"]
    _validate_commands("tasks.code_hygiene.write_commands", hygiene["write_commands"])
    for task_name in ("documentation", "code_hygiene"):
        if cfg["tasks"][task_name]["mode"] not in ("check", "write"):
            raise ConfigError(f"tasks.{task_name}.mode: must be 'check' or 'write'")

    policy = cfg["policy"]
    for key in ("allowed_read_paths", "allowed_write_paths", "denied_paths"):
        policy[key] = [validate_glob(p, f"policy.{key}") for p in policy[key]]
    commit = cfg["commit"]
    commit["allow_paths"] = [validate_glob(p, "commit.allow_paths") for p in commit["allow_paths"]]
    for pattern in commit["allow_paths"]:
        if not pattern_covered(pattern, policy["allowed_write_paths"]):
            raise ConfigError(
                f"commit.allow_paths: {pattern!r} is not covered by policy.allowed_write_paths"
            )
    hygiene["paths"] = [validate_glob(p, "tasks.code_hygiene.paths") for p in hygiene["paths"]]

    out_dir = cfg["reports"]["output_directory"]
    if is_unsafe_relative(out_dir):
        raise ConfigError("reports.output_directory: must be a relative path inside the repository")

    safe = cfg["runtime"]["mode"] == "safe"
    writes: list[str] = []
    if cfg["tasks"]["documentation"]["mode"] == "write":
        writes.append("tasks.documentation.mode: write")
    if hygiene["mode"] == "write":
        writes.append("tasks.code_hygiene.mode: write")
    if cfg["reports"]["write_to_repository"]:
        writes.append("reports.write_to_repository: true")
    if cfg["tasks"]["repository_health"]["write_snapshot"]:
        writes.append("tasks.repository_health.write_snapshot: true")
    if commit["enabled"]:
        writes.append("commit.enabled: true")
    if safe and writes:
        raise ConfigError(f"{writes[0]} requires runtime.mode: standard")

    if cfg["tasks"]["documentation"]["mode"] == "write":
        ref = cfg["tasks"]["documentation"]["generated_cli_reference"]
        if not ref:
            raise ConfigError("tasks.documentation.generated_cli_reference: required in write mode")
        if not _path_allowed(ref, policy["allowed_write_paths"]):
            raise ConfigError(f"tasks.documentation: {ref!r} is not in policy.allowed_write_paths")
    if hygiene["mode"] == "write":
        if not hygiene["write_commands"] or not hygiene["paths"]:
            raise ConfigError("tasks.code_hygiene: write mode needs write_commands and paths")
        for pattern in hygiene["paths"]:
            if not pattern_covered(pattern, policy["allowed_write_paths"]):
                raise ConfigError(
                    f"tasks.code_hygiene.paths: {pattern!r} is not in policy.allowed_write_paths"
                )
    if cfg["reports"]["write_to_repository"] and not _path_allowed(
        out_dir.strip("/") + "/probe.md", policy["allowed_write_paths"]
    ):
        raise ConfigError("reports.output_directory: not covered by policy.allowed_write_paths")
    if cfg["tasks"]["repository_health"]["write_snapshot"] and not _path_allowed(
        out_dir.strip("/") + "/health.md", policy["allowed_write_paths"]
    ):
        raise ConfigError("tasks.repository_health.write_snapshot: output not in allowed_write_paths")

    if commit["push"]:
        if not commit["enabled"]:
            raise ConfigError("commit.push: requires commit.enabled")
        if not commit["remote"] or not commit["branch"]:
            raise ConfigError("commit.push: requires commit.remote and commit.branch")
        if not policy["allow_network"]:
            raise ConfigError("commit.push: requires policy.allow_network")
    if commit["enabled"] and not (commit["author_name"].strip() and commit["author_email"].strip()):
        raise ConfigError("commit.author_name and commit.author_email: must not be empty")

    return Config(cfg, warnings)


def apply_environment(raw: dict[str, Any], environ: Mapping[str, str]) -> list[str]:
    """Apply documented environment overrides to a raw config mapping. Returns names applied."""
    applied: list[str] = []
    for variable, (section, key, kind) in ENV_OVERRIDES.items():
        text = environ.get(variable)
        if text is None or text == "":
            continue
        try:
            value: Any = kind(text)
        except ValueError:
            raise ConfigError(f"{variable}: expected {kind.__name__}, got {text!r}") from None
        raw.setdefault(section, {})
        if not isinstance(raw[section], dict):
            raise ConfigError(f"{section}: expected a mapping")
        raw[section][key] = value
        applied.append(variable)
    return applied


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read configuration {path}: {exc}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from None
    if data is None:
        raise ConfigError(f"{path}: configuration is empty (version is required)")
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a mapping")
    applied = apply_environment(data, env)
    cfg = validate(data)
    cfg.source = str(path)
    cfg.env_applied = applied
    return cfg


def resolve_repo_path(cfg: Config, config_path: Path | None, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    base = Path(config_path).resolve().parent if config_path else Path.cwd()
    return (base / cfg["repository"]["path"]).expanduser().resolve()


def starter_yaml() -> str:
    """The starter configuration. pulse.example.yml is generated from this, so they cannot drift."""
    lines = [
        "# DevTrellis Pulse configuration.",
        "# Safe defaults: read only mode, no commits, no push, no network, no deletion.",
        "# Run `pulse validate-config` after editing.",
        "",
    ]
    for key, value in DEFAULTS.items():
        lines.append(f"# {SECTION_COMMENTS[key]}")
        lines.append(
            yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False, width=100).rstrip()
        )
        lines.append("")
    return "\n".join(lines)
