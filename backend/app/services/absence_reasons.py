"""Editable absence reason library."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.absence_funding import FUNDING_VALUES
from app.audit import write_audit_log
from app.config import get_settings


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    return d


async def list_reasons(conn: asyncpg.Connection, *, active_only: bool = True) -> list[dict]:
    settings = get_settings()
    where = "WHERE is_active = TRUE" if active_only else ""
    rows = await conn.fetch(
        f"SELECT * FROM {settings.db_schema}.absence_reasons {where} ORDER BY name"
    )
    return [_row_to_dict(r) for r in rows]


async def create_reason(
    conn: asyncpg.Connection,
    *,
    name: str,
    funding: str,
    counts_as_worked: bool,
    actor_id: UUID | None = None,
) -> dict:
    if funding not in FUNDING_VALUES:
        raise ValueError(f"funding must be one of {sorted(FUNDING_VALUES)}")
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.absence_reasons (name, funding, counts_as_worked)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        name.strip(),
        funding,
        counts_as_worked,
    )
    if row is None:
        raise RuntimeError("reason insert failed")
    result = _row_to_dict(row)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="create",
        table_name="absence_reasons",
        record_id=row["id"],
        actor_id=actor_id,
        new_values=result,
    )
    return result


async def update_reason(
    conn: asyncpg.Connection,
    *,
    reason_id: UUID,
    name: str | None = None,
    funding: str | None = None,
    counts_as_worked: bool | None = None,
    is_active: bool | None = None,
    actor_id: UUID | None = None,
) -> dict | None:
    settings = get_settings()
    old_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.absence_reasons WHERE id = $1",
        reason_id,
    )
    if old_row is None:
        return None
    old = _row_to_dict(old_row)

    if funding is not None and funding not in VALID_FUNDING_VALUES:
        raise ValueError(f"funding must be one of {VALID_FUNDING_VALUES}")

    updates: list[str] = []
    params: list[Any] = [reason_id]
    idx = 2
    if name is not None:
        updates.append(f"name = ${idx}")
        params.append(name.strip())
        idx += 1
    if funding is not None:
        updates.append(f"funding = ${idx}")
        params.append(funding)
        idx += 1
    if counts_as_worked is not None:
        updates.append(f"counts_as_worked = ${idx}")
        params.append(counts_as_worked)
        idx += 1
    if is_active is not None:
        updates.append(f"is_active = ${idx}")
        params.append(is_active)
        idx += 1

    if updates:
        await conn.execute(
            f"UPDATE {settings.db_schema}.absence_reasons SET {', '.join(updates)} WHERE id = $1",
            *params,
        )

    new_row = await conn.fetchrow(
        f"SELECT * FROM {settings.db_schema}.absence_reasons WHERE id = $1",
        reason_id,
    )
    new = _row_to_dict(new_row) if new_row else old
    await write_audit_log(
        conn,
        actor_type="admin",
        action="update",
        table_name="absence_reasons",
        record_id=reason_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new
