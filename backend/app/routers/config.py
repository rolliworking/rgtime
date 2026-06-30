"""Config endpoints — demonstrates audit_log wiring on mutations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.audit import write_audit_log
from app.config import get_settings
from app.dependencies import DbConn, get_actor_type
from fastapi import Depends, Request

router = APIRouter(prefix="/config", tags=["config"])


class ConfigUpdate(BaseModel):
    value: Any
    actor_id: UUID | None = None


class ConfigEntry(BaseModel):
    key: str
    value: Any
    description: str | None = None


@router.get("", response_model=list[ConfigEntry])
async def list_config(conn: DbConn) -> list[ConfigEntry]:
    settings = get_settings()
    rows = await conn.fetch(
        f"SELECT key, value, description FROM {settings.db_schema}.config ORDER BY key"
    )
    return [
        ConfigEntry(key=r["key"], value=r["value"], description=r["description"]) for r in rows
    ]


@router.put("/{key}", response_model=ConfigEntry)
async def update_config(
    key: str,
    body: ConfigUpdate,
    conn: DbConn,
    request: Request,
    actor_type: str = Depends(get_actor_type),
) -> ConfigEntry:
    settings = get_settings()
    existing = await conn.fetchrow(
        f"SELECT key, value, description FROM {settings.db_schema}.config WHERE key = $1",
        key,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Config key not found: {key}")

    old_values = {"key": existing["key"], "value": existing["value"]}

    row = await conn.fetchrow(
        f"""
        UPDATE {settings.db_schema}.config
        SET value = $2::jsonb, updated_by = $3, updated_at = now()
        WHERE key = $1
        RETURNING key, value, description
        """,
        key,
        body.value,
        body.actor_id,
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Config update failed")

    await write_audit_log(
        conn,
        actor_type=actor_type,
        action="update",
        table_name="config",
        record_id=None,
        actor_id=body.actor_id,
        old_values=old_values,
        new_values={"key": row["key"], "value": row["value"]},
    )

    return ConfigEntry(key=row["key"], value=row["value"], description=row["description"])
