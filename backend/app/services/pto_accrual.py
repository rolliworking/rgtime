"""PTO accrual engine — locked rules §1.

Literal rate table by tenure tier; qualifying day = >=8.0 hrs on counts_as_worked days.
One day's accrual per calendar day max; overtime earns no extra.
Remote days use absences.reported_hours for the >=8hr test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.pto_rates import (
    QUALIFYING_HOURS_THRESHOLD,
    rate_for_tenure_years,
    tenure_years_on_date,
)
from app.services.time_tracking import get_day_events
from app.timezone_util import TZ

TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class DayAccrualInput:
    work_date: date
    hours_worked: Decimal
    counts_as_worked: bool


@dataclass(frozen=True)
class DayAccrualResult:
    work_date: date
    hours_worked: Decimal
    qualifying: bool
    tenure_years: int
    rate: Decimal
    accrual_hours: Decimal


def accrual_for_day(
    *,
    hire_date: date,
    work_date: date,
    hours_worked: Decimal,
    counts_as_worked: bool,
) -> DayAccrualResult:
    """Pure accrual math for one calendar day."""
    tenure = tenure_years_on_date(hire_date, work_date)
    rate = rate_for_tenure_years(tenure)
    qualifying = counts_as_worked and hours_worked >= QUALIFYING_HOURS_THRESHOLD
    accrual = rate if qualifying else Decimal("0.000")
    return DayAccrualResult(
        work_date=work_date,
        hours_worked=hours_worked,
        qualifying=qualifying,
        tenure_years=tenure,
        rate=rate,
        accrual_hours=accrual,
    )


def _minutes_between(start: datetime, end: datetime) -> int:
    delta = end.astimezone(TZ) - start.astimezone(TZ)
    return max(0, int(delta.total_seconds() // 60))


async def compute_punched_hours(
    conn: asyncpg.Connection,
    staff_id: UUID,
    work_date: date,
) -> Decimal:
    """Sum paired punch durations minus lunch deductions for a work_date."""
    settings = get_settings()
    events = await conn.fetch(
        f"""
        SELECT event_type, occurred_at, lunch_deducted_minutes
        FROM {settings.db_schema}.time_events
        WHERE staff_id = $1 AND work_date = $2
        ORDER BY occurred_at ASC, created_at ASC
        """,
        staff_id,
        work_date,
    )
    total_minutes = 0
    lunch_deduct = 0
    clock_in_at: datetime | None = None
    for ev in events:
        if ev["event_type"] == "clock_in":
            clock_in_at = ev["occurred_at"]
        elif ev["event_type"] in ("clock_out", "auto_clock_out") and clock_in_at is not None:
            total_minutes += _minutes_between(clock_in_at, ev["occurred_at"])
            lunch_deduct += int(ev["lunch_deducted_minutes"] or 0)
            clock_in_at = None
    net = max(0, total_minutes - lunch_deduct)
    return (Decimal(net) / Decimal(60)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


async def get_day_accrual_input(
    conn: asyncpg.Connection,
    staff_id: UUID,
    work_date: date,
) -> DayAccrualInput:
    """Resolve hours + counts_as_worked for a day (punches vs remote absence)."""
    settings = get_settings()
    absence = await conn.fetchrow(
        f"""
        SELECT a.reported_hours, r.counts_as_worked
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.staff_id = $1 AND a.absence_date = $2
        """,
        staff_id,
        work_date,
    )
    if absence is not None:
        if absence["counts_as_worked"]:
            hours = Decimal(str(absence["reported_hours"] or 0)).quantize(TWOPLACES)
            return DayAccrualInput(work_date, hours, True)
        return DayAccrualInput(work_date, Decimal("0"), False)

    punched = await compute_punched_hours(conn, staff_id, work_date)
    if punched > 0:
        return DayAccrualInput(work_date, punched, True)

    return DayAccrualInput(work_date, Decimal("0"), False)


async def get_current_balance(conn: asyncpg.Connection, staff_id: UUID) -> Decimal:
    settings = get_settings()
    row = await conn.fetchrow(
        f"SELECT pto_balance FROM {settings.db_schema}.staff WHERE id = $1",
        staff_id,
    )
    if row is None:
        return Decimal("0")
    return Decimal(str(row["pto_balance"])).quantize(TWOPLACES)


async def accrue_for_date_range(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    hire_date: date,
    start_date: date,
    end_date: date,
    actor_id: UUID | None = None,
    pay_period_start: date | None = None,
) -> list[DayAccrualResult]:
    """
    Accrue PTO for each day in [start_date, end_date] inclusive.
    Idempotent per day: skips days that already have an accrual ledger entry.
    """
    settings = get_settings()
    results: list[DayAccrualResult] = []
    balance = await get_current_balance(conn, staff_id)

    day = start_date
    while day <= end_date:
        existing = await conn.fetchval(
            f"""
            SELECT id FROM {settings.db_schema}.pto_ledger
            WHERE staff_id = $1 AND entry_type = 'accrual' AND work_date = $2
            """,
            staff_id,
            day,
        )
        if existing is None:
            inp = await get_day_accrual_input(conn, staff_id, day)
            result = accrual_for_day(
                hire_date=hire_date,
                work_date=day,
                hours_worked=inp.hours_worked,
                counts_as_worked=inp.counts_as_worked,
            )
            if result.accrual_hours > 0:
                balance = (balance + result.accrual_hours).quantize(TWOPLACES)
                await conn.execute(
                    f"""
                    INSERT INTO {settings.db_schema}.pto_ledger (
                        staff_id, entry_type, hours, balance_after, work_date,
                        pay_period_start, notes, created_by
                    )
                    VALUES ($1, 'accrual', $2, $3, $4, $5, $6, $7)
                    """,
                    staff_id,
                    result.accrual_hours,
                    balance,
                    day,
                    pay_period_start,
                    f"Qualifying day ({result.hours_worked}h, tier {result.tenure_years})",
                    actor_id,
                )
                await conn.execute(
                    f"""
                    UPDATE {settings.db_schema}.staff SET pto_balance = $2 WHERE id = $1
                    """,
                    staff_id,
                    balance,
                )
            results.append(result)
        day += timedelta(days=1)

    return results


async def forfeit_balance(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    actor_id: UUID | None = None,
    notes: str = "Termination forfeiture",
) -> Decimal:
    """Zero PTO balance with forfeiture ledger entry. Returns forfeited amount."""
    balance = await get_current_balance(conn, staff_id)
    if balance <= 0:
        return Decimal("0")

    settings = get_settings()
    await conn.execute(
        f"""
        INSERT INTO {settings.db_schema}.pto_ledger (
            staff_id, entry_type, hours, balance_after, notes, created_by
        )
        VALUES ($1, 'forfeiture', $2, 0, $3, $4)
        """,
        staff_id,
        balance,
        notes,
        actor_id,
    )
    await conn.execute(
        f"UPDATE {settings.db_schema}.staff SET pto_balance = 0 WHERE id = $1",
        staff_id,
    )
    await write_audit_log(
        conn,
        actor_type="admin",
        action="pto_forfeiture",
        table_name="pto_ledger",
        record_id=staff_id,
        actor_id=actor_id,
        old_values={"pto_balance": str(balance)},
        new_values={"pto_balance": "0"},
    )
    return balance
