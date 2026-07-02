"""Phase 4.5 acceptance — PTO offer flexibility, ladder, staff identity."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import asyncpg
import pytest

from app.pto_rates import (
    EXPECTED_WORKDAYS_PER_YEAR,
    PtoOffer,
    derive_daily_rate_from_annual,
    resolve_pto_rate,
)
from app.services.offer_templates import create_template, template_to_offer
from app.services.pto_accrual import accrual_for_day
from app.services.pto_ladder import get_ladder_for_work_date, upsert_ladder_tier
from app.services.staff import set_pto_offer, suggest_staff_code

HIRE = date(2020, 1, 15)
TODAY = date(2025, 7, 1)


class TestDefaultOfferRegression:
    """Default staff member accrues exactly as Phase 4."""

    def test_yr1_rate_unchanged(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2021, 1, 15),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=PtoOffer(),
        )
        assert r.rate == Decimal("0.031")
        assert r.accrual_hours == Decimal("0.031")

    def test_yr2_rate_unchanged(self):
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=date(2022, 3, 1),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
        )
        assert r.accrual_hours == Decimal("0.062")


class TestTenureCreditOffer:
    def test_hire_today_plus_3_credit_accrues_yr3_rate(self):
        hire = TODAY
        offer = PtoOffer(offer_type="tenure_credit", tenure_credit_years=3)
        r = accrual_for_day(
            hire_date=hire,
            work_date=TODAY,
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=offer,
        )
        assert r.tenure_years == 0
        assert r.rate == Decimal("0.092")
        assert r.accrual_hours == Decimal("0.092")

    def test_anniversary_advances_tier_with_credit(self):
        hire = TODAY - timedelta(days=365)
        offer = PtoOffer(offer_type="tenure_credit", tenure_credit_years=3)
        before = accrual_for_day(
            hire_date=hire,
            work_date=hire.replace(year=hire.year + 1) - timedelta(days=1),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=offer,
        )
        on_day = accrual_for_day(
            hire_date=hire,
            work_date=hire.replace(year=hire.year + 1),
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=offer,
        )
        assert before.rate == Decimal("0.092")  # effective tenure 3
        assert on_day.tenure_years == 1
        assert on_day.rate == Decimal("0.123")  # effective tenure 4


class TestCustomRateOffer:
    def test_80_annual_hours_derived_daily_rate(self):
        annual = Decimal("80")
        expected_rate = derive_daily_rate_from_annual(annual)
        assert expected_rate == (Decimal("80") / Decimal(EXPECTED_WORKDAYS_PER_YEAR)).quantize(
            Decimal("0.001")
        )

        offer = PtoOffer(offer_type="custom_rate", custom_annual_hours=annual)
        rate, _ = resolve_pto_rate(hire_date=HIRE, work_date=TODAY, offer=offer)
        assert rate == expected_rate

        r = accrual_for_day(
            hire_date=HIRE,
            work_date=TODAY,
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=offer,
        )
        assert r.rate == expected_rate
        assert r.accrual_hours == expected_rate

    def test_explicit_daily_rate(self):
        offer = PtoOffer(offer_type="custom_rate", custom_daily_rate=Decimal("0.200"))
        r = accrual_for_day(
            hire_date=HIRE,
            work_date=TODAY,
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=offer,
        )
        assert r.accrual_hours == Decimal("0.200")


class TestStaffCodeSuggestion:
    @pytest.mark.asyncio
    async def test_vianna_suggestion_and_collision(self):
        from app.config import get_settings

        settings = get_settings()
        try:
            conn = await asyncpg.connect(
                dsn=settings.database_url,
                timeout=5,
                server_settings={"search_path": "rgtime,public"},
            )
        except Exception:
            pytest.skip("DATABASE_URL not reachable")

        code1 = await suggest_staff_code(conn, first_name="Vianna", last_name="Reyes")
        assert code1 == "VR"

        staff_id = uuid.uuid4()
        try:
            await conn.execute(
                """
                INSERT INTO rgtime.staff (id, staff_code, first_name, last_name, hire_date)
                VALUES ($1, 'VR', 'Existing', 'Staff', '2020-01-01')
                """,
                staff_id,
            )
            code2 = await suggest_staff_code(conn, first_name="Vianna", last_name="Reyes")
            assert code2 == "VR2"
        finally:
            await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", staff_id)
            await conn.close()


@pytest.mark.asyncio
async def test_template_matches_manual_offer():
    from app.config import get_settings

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    tpl_name = f"Senior-{uuid.uuid4().hex[:8]}"
    try:
        tpl = await create_template(
            conn,
            name=tpl_name,
            offer_type="tenure_credit",
            tenure_credit_years=3,
        )
        manual = PtoOffer(offer_type="tenure_credit", tenure_credit_years=3)
        from_tpl = template_to_offer(tpl)

        hire = TODAY
        manual_r = accrual_for_day(
            hire_date=hire,
            work_date=TODAY,
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=manual,
        )
        tpl_r = accrual_for_day(
            hire_date=hire,
            work_date=TODAY,
            hours_worked=Decimal("8.0"),
            counts_as_worked=True,
            offer=from_tpl,
        )
        assert manual_r.accrual_hours == tpl_r.accrual_hours
    finally:
        await conn.execute("DELETE FROM rgtime.offer_templates WHERE name = $1", tpl_name)
        await conn.close()


@pytest.mark.asyncio
async def test_ladder_effective_dating():
    from app.config import get_settings

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    future = date(2099, 1, 1)
    past = date(2024, 6, 1)
    try:
        before_ladder = await get_ladder_for_work_date(conn, past)
        before_rate = resolve_pto_rate(
            hire_date=HIRE,
            work_date=past,
            offer=PtoOffer(),
            ladder=before_ladder,
        )[0]

        await upsert_ladder_tier(
            conn,
            min_years=5,
            max_years=None,
            tier_label="Yr 5+",
            annual_pto_hours=260,
            rate_per_qualifying_day=Decimal("0.999"),
            effective_from=future,
            confirmed=True,
        )

        past_ladder = await get_ladder_for_work_date(conn, past)
        past_rate = resolve_pto_rate(
            hire_date=HIRE,
            work_date=past,
            offer=PtoOffer(),
            ladder=past_ladder,
        )[0]
        assert past_rate == before_rate

        future_work = date(2099, 6, 1)  # tenure 79 → Yr 5+ tier
        future_ladder = await get_ladder_for_work_date(conn, future_work)
        future_rate = resolve_pto_rate(
            hire_date=HIRE,
            work_date=future_work,
            offer=PtoOffer(),
            ladder=future_ladder,
        )[0]
        assert future_rate == Decimal("0.999")
    finally:
        await conn.execute(
            "DELETE FROM rgtime.pto_ladder_rates WHERE effective_from = $1", future
        )
        await conn.close()


@pytest.mark.asyncio
async def test_offer_and_ladder_audit_logged():
    from app.config import get_settings

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    staff_id = uuid.uuid4()
    code = f"P45{uuid.uuid4().hex[:6].upper()}"
    future = date(2098, 6, 1)
    try:
        await conn.execute(
            """
            INSERT INTO rgtime.staff (id, staff_code, first_name, last_name, hire_date)
            VALUES ($1, $2, 'Audit', 'Test', '2020-01-15')
            """,
            staff_id,
            code,
        )
        await set_pto_offer(
            conn,
            staff_id=staff_id,
            pto_offer_type="custom_rate",
            pto_custom_annual_hours=Decimal("80"),
        )
        offer_audit = await conn.fetchval(
            """
            SELECT COUNT(*) FROM rgtime.audit_log
            WHERE table_name = 'staff' AND action = 'set_pto_offer' AND record_id = $1
            """,
            staff_id,
        )
        assert offer_audit >= 1

        await upsert_ladder_tier(
            conn,
            min_years=2,
            max_years=3,
            tier_label="Yr 2-3",
            annual_pto_hours=20,
            rate_per_qualifying_day=Decimal("0.077"),
            effective_from=future,
            confirmed=True,
        )
        ladder_audit = await conn.fetchval(
            """
            SELECT COUNT(*) FROM rgtime.audit_log
            WHERE table_name = 'pto_ladder_rates' AND action = 'update_ladder'
            """,
        )
        assert ladder_audit >= 1
    finally:
        await conn.execute(
            "DELETE FROM rgtime.pto_ladder_rates WHERE effective_from = $1", future
        )
        await conn.execute("DELETE FROM rgtime.audit_log WHERE record_id = $1", staff_id)
        await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", staff_id)
        await conn.close()


def test_fk_staff_id_compliance():
    """Phase 0 FKs reference staff.id UUID — already compliant."""
    import pathlib

    schema = (
        pathlib.Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20250630000000_rgtime_schema.sql"
    )
    text = schema.read_text(encoding="utf-8")
    for table in ("time_events", "absences", "punch_photos", "weekly_summary", "pto_ledger"):
        assert f"{table}" in text
        assert "staff_id UUID NOT NULL REFERENCES rgtime.staff (id)" in text.replace("\n", " ")
