"""Kiosk punch and photo storage."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from app.config import get_settings

STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "punch_photos"


async def save_punch_photos(
    conn: asyncpg.Connection,
    *,
    time_event_id: UUID,
    staff_id: UUID,
    photos: list[dict],
) -> int:
    """Persist up to 3 punch photos. Returns count saved."""
    settings = get_settings()
    saved = 0
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

    for photo in photos:
        seq = int(photo["sequence_number"])
        if seq < 1 or seq > 3:
            continue
        captured_at = datetime.fromisoformat(photo["captured_at"].replace("Z", "+00:00"))
        raw = photo.get("data_base64", "")
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception:
            continue

        staff_dir = STORAGE_ROOT / str(staff_id) / str(time_event_id)
        staff_dir.mkdir(parents=True, exist_ok=True)
        rel_path = f"punch_photos/{staff_id}/{time_event_id}/{seq}.jpg"
        abs_path = STORAGE_ROOT / str(staff_id) / str(time_event_id) / f"{seq}.jpg"
        abs_path.write_bytes(data)

        await conn.execute(
            f"""
            INSERT INTO {settings.db_schema}.punch_photos (
                time_event_id, staff_id, sequence_number, captured_at, storage_path
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (time_event_id, sequence_number) DO NOTHING
            """,
            time_event_id,
            staff_id,
            seq,
            captured_at,
            rel_path,
        )
        saved += 1
    return saved
