#!/usr/bin/env python3
"""Seed a test staff member for kiosk acceptance (PIN 1234)."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import asyncpg

from app.pin import hash_pin

SCHEMA = "rgtime"
PIN = "1234"
STAFF_CODE = "TEST01"


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres")
    conn = await asyncpg.connect(dsn, server_settings={"search_path": f"{SCHEMA},public"})

    existing = await conn.fetchval(
        f"SELECT id FROM {SCHEMA}.staff WHERE staff_code = $1", STAFF_CODE
    )
    if existing:
        print(f"Staff {STAFF_CODE} already exists: {existing}")
        await conn.close()
        return 0

    staff_id = await conn.fetchval(
        f"""
        INSERT INTO {SCHEMA}.staff (
            staff_code, first_name, last_name, hire_date,
            auto_clock_out_cap, face_check_enabled
        )
        VALUES ($1, 'Test', 'Worker', '2024-01-15', '21:00:00', FALSE)
        RETURNING id
        """,
        STAFF_CODE,
    )

    preset = await conn.fetchval(
        f"SELECT id FROM {SCHEMA}.schedule_presets WHERE name = '9-5'"
    )
    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.schedules (
            staff_id, preset_id, scheduled_start_time, scheduled_end_time
        )
        SELECT $1, id, scheduled_start_time, scheduled_end_time
        FROM {SCHEMA}.schedule_presets WHERE name = '9-5'
        """,
        staff_id,
    )

    await conn.execute(
        f"""
        INSERT INTO {SCHEMA}.pin_credentials (staff_id, pin_hash)
        VALUES ($1, $2)
        """,
        staff_id,
        hash_pin(PIN),
    )

    print(f"Seeded staff {STAFF_CODE} id={staff_id} PIN={PIN}")
    await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
