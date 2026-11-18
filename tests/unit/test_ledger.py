import json
from datetime import timedelta

from devtrellis_pulse.core.clock import iso_utc, utc_now
from devtrellis_pulse.ledger import reader
from devtrellis_pulse.ledger import schema as S
from devtrellis_pulse.ledger.retention import apply_retention
from devtrellis_pulse.ledger.writer import LedgerWriter

REPO = "sha256:abc"


def finished(run_id, commit_status="disabled", fingerprint="f", when=None):
    return S.make_event(
        S.RUN_FINISHED,
        run_id,
        repository={"root_fingerprint": REPO},
        status="passed",
        run={"commit_status": commit_status, "fingerprint": fingerprint},
        **({"timestamp": when} if when else {}),
    )


def test_every_record_has_schema_id_and_utc_time(tmp_path):
    writer = LedgerWriter(tmp_path / "l.jsonl")
    writer.append(S.make_event(S.RUN_STARTED, "run_1", repository={"root_fingerprint": REPO}))
    writer.append(S.make_event(S.TASK_FINISHED, "run_1", task_id="documentation"))
    records = [r for _, r in reader.iter_records(tmp_path / "l.jsonl")]
    assert [r["schema_version"] for r in records] == [1, 1]
    assert len({r["event_id"] for r in records}) == 2
    assert all(r["timestamp"].endswith("Z") for r in records)


def test_corrupt_lines_are_reported_with_numbers_and_valid_records_survive(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    writer.append(finished("run_1"))
    with open(path, "a") as handle:
        handle.write("{not json\n")
    writer.append(finished("run_2"))
    with open(path, "a") as handle:
        handle.write('{"truncated": ')
    assert reader.corrupt_lines(path) == [2, 4]
    assert [r["run_id"] for r in reader.recent_runs(path, REPO, 10)] == ["run_1", "run_2"]


def test_a_cut_off_final_line_does_not_swallow_the_next_record(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text('{"event_type": "x", "half')  # no trailing newline
    LedgerWriter(path).append(finished("run_9"))
    assert reader.corrupt_lines(path) == [1]
    assert reader.recent_runs(path, REPO, 5)[0]["run_id"] == "run_9"


def test_secrets_are_redacted_before_they_reach_the_ledger(tmp_path):
    path = tmp_path / "l.jsonl"
    LedgerWriter(path, redact_patterns=[r"token=\S+"]).append(
        S.make_event(S.TASK_FINISHED, "r", summary="token=abc123 AKIAABCDEFGHIJKLMNOP")
    )
    text = path.read_text()
    assert "abc123" not in text and "AKIA" not in text
    json.loads(text)  # still valid JSON


def test_history_is_bounded_and_filtered_by_repository(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    for number in range(30):
        writer.append(finished(f"run_{number:02d}"))
    other = finished("other_repo")
    other["repository"] = {"root_fingerprint": "sha256:zzz"}
    writer.append(other)
    runs = reader.recent_runs(path, REPO, 5)
    assert [r["run_id"] for r in runs] == [f"run_{n:02d}" for n in range(25, 30)]
    assert reader.find_run(path, "run_03", REPO)["run_id"] == "run_03"
    assert reader.find_run(path, "other_repo", REPO) is None


def test_last_committed_fingerprint(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    writer.append(finished("a", "committed", "fp-1"))
    writer.append(finished("b", "disabled", "fp-2"))
    assert reader.last_committed_fingerprint(path, REPO) == "fp-1"
    assert reader.last_committed_fingerprint(path, "sha256:other") is None


def test_unfinished_runs_are_detected(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    writer.append(S.make_event(S.RUN_STARTED, "crashed", repository={"root_fingerprint": REPO}))
    writer.append(S.make_event(S.RUN_STARTED, "fine", repository={"root_fingerprint": REPO}))
    writer.append(finished("fine"))
    assert reader.unfinished_run_ids(path, REPO) == ["crashed"]


def test_duration_estimates_use_the_median(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    for ms in (1000, 3000, 2000):
        writer.append(
            S.make_event(
                S.TASK_FINISHED, "r", task_id="tests", status="passed", duration_ms=ms,
                repository={"root_fingerprint": REPO},
            )
        )
    assert reader.median_task_durations(path, REPO) == {"tests": 2.0}


def test_rotation_keeps_old_data_and_logs_it(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path, max_megabytes=1)
    writer.max_bytes = 200  # force rotation without writing a megabyte
    for number in range(5):
        writer.append(S.make_event(S.TASK_FINISHED, f"r{number}", summary="x" * 80))
    archives = list(tmp_path.glob("l-*.jsonl"))
    assert archives, "an archived ledger file should exist"
    types = [r["event_type"] for _, r in reader.iter_records(path) if r]
    assert S.LEDGER_ROTATED in types


def test_retention_backs_up_then_drops_old_records(tmp_path):
    path = tmp_path / "l.jsonl"
    writer = LedgerWriter(path)
    old = iso_utc(utc_now() - timedelta(days=200))
    writer.append(finished("old_run", when=old))
    writer.append(finished("new_run"))
    with open(path, "a") as handle:
        handle.write("garbage line\n")  # malformed lines are kept as evidence
    dropped, backup = apply_retention(path, 90)
    assert dropped == 1 and backup and backup.exists()
    ids = [r.get("run_id") for _, r in reader.iter_records(path) if r]
    assert "old_run" not in ids and "new_run" in ids
    assert reader.corrupt_lines(path) == [2]
    assert any(r and r["event_type"] == S.RETENTION_APPLIED for _, r in reader.iter_records(path))


def test_retention_of_zero_means_keep_forever(tmp_path):
    path = tmp_path / "l.jsonl"
    LedgerWriter(path).append(finished("old", when=iso_utc(utc_now() - timedelta(days=9999))))
    assert apply_retention(path, 0) == (0, None)
