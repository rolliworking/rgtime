#!/usr/bin/env python3
"""Run Phase 1 acceptance demo and print resulting DB rows."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.photos import save_punch_photos
from app.services.time_tracking import record_punch, run_auto_clock_outs
from app.timezone_util import TZ, combine_eastern

SCHEMA = "rgtime"
DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres")
STAFF_CODE = "TEST01"
TINY_JPEG = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k="
)


async def main() -> int:
    conn = await asyncpg.connect(DSN, server_settings={"search_path": f"{SCHEMA},public"})
    staff = await conn.fetchrow(
        f"SELECT id, first_name, last_name FROM {SCHEMA}.staff WHERE staff_code = $1",
        STAFF_CODE,
    )
    if not staff:
        print(f"Run scripts/seed_test_staff.py first — {STAFF_CODE} not found")
        return 1

    staff_id = staff["id"]
    name = f"{staff['first_name']} {staff['last_name']}"
    work_date = datetime.now(TZ).date()

    # Clean prior demo events for today
    await conn.execute(
        f"DELETE FROM {SCHEMA}.time_events WHERE staff_id = $1 AND work_date = $2",
        staff_id,
        work_date,
    )

    cin = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name=name,
        event_type="clock_in",
        occurred_at=combine_eastern(work_date, datetime.strptime("09:45", "%H:%M").time()),
    )
    await save_punch_photos(
        conn,
        time_event_id=cin.event_id,
        staff_id=staff_id,
        photos=[
            {"sequence_number": i, "captured_at": datetime.now(TZ).isoformat(), "data_base64": TINY_JPEG}
            for i in range(1, 4)
        ],
    )

    cout = await record_punch(
        conn,
        staff_id=staff_id,
        staff_name=name,
        event_type="clock_out",
        occurred_at=combine_eastern(work_date, datetime.strptime("17:00", "%H:%M").time()),
    )

    await record_punch(
        conn,
        staff_id=staff_id,
        staff_name=name,
        event_type="clock_in",
        occurred_at=combine_eastern(work_date, datetime.strptime("18:00", "%H:%M").time()),
    )
    await run_auto_clock_outs(conn, combine_eastern(work_date, datetime.strptime("21:00", "%H:%M").time()))

    events = await conn.fetch(
        f"""
        SELECT event_type, occurred_at, is_late_arrival, late_minutes,
               lunch_deducted_minutes, is_missing_clockout_flag
        FROM {SCHEMA}.time_events
        WHERE staff_id = $1 AND work_date = $2
        ORDER BY occurred_at
        """,
        staff_id,
        work_date,
    )
    photos = await conn.fetch(
        f"""
        SELECT pp.sequence_number, pp.storage_path, te.event_type
        FROM {SCHEMA}.punch_photos pp
        JOIN {SCHEMA}.time_events te ON te.id = pp.time_event_id
        WHERE pp.staff_id = $1 AND te.work_date = $2
        ORDER BY pp.captured_at, pp.sequence_number
        """,
        staff_id,
        work_date,
    )

    print("=== time_events ===")
    for e in events:
        print(dict(e))
    print(f"\n=== punch_photos ({len(photos)} rows) ===")
    for p in photos:
        print(dict(p))

    await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
