"""Phase 7 acceptance — PDF pay-period report."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.pay_period import PayPeriod
from app.services.pay_period_report import build_pay_period_report, staff_time_card
from app.services.pdf_report import render_pay_period_pdf, render_time_card_pdf


PERIOD = PayPeriod(date(2025, 1, 6), date(2025, 1, 19))


@pytest.mark.asyncio
async def test_pdf_report_two_tables_and_timecard():
    from app.config import get_settings

    import asyncpg

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    try:
        report = await build_pay_period_report(conn, PERIOD)
        assert "clean" in report and "flagged" in report
        assert isinstance(report["flagged"], list)
        assert isinstance(report["clean"], list)

        pdf = render_pay_period_pdf(report)
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 500

        if report["flagged"]:
            sid = report["flagged"][0]["staff_id"]
            from uuid import UUID

            card = await staff_time_card(conn, staff_id=UUID(sid), period=PERIOD)
            assert card["days"]
            tc_pdf = render_time_card_pdf(card["summary"], card["days"])
            assert tc_pdf[:4] == b"%PDF"
    finally:
        await conn.close()
