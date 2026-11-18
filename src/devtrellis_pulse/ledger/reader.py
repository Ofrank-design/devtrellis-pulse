"""Streaming ledger reader. Never loads the whole file; reports corrupt lines by number."""

from __future__ import annotations

import json
import statistics
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from devtrellis_pulse.ledger.schema import RUN_FINISHED, RUN_STARTED, TASK_FINISHED


def iter_records(path: Path) -> Iterator[tuple[int, dict[str, Any] | None]]:
    """Yield (line number, record). The record is None for a malformed line."""
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except ValueError:
                yield number, None
                continue
            yield number, value if isinstance(value, dict) else None


def corrupt_lines(path: Path) -> list[int]:
    return [number for number, record in iter_records(path) if record is None]


def _for_repo(record: dict[str, Any], repo_fp: str | None) -> bool:
    return repo_fp is None or record.get("repository", {}).get("root_fingerprint") == repo_fp


def recent_runs(path: Path, repo_fp: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """The most recent finished runs, oldest first. Memory use is bounded by `limit`."""
    window: deque[dict[str, Any]] = deque(maxlen=max(limit, 1))
    for _, record in iter_records(path):
        if record and record.get("event_type") == RUN_FINISHED and _for_repo(record, repo_fp):
            window.append(record)
    return list(window)


def find_run(path: Path, run_id: str, repo_fp: str | None = None) -> dict[str, Any] | None:
    found = None
    for _, record in iter_records(path):
        if (
            record
            and record.get("event_type") == RUN_FINISHED
            and record.get("run_id") == run_id
            and _for_repo(record, repo_fp)
        ):
            found = record
    return found


def last_committed_fingerprint(path: Path, repo_fp: str | None) -> str | None:
    found = None
    for _, record in iter_records(path):
        if record and record.get("event_type") == RUN_FINISHED and _for_repo(record, repo_fp):
            run = record.get("run", {})
            if run.get("commit_status") == "committed":
                found = run.get("fingerprint")
    return found


def unfinished_run_ids(path: Path, repo_fp: str | None) -> list[str]:
    started: set[str] = set()
    finished: set[str] = set()
    for _, record in iter_records(path):
        if not record or not record.get("run_id"):
            continue
        if record["event_type"] == RUN_STARTED and _for_repo(record, repo_fp):
            started.add(record["run_id"])
        elif record["event_type"] == RUN_FINISHED:
            finished.add(record["run_id"])
    return sorted(started - finished)


def median_task_durations(path: Path, repo_fp: str | None, window: int = 500) -> dict[str, float]:
    """Median duration in seconds per task id from recent history. An estimate, never a promise."""
    samples: deque[tuple[str, int]] = deque(maxlen=window)
    for _, record in iter_records(path):
        if record and record.get("event_type") == TASK_FINISHED and _for_repo(record, repo_fp):
            if record.get("status") in ("passed", "failed", "timed_out"):
                samples.append((record["task_id"], int(record.get("duration_ms", 0))))
    grouped: dict[str, list[int]] = {}
    for task_id, millis in samples:
        grouped.setdefault(task_id, []).append(millis)
    return {k: round(statistics.median(v) / 1000, 2) for k, v in grouped.items()}
