"""Find a recorded run and render it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devtrellis_pulse.app.services import Environment
from devtrellis_pulse.core.errors import PersistenceError, PolicyError, UsageError
from devtrellis_pulse.ledger.reader import find_run, recent_runs
from devtrellis_pulse.platform.files import atomic_write_text
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.reports.json_report import to_json
from devtrellis_pulse.reports.markdown import to_markdown


def load_run(env: Environment, run_id: str | None) -> dict[str, Any]:
    if run_id:
        record = find_run(env.ledger_path, run_id, env.fingerprint)
        if record is None:
            raise UsageError(f"no recorded run with id {run_id}")
        return record["run"]
    runs = recent_runs(env.ledger_path, env.fingerprint, 1)
    if not runs:
        raise UsageError("no recorded runs yet")
    return runs[-1]["run"]


def render(env: Environment, run: dict[str, Any], fmt: str) -> str:
    patterns = env.cfg["reports"]["redact_patterns"]
    return to_json(run, patterns) if fmt == "json" else to_markdown(run, patterns)


def write_output(env: Environment, text: str, output: str) -> Path:
    """Write a report where the operator asked. Inside the repository, policy must allow it."""
    target = Path(output).expanduser().resolve()
    root = env.repo.resolve()
    if target == root or root in target.parents:
        rel = str(target.relative_to(root))
        try:
            PolicyEngine(env.cfg, root).paths.check_write(rel)
        except PolicyError as exc:
            raise PolicyError(f"report output refused: {exc}") from None
    try:
        atomic_write_text(target, text)
    except OSError as exc:
        raise PersistenceError(f"cannot write report: {exc}") from None
    return target
