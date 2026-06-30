"""Audit log writer — every mutating endpoint must call write_audit_log."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings

ActorType = str  # 'admin' | 'system' | 'kiosk'


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


async def write_audit_log(
    conn: asyncpg.Connection,
    *,
    actor_type: ActorType,
    action: str,
    table_name: str,
    record_id: UUID | None = None,
    actor_id: UUID | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> UUID:
    """Insert an audit_log row and return its id. Loud failure on DB error."""
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.audit_log (
            actor_id, actor_type, action, table_name, record_id,
            old_values, new_values
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
        RETURNING id
        """,
        actor_id,
        actor_type,
        action,
        table_name,
        record_id,
        json.dumps(_json_safe(old_values)) if old_values is not None else None,
        json.dumps(_json_safe(new_values)) if new_values is not None else None,
    )
    if row is None:
        raise RuntimeError("audit_log insert failed — no row returned")
    return row["id"]


class AuditedMutation:
    """Mixin-style helper for routers performing create/update/delete."""

    @staticmethod
    async def log(
        conn: asyncpg.Connection,
        *,
        actor_type: ActorType,
        action: str,
        table_name: str,
        record_id: UUID | None = None,
        actor_id: UUID | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> UUID:
        return await write_audit_log(
            conn,
            actor_type=actor_type,
            action=action,
            table_name=table_name,
            record_id=record_id,
            actor_id=actor_id,
            old_values=old_values,
            new_values=new_values,
        )
