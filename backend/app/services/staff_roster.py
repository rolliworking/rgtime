"""Staff roster export for consumer apps — RG Time is authoritative staff source."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.staff_names import format_display_name


def _roster_entry(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "staff_code": row["staff_code"],
        "first_name": row["first_name"],
        "middle_name": row.get("middle_name"),
        "last_name": row["last_name"],
        "display_name": format_display_name(
            row["first_name"],
            row["last_name"],
            middle_name=row.get("middle_name"),
        ),
        "role": row.get("role"),
        "active": row["is_active"],
        "hire_date": row["hire_date"].isoformat() if row.get("hire_date") else None,
    }


async def list_active_roster(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT staff_code, first_name, middle_name, last_name, hire_date, is_active,
               NULL::TEXT AS role
        FROM {settings.db_schema}.staff
        WHERE is_active = TRUE
        ORDER BY staff_code
        """
    )
    return [_roster_entry(r) for r in rows]


async def get_roster_member(
    conn: asyncpg.Connection,
    staff_code: str,
) -> dict[str, Any] | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT staff_code, first_name, middle_name, last_name, hire_date, is_active,
               NULL::TEXT AS role
        FROM {settings.db_schema}.staff
        WHERE staff_code = $1
        """,
        staff_code.upper(),
    )
    return _roster_entry(row) if row else None
