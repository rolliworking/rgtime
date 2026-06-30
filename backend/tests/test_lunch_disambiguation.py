"""Lunch break vs evening re-entry disambiguation — locked §2."""

from __future__ import annotations

import os
from datetime import date, datetime
from uuid import uuid4

import asyncpg
import pytest

from app.pin import hash_pin
from app.services.time_tracking import (
    LUNCH_BREAK_MAX_GAP_MINUTES,
    day_has_lunch_punch,
    is_lunch_break_pair,
    record_punch,
)
from app.timezone_util import TZ, combine_eastern, work_date_for

SCHEMA = "rgtime"
DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres")


def test_lunch_pair_within_gap_threshold():
    d = date(2026, 6, 30)
    out_at = combine_eastern(d, datetime.strptime("12:00", "%H:%M").time())
    in_at = combine_eastern(d, datetime.strptime("12:30", "%H:%M").time())
    assert is_lunch_break_pair(out_at, in_at) is True


def test_evening_reentry_beyond_gap_threshold():
    d = date(2026, 6, 30)
    out_at = combine_eastern(d, datetime.strptime("12:00", "%H:%M").time())
    in_at = combine_eastern(d, datetime.strptime("18:00", "%H:%M").time())
    gap_hours = 6
    assert gap_hours * 60 > LUNCH_BREAK_MAX_GAP_MINUTES
    assert is_lunch_break_pair(out_at, in_at) is False


def test_day_has_lunch_punch_rejects_long_gap():
    d = date(2026, 6, 30)
    events = [
        {"event_type": "clock_in", "occurred_at": combine_eastern(d, datetime.strptime("08:00", "%H:%M").time())},
        {"event_type": "clock_out", "occurred_at": combine_eastern(d, datetime.strptime("12:00", "%H:%M").time())},
        {"event_type": "clock_in", "occurred_at": combine_eastern(d, datetime.strptime("18:00", "%H:%M").time())},
    ]
    assert day_has_lunch_punch(events) is False


def test_day_has_lunch_punch_accepts_short_gap():
    d = date(2026, 6, 30)
    events = [
        {"event_type": "clock_in", "occurred_at": combine_eastern(d, datetime.strptime("08:00", "%H:%M").time())},
        {"event_type": "clock_out", "occurred_at": combine_eastern(d, datetime.strptime("12:00", "%H:%M").time())},
        {"event_type": "clock_in", "occurred_at": combine_eastern(d, datetime.strptime("12:30", "%H:%M").time())},
    ]
    assert day_has_lunch_punch(events) is True


@pytest.fixture
async def db_conn():
    conn = await asyncpg.connect(DSN, server_settings={"search_path": f"{SCHEMA},public"})
    staff_id = uuid4()
    code = f"L{uuid4().hex[:6].upper()}"
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.staff (id, staff_code, first_name, last_name, hire_date, auto_clock_out_cap)
        VALUES ($1, $2, 'Lunch', 'Test', '2024-01-01', '21:00:00')
        """,
        staff_id,
        code,
    )
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.schedules (staff_id, scheduled_start_time, scheduled_end_time)
        VALUES ($1, '09:00:00', '17:00:00')
        """,
        staff_id,
    )
    await conn.execute(
        f"INSERT INTO {SCHEMA}.pin_credentials (staff_id, pin_hash) VALUES ($1, $2)",
        staff_id,
        hash_pin("9999"),
    )
    yield conn, staff_id
    await conn.execute(f"DELETE FROM {SCHEMA}.staff WHERE id = $1", staff_id)
    await conn.close()


@pytest.mark.asyncio
async def test_evening_reentry_still_gets_lunch_deduct(db_conn):
    """Leave at noon, return at 6 PM — long gap is NOT lunch; deduct on final out."""
    conn, staff_id = db_conn
    work_date = date(2026, 6, 30)
    t = lambda h, m: combine_eastern(work_date, datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time())

    await record_punch(conn, staff_id=staff_id, staff_name="L", event_type="clock_in", occurred_at=t(8, 0))
    await record_punch(conn, staff_id=staff_id, staff_name="L", event_type="clock_out", occurred_at=t(12, 0))
    await record_punch(conn, staff_id=staff_id, staff_name="L", event_type="clock_in", occurred_at=t(18, 0))
    cout = await record_punch(
        conn, staff_id=staff_id, staff_name="L", event_type="clock_out", occurred_at=t(21, 0)
    )
    assert cout.lunch_deducted_minutes == 30


@pytest.mark.asyncio
async def test_first_clock_in_uses_eastern_work_date_not_utc(db_conn):
    """Punch just after midnight Eastern is first clock_in of that work_date (§3)."""
    conn, staff_id = db_conn
    # 2026-07-01 00:15 America/New_York = 2026-07-01 04:15 UTC (EDT)
    eastern_midnight_plus = combine_eastern(date(2026, 7, 1), datetime.strptime("00:15", "%H:%M").time())
    assert work_date_for(eastern_midnight_plus) == date(2026, 7, 1)

    result = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="L",
        event_type="clock_in",
        occurred_at=eastern_midnight_plus,
    )
    assert result.work_date == date(2026, 7, 1)
    # Scheduled 9:00 — 00:15 is on-time (not late)
    assert result.is_late_arrival is False

    await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="L",
        event_type="clock_out",
        occurred_at=combine_eastern(date(2026, 7, 1), datetime.strptime("08:00", "%H:%M").time()),
    )
    # Re-entry hours later — must not be evaluated for lateness (§3)
    second = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="L",
        event_type="clock_in",
        occurred_at=combine_eastern(date(2026, 7, 1), datetime.strptime("14:00", "%H:%M").time()),
    )
    assert second.work_date == date(2026, 7, 1)
    assert second.is_late_arrival is False
    assert second.late_minutes is None
