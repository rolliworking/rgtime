"""Schedule presets and per-staff schedule management."""

from __future__ import annotations

from datetime import date, time
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings


def _time_str(t: time) -> str:
    return t.strftime("%H:%M:%S")


def _preset_row(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["scheduled_start_time"] = _time_str(d["scheduled_start_time"])
    d["scheduled_end_time"] = _time_str(d["scheduled_end_time"])
    return d


def _schedule_row(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["staff_id"] = str(d["staff_id"])
    if d.get("preset_id"):
        d["preset_id"] = str(d["preset_id"])
    d["scheduled_start_time"] = _time_str(d["scheduled_start_time"])
    d["scheduled_end_time"] = _time_str(d["scheduled_end_time"])
    if d.get("effective_from"):
        d["effective_from"] = d["effective_from"].isoformat()
    return d


async def list_presets(conn: asyncpg.Connection) -> list[dict]:
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT * FROM {settings.db_schema}.schedule_presets
        ORDER BY name
        """
    )
    return [_preset_row(r) for r in rows]


async def create_preset(
    conn: asyncpg.Connection,
    *,
    name: str,
    scheduled_start_time: time,
    scheduled_end_time: time,
    actor_id: UUID | None = None,
) -> dict:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.schedule_presets (name, scheduled_start_time, scheduled_end_time)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        name.strip(),
        scheduled_start_time,
        scheduled_end_time,
    )
    if row is None:
        raise RuntimeError("preset insert failed")
    result = _preset_row(row)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="create",
        table_name="schedule_presets",
        record_id=row["id"],
        actor_id=actor_id,
        new_values=result,
    )
    return result


async def update_preset(
    conn: asyncpg.Connection,
    *,
    preset_id: UUID,
    name: str | None = None,
    scheduled_start_time: time | None = None,
    scheduled_end_time: time | None = None,
    actor_id: UUID | None = None,
) -> dict | None:
    settings = get_settings()
    old_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.schedule_presets WHERE id = $1",
        preset_id,
    )
    if old_row is None:
        return None
    old = _preset_row(old_row)

    updates: list[str] = []
    params: list[Any] = [preset_id]
    idx = 2
    if name is not None:
        updates.append(f"name = ${idx}")
        params.append(name.strip())
        idx += 1
    if scheduled_start_time is not None:
        updates.append(f"scheduled_start_time = ${idx}")
        params.append(scheduled_start_time)
        idx += 1
    if scheduled_end_time is not None:
        updates.append(f"scheduled_end_time = ${idx}")
        params.append(scheduled_end_time)
        idx += 1

    if updates:
        await conn.execute(
            f"UPDATE {settings.db_schema}.schedule_presets SET {', '.join(updates)} WHERE id = $1",
            *params,
        )

    new_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.schedule_presets WHERE id = $1",
        preset_id,
    )
    new = _preset_row(new_row) if new_row else old
    await write_audit_log(
        conn,
        actor_type="admin",
        action="update",
        table_name="schedule_presets",
        record_id=preset_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new


async def get_staff_schedule(conn: asyncpg.Connection, staff_id: UUID) -> dict | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.schedules WHERE staff_id = $1",
        staff_id,
    )
    return _schedule_row(row) if row else None


async def set_staff_schedule(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    preset_id: UUID | None = None,
    scheduled_start_time: time | None = None,
    scheduled_end_time: time | None = None,
    effective_from: date | None = None,
    actor_id: UUID | None = None,
) -> dict:
    settings = get_settings()

    if preset_id is not None:
        preset = await conn.fetchrow(
            f"SELECT * FROM {settings.db_schema}.schedule_presets WHERE id = $1",
            preset_id,
        )
        if preset is None:
            raise ValueError("preset not found")
        start = preset["scheduled_start_time"]
        end = preset["scheduled_end_time"]
    else:
        if scheduled_start_time is None or scheduled_end_time is None:
            raise ValueError("scheduled_start_time and scheduled_end_time required without preset")
        start = scheduled_start_time
        end = scheduled_end_time
        preset_id = None

    old_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.schedules WHERE staff_id = $1",
        staff_id,
    )
    old = _schedule_row(old_row) if old_row else None

    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.schedules (
            staff_id, preset_id, scheduled_start_time, scheduled_end_time, effective_from
        )
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (staff_id) DO UPDATE SET
            preset_id = EXCLUDED.preset_id,
            scheduled_start_time = EXCLUDED.scheduled_start_time,
            scheduled_end_time = EXCLUDED.scheduled_end_time,
            effective_from = EXCLUDED.effective_from,
            updated_at = now()
        RETURNING *
        """,
        staff_id,
        preset_id,
        start,
        end,
        effective_from,
    )
    if row is None:
        raise RuntimeError("schedule upsert failed")
    new = _schedule_row(row)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="upsert",
        table_name="schedules",
        record_id=row["id"],
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new
