"""Phase 6 acceptance — planned-absence calendar."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import asyncpg
import pytest

from app.services.absences import list_absences_in_range, list_upcoming_for_staff


@pytest.mark.asyncio
async def test_future_vacation_on_calendar_and_upcoming():
    from app.config import get_settings
    from app.services.absences import upsert_absence

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
    code = f"CAL{uuid.uuid4().hex[:5].upper()}"
    future = date.today() + timedelta(days=14)
    month_end = date(future.year, future.month, 28) + timedelta(days=4)
    month_end = month_end - timedelta(days=month_end.day)

    try:
        await conn.execute(
            """
            INSERT INTO rgtime.staff (id, staff_code, first_name, last_name, hire_date)
            VALUES ($1, $2, 'Calendar', 'Test', '2020-01-01')
            """,
            staff_id,
            code,
        )
        vacation_id = await conn.fetchval(
            "SELECT id FROM rgtime.absence_reasons WHERE name = 'Vacation'"
        )
        await upsert_absence(
            conn,
            staff_id=staff_id,
            absence_date=future,
            reason_id=vacation_id,
            notes="Planned PTO",
        )

        month_start = date(future.year, future.month, 1)
        cal = await list_absences_in_range(conn, start_date=month_start, end_date=month_end)
        on_cal = [a for a in cal if a["staff_id"] == str(staff_id) and a["absence_date"] == future.isoformat()]
        assert len(on_cal) == 1
        assert on_cal[0]["reason_name"] == "Vacation"

        upcoming = await list_upcoming_for_staff(conn, staff_id=staff_id)
        assert any(u["absence_date"] == future.isoformat() for u in upcoming)
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", staff_id)
        await conn.close()
