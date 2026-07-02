"""Weekly summary rollup for RS integration — Phase 8."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.services.biweekly_audit import _day_credit_hours
from app.timezone_util import TZ

WEEKLY_TARGET = Decimal("40.00")
TWOPLACES = Decimal("0.01")


def week_bounds(week_start: date) -> tuple[date, date]:
    """Monday–Sunday week (week_start must be Monday)."""
    return week_start, week_start + timedelta(days=6)


def monday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday()))


async def compute_staff_week(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    staff_code: str,
    week_start: date,
) -> dict[str, Any]:
    settings = get_settings()
    week_start, week_end = week_bounds(week_start)
    hours = Decimal("0")
    days_attended = 0
    days_missed = 0
    days_excused = 0
    late_arrivals = 0

    d = week_start
    while d <= week_end:
        day_hrs = await _day_credit_hours(conn, staff_id, d)
        if day_hrs > 0:
            days_attended += 1
            hours += day_hrs

        absence = await conn.fetchrow(
            f"""
            SELECT r.funding, r.counts_as_worked
            FROM {settings.db_schema}.absences a
            JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
            WHERE a.staff_id = $1 AND a.absence_date = $2
            """,
            staff_id,
            d,
        )
        if absence and day_hrs == 0:
            if absence["funding"] in ("paid_outright", "paid_from_pto"):
                days_excused += 1
            else:
                days_missed += 1

        late = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM {settings.db_schema}.time_events
            WHERE staff_id = $1 AND work_date = $2 AND is_late_arrival = TRUE
            """,
            staff_id,
            d,
        )
        late_arrivals += int(late or 0)
        d += timedelta(days=1)

    computed_at = datetime.now(TZ)
    return {
        "staff_id": staff_id,
        "staff_code": staff_code,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "hours_worked": hours.quantize(TWOPLACES),
        "days_attended": days_attended,
        "days_missed": days_missed,
        "days_excused": days_excused,
        "late_arrivals": late_arrivals,
        "weekly_target_hours": WEEKLY_TARGET,
        "summary_computed_at": computed_at,
    }


async def upsert_weekly_summary(conn: asyncpg.Connection, summary: dict[str, Any]) -> UUID:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.weekly_summary (
            staff_id, staff_code, week_start_date, week_end_date,
            hours_worked, days_attended, days_missed, days_excused,
            late_arrivals, weekly_target_hours, summary_computed_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (staff_code, week_start_date) DO UPDATE SET
            staff_id = EXCLUDED.staff_id,
            week_end_date = EXCLUDED.week_end_date,
            hours_worked = EXCLUDED.hours_worked,
            days_attended = EXCLUDED.days_attended,
            days_missed = EXCLUDED.days_missed,
            days_excused = EXCLUDED.days_excused,
            late_arrivals = EXCLUDED.late_arrivals,
            weekly_target_hours = EXCLUDED.weekly_target_hours,
            summary_computed_at = EXCLUDED.summary_computed_at
        RETURNING id
        """,
        summary["staff_id"],
        summary["staff_code"],
        summary["week_start_date"],
        summary["week_end_date"],
        summary["hours_worked"],
        summary["days_attended"],
        summary["days_missed"],
        summary["days_excused"],
        summary["late_arrivals"],
        summary["weekly_target_hours"],
        summary["summary_computed_at"],
    )
    assert row is not None
    return row["id"]


async def rollup_week(
    conn: asyncpg.Connection,
    *,
    week_start: date,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Idempotent rollup for all active staff for one week."""
    settings = get_settings()
    staff_rows = await conn.fetch(
        f"""
        SELECT id, staff_code FROM {settings.db_schema}.staff WHERE is_active = TRUE
        """
    )
    count = 0
    for s in staff_rows:
        summary = await compute_staff_week(
            conn, staff_id=s["id"], staff_code=s["staff_code"], week_start=week_start
        )
        await upsert_weekly_summary(conn, summary)
        count += 1

    result = {"week_start_date": week_start.isoformat(), "staff_rolled_up": count}
    await write_audit_log(
        conn,
        actor_type="system",
        action="weekly_rollup",
        table_name="weekly_summary",
        actor_id=actor_id,
        new_values=result,
    )
    return result


async def list_summaries(
    conn: asyncpg.Connection,
    *,
    week_start_date: date,
    staff_code: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if staff_code:
        rows = await conn.fetch(
            f"""
            SELECT staff_code, week_start_date, week_end_date, hours_worked,
                   days_attended, days_missed, days_excused, late_arrivals,
                   weekly_target_hours, summary_computed_at
            FROM {settings.db_schema}.weekly_summary
            WHERE week_start_date = $1 AND staff_code = $2
            """,
            week_start_date,
            staff_code.upper(),
        )
    else:
        rows = await conn.fetch(
            f"""
            SELECT staff_code, week_start_date, week_end_date, hours_worked,
                   days_attended, days_missed, days_excused, late_arrivals,
                   weekly_target_hours, summary_computed_at
            FROM {settings.db_schema}.weekly_summary
            WHERE week_start_date = $1
            ORDER BY staff_code
            """,
            week_start_date,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "staff_code": r["staff_code"],
                "week_start_date": r["week_start_date"].isoformat(),
                "week_end_date": r["week_end_date"].isoformat(),
                "hours_worked": float(r["hours_worked"]),
                "days_attended": r["days_attended"],
                "days_missed": r["days_missed"],
                "days_excused": r["days_excused"],
                "late_arrivals": r["late_arrivals"],
                "weekly_target_hours": float(r["weekly_target_hours"] or 40),
                "summary_computed_at": r["summary_computed_at"].isoformat(),
            }
        )
    return out
