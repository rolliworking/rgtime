"""Face reference photo storage — same JPEG format as punch photos."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings

STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "face_reference"


async def save_face_reference(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    data_base64: str,
    captured_at: datetime | None = None,
    actor_id: UUID | None = None,
) -> str:
    settings = get_settings()
    raw = data_base64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    data = base64.b64decode(raw, validate=True)

    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    rel_path = f"face_reference/{staff_id}.jpg"
    abs_path = STORAGE_ROOT / f"{staff_id}.jpg"
    abs_path.write_bytes(data)

    old_path = await conn.fetchval(
        f"SELECT face_reference_photo_path FROM {settings.db_schema}.staff WHERE id = $1",
        staff_id,
    )

    await conn.execute(
        f"""
        UPDATE {settings.db_schema}.staff
        SET face_reference_photo_path = $2
        WHERE id = $1
        """,
        staff_id,
        rel_path,
    )

    await write_audit_log(
        conn,
        actor_type="admin",
        action="set_face_reference",
        table_name="staff",
        record_id=staff_id,
        actor_id=actor_id,
        old_values={"face_reference_photo_path": old_path},
        new_values={
            "face_reference_photo_path": rel_path,
            "captured_at": (captured_at or datetime.now(timezone.utc)).isoformat(),
        },
    )
    return rel_path
