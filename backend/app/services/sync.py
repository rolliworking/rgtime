"""Offline punch sync — replay queued punches in timestamp order."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.pin import validate_pin_format
from app.services.photos import save_punch_photos
from app.services.time_tracking import (
    PunchResult,
    get_last_event,
    get_punch_by_client_local_id,
    get_staff_by_pin,
    next_event_type,
    record_punch,
)
from app.timezone_util import TZ


async def log_sync_failure(
    conn: asyncpg.Connection,
    *,
    client_local_id: str | None,
    staff_id: UUID | None,
    error_message: str,
    payload: dict[str, Any],
) -> UUID:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.sync_failures (
            client_local_id, staff_id, error_message, payload
        )
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        client_local_id,
        staff_id,
        error_message,
        json.dumps(payload),
    )
    assert row is not None
    return row["id"]


async def apply_queued_punch(
    conn: asyncpg.Connection,
    *,
    client_local_id: str,
    pin: str,
    occurred_at: datetime,
    photos: list[dict],
) -> tuple[PunchResult, int, bool]:
    """
    Apply one queued punch. Returns (result, photos_saved, was_duplicate).
    Raises on hard failure after logging sync_failure.
    """
    validate_pin_format(pin)
    existing = await get_punch_by_client_local_id(conn, client_local_id)
    if existing is not None:
        return existing, 0, True

    staff = await get_staff_by_pin(conn, pin)
    if staff is None:
        await log_sync_failure(
            conn,
            client_local_id=client_local_id,
            staff_id=None,
            error_message="Invalid PIN during offline sync",
            payload={"client_local_id": client_local_id, "occurred_at": occurred_at.isoformat()},
        )
        raise ValueError("Invalid PIN during offline sync")

    staff_id = staff["id"]
    display_name = f"{staff['first_name']} {staff['last_name']}"
    last = await get_last_event(conn, staff_id)
    event_type = next_event_type(last)

    try:
        result = await record_punch(
            conn,
            staff_id=staff_id,
            staff_name=display_name,
            event_type=event_type,
            occurred_at=occurred_at,
            client_local_id=client_local_id,
            mark_synced=True,
        )
        photos_saved = await save_punch_photos(
            conn,
            time_event_id=result.event_id,
            staff_id=staff_id,
            photos=photos,
        )
        return result, photos_saved, False
    except Exception as exc:
        await log_sync_failure(
            conn,
            client_local_id=client_local_id,
            staff_id=staff_id,
            error_message=str(exc),
            payload={
                "client_local_id": client_local_id,
                "occurred_at": occurred_at.isoformat(),
                "pin_last_two": pin[-2:],
            },
        )
        raise


async def sync_punch_batch(
    conn: asyncpg.Connection,
    punches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process punches in occurred_at order; idempotent on client_local_id."""
    ordered = sorted(punches, key=lambda p: p["occurred_at"])
    synced: list[str] = []
    duplicates: list[str] = []
    failures: list[dict[str, str]] = []

    for item in ordered:
        cid = item["client_local_id"]
        try:
            occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
            result, _photos, dup = await apply_queued_punch(
                conn,
                client_local_id=cid,
                pin=item["pin"],
                occurred_at=occurred,
                photos=item.get("photos", []),
            )
            if dup:
                duplicates.append(cid)
            else:
                synced.append(cid)
        except Exception as exc:
            failures.append({"client_local_id": cid, "error": str(exc)})

    return {
        "synced": synced,
        "duplicates": duplicates,
        "failures": failures,
        "failure_count": len(failures),
    }
