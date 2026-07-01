"""Unit tests for PTO accrual engine — Phase 4 acceptance scenarios."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest

from app.pto_rates import QUALIFYING_HOURS_THRESHOLD
from app.services.pto_accrual import (
    accrual_for_day,
    accrue_for_date_range,
    forfeit_balance,
    get_day_accrual_input,
)

HIRE = date(2020, 1, 15)


class TestAccrualPureMath:
    def test_yr0_tier_earns_zero(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2020, 6, 1),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r.tenure_years == 0
        assert r.rate == Decimal("0.000")
        assert r.accrual_hours == Decimal("0.000")

    def test_yr1_tier_boundary(self):
        # Day before anniversary: still yr 0
        r0 = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2021, 1, 14),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r0.tenure_years == 0
        assert r0.accrual_hours == Decimal("0.000")

        # On anniversary: yr 1
        r1 = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2021, 1, 15),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r1.tenure_years == 1
        assert r1.rate == Decimal("0.031")
        assert r1.accrual_hours == Decimal("0.031")

    def test_7_5_hr_day_earns_zero(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2022, 3, 1),
            hours_worked=Decimal("7.5"),
            counts_as_worked=True,
        )
        assert r.qualifying is False
        assert r.accrual_hours == Decimal("0.000")

    def test_8_0_hr_day_earns_exact_tier_rate(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2022, 3, 1),  # tenure 2 → 0.062
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r.tenure_years == 2
        assert r.accrual_hours == Decimal("0.062")

    def test_anniversary_mid_period_bumps_rate(self):
        before = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2023, 1, 14),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        after = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2023, 1, 15),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert before.tenure_years == 2
        assert before.accrual_hours == Decimal("0.062")
        assert after.tenure_years == 3
        assert after.accrual_hours == Decimal("0.092")

    def test_overtime_10hr_earns_only_one_day(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2024, 6, 1),  # tenure 4 → 0.123
            hours_worked=Decimal("10.0"),
            counts_as_worked=True,
        )
        assert r.accrual_hours == Decimal("0.123")

    def test_non_counts_as_worked_earns_zero_even_at_8hrs(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2024, 6, 1),
            hours_worked=Decimal("8.0"),
            counts_as_worked=False,
        )
        assert r.accrual_hours == Decimal("0.000")

    def test_remote_day_reported_hours_gte_8_accrues(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2025, 6, 1),  # tenure 5 → 0.154
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r.accrual_hours == Decimal("0.154")

    def test_remote_day_reported_hours_lt_8_no_accrual(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2025, 6, 1),
            hours_worked=Decimal("7.99"),
            counts_as_worked=True,
        )
        assert r.accrual_hours == Decimal("0.000")

    def test_qualifying_threshold_is_8(self):
        assert QUALIFYING_HOURS_THRESHOLD == Decimal("8.0")


@pytest.mark.asyncio
async def test_termination_zeroes_balance():
    from app.config import get_settings

    settings = get_settings()
    dsn = settings.database_url
    try:
        conn = await asyncpg.connect(dsn, timeout=5, server_settings={"search_path": "rgtime,public"})
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    staff_id = uuid.uuid4()
    code = f"P4{uuid.uuid4().hex[:6].upper()}"
    try:
        await conn.execute(
            """
            INSERT INTO rgtime.staff (
                id, staff_code, first_name, last_name, hire_date, pto_balance
            )
            VALUES ($1, $2, 'PTO', 'Test', '2020-01-15', 5.50)
            """,
            staff_id,
            code,
        )
        forfeited = await forfeit_balance(conn, staff_id=staff_id)
        assert forfeited == Decimal("5.50")
        bal = await conn.fetchval("SELECT pto_balance FROM rgtime.staff WHERE id = $1", staff_id)
        assert Decimal(str(bal)) == Decimal("0")
        entry = await conn.fetchrow(
            """
            SELECT entry_type, balance_after FROM rgtime.pto_ledger
            WHERE staff_id = $1 ORDER BY created_at DESC LIMIT 1
            """,
            staff_id,
        )
        assert entry["entry_type"] == "forfeiture"
        assert Decimal(str(entry["balance_after"])) == Decimal("0")
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", staff_id)
        await conn.close()


@pytest.mark.asyncio
async def test_remote_absence_uses_reported_hours():
    from app.config import get_settings

    settings = get_settings()
    dsn = settings.database_url
    try:
        conn = await asyncpg.connect(dsn, timeout=5, server_settings={"search_path": "rgtime,public"})
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    staff_id = uuid.uuid4()
    code = f"P4R{uuid.uuid4().hex[:6].upper()}"
    work_date = date(2025, 3, 10)
    try:
        await conn.execute(
            """
            INSERT INTO rgtime.staff (id, staff_code, first_name, last_name, hire_date)
            VALUES ($1, $2, 'Remote', 'Worker', '2020-01-15')
            """,
            staff_id,
            code,
        )
        reason_id = await conn.fetchval(
            "SELECT id FROM rgtime.absence_reasons WHERE name = 'Working remotely'"
        )
        await conn.execute(
            """
            INSERT INTO rgtime.absences (staff_id, absence_date, reason_id, reported_hours)
            VALUES ($1, $2, $3, 8.5)
            """,
            staff_id,
            work_date,
            reason_id,
        )
        inp = await get_day_accrual_input(conn, staff_id, work_date)
        assert inp.hours_worked == Decimal("8.50")
        assert inp.counts_as_worked is True

        inp_low = await get_day_accrual_input(conn, staff_id, date(2025, 3, 11))
        await conn.execute(
            """
            INSERT INTO rgtime.absences (staff_id, absence_date, reason_id, reported_hours)
            VALUES ($1, $2, $3, 6.0)
            """,
            staff_id,
            date(2025, 3, 11),
            reason_id,
        )
        inp_low = await get_day_accrual_input(conn, staff_id, date(2025, 3, 11))
        assert inp_low.hours_worked == Decimal("6.00")
        r = accrual_for_day(
            hire_date=date(2020, 1, 15),
            work_date=date(2025, 3, 11),
            hours_worked=inp_low.hours_worked,
            counts_as_worked=inp_low.counts_as_worked,
        )
        assert r.accrual_hours == Decimal("0.000")
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", staff_id)
        await conn.close()
