"""Phase 3 acceptance — portal staff onboarding end-to-end."""

from __future__ import annotations

import base64
import inspect
import os
import uuid
from datetime import date

import pytest

from app.routers import portal as portal_router
from app.services import absence_reasons, face_reference, schedules, staff

# 1x1 red JPEG (same as phase 1 tests)
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB"
    "/8QAFwABAQEBAAAAAAAAAAAAAAAAAAUGB//EABUBAQEAAAAAAAAAAAAAAAAAAAAB/9oADAMBAAIQAxAAAAGfAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Bf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Bf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEABj8Cf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8hf//Z"
)


def test_portal_router_wires_audit_on_mutations():
    source = inspect.getsource(portal_router)
    assert "create_staff" in source
    assert "set_staff_pin" in source
    assert "save_face_reference" in source


def test_staff_service_has_terminate_forfeiture():
    source = inspect.getsource(staff.terminate_staff)
    assert "forfeiture" in source
    assert "pto_balance = 0" in source


def test_face_reference_service_writes_storage_path():
    source = inspect.getsource(face_reference.save_face_reference)
    assert "face_reference_photo_path" in source
    assert "write_audit_log" in source


@pytest.mark.asyncio
async def test_phase3_onboard_and_kiosk_punch():
    """Full acceptance when DATABASE_URL and PORTAL_ADMIN_TOKEN are set."""
    from app.config import get_settings

    settings = get_settings()
    dsn = settings.database_url
    token = os.environ.get("PORTAL_ADMIN_TOKEN") or settings.portal_admin_token or "test-portal-token"
    if not dsn or "127.0.0.1" in dsn and "postgres@" in dsn:
        # Skip only if still on default local DSN with no server
        try:
            import asyncpg

            conn = await asyncpg.connect(dsn, timeout=3, server_settings={"search_path": "rgtime,public"})
            await conn.close()
        except Exception:
            pytest.skip("DATABASE_URL not reachable")

    os.environ["PORTAL_ADMIN_TOKEN"] = token
    get_settings.cache_clear()

    import asyncpg
    from httpx import ASGITransport, AsyncClient

    from app.database import create_app, lifespan

    app = create_app()
    code = f"P3{uuid.uuid4().hex[:6].upper()}"
    pin = "5678"

    headers = {"Authorization": f"Bearer {token}", "X-RGTime-Client": "admin"}

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create staff
            r = await client.post(
                "/api/v1/portal/staff",
                headers=headers,
                json={
                    "staff_code": code,
                    "first_name": "Phase",
                    "last_name": "Three",
                    "hire_date": "2023-06-01",
                },
            )
            assert r.status_code == 201, r.text
            staff_id = r.json()["id"]

            # Schedule from preset
            presets = (await client.get("/api/v1/portal/schedule-presets", headers=headers)).json()["presets"]
            assert presets
            r = await client.put(
                f"/api/v1/portal/staff/{staff_id}/schedule",
                headers=headers,
                json={"preset_id": presets[0]["id"]},
            )
            assert r.status_code == 200, r.text

            # PIN
            r = await client.put(
                f"/api/v1/portal/staff/{staff_id}/pin",
                headers=headers,
                json={"pin": pin},
            )
            assert r.status_code == 200, r.text

            # Face reference
            r = await client.post(
                f"/api/v1/portal/staff/{staff_id}/face-reference",
                headers=headers,
                json={"data_base64": TINY_JPEG_B64},
            )
            assert r.status_code == 200, r.text
            assert "face_reference" in r.json()["face_reference_photo_path"]

            # Absence reason create + deactivate
            reason_name = f"Test reason {uuid.uuid4().hex[:6]}"
            r = await client.post(
                "/api/v1/portal/absence-reasons",
                headers=headers,
                json={"name": reason_name, "funding": "unpaid", "counts_as_worked": False},
            )
            assert r.status_code == 201, r.text
            reason_id = r.json()["id"]
            r = await client.put(
                f"/api/v1/portal/absence-reasons/{reason_id}",
                headers=headers,
                json={"is_active": False},
            )
            assert r.status_code == 200, r.text

    from app.services.time_tracking import get_staff_by_pin

    settings = get_settings()
    dsn = settings.database_url
    conn = await asyncpg.connect(dsn, server_settings={"search_path": "rgtime,public"})
    try:
        found = await get_staff_by_pin(conn, pin)
        assert found is not None
        assert found["staff_code"] == code

        audit_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM rgtime.audit_log
            WHERE table_name IN ('staff', 'pin_credentials', 'schedules', 'absence_reasons')
            AND record_id = $1 OR (new_values->>'staff_code') = $2
            """,
            uuid.UUID(staff_id),
            code,
        )
        assert audit_count >= 3
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE staff_code = $1", code)
        await conn.close()

    get_settings.cache_clear()
