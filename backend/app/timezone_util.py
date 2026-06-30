"""America/New_York workday helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


def now_eastern() -> datetime:
    return datetime.now(TZ)


def work_date_for(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).date()


def combine_eastern(work_date: date, t: time) -> datetime:
    return datetime.combine(work_date, t, tzinfo=TZ)


def format_time_eastern(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return local.strftime("%-I:%M %p") if hasattr(local, "strftime") else local.strftime("%I:%M %p").lstrip("0")
