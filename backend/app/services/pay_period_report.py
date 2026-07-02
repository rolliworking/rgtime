"""Pay-period report data aggregation for PDF and drill-down."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.pto_rates import QUALIFYING_HOURS_THRESHOLD
from app.services.biweekly_audit import _day_credit_hours, audit_staff_period, build_period_audit
from app.services.pay_period import PayPeriod, iter_dates, weeks_in_period
from app.services.timesheet import get_staff_timesheet

TWOPLACES = Decimal("0.01")


async def _pto_sum(
    conn: asyncpg.Connection,
    staff_id: UUID,
    period: PayPeriod,
    entry_type: str,
) -> Decimal:
    settings = get_settings()
    val = await conn.fetchval(
        f"""
        SELECT COALESCE(SUM(hours), 0)
        FROM {settings.db_schema}.pto_ledger
        WHERE staff_id = $1 AND entry_type = $2
          AND (
            (work_date BETWEEN $3 AND $4)
            OR (pay_period_start = $3)
          )
        """,
        staff_id,
        entry_type,
        period.start_date,
        period.end_date,
    )
    return Decimal(str(val)).quantize(TWOPLACES)


async def staff_period_row(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    period: PayPeriod,
) -> dict[str, Any]:
    settings = get_settings()
    staff = await conn.fetchrow(
        f"""
        SELECT id, staff_code, first_name, last_name, pto_balance
        FROM {settings.db_schema}.staff WHERE id = $1
        """,
        staff_id,
    )
    if staff is None:
        raise ValueError("staff not found")

    week1, week2 = weeks_in_period(period)
    w1 = Decimal("0")
    w2 = Decimal("0")
    days_worked = 0
    qualifying_days = 0
    total_hours = Decimal("0")

    for d in iter_dates(period.start_date, period.end_date):
        hrs = await _day_credit_hours(conn, staff_id, d)
        if hrs > 0:
            days_worked += 1
            total_hours += hrs
        if hrs >= QUALIFYING_HOURS_THRESHOLD:
            qualifying_days += 1
        if week1.start_date <= d <= week1.end_date:
            w1 += hrs
        else:
            w2 += hrs

    late = await conn.fetchval(
        f"""
        SELECT COUNT(*) FROM {settings.db_schema}.time_events
        WHERE staff_id = $1 AND work_date BETWEEN $2 AND $3
          AND is_late_arrival = TRUE
        """,
        staff_id,
        period.start_date,
        period.end_date,
    )

    abs_rows = await conn.fetch(
        f"""
        SELECT r.name, COUNT(*) AS cnt
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.staff_id = $1 AND a.absence_date BETWEEN $2 AND $3
        GROUP BY r.name
        ORDER BY r.name
        """,
        staff_id,
        period.start_date,
        period.end_date,
    )
    absences_by_reason = {r["name"]: r["cnt"] for r in abs_rows}

    pto_earned = await _pto_sum(conn, staff_id, period, "accrual")
    pto_used = await _pto_sum(conn, staff_id, period, "draw")
    audit = await audit_staff_period(conn, staff_id=staff_id, period=period)

    return {
        "staff_id": str(staff_id),
        "staff_code": staff["staff_code"],
        "name": f"{staff['first_name']} {staff['last_name']}",
        "days_worked": days_worked,
        "total_hours": str(total_hours.quantize(TWOPLACES)),
        "qualifying_days": qualifying_days,
        "pto_earned": str(pto_earned),
        "pto_used": str(pto_used),
        "pto_balance": str(Decimal(str(staff["pto_balance"])).quantize(TWOPLACES)),
        "absences_by_reason": absences_by_reason,
        "late_arrivals": int(late or 0),
        "week1_hours": str(w1.quantize(TWOPLACES)),
        "week2_hours": str(w2.quantize(TWOPLACES)),
        "bucket": "clean" if audit.is_clean else "flagged",
    }


async def build_pay_period_report(
    conn: asyncpg.Connection,
    period: PayPeriod,
) -> dict[str, Any]:
    audit = await build_period_audit(conn, period)
    clean_rows: list[dict[str, Any]] = []
    flagged_rows: list[dict[str, Any]] = []

    for entry in audit["clean"]:
        row = await staff_period_row(conn, staff_id=UUID(entry["staff_id"]), period=period)
        clean_rows.append(row)
    for entry in audit["flagged"]:
        row = await staff_period_row(conn, staff_id=UUID(entry["staff_id"]), period=period)
        flagged_rows.append(row)

    return {
        "pay_period_start": period.start_date.isoformat(),
        "pay_period_end": period.end_date.isoformat(),
        "clean": clean_rows,
        "flagged": flagged_rows,
    }


async def staff_time_card(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    period: PayPeriod,
) -> dict[str, Any]:
    row = await staff_period_row(conn, staff_id=staff_id, period=period)
    days = await get_staff_timesheet(
        conn, staff_id=staff_id, start_date=period.start_date, end_date=period.end_date
    )
    return {"summary": row, "days": days}
