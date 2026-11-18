from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# User facing status vocabulary (specification 17.2).
PLANNED = "planned"
RUNNING = "running"
PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
BLOCKED = "blocked"
TIMED_OUT = "timed_out"
CANCELLED = "cancelled"
NO_CHANGES = "no_changes"
PARTIAL_SUCCESS = "partial_success"

BAD_TASK_STATUSES = {FAILED, TIMED_OUT, BLOCKED}


@dataclass
class Finding:
    severity: str  # "error" | "warning" | "info"
    message: str
    path: str | None = None


@dataclass
class TaskResult:
    task_id: str
    name: str
    status: str
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    # metrics are stable facts and take part in the change fingerprint.
    metrics: dict[str, Any] = field(default_factory=dict)
    # details are informational and never affect the fingerprint.
    details: dict[str, Any] = field(default_factory=dict)
    changed_paths: list[str] = field(default_factory=list)
    attempt: int = 1
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    error_code: str | None = None


@dataclass
class ValidationResult:
    ok: bool = True
    messages: list[str] = field(default_factory=list)


@dataclass
class PlannedTask:
    task_id: str
    name: str
    status: str  # planned | skipped | blocked
    reason: str
    read_paths: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=list)
    subprocess: bool = False
    operations: int = 1
    estimated_seconds: float | None = None

    @property
    def will_run(self) -> bool:
        return self.status == PLANNED


@dataclass
class StatusEntry:
    path: str
    index: str
    worktree: str
    orig_path: str | None = None

    @property
    def untracked(self) -> bool:
        return self.index == "?" and self.worktree == "?"

    @property
    def staged(self) -> bool:
        return self.index not in (" ", "?", "!")


@dataclass
class RepoSnapshot:
    root: str
    branch: str | None
    head: str | None
    remote: str | None
    entries: list[StatusEntry] = field(default_factory=list)
    operation: str | None = None  # merge | rebase | cherry-pick | revert
    shallow: bool = False
    sparse: bool = False
    submodules: list[str] = field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return bool(self.entries)

    @property
    def dirty_paths(self) -> set[str]:
        paths: set[str] = set()
        for entry in self.entries:
            paths.add(entry.path)
            if entry.orig_path:
                paths.add(entry.orig_path)
        return paths

    @property
    def staged_paths(self) -> set[str]:
        return {e.path for e in self.entries if e.staged}

    @property
    def detached(self) -> bool:
        return self.branch is None


@dataclass
class CommitRecord:
    status: str  # committed | failed | skipped
    task_ids: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    subject: str = ""
    sha: str | None = None
    reason: str = ""
    pushed: bool = False
    push_reason: str = ""


@dataclass
class RunResult:
    run_id: str
    started_at: str
    finished_at: str
    dry_run: bool
    status: str
    repo: dict[str, Any] = field(default_factory=dict)
    config_fingerprint: str = ""
    plan: list[PlannedTask] = field(default_factory=list)
    tasks: list[TaskResult] = field(default_factory=list)
    commits: list[CommitRecord] = field(default_factory=list)
    commit_status: str = "disabled"  # disabled | no_changes | skipped | committed | failed
    validation: ValidationResult = field(default_factory=ValidationResult)
    reports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    operator_actions: list[str] = field(default_factory=list)
    fingerprint: str = ""
    operations_used: int = 0
    runtime_seconds: float = 0.0
    exit_code: int = 0
    exit_reasons: list[str] = field(default_factory=list)
    diff_stat: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
