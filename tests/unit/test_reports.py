import json

from devtrellis_pulse.reports.json_report import REPORT_SCHEMA_VERSION, to_json
from devtrellis_pulse.reports.markdown import to_markdown
from devtrellis_pulse.reports.summary import build_summary


def run_record(**overrides):
    record = {
        "run_id": "run_x",
        "started_at": "2026-11-03T10:00:00Z",
        "finished_at": "2026-11-03T10:00:05Z",
        "dry_run": False,
        "status": "partial_success",
        "repo": {"name": "demo", "branch": "main", "head": "abc123def456abc", "remote": None},
        "plan": [{"task_id": "documentation", "status": "planned", "reason": "r"}],
        "tasks": [
            {"task_id": "documentation", "status": "passed", "summary": "ok", "duration_ms": 400,
             "findings": [], "changed_paths": []},
            {"task_id": "tests", "status": "failed", "summary": "1/2 | commands", "duration_ms": 4100,
             "findings": [{"severity": "error", "message": "boom\ntrace line", "path": None}],
             "changed_paths": []},
            {"task_id": "code_hygiene", "status": "skipped", "summary": "disabled", "duration_ms": 0,
             "findings": [], "changed_paths": []},
        ],
        "commits": [],
        "commit_status": "disabled",
        "validation": {"ok": True, "messages": []},
        "warnings": ["careful"],
        "operator_actions": ["Review the tests findings and rerun after fixing them."],
        "operations_used": 3,
        "runtime_seconds": 5.0,
    }
    record.update(overrides)
    return record


def test_summary_counts_only_what_happened():
    summary = build_summary(run_record())
    assert summary["passed"] == 1 and summary["failed"] == 1 and summary["skipped"] == 1
    assert summary["files_changed"] == 0 and summary["commits_created"] == 0


def test_markdown_follows_the_documented_layout():
    text = to_markdown(run_record())
    for heading in ("# DevTrellis Pulse Run Report", "## Summary", "## Tasks", "## Changes",
                    "## Validation", "## Commit outcome", "## Warnings", "## Recommended operator action"):
        assert heading in text
    assert "Overall status: `partial_success`" in text
    assert "| tests | failed | 4.1s | 1/2 / commands |" in text
    assert text.endswith("\n")


def test_a_run_with_no_changes_says_so():
    text = to_markdown(run_record())
    assert "No files were changed by this run." in text
    assert "No commit created. Commit mode is disabled." in text


def test_dry_runs_are_clearly_plans():
    text = to_markdown(run_record(dry_run=True, status="planned", tasks=[]))
    assert "Dry run: this is a plan" in text and "## Planned work" in text
    assert "## Tasks" not in text and "Commits created" not in text


def test_no_eligible_tasks_is_reported_honestly():
    text = to_markdown(run_record(tasks=[], status="no_changes"))
    assert "No eligible tasks" in text


def test_commits_are_listed_with_their_hash():
    commit = {"status": "committed", "sha": "1234567890abcdef", "subject": "chore(pulse): x",
              "pushed": False, "task_ids": [], "files": []}
    text = to_markdown(run_record(commits=[commit], commit_status="committed"))
    assert "`1234567890ab` chore(pulse): x (not pushed)" in text


def test_reports_redact_secrets_and_configured_patterns():
    record = run_record(warnings=["token=s3cr3tval and AKIAABCDEFGHIJKLMNOP"])
    markdown = to_markdown(record, [r"token=\S+"])
    document = to_json(record, [r"token=\S+"])
    for text in (markdown, document):
        assert "s3cr3tval" not in text and "AKIA" not in text


def test_json_report_is_versioned_and_valid():
    data = json.loads(to_json(run_record()))
    assert data["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert data["summary"]["failed"] == 1 and data["run"]["run_id"] == "run_x"
