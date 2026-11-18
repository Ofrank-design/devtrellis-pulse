"""Run orchestration, including the extra rules that apply to scheduler invocations."""

from __future__ import annotations

from devtrellis_pulse.app.services import Environment
from devtrellis_pulse.core.clock import iso_utc
from devtrellis_pulse.core.ids import new_run_id
from devtrellis_pulse.core.models import SKIPPED, RunResult
from devtrellis_pulse.execution.cancellation import CancellationToken
from devtrellis_pulse.execution.engine import RunEngine
from devtrellis_pulse.ledger.reader import recent_runs
from devtrellis_pulse.scheduling.schedule import already_ran_today, is_scheduled_day


def scheduled_skip_reason(env: Environment) -> str | None:
    """Why a scheduler invocation should do nothing. No catch up runs, repeats are harmless."""
    cfg = env.cfg
    if not cfg["schedule"]["enabled"]:
        return "schedule.enabled is false"
    if not is_scheduled_day(cfg):
        return "today is not one of the configured schedule.weekdays"
    if already_ran_today(recent_runs(env.ledger_path, env.fingerprint, 5), cfg):
        return "a run already finished today; repeated invocations are skipped"
    return None


def skipped_run(reason: str) -> RunResult:
    now = iso_utc()
    run = RunResult(new_run_id(), now, now, False, SKIPPED)
    run.warnings.append(f"scheduled invocation skipped: {reason}")
    return run


def run(
    env: Environment,
    *,
    dry_run: bool,
    only: list[str] | None = None,
    scheduled: bool = False,
    cancel: CancellationToken | None = None,
) -> RunResult:
    if scheduled:
        reason = scheduled_skip_reason(env)
        if reason:
            return skipped_run(reason)
    engine = RunEngine(env.cfg, env.repo, env.state_dir, env.ledger_path, cancel)
    return engine.execute(dry_run=dry_run, only=only)
