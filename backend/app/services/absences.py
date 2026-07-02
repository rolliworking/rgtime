"""Absence records for biweekly audit."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["staff_id"] = str(d["staff_id"])
    d["reason_id"] = str(d["reason_id"])
    if d.get("absence_date"):
        d["absence_date"] = d["absence_date"].isoformat()
    if d.get("pay_period_start"):
        d["pay_period_start"] = d["pay_period_start"].isoformat()
    if d.get("reported_hours") is not None:
        d["reported_hours"] = str(d["reported_hours"])
    return d


async def get_absence(
    conn: asyncpg.Connection,
    staff_id: UUID,
    absence_date: date,
) -> dict[str, Any] | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT a.*, r.name AS reason_name, r.funding, r.counts_as_worked
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.staff_id = $1 AND a.absence_date = $2
        """,
        staff_id,
        absence_date,
    )
    return _row_to_dict(row) if row else None


async def upsert_absence(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    absence_date: date,
    reason_id: UUID,
    notes: str | None = None,
    reported_hours: Decimal | None = None,
    pay_period_start: date | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    old = await get_absence(conn, staff_id, absence_date)

    reason = await conn.fetchrow(
        f"SELECT counts_as_worked, funding FROM {settings.db_schema}.absence_reasons WHERE id = $1",
        reason_id,
    )
    if reason is None:
        raise ValueError("absence reason not found")
    if reason["counts_as_worked"] and reported_hours is None:
        raise ValueError("reported_hours required for counts_as_worked absences")

    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.absences (
            staff_id, absence_date, reason_id, notes, reported_hours,
            pay_period_start, entered_by, audit_resolved
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE)
        ON CONFLICT (staff_id, absence_date) DO UPDATE SET
            reason_id = EXCLUDED.reason_id,
            notes = EXCLUDED.notes,
            reported_hours = EXCLUDED.reported_hours,
            pay_period_start = EXCLUDED.pay_period_start,
            audit_resolved = FALSE,
            updated_at = now()
        RETURNING *
        """,
        staff_id,
        absence_date,
        reason_id,
        notes,
        reported_hours,
        pay_period_start,
        actor_id,
    )
    if row is None:
        raise RuntimeError("absence upsert failed")

    result = await get_absence(conn, staff_id, absence_date)
    assert result is not None
    await write_audit_log(
        conn,
        actor_type="admin",
        action="upsert",
        table_name="absences",
        record_id=UUID(result["id"]),
        actor_id=actor_id,
        old_values=old,
        new_values=result,
    )
    return result


async def mark_absence_resolved(
    conn: asyncpg.Connection,
    *,
    absence_id: UUID,
    actor_id: UUID | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    old_row = await conn.fetchrow(
        f"""
        SELECT a.*, r.name AS reason_name, r.funding
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.id = $1
        """,
        absence_id,
    )
    if old_row is None:
        return None
    old = _row_to_dict(old_row)

    await conn.execute(
        f"UPDATE {settings.db_schema}.absences SET audit_resolved = TRUE WHERE id = $1",
        absence_id,
    )
    new_row = await conn.fetchrow(
        f"""
        SELECT a.*, r.name AS reason_name, r.funding
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.id = $1
        """,
        absence_id,
    )
    new = _row_to_dict(new_row) if new_row else old
    await write_audit_log(
        conn,
        actor_type="admin",
        action="resolve",
        table_name="absences",
        record_id=absence_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new
