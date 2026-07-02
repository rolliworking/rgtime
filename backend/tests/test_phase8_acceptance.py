"""Phase 8 acceptance — weekly rollup + RS weekly-summary endpoint."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import asyncpg
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.rs_auth import require_rs_auth
from app.services.weekly_rollup import list_summaries, monday_on_or_before, rollup_week


@pytest.mark.asyncio
async def test_rollup_idempotent_and_contract_shape():
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

    week_start = monday_on_or_before(date(2025, 1, 15))
    try:
        r1 = await rollup_week(conn, week_start=week_start)
        r2 = await rollup_week(conn, week_start=week_start)
        assert r1["staff_rolled_up"] == r2["staff_rolled_up"]
        assert r1["staff_rolled_up"] >= 1

        summaries = await list_summaries(conn, week_start_date=week_start)
        assert summaries
        s = summaries[0]
        for key in (
            "staff_code",
            "week_start_date",
            "week_end_date",
            "hours_worked",
            "days_attended",
            "days_missed",
            "days_excused",
            "late_arrivals",
            "weekly_target_hours",
            "summary_computed_at",
        ):
            assert key in s
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_weekly_summary_auth_fail_closed():
    from app.config import Settings

    with patch("app.rs_auth.get_settings") as mock_gs:
        mock_gs.return_value = Settings(rgtime_to_rs_token="")
        with pytest.raises(HTTPException) as exc:
            await require_rs_auth(credentials=None)
        assert exc.value.status_code == 503

    with patch("app.rs_auth.get_settings") as mock_gs:
        mock_gs.return_value = Settings(ROLLICLOCK_TO_RS_TOKEN="secret")
        with pytest.raises(HTTPException) as exc:
            await require_rs_auth(credentials=None)
        assert exc.value.status_code == 401

        class Creds:
            credentials = "wrong"

        with pytest.raises(HTTPException) as exc:
            await require_rs_auth(credentials=Creds())
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_weekly_summary_endpoint_with_db():
    from app.config import get_settings
    from app.database import create_app

    settings = get_settings()
    token = settings.rgtime_to_rs_token or "test-token-phase8"
    if not settings.rgtime_to_rs_token:
        import os

        os.environ["ROLLICLOCK_TO_RS_TOKEN"] = token
        get_settings.cache_clear()

    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
        await conn.close()
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    app = create_app()
    week = "2025-01-06"
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r200 = await client.get(
                f"/api/v1/weekly-summary?week_start_date={week}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r200.status_code == 200
            body = r200.json()
            assert "summaries" in body
            if body["summaries"]:
                s = body["summaries"][0]
                assert "staff_code" in s and "hours_worked" in s
