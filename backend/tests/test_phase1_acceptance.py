"""Phase 1 acceptance: full kiosk day with lateness, lunch deduct, auto clock-out."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from app.pin import hash_pin
from app.services.time_tracking import (
    get_day_events,
    get_last_event,
    is_clocked_in,
    record_punch,
    run_auto_clock_outs,
)
from app.timezone_util import TZ, combine_eastern, work_date_for

SCHEMA = "rgtime"
DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres")

# 1x1 red JPEG
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB"
    "/8QAFwABAQEBAAAAAAAAAAAAAAAAAAUGB//EABUBAQEAAAAAAAAAAAAAAAAAAAAB/9oADAMBAAIQAxAAAAGfAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Bf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Bf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEABj8Cf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8hf//Z"
)


@pytest.fixture
async def db_conn():
    conn = await asyncpg.connect(DSN, server_settings={"search_path": f"{SCHEMA},public"})
    staff_id = uuid4()
    code = f"T{uuid4().hex[:6].upper()}"

    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.staff (
            id, staff_code, first_name, last_name, hire_date, auto_clock_out_cap
        )
        VALUES ($1, $2, 'Accept', 'Test', '2024-01-01', '21:00:00')
        """,
        staff_id,
        code,
    )
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.schedules (
            staff_id, scheduled_start_time, scheduled_end_time
        )
        VALUES ($1, '09:00:00', '17:00:00')
        """,
        staff_id,
    )
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.pin_credentials (staff_id, pin_hash)
        VALUES ($1, $2)
        """,
        staff_id,
        hash_pin("5678"),
    )

    yield conn, staff_id

    await conn.execute(f"DELETE FROM {SCHEMA}.staff WHERE id = $1", staff_id)
    await conn.close()


@pytest.mark.asyncio
async def test_full_day_lateness_lunch_auto_clockout(db_conn):
    conn, staff_id = db_conn
    work_date = datetime.now(TZ).date()

    # Late clock-in: 9:45 AM (45 min after 9:00 → flagged, 45 late_minutes)
    late_in = combine_eastern(work_date, datetime.strptime("09:45", "%H:%M").time())
    cin = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="Accept Test",
        event_type="clock_in",
        occurred_at=late_in,
    )
    assert cin.is_late_arrival is True
    assert cin.late_minutes == 45

    # End of day clock-out without lunch punches → 30 min deduction
    late_out = combine_eastern(work_date, datetime.strptime("17:30", "%H:%M").time())
    cout = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="Accept Test",
        event_type="clock_out",
        occurred_at=late_out,
    )
    assert cout.lunch_deducted_minutes == 30

    # New shift: clock in, leave open, trigger auto clock-out at cap
    eve_in = combine_eastern(work_date, datetime.strptime("18:00", "%H:%M").time())
    await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="Accept Test",
        event_type="clock_in",
        occurred_at=eve_in,
    )
    cap_moment = combine_eastern(work_date, datetime.strptime("21:00", "%H:%M").time())
    auto_results = await run_auto_clock_outs(conn, cap_moment)
    assert any(r.is_missing_clockout_flag for r in auto_results)

    events = await conn.fetch(
        f"""
        SELECT event_type, is_late_arrival, late_minutes,
               lunch_deducted_minutes, is_missing_clockout_flag
        FROM {SCHEMA}.time_events
        WHERE staff_id = $1 AND work_date = $2
        ORDER BY occurred_at
        """,
        staff_id,
        work_date,
    )
    assert len(events) >= 4
    assert events[0]["is_late_arrival"] is True
    assert events[1]["lunch_deducted_minutes"] == 30
    assert any(e["event_type"] == "auto_clock_out" for e in events)
    assert any(e["is_missing_clockout_flag"] for e in events)


@pytest.mark.asyncio
async def test_lunch_punch_no_deduction(db_conn):
    conn, staff_id = db_conn
    work_date = datetime.now(TZ).date()
    t = lambda h, m: combine_eastern(work_date, datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time())

    await record_punch(conn, staff_id=staff_id, staff_name="A", event_type="clock_in", occurred_at=t(8, 0))
    await record_punch(conn, staff_id=staff_id, staff_name="A", event_type="clock_out", occurred_at=t(12, 0))
    await record_punch(conn, staff_id=staff_id, staff_name="A", event_type="clock_in", occurred_at=t(12, 30))
    cout = await record_punch(
        conn, staff_id=staff_id, staff_name="A", event_type="clock_out", occurred_at=t(17, 0)
    )
    assert cout.lunch_deducted_minutes == 0
