"""Deliberate retention: backup first, streaming rewrite, then a logged event. Never automatic."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

from devtrellis_pulse.core.clock import parse_iso, utc_now
from devtrellis_pulse.ledger.reader import iter_records
from devtrellis_pulse.ledger.schema import RETENTION_APPLIED, make_event
from devtrellis_pulse.ledger.writer import LedgerWriter
from devtrellis_pulse.platform.files import atomic_write_text


def apply_retention(path: Path, retention_days: int) -> tuple[int, Path | None]:
    """Drop records older than retention_days. Returns (records dropped, backup path).

    retention_days of 0 means keep forever. Malformed lines are preserved as evidence.
    """
    path = Path(path)
    if retention_days <= 0 or not path.exists():
        return 0, None
    cutoff = utc_now() - timedelta(days=retention_days)
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    parsed = {number: record for number, record in iter_records(path)}
    keep: list[str] = []
    dropped = 0
    line_numbers = iter(range(1, len(raw_lines) + 1))
    for text in raw_lines:
        number = next(line_numbers)
        if not text.strip():
            continue
        record = parsed.get(number)
        when = parse_iso(record.get("timestamp", "")) if record else None
        if record is not None and when is not None and when < cutoff:
            dropped += 1
        else:
            keep.append(text)
    if not dropped:
        return 0, None
    backup = path.with_name(f"{path.name}.bak-{utc_now().strftime('%Y%m%dT%H%M%SZ')}")
    shutil.copy2(path, backup)
    atomic_write_text(path, "\n".join(keep) + ("\n" if keep else ""))
    LedgerWriter(path).append(
        make_event(RETENTION_APPLIED, None, dropped=dropped, backup=backup.name, days=retention_days)
    )
    return dropped, backup

