"""Staff code initials scheme + middle_name acceptance."""

from __future__ import annotations

import uuid
from datetime import date

import asyncpg
import pytest

from app.services.staff import create_staff, get_staff, suggest_staff_code, update_staff
from app.staff_names import format_display_name, suggest_staff_code_sync


class TestStaffCodeLogic:
    def test_michael_hui_suggests_mh(self):
        assert suggest_staff_code_sync("Michael", "Hui") == "MH"

    def test_second_mh_with_middle_suggests_mjh(self):
        assert (
            suggest_staff_code_sync(
                "Michael",
                "Hui",
                middle_name="James",
                code_exists={"MH"},
            )
            == "MJH"
        )

    def test_third_mh_collision_without_middle_suggests_mh2(self):
        assert (
            suggest_staff_code_sync(
                "Michael",
                "Hui",
                code_exists={"MH", "MJH"},
            )
            == "MH2"
        )

    def test_mjh_collision_suggests_mjh2(self):
        assert (
            suggest_staff_code_sync(
                "Michael",
                "Hui",
                middle_name="James",
                code_exists={"MH", "MJH"},
            )
            == "MJH2"
        )

    def test_display_name_formats(self):
        assert (
            format_display_name("Michael", "Hui", middle_name="James")
            == "Michael James Hui"
        )
        assert (
            format_display_name("Michael", "Hui", middle_name="James", short_middle=True)
            == "Michael J. Hui"
        )


@pytest.mark.asyncio
async def test_suggest_respects_terminated_staff_codes():
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

    term_id = uuid.uuid4()
    try:
        await conn.execute(
            "DELETE FROM rgtime.staff WHERE staff_code = 'MH' AND first_name = 'Old' AND last_name = 'Hui'"
        )
        await conn.execute(
            """
            INSERT INTO rgtime.staff (
                id, staff_code, first_name, last_name, hire_date, is_active, terminated_at
            )
            VALUES ($1, 'MH', 'Old', 'Hui', '2019-01-01', FALSE, now())
            """,
            term_id,
        )

        suggested = await suggest_staff_code(conn, first_name="Michael", last_name="Hui")
        assert suggested == "MH2"
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", term_id)
        await conn.close()


@pytest.mark.asyncio
async def test_middle_name_persists_and_immutable_staff_code():
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
    code = f"TST{uuid.uuid4().hex[:4].upper()}"
    created_id: uuid.UUID | None = None
    try:
        created = await create_staff(
            conn,
            staff_code=code,
            first_name="Michael",
            middle_name="James",
            last_name="Hui",
            hire_date=date(2024, 1, 1),
        )
        created_id = uuid.UUID(created["id"])
        assert created["middle_name"] == "James"
        assert created["display_name"] == "Michael James Hui"
        assert created["staff_code"] == code

        updated = await update_staff(
            conn,
            staff_id=created_id,
            middle_name="Joseph",
            update_middle_name=True,
        )
        assert updated is not None
        assert updated["middle_name"] == "Joseph"
        assert updated["staff_code"] == code

        row = await get_staff(conn, created_id)
        assert row is not None
        assert row["display_name_short"] == "Michael J. Hui"
    finally:
        if created_id is not None:
            await conn.execute("DELETE FROM rgtime.audit_log WHERE record_id = $1", created_id)
            await conn.execute("DELETE FROM rgtime.staff WHERE id = $1", created_id)
        await conn.close()
