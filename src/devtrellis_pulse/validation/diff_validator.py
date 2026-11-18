"""Validate a set of changed files before commit: scope, file type, size and run level limits."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from devtrellis_pulse.core.models import ValidationResult
from devtrellis_pulse.policy.commit_policy import commit_scope_problems
from devtrellis_pulse.policy.paths import PathPolicy

PROHIBITED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")
PROHIBITED_NAMES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass")


def validate_changes(
    repo_root: Path, paths: list[str], cfg: dict[str, Any], policy: PathPolicy
) -> ValidationResult:
    result = ValidationResult()
    result.messages.extend(commit_scope_problems(paths, cfg, policy))
    limits = cfg["limits"]
    max_file = cfg["commit"]["max_file_kilobytes"] * 1024
    if len(paths) > limits["max_changed_files_per_run"]:
        result.messages.append(
            f"{len(paths)} changed files exceeds limits.max_changed_files_per_run "
            f"({limits['max_changed_files_per_run']})"
        )
    total = 0
    for rel in paths:
        name = os.path.basename(rel)
        if rel.endswith(PROHIBITED_SUFFIXES) or name.startswith(PROHIBITED_NAMES):
            result.messages.append(f"prohibited file type: {rel}")
        target = repo_root / rel
        if target.is_symlink():
            result.messages.append(f"symbolic link: {rel}")
            continue
        if target.is_file():
            size = target.stat().st_size
            total += size
            if size > max_file:
                result.messages.append(f"file exceeds commit.max_file_kilobytes: {rel}")
    if total > limits["max_changed_bytes_per_run"]:
        result.messages.append(
            f"{total} changed bytes exceeds limits.max_changed_bytes_per_run "
            f"({limits['max_changed_bytes_per_run']})"
        )
    result.ok = not result.messages
    return result
