"""Phase 2: offline punch queue sync acceptance."""

from __future__ import annotations

import os
from datetime import date, datetime
from uuid import uuid4

import asyncpg
import pytest

from app.pin import hash_pin
from app.services.sync import sync_punch_batch
from app.timezone_util import combine_eastern

SCHEMA = "rgtime"
DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres")
TINY_PHOTO = {
    "sequence_number": 1,
    "captured_at": "2026-06-30T13:00:00+00:00",
    "data_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k=",
}


@pytest.fixture
async def db_conn():
    conn = await asyncpg.connect(DSN, server_settings={"search_path": f"{SCHEMA},public"})
    staff_id = uuid4()
    code = f"O{uuid4().hex[:6].upper()}"
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.staff (id, staff_code, first_name, last_name, hire_date, auto_clock_out_cap)
        VALUES ($1, $2, 'Offline', 'Test', '2024-01-01', '21:00:00')
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
        hash_pin("4321"),
    )
    yield conn, staff_id
    await conn.execute(f"DELETE FROM {SCHEMA}.staff WHERE id = $1", staff_id)
    await conn.close()


@pytest.mark.asyncio
async def test_offline_mid_shift_sync_zero_loss(db_conn):
    """Simulate WiFi loss: queue clock-in + clock-out, sync in timestamp order."""
    conn, staff_id = db_conn
    work_date = date(2026, 6, 30)
    cid_in = str(uuid4())
    cid_out = str(uuid4())
    t_in = combine_eastern(work_date, datetime.strptime("08:00", "%H:%M").time())
    t_out = combine_eastern(work_date, datetime.strptime("17:00", "%H:%M").time())

    batch = [
        {
            "client_local_id": cid_out,
            "pin": "4321",
            "occurred_at": t_out.isoformat(),
            "photos": [TINY_PHOTO],
        },
        {
            "client_local_id": cid_in,
            "pin": "4321",
            "occurred_at": t_in.isoformat(),
            "photos": [TINY_PHOTO],
        },
    ]
    result = await sync_punch_batch(conn, batch)
    assert result["failure_count"] == 0
    assert cid_in in result["synced"]
    assert cid_out in result["synced"]

    events = await conn.fetch(
        f"""
        SELECT event_type, client_local_id, synced_at IS NOT NULL AS synced
        FROM {SCHEMA}.time_events
        WHERE staff_id = $1
        ORDER BY occurred_at
        """,
        staff_id,
    )
    assert len(events) == 2
    assert events[0]["event_type"] == "clock_in"
    assert events[0]["client_local_id"] == cid_in
    assert events[1]["event_type"] == "clock_out"
    assert events[0]["synced"] is True

    photos = await conn.fetchval(
        f"SELECT COUNT(*) FROM {SCHEMA}.punch_photos pp JOIN {SCHEMA}.time_events te ON te.id = pp.time_event_id WHERE te.staff_id = $1",
        staff_id,
    )
    assert photos == 2

    # Idempotent re-sync
    result2 = await sync_punch_batch(conn, batch)
    assert result2["failure_count"] == 0
    assert set(result2["duplicates"]) == {cid_in, cid_out}
    count = await conn.fetchval(
        f"SELECT COUNT(*) FROM {SCHEMA}.time_events WHERE staff_id = $1", staff_id
    )
    assert count == 2


@pytest.mark.asyncio
async def test_sync_failure_logged_loudly(db_conn):
    conn, _staff_id = db_conn
    result = await sync_punch_batch(
        conn,
        [
            {
                "client_local_id": str(uuid4()),
                "pin": "0000",
                "occurred_at": datetime.now().astimezone().isoformat(),
                "photos": [],
            }
        ],
    )
    assert result["failure_count"] == 1
    row = await conn.fetchrow(
        f"SELECT error_message FROM {SCHEMA}.sync_failures ORDER BY created_at DESC LIMIT 1"
    )
    assert row is not None
    assert "PIN" in row["error_message"]
