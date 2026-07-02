"""Timesheet viewing and manager edits during biweekly audit."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.services.pto_accrual import compute_punched_hours
from app.timezone_util import TZ, combine_eastern, work_date_for


def _event_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["staff_id"] = str(d["staff_id"])
    if d.get("occurred_at"):
        d["occurred_at"] = d["occurred_at"].astimezone(TZ).isoformat()
    if d.get("work_date"):
        d["work_date"] = d["work_date"].isoformat()
    return d


async def get_staff_timesheet(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    settings = get_settings()
    days: list[dict[str, Any]] = []
    d = start_date
    while d <= end_date:
        events = await conn.fetch(
            f"""
            SELECT id, staff_id, event_type, occurred_at, work_date,
                   is_late_arrival, late_minutes, is_missing_clockout_flag,
                   face_mismatch_flag, lunch_deducted_minutes
            FROM {settings.db_schema}.time_events
            WHERE staff_id = $1 AND work_date = $2
            ORDER BY occurred_at ASC, created_at ASC
            """,
            staff_id,
            d,
        )
        absence = await conn.fetchrow(
            f"""
            SELECT a.id, a.notes, a.audit_resolved, a.reported_hours,
                   r.name AS reason_name, r.funding
            FROM {settings.db_schema}.absences a
            JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
            WHERE a.staff_id = $1 AND a.absence_date = $2
            """,
            staff_id,
            d,
        )
        hours = await compute_punched_hours(conn, staff_id, d)
        day: dict[str, Any] = {
            "work_date": d.isoformat(),
            "hours_worked": str(hours),
            "events": [_event_dict(e) for e in events],
        }
        if absence:
            day["absence"] = {
                "id": str(absence["id"]),
                "reason_name": absence["reason_name"],
                "funding": absence["funding"],
                "audit_resolved": absence["audit_resolved"],
                "reported_hours": (
                    str(absence["reported_hours"]) if absence["reported_hours"] is not None else None
                ),
                "notes": absence["notes"],
            }
        days.append(day)
        d = date.fromordinal(d.toordinal() + 1)
    return days


async def update_time_event(
    conn: asyncpg.Connection,
    *,
    event_id: UUID,
    occurred_at: datetime | None = None,
    clear_missing_clockout: bool = False,
    clear_face_mismatch: bool = False,
    actor_id: UUID | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    old_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.time_events WHERE id = $1",
        event_id,
    )
    if old_row is None:
        return None
    old = _event_dict(old_row)

    updates: list[str] = []
    params: list[Any] = [event_id]
    idx = 2

    if occurred_at is not None:
        updates.append(f"occurred_at = ${idx}")
        params.append(occurred_at)
        idx += 1
        updates.append(f"work_date = ${idx}")
        params.append(work_date_for(occurred_at))
        idx += 1
    if clear_missing_clockout:
        updates.append("is_missing_clockout_flag = FALSE")
    if clear_face_mismatch:
        updates.append("face_mismatch_flag = FALSE")

    if not updates:
        return old

    await conn.execute(
        f"UPDATE {settings.db_schema}.time_events SET {', '.join(updates)} WHERE id = $1",
        *params,
    )
    new_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.time_events WHERE id = $1",
        event_id,
    )
    new = _event_dict(new_row) if new_row else old
    await write_audit_log(
        conn,
        actor_type="admin",
        action="update",
        table_name="time_events",
        record_id=event_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new


async def resolve_missing_clockout(
    conn: asyncpg.Connection,
    *,
    event_id: UUID,
    departure_time: str,
    work_date: date,
    actor_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Set last-known departure on an auto_clock_out event."""
    parts = departure_time.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    occurred_at = combine_eastern(work_date, time(h, m, s))
    return await update_time_event(
        conn,
        event_id=event_id,
        occurred_at=occurred_at,
        clear_missing_clockout=True,
        actor_id=actor_id,
    )
