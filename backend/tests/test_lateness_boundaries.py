"""Lateness boundary tests — locked §1."""

from datetime import date, datetime, time

from app.services.time_tracking import (
    LATENESS_FLAG_THRESHOLD_MINUTES,
    ScheduleInfo,
    compute_lateness,
    minutes_late_floor,
)
from app.timezone_util import TZ, combine_eastern


def _schedule() -> ScheduleInfo:
    return ScheduleInfo(time(9, 0), time(17, 0))


def _at(work_date: date, h: int, m: int, s: int = 0) -> datetime:
    return combine_eastern(work_date, time(h, m, s))


def test_minutes_late_floors_seconds():
    work_date = date(2026, 6, 30)
    start = _at(work_date, 9, 0)
    assert minutes_late_floor(_at(work_date, 9, 30, 59), start) == 30
    assert minutes_late_floor(_at(work_date, 9, 30, 0), start) == 30
    assert minutes_late_floor(_at(work_date, 9, 31, 0), start) == 31


def test_29_minutes_not_flagged():
    work_date = date(2026, 6, 30)
    flagged, mins = compute_lateness(_at(work_date, 9, 29), work_date, _schedule())
    assert flagged is False
    assert mins is None


def test_30_minutes_not_flagged_including_seconds():
    work_date = date(2026, 6, 30)
    for punch in (_at(work_date, 9, 30, 0), _at(work_date, 9, 30, 59)):
        flagged, mins = compute_lateness(punch, work_date, _schedule())
        assert flagged is False, f"expected on-time at {punch}"
        assert mins is None


def test_31_minutes_flagged():
    work_date = date(2026, 6, 30)
    flagged, mins = compute_lateness(_at(work_date, 9, 31), work_date, _schedule())
    assert flagged is True
    assert mins == 31


def test_threshold_constant():
    assert LATENESS_FLAG_THRESHOLD_MINUTES == 31
