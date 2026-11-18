"""Commit manager. Commits only verified files that Pulse itself produced.

Rules enforced here (specification 6.5 and Appendix M):
* never runs unless commit.enabled is true and runtime.mode is standard
* only files produced by this run, listed explicitly, inside commit.allow_paths, never denied
* never touches paths that already had uncommitted changes before the run
* no empty commits; unchanged content produces no commit
* staged content is scanned for secrets; file types, sizes and change volume are limited
* `git commit --only <paths>` so unrelated staged user changes are never included
* no `git add -A`, no reset --hard, no amend, no custom dates, no force push
* on failure nothing is discarded: the working tree is preserved for inspection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from devtrellis_pulse.commits.grouping import group_changes
from devtrellis_pulse.commits.messages import build_message
from devtrellis_pulse.core.errors import GitError
from devtrellis_pulse.core.models import (
    BAD_TASK_STATUSES,
    CommitRecord,
    RepoSnapshot,
    TaskResult,
    ValidationResult,
)
from devtrellis_pulse.policy.commit_policy import (
    commit_scope_problems,
    overlap_with_user_changes,
    push_blockers,
)
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.repository.diff import staged_names
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.validation.diff_validator import validate_changes
from devtrellis_pulse.validation.engine import validate_staged

REPORT_TASK = "activity_report"
INSPECT_HINT = (
    "Inspect with `git status` and `git diff --cached`. Pulse did not reset, discard or "
    "rewrite anything."
)


@dataclass
class CommitPhase:
    status: str = "no_changes"  # no_changes | skipped | blocked | committed | failed
    records: list[CommitRecord] = field(default_factory=list)
    validation: ValidationResult = field(default_factory=ValidationResult)
    warnings: list[str] = field(default_factory=list)
    operator_actions: list[str] = field(default_factory=list)
    push_failed: bool = False


def _push(
    git: GitCli, cfg: dict[str, Any], snap: RepoSnapshot, phase: CommitPhase
) -> None:
    commit = cfg["commit"]
    committed = [r for r in phase.records if r.status == "committed"]
    if not committed or not commit["push"]:
        return
    blockers = push_blockers(cfg, snap.branch)
    if blockers:
        reason = "push skipped: " + "; ".join(blockers)
        for record in committed:
            record.push_reason = reason
        phase.warnings.append(reason)
        return
    try:
        git.push(commit["remote"], commit["branch"])
    except GitError as exc:
        phase.push_failed = True
        for record in committed:
            record.push_reason = f"push failed: {exc}"
        phase.operator_actions.append(
            f"Push failed ({exc}). The local commit is preserved and was not published. "
            f"Fix the cause, then run `git push {commit['remote']} {commit['branch']}` yourself."
        )
        return
    for record in committed:
        record.pushed = True


def run_commit_phase(
    git: GitCli,
    cfg: dict[str, Any],
    policy: PolicyEngine,
    snap: RepoSnapshot,
    results: list[TaskResult],
    fingerprint: str,
    last_fingerprint: str | None,
    run_id: str,
) -> CommitPhase:
    settings = cfg["commit"]
    phase = CommitPhase()

    if any(r.attempt >= 1 and r.status in BAD_TASK_STATUSES for r in results):
        phase.status = "skipped"
        phase.records.append(CommitRecord("skipped", reason="the run had failing or blocked tasks"))
        return phase

    groups = group_changes(results, settings["group_by"])
    if not groups:
        return phase  # no_changes

    # The activity report carries run data, so it is committed only when results changed.
    kept = []
    for group in groups:
        if group.task_ids == [REPORT_TASK] and fingerprint == last_fingerprint:
            phase.records.append(
                CommitRecord(
                    "skipped",
                    group.task_ids,
                    group.paths,
                    reason="results match the last committed run, nothing new to record",
                )
            )
            continue
        kept.append(group)
    if not kept:
        phase.status = "skipped"
        return phase

    paths = sorted({p for g in kept for p in g.paths})
    overlap = overlap_with_user_changes(paths, snap)
    if overlap:
        phase.status = "skipped"
        phase.records.append(
            CommitRecord("skipped", reason=f"paths had uncommitted changes before the run: {overlap}")
        )
        return phase

    if settings["require_validation"]:
        phase.validation = validate_changes(git.root, paths, cfg, policy.paths)
    else:
        problems = commit_scope_problems(paths, cfg, policy.paths)
        phase.validation = ValidationResult(ok=not problems, messages=problems)
    if not phase.validation.ok:
        phase.status = "blocked"
        phase.operator_actions.append(
            "Validation blocked the commit. Review the listed files; nothing was staged or committed."
        )
        return phase

    for group in kept:
        try:
            git.stage(group.paths)
            staged = staged_names(git, group.paths)
            if not staged:
                phase.records.append(
                    CommitRecord("skipped", group.task_ids, group.paths, reason="no content changes")
                )
                continue
            if settings["require_validation"]:
                scan = validate_staged(git, staged)
                if not scan.ok:
                    git.unstage(group.paths)
                    phase.validation.ok = False
                    phase.validation.messages.extend(scan.messages)
                    phase.status = "blocked"
                    phase.operator_actions.append(
                        "A possible secret was found in staged content, so the commit was blocked "
                        "and the files were unstaged. Remove the secret and rotate it if it was real."
                    )
                    return phase
            subject, body = build_message(settings["message_prefix"], group, results, run_id)
            sha = git.commit(staged, subject, body, settings["author_name"], settings["author_email"])
            phase.records.append(CommitRecord("committed", group.task_ids, staged, subject, sha))
        except GitError as exc:
            git.unstage(group.paths)
            phase.records.append(
                CommitRecord("failed", group.task_ids, group.paths, reason=str(exc))
            )
            phase.status = "failed"
            phase.operator_actions.append(f"Commit failed ({exc}). {INSPECT_HINT}")
            return phase

    committed = [r for r in phase.records if r.status == "committed"]
    phase.status = "committed" if committed else "skipped" if phase.records else "no_changes"
    _push(git, cfg, snap, phase)
    return phase
