from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(moment: datetime | None = None) -> str:
    """UTC timestamp with a trailing Z, whole seconds."""
    moment = moment or utc_now()
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_zone(name: str) -> tzinfo:
    """Look up a timezone. UTC always works, even on systems with no timezone database."""
    if name in ("UTC", "Etc/UTC", "Z"):
        return UTC
    return ZoneInfo(name)  # raises ZoneInfoNotFoundError, ValueError or OSError
