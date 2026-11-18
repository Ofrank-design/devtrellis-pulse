from datetime import UTC, datetime

import pytest

from devtrellis_pulse.core.errors import UsageError
from devtrellis_pulse.scheduling import schedule as sch
from tests.helpers import make_cfg

# 2026-11-02 is a Monday.
MON = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
TUE = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def cfg(days, tz="UTC"):
    return make_cfg(schedule={"enabled": True, "weekdays": days, "timezone": tz})


def test_scheduled_days_follow_the_configuration():
    config = cfg(["mon", "wed", "fri"])
    assert sch.is_scheduled_day(config, MON)
    assert not sch.is_scheduled_day(config, TUE)


@pytest.mark.parametrize("days", [["mon", "wed", "fri"], ["mon", "tue", "thu", "fri"], ["mon", "tue", "wed", "thu", "fri"]])
def test_three_four_or_five_weekdays_are_supported(days):
    config = cfg(days)
    assert not config.warnings
    assert len(sch.next_occurrences(config, 10, now=MON)) == 10


def test_timezone_decides_which_day_it_is():
    # 23:30 UTC on Monday is already Tuesday in Accra? No: Accra is UTC+0. Tokyo is UTC+9.
    late = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)
    assert sch.is_scheduled_day(cfg(["mon"], "UTC"), late)
    assert not sch.is_scheduled_day(cfg(["mon"], "Asia/Tokyo"), late)  # Tuesday in Tokyo
    assert sch.is_scheduled_day(cfg(["tue"], "Asia/Tokyo"), late)


def test_next_occurrences_are_future_and_ordered():
    found = sch.next_occurrences(cfg(["mon", "wed"]), 3, "18:00", now=MON)
    assert [m.strftime("%a %H:%M") for m in found] == ["Mon 18:00", "Wed 18:00", "Mon 18:00"]
    assert found == sorted(found)
    assert all(m > MON for m in found)


def test_already_ran_today_ignores_dry_runs_and_other_days():
    config = cfg(["mon"])
    today = {"timestamp": "2026-11-02T08:00:00Z", "run": {"dry_run": False}}
    dry = {"timestamp": "2026-11-02T08:00:00Z", "run": {"dry_run": True}}
    yesterday = {"timestamp": "2026-11-01T08:00:00Z", "run": {"dry_run": False}}
    assert sch.already_ran_today([today], config, MON)
    assert not sch.already_ran_today([dry, yesterday], config, MON)


def test_cron_rendering():
    text = sch.render_cron(cfg(["mon", "wed", "fri"]), "18:30", "pulse run --execute")
    assert "30 18 * * 1,3,5 pulse run --execute" in text


def test_github_cron_converts_to_utc_and_shifts_the_weekday():
    # 02:00 on Monday in Tokyo is 17:00 on Sunday UTC.
    text = sch.render_github_cron(cfg(["mon"], "Asia/Tokyo"), "02:00")
    assert '- cron: "0 17 * * 0"' in text
    assert "may delay or skip" in text


def test_systemd_does_not_replay_missed_runs():
    text = sch.render_systemd(cfg(["mon", "fri"]), "06:15", "pulse run --execute")
    assert "OnCalendar=Mon,Fri *-*-* 06:15:00" in text
    assert "Persistent=false" in text


def test_windows_task_scheduler():
    assert "/D MON,WED" in sch.render_task_scheduler(cfg(["mon", "wed", "fri"][:2]), "09:00", "pulse run")


@pytest.mark.parametrize("bad", ["25:00", "12:60", "noon", "1200", ""])
def test_bad_times_are_rejected(bad):
    with pytest.raises(UsageError):
        sch.parse_time(bad)


def test_utc_works_without_a_timezone_database(monkeypatch):
    from zoneinfo import ZoneInfoNotFoundError

    from devtrellis_pulse.core import clock

    def missing(name):
        raise ZoneInfoNotFoundError(name)

    monkeypatch.setattr(clock, "ZoneInfo", missing)
    assert clock.get_zone("UTC") is UTC
    with pytest.raises(ZoneInfoNotFoundError):
        clock.get_zone("Africa/Accra")
