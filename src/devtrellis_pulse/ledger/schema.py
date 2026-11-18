"""Ledger record schema (version 1). Every record carries schema_version, event_id and a UTC time."""

from __future__ import annotations

from typing import Any

from devtrellis_pulse.core.clock import iso_utc
from devtrellis_pulse.core.ids import new_event_id

SCHEMA_VERSION = 1

RUN_STARTED = "run_started"
TASK_STARTED = "task_started"
TASK_FINISHED = "task_finished"
VALIDATION_FINISHED = "validation_finished"
COMMIT_CREATED = "commit_created"
COMMIT_FAILED = "commit_failed"
RUN_FINISHED = "run_finished"
LEDGER_ROTATED = "ledger_rotated"
RETENTION_APPLIED = "retention_applied"


def make_event(event_type: str, run_id: str | None = None, **fields: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "event_id": new_event_id(),
        "run_id": run_id,
        "timestamp": iso_utc(),
    }
    record.update(fields)
    return record
