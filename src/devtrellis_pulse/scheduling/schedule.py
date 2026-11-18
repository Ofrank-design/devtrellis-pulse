"""Scheduling helpers. Pulse never runs a daemon: schedulers invoke `pulse run`.

Schedulers can delay or skip invocations. Pulse does not assume exact timing, never makes up
for missed runs, and treats repeated invocations as safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from devtrellis_pulse.core.clock import get_zone, parse_iso, utc_now
from devtrellis_pulse.core.errors import UsageError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CRON_NUMBER = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}


def zone(cfg: dict[str, Any]) -> tzinfo:
    return get_zone(cfg["schedule"]["timezone"])


def local_now(cfg: dict[str, Any], now: datetime | None = None) -> datetime:
    return (now or utc_now()).astimezone(zone(cfg))


def is_scheduled_day(cfg: dict[str, Any], now: datetime | None = None) -> bool:
    return WEEKDAYS[local_now(cfg, now).weekday()] in cfg["schedule"]["weekdays"]


def already_ran_today(runs: list[dict[str, Any]], cfg: dict[str, Any], now: datetime | None = None) -> bool:
    """True when a real (non dry run) run already finished today in the schedule timezone."""
    today = local_now(cfg, now).date()
    tz = zone(cfg)
    for record in runs:
        run = record.get("run", {})
        if run.get("dry_run"):
            continue
        finished = parse_iso(record.get("timestamp", ""))
        if finished and finished.astimezone(tz).date() == today:
            return True
    return False


def parse_time(text: str) -> tuple[int, int]:
    try:
        hour, minute = text.split(":")
        h, m = int(hour), int(minute)
    except ValueError:
        raise UsageError(f"--at must look like HH:MM, got {text!r}") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise UsageError(f"--at must be a valid time, got {text!r}")
    return h, m


def next_occurrences(
    cfg: dict[str, Any], count: int, at: str = "18:00", now: datetime | None = None
) -> list[datetime]:
    hour, minute = parse_time(at)
    tz = zone(cfg)
    current = local_now(cfg, now)
    found: list[datetime] = []
    for offset in range(0, 400):
        day = (current + timedelta(days=offset)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if candidate > current and WEEKDAYS[candidate.weekday()] in cfg["schedule"]["weekdays"]:
            found.append(candidate)
            if len(found) == count:
                break
    return found


def _cron_days(cfg: dict[str, Any]) -> str:
    return ",".join(str(_CRON_NUMBER[d]) for d in cfg["schedule"]["weekdays"])


def render_cron(cfg: dict[str, Any], at: str, command: str) -> str:
    hour, minute = parse_time(at)
    return (
        f"# {cfg['schedule']['timezone']} wall clock time: cron uses the system timezone\n"
        f"{minute} {hour} * * {_cron_days(cfg)} {command}"
    )


def render_github_cron(cfg: dict[str, Any], at: str) -> str:
    """GitHub Actions schedules run in UTC, so convert the local time using today's offset."""
    hour, minute = parse_time(at)
    tz = zone(cfg)
    now = local_now(cfg)
    local = datetime(now.year, now.month, now.day, hour, minute, tzinfo=tz)
    utc = local.astimezone(UTC)
    days = cfg["schedule"]["weekdays"]
    shift = (utc.date() - local.date()).days  # the weekday can change after conversion
    numbers = sorted({(_CRON_NUMBER[d] + shift) % 7 for d in days})
    return (
        "on:\n  workflow_dispatch:\n  schedule:\n"
        f"    # {at} {cfg['schedule']['timezone']} is {utc:%H:%M} UTC today; "
        "daylight saving may shift it.\n"
        "    # GitHub may delay or skip scheduled runs under load.\n"
        f"    - cron: \"{utc.minute} {utc.hour} * * {','.join(map(str, numbers))}\""
    )


def render_systemd(cfg: dict[str, Any], at: str, command: str) -> str:
    hour, minute = parse_time(at)
    days = ",".join(d.capitalize() for d in cfg["schedule"]["weekdays"])
    return (
        "# ~/.config/systemd/user/devtrellis-pulse.service\n"
        "[Unit]\nDescription=DevTrellis Pulse run\n\n"
        f"[Service]\nType=oneshot\nExecStart={command}\n\n"
        "# ~/.config/systemd/user/devtrellis-pulse.timer\n"
        f"[Unit]\nDescription=DevTrellis Pulse schedule\n\n"
        f"[Timer]\nOnCalendar={days} *-*-* {hour:02d}:{minute:02d}:00\n"
        f"Persistent=false\n\n[Install]\nWantedBy=timers.target\n"
        "# Persistent=false keeps missed runs from being replayed after the machine was off."
    )


def render_task_scheduler(cfg: dict[str, Any], at: str, command: str) -> str:
    hour, minute = parse_time(at)
    days = ",".join(d.upper() for d in cfg["schedule"]["weekdays"])
    return (
        f'schtasks /Create /TN "DevTrellis Pulse" /SC WEEKLY /D {days} '
        f'/ST {hour:02d}:{minute:02d} /TR "{command}"'
    )
