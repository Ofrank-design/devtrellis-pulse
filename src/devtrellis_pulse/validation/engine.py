"""Validation engine: combines change validation and the secret scan of staged content."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.core.models import ValidationResult
from devtrellis_pulse.policy.paths import PathPolicy
from devtrellis_pulse.repository.diff import staged_added_text
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.validation.diff_validator import validate_changes
from devtrellis_pulse.validation.secret_scan import scan_text


def validate_before_staging(
    git: GitCli, paths: list[str], cfg: dict[str, Any], policy: PathPolicy
) -> ValidationResult:
    return validate_changes(git.root, paths, cfg, policy)


def validate_staged(git: GitCli, staged: list[str]) -> ValidationResult:
    """Scan only the added lines of the staged diff. Messages carry the kind, never the value."""
    result = ValidationResult()
    hits = scan_text(staged_added_text(git, staged))
    for kind in sorted({kind for kind, _ in hits}):
        result.messages.append(f"possible secret in staged content ({kind})")
    result.ok = not result.messages
    return result
