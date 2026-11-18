"""The run engine: plan, execute, validate, commit, record.

A run never invents work. Tasks that have nothing to do finish as no_changes, a run with no
eligible tasks finishes as no_changes, and a run that changes nothing commits nothing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from pathlib import Path
from typing import Any

from devtrellis_pulse import __version__
from devtrellis_pulse.commits.manager import CommitPhase, run_commit_phase
from devtrellis_pulse.core import errors as E
from devtrellis_pulse.core.clock import iso_utc
from devtrellis_pulse.core.config import Config
from devtrellis_pulse.core.ids import new_run_id
from devtrellis_pulse.core.logging import get_logger
from devtrellis_pulse.core.models import (
    BAD_TASK_STATUSES,
    BLOCKED,
    CANCELLED,
    FAILED,
    NO_CHANGES,
    PARTIAL_SUCCESS,
    PASSED,
    PLANNED,
    SKIPPED,
    TIMED_OUT,
    Finding,
    RunResult,
    TaskResult,
)
from devtrellis_pulse.discovery.planner import build_plan
from devtrellis_pulse.execution.cancellation import (
    CancellationToken,
    install_signal_handlers,
    restore_signal_handlers,
)
from devtrellis_pulse.execution.context import TaskContext
from devtrellis_pulse.execution.limits import Budget, ChangeTracker
from devtrellis_pulse.ledger import schema as S
from devtrellis_pulse.ledger.reader import (
    last_committed_fingerprint,
    median_task_durations,
    unfinished_run_ids,
)
from devtrellis_pulse.ledger.writer import LedgerWriter
from devtrellis_pulse.platform.files import atomic_write_text, canonical_json
from devtrellis_pulse.platform.paths import (
    ensure_private_dir,
    repo_fingerprint,
    short_fingerprint,
)
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.reports.json_report import to_json
from devtrellis_pulse.reports.markdown import to_markdown
from devtrellis_pulse.repository.diff import change_summary
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.scheduling.lock import RunLock
from devtrellis_pulse.tasks import REGISTRY, PlanContext

REPORT_TASK = "activity_report"


def fingerprint_of(tasks: list[TaskResult]) -> str:
    """Hash of what the run found, ignoring timing. Equal fingerprints mean nothing new."""
    payload = [
        {
            "id": t.task_id,
            "status": t.status,
            "metrics": t.metrics,
            "findings": sorted((f.severity, f.message, f.path or "") for f in t.findings),
        }
        for t in tasks
        if t.task_id != REPORT_TASK
    ]
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def run_status(tasks: list[TaskResult]) -> str:
    executed = [t for t in tasks if t.attempt >= 1]
    if not executed:
        return BLOCKED if any(t.status == BLOCKED for t in tasks) else NO_CHANGES
    bad = [t for t in executed if t.status in BAD_TASK_STATUSES]
    if not bad:
        return PASSED if any(t.status == PASSED for t in executed) else NO_CHANGES
    return FAILED if len(bad) == len(executed) else PARTIAL_SUCCESS


def compute_exit(run: RunResult, persistence_failed: bool, push_failed: bool) -> None:
    """Fill run.exit_code and run.exit_reasons. Precedence is documented in docs/reference."""
    reasons: list[str] = []
    codes: list[int] = []

    def add(reason: str, code: int) -> None:
        reasons.append(reason)
        codes.append(code)

    if run.status == CANCELLED:
        add("cancelled", E.EXIT_INTERRUPTED)
    if persistence_failed:
        add("persistence_failed", E.EXIT_PERSISTENCE)
    if run.commit_status == "failed" or push_failed:
        add("commit_failed" if run.commit_status == "failed" else "push_failed", E.EXIT_COMMIT)
    if not run.validation.ok:
        add("validation_failed", E.EXIT_VALIDATION)
    executed = [t for t in run.tasks if t.attempt >= 1]
    if any(t.error_code == "budget_exceeded" for t in executed):
        add("budget_exceeded", E.EXIT_BUDGET)
    if any(t.status in BAD_TASK_STATUSES for t in executed):
        add("tasks_failed", E.EXIT_TASKS_FAILED)
    run.exit_reasons = reasons
    run.exit_code = codes[0] if codes else E.EXIT_OK


class RunEngine:
    def __init__(
        self,
        cfg: Config,
        repo: Path,
        state_dir: Path,
        ledger_path: Path,
        cancel: CancellationToken | None = None,
    ) -> None:
        self.cfg = cfg
        self.repo = Path(repo)
        self.state_dir = Path(state_dir)
        self.ledger_path = Path(ledger_path)
        self.cancel = cancel or CancellationToken()
        self.log = get_logger()

    # ---- helpers ----------------------------------------------------------------------

    def _repo_info(self, snap, fp: str) -> dict[str, Any]:
        paths = sorted(snap.dirty_paths)
        return {
            "name": self.cfg["project"]["name"],
            "root_fingerprint": fp,
            "branch": snap.branch,
            "head": snap.head,
            "remote": snap.remote,
            "operation": snap.operation,
            "shallow": snap.shallow,
            "sparse": snap.sparse,
            "submodules": len(snap.submodules),
            "dirty_count": len(paths),
            "dirty_paths": paths[:25],
        }

    def _plan_only(self, run: RunResult, plan_blocked: str | None) -> RunResult:
        run.finished_at = iso_utc()
        if plan_blocked:
            run.status = BLOCKED
            run.warnings.append(f"a real run would be blocked: {plan_blocked}")
            run.exit_code = E.EXIT_POLICY
            run.exit_reasons = ["policy_blocked"]
        return run

    def _skipped(self, item, status: str, reason: str) -> TaskResult:
        now = iso_utc()
        return TaskResult(
            item.task_id, item.name, status, reason, attempt=0, started_at=now, finished_at=now
        )

    def _task_event(self, writer: LedgerWriter, run_id: str, result: TaskResult) -> None:
        writer.append(
            S.make_event(
                S.TASK_FINISHED,
                run_id,
                task_id=result.task_id,
                attempt=result.attempt,
                status=result.status,
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_ms=result.duration_ms,
                changed_paths=result.changed_paths,
                summary=result.summary,
                error_code=result.error_code,
            )
        )

    # ---- one task ---------------------------------------------------------------------

    def _run_attempt(self, task, ctx: TaskContext, snap, attempt: int) -> TaskResult:
        started = time.monotonic()
        started_at = iso_utc()
        try:
            ctx.budget.spend(1)
            result = task.execute(ctx, task.plan(PlanContext(self.cfg, snap)))
            check = task.validate(ctx, result)
            if not check.ok:
                result.status = FAILED
                result.error_code = "validation_failed"
                result.findings.extend(Finding("error", m) for m in check.messages)
        except E.TaskTimeout as exc:
            cancelled = self.cancel.is_set()
            result = TaskResult(
                task.task_id, task.name, CANCELLED if cancelled else TIMED_OUT, str(exc),
                findings=[Finding("error", str(exc))], error_code=exc.error_code,
            )
        except E.PulseError as exc:
            result = TaskResult(
                task.task_id, task.name, FAILED, str(exc),
                findings=[Finding("error", str(exc))], error_code=exc.error_code,
            )
        except Exception as exc:  # a task bug becomes a failure record, never a crash
            from devtrellis_pulse.validation.secret_scan import redact

            message = redact(f"unexpected {type(exc).__name__}: {exc}")
            result = TaskResult(
                task.task_id, task.name, FAILED, message,
                findings=[Finding("error", message)], error_code="unexpected_error",
            )
        if not result.changed_paths:
            result.changed_paths = list(ctx.changed_paths)
        result.attempt = attempt
        result.started_at = started_at
        result.finished_at = iso_utc()
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    # ---- the run ----------------------------------------------------------------------

    def execute(self, *, dry_run: bool, only: list[str] | None = None) -> RunResult:
        cfg = self.cfg
        git = GitCli(self.repo)
        snap = git.snapshot()
        root = Path(snap.root)
        git = GitCli(root)
        policy = PolicyEngine(cfg, root)
        fp = repo_fingerprint(root)
        estimates = median_task_durations(self.ledger_path, fp)
        plan = build_plan(cfg, policy, only, estimates)
        will_write = bool(cfg["commit"]["enabled"]) or any(
            p.status == PLANNED and p.write_paths for p in plan
        )
        run = RunResult(
            run_id=new_run_id(),
            started_at=iso_utc(),
            finished_at="",
            dry_run=dry_run,
            status="planned" if dry_run else PASSED,
            repo=self._repo_info(snap, fp),
            config_fingerprint=cfg.fingerprint,
            plan=plan,
        )
        run.warnings.extend(cfg.warnings)
        try:
            run.warnings.extend(policy.check_preconditions(snap, will_write))
        except E.PolicyError as exc:
            if dry_run:
                return self._plan_only(run, str(exc))
            raise
        if dry_run:
            return self._plan_only(run, None)
        return self._execute_real(run, git, policy, snap, fp)

    def _execute_real(self, run, git, policy, snap, fp) -> RunResult:
        cfg = self.cfg
        t0 = time.monotonic()
        ensure_private_dir(self.state_dir)
        lock = RunLock(
            self.state_dir / "locks" / f"{short_fingerprint(fp)}.lock",
            cfg["runtime"]["lock_wait_seconds"],
        )
        writer = LedgerWriter(
            self.ledger_path, cfg["ledger"]["max_file_megabytes"], cfg["reports"]["redact_patterns"]
        )
        previous = install_signal_handlers(self.cancel)
        persistence_failed = False
        push_failed = False
        try:
            with lock:
                writer.append(
                    S.make_event(
                        S.RUN_STARTED,
                        run.run_id,
                        repository={
                            "root_fingerprint": fp,
                            "branch": snap.branch,
                            "head": snap.head,
                        },
                        pulse_version=__version__,
                        config_fingerprint=cfg.fingerprint,
                        config_snapshot=dict(cfg),
                    )
                )
                orphans = [r for r in unfinished_run_ids(self.ledger_path, fp) if r != run.run_id]
                if orphans:
                    run.warnings.append(
                        f"earlier run(s) never finished and were not assumed successful: {', '.join(orphans)}"
                    )
                runtime = cfg["runtime"]
                budget = Budget(runtime["max_operations_per_run"], runtime["max_runtime_seconds"])
                limits = cfg["limits"]
                changes = ChangeTracker(
                    limits["max_changed_files_per_run"], limits["max_changed_bytes_per_run"]
                )

                def provisional() -> dict[str, Any]:
                    view = dataclasses.replace(
                        run,
                        tasks=list(run.tasks),
                        finished_at=iso_utc(),
                        status=run_status(run.tasks),
                        commit_status="pending",
                        operations_used=budget.used,
                        runtime_seconds=round(time.monotonic() - t0, 2),
                    )
                    return view.to_dict()

                stop_reason: str | None = None
                for item in run.plan:
                    if not item.will_run:
                        result = self._skipped(item, item.status, item.reason)
                    elif item.task_id != REPORT_TASK and stop_reason:
                        result = self._skipped(item, CANCELLED if self.cancel.is_set() else SKIPPED, stop_reason)
                    elif self.cancel.is_set():
                        result = self._skipped(item, CANCELLED, f"cancelled ({self.cancel.reason})")
                    else:
                        result = self._run_planned(item, writer, run, git, policy, budget, changes, snap, provisional)
                        if result.status in BAD_TASK_STATUSES and runtime["fail_fast"]:
                            stop_reason = "fail_fast"
                            run.warnings.append(f"stopped early after {item.task_id} failed (fail_fast)")
                    run.tasks.append(result)
                    if not item.will_run:
                        self._task_event(writer, run.run_id, result)

                run.operations_used = budget.used
                run.fingerprint = fingerprint_of(run.tasks)
                run.status = run_status(run.tasks)

                phase = CommitPhase(status="disabled")
                if cfg["commit"]["enabled"] and not self.cancel.is_set():
                    phase = run_commit_phase(
                        git, cfg, policy, snap, run.tasks, run.fingerprint,
                        last_committed_fingerprint(self.ledger_path, fp), run.run_id,
                    )
                    run.commits = phase.records
                    run.validation = phase.validation
                    run.warnings.extend(phase.warnings)
                    run.operator_actions.extend(phase.operator_actions)
                    push_failed = phase.push_failed
                    self._commit_events(writer, run.run_id, phase)
                    if phase.status in ("failed", "blocked") or push_failed:
                        if run.status in (PASSED, NO_CHANGES):
                            run.status = PARTIAL_SUCCESS
                run.commit_status = phase.status

                if self.cancel.is_set():
                    run.status = CANCELLED
                if cfg["reports"]["include_diff_stat"]:
                    changed = sorted({p for t in run.tasks for p in t.changed_paths})
                    run.diff_stat = change_summary(git, changed)
                run.runtime_seconds = round(time.monotonic() - t0, 2)
                run.finished_at = iso_utc()
                self._add_operator_actions(run)

                try:
                    run.reports.extend(self._write_state_reports(run, fp))
                except OSError as exc:
                    persistence_failed = True
                    run.warnings.append(f"could not write report files: {exc}")
                compute_exit(run, persistence_failed, push_failed)
                writer.append(
                    S.make_event(
                        S.RUN_FINISHED,
                        run.run_id,
                        repository={"root_fingerprint": fp, "branch": snap.branch, "head": snap.head},
                        status=run.status,
                        exit_code=run.exit_code,
                        run=run.to_dict(),
                    )
                )
        finally:
            restore_signal_handlers(previous)
        return run

    def _run_planned(self, item, writer, run, git, policy, budget, changes, snap, provisional) -> TaskResult:
        task = REGISTRY[item.task_id]
        retries = self.cfg["limits"]["max_retries_per_task"] if task.retry_safe else 0
        result: TaskResult | None = None
        for attempt in range(1, retries + 2):
            ctx = TaskContext(
                repo=git.root,
                config=self.cfg,
                task=task,
                task_config=self.cfg["tasks"].get(task.task_id, {}),
                git=git,
                policy=policy,
                budget=budget,
                changes=changes,
                cancel=self.cancel,
                run_id=run.run_id,
                run_snapshot=provisional,
            )
            writer.append(S.make_event(S.TASK_STARTED, run.run_id, task_id=task.task_id, attempt=attempt))
            result = self._run_attempt(task, ctx, snap, attempt)
            self._task_event(writer, run.run_id, result)
            self.log.debug(
                result.summary,
                extra={"run_id": run.run_id, "task_id": task.task_id, "duration_ms": result.duration_ms},
            )
            if result.status not in BAD_TASK_STATUSES or self.cancel.is_set():
                break
        assert result is not None
        return result

    def _commit_events(self, writer: LedgerWriter, run_id: str, phase: CommitPhase) -> None:
        if phase.validation.messages:
            writer.append(
                S.make_event(
                    S.VALIDATION_FINISHED, run_id, ok=phase.validation.ok, messages=phase.validation.messages
                )
            )
        for record in phase.records:
            if record.status == "committed":
                writer.append(
                    S.make_event(
                        S.COMMIT_CREATED, run_id, commit=record.sha, subject=record.subject,
                        task_ids=record.task_ids, changed_paths=record.files,
                        pushed=record.pushed, push_reason=record.push_reason,
                    )
                )
            elif record.status == "failed":
                writer.append(
                    S.make_event(S.COMMIT_FAILED, run_id, task_ids=record.task_ids, reason=record.reason)
                )

    def _add_operator_actions(self, run: RunResult) -> None:
        for task in run.tasks:
            if task.attempt >= 1 and task.status in BAD_TASK_STATUSES:
                run.operator_actions.append(f"Review the {task.task_id} findings and rerun after fixing them.")
        if not run.operator_actions and run.status in (PASSED, NO_CHANGES):
            run.operator_actions.append("No action needed.")

    def _write_state_reports(self, run: RunResult, fp: str) -> list[str]:
        out = self.state_dir / "reports" / short_fingerprint(fp)
        patterns = self.cfg["reports"]["redact_patterns"]
        data = run.to_dict()
        written = []
        for fmt in self.cfg["reports"]["format"]:
            if fmt == "markdown":
                path, text = out / f"{run.run_id}.md", to_markdown(data, patterns)
            else:
                path, text = out / f"{run.run_id}.json", to_json(data, patterns)
            atomic_write_text(path, text)
            written.append(str(path))
        for task in run.tasks:
            if task.task_id == REPORT_TASK:
                written.extend(task.changed_paths)
        return written
