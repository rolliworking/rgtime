"""Staff CRUD, termination, and PIN management."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.pin import hash_pin, validate_pin_format
from app.pto_rates import PTO_ACCRUAL_TIERS, tenure_years_on_date

STAFF_CODE_PATTERN = re.compile(r"^[A-Z0-9]{1,16}$")


def validate_staff_code(code: str) -> str:
    upper = code.strip().upper()
    if not STAFF_CODE_PATTERN.match(upper):
        raise ValueError("staff_code must be 1–16 uppercase alphanumeric characters")
    return upper


def tenure_info(hire_date: date, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    years = tenure_years_on_date(hire_date, as_of)
    tier = next(
        (
            t
            for t in PTO_ACCRUAL_TIERS
            if (t.max_years is None and years >= t.min_years)
            or (t.max_years is not None and t.min_years <= years < t.max_years)
        ),
        PTO_ACCRUAL_TIERS[0],
    )
    return {
        "tenure_years": years,
        "tenure_label": tier.tenure_label,
        "pto_rate_per_qualifying_day": str(tier.rate_per_qualifying_day),
    }


def _staff_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("id",):
        if key in d and d[key] is not None:
            d[key] = str(d[key])
    if d.get("hire_date"):
        d["hire_date"] = d["hire_date"].isoformat()
    if d.get("auto_clock_out_cap"):
        cap = d["auto_clock_out_cap"]
        d["auto_clock_out_cap"] = cap.isoformat() if isinstance(cap, time) else str(cap)
    if d.get("terminated_at") and isinstance(d["terminated_at"], datetime):
        d["terminated_at"] = d["terminated_at"].isoformat()
    if d.get("pto_balance") is not None:
        d["pto_balance"] = str(d["pto_balance"])
    if d.get("hire_date"):
        hire = date.fromisoformat(d["hire_date"]) if isinstance(d["hire_date"], str) else d["hire_date"]
        d.update(tenure_info(hire))
    d["has_pin"] = bool(d.pop("has_pin", False))
    return d


async def list_staff(conn: asyncpg.Connection, *, include_terminated: bool = False) -> list[dict]:
    settings = get_settings()
    where = "" if include_terminated else "WHERE s.is_active = TRUE"
    rows = await conn.fetch(
        f"""
        SELECT s.*, (pc.pin_hash IS NOT NULL) AS has_pin
        FROM {settings.db_schema}.staff s
        LEFT JOIN {settings.db_schema}.pin_credentials pc ON pc.staff_id = s.id
        {where}
        ORDER BY s.staff_code
        """
    )
    return [_staff_row_to_dict(r) for r in rows]


async def get_staff(conn: asyncpg.Connection, staff_id: UUID) -> dict | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT s.*, (pc.pin_hash IS NOT NULL) AS has_pin
        FROM {settings.db_schema}.staff s
        LEFT JOIN {settings.db_schema}.pin_credentials pc ON pc.staff_id = s.id
        WHERE s.id = $1
        """,
        staff_id,
    )
    return _staff_row_to_dict(row) if row else None


async def create_staff(
    conn: asyncpg.Connection,
    *,
    staff_code: str,
    first_name: str,
    last_name: str,
    hire_date: date,
    auto_clock_out_cap: time = time(21, 0),
    face_check_enabled: bool = False,
    actor_id: UUID | None = None,
) -> dict:
    settings = get_settings()
    code = validate_staff_code(staff_code)
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.staff (
            staff_code, first_name, last_name, hire_date,
            auto_clock_out_cap, face_check_enabled
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        code,
        first_name.strip(),
        last_name.strip(),
        hire_date,
        auto_clock_out_cap,
        face_check_enabled,
    )
    if row is None:
        raise RuntimeError("staff insert failed")
    staff_id = row["id"]
    await write_audit_log(
        conn,
        actor_type="admin",
        action="create",
        table_name="staff",
        record_id=staff_id,
        actor_id=actor_id,
        new_values=dict(row),
    )
    result = await get_staff(conn, staff_id)
    assert result is not None
    return result


async def update_staff(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    first_name: str | None = None,
    last_name: str | None = None,
    hire_date: date | None = None,
    auto_clock_out_cap: time | None = None,
    face_check_enabled: bool | None = None,
    actor_id: UUID | None = None,
) -> dict | None:
    settings = get_settings()
    old = await get_staff(conn, staff_id)
    if old is None:
        return None
    updates: list[str] = []
    params: list[Any] = [staff_id]
    idx = 2

    if first_name is not None:
        updates.append(f"first_name = ${idx}")
        params.append(first_name.strip())
        idx += 1
    if last_name is not None:
        updates.append(f"last_name = ${idx}")
        params.append(last_name.strip())
        idx += 1
    if hire_date is not None:
        updates.append(f"hire_date = ${idx}")
        params.append(hire_date)
        idx += 1
    if auto_clock_out_cap is not None:
        updates.append(f"auto_clock_out_cap = ${idx}")
        params.append(auto_clock_out_cap)
        idx += 1
    if face_check_enabled is not None:
        updates.append(f"face_check_enabled = ${idx}")
        params.append(face_check_enabled)
        idx += 1

    if not updates:
        return old

    await conn.execute(
        f"""
        UPDATE {settings.db_schema}.staff
        SET {", ".join(updates)}
        WHERE id = $1
        """,
        *params,
    )
    new = await get_staff(conn, staff_id)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="update",
        table_name="staff",
        record_id=staff_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new


async def terminate_staff(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    actor_id: UUID | None = None,
) -> dict | None:
    settings = get_settings()
    old = await get_staff(conn, staff_id)
    if old is None or not old.get("is_active", True):
        return old

    balance = await conn.fetchval(
        f"SELECT pto_balance FROM {settings.db_schema}.staff WHERE id = $1",
        staff_id,
    )
    balance = Decimal(str(balance or 0))

    await conn.execute(
        f"""
        UPDATE {settings.db_schema}.staff
        SET is_active = FALSE, terminated_at = now(), pto_balance = 0
        WHERE id = $1
        """,
        staff_id,
    )

    if balance > 0:
        await conn.execute(
            f"""
            INSERT INTO {settings.db_schema}.pto_ledger (
                staff_id, entry_type, hours, balance_after, notes, created_by
            )
            VALUES ($1, 'forfeiture', $2, 0, 'Termination forfeiture', $3)
            """,
            staff_id,
            balance,
            actor_id,
        )

    new = await get_staff(conn, staff_id)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="terminate",
        table_name="staff",
        record_id=staff_id,
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )
    return new


async def set_staff_pin(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    pin: str,
    actor_id: UUID | None = None,
) -> None:
    settings = get_settings()
    validate_pin_format(pin)
    pin_hash = hash_pin(pin)
    existing = await conn.fetchrow(
        f"SELECT pin_hash FROM {settings.db_schema}.pin_credentials WHERE staff_id = $1",
        staff_id,
    )
    await conn.execute(
        f"""
        INSERT INTO {settings.db_schema}.pin_credentials (staff_id, pin_hash)
        VALUES ($1, $2)
        ON CONFLICT (staff_id) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, updated_at = now()
        """,
        staff_id,
        pin_hash,
    )
    await write_audit_log(
        conn,
        actor_type="admin",
        action="set_pin" if existing else "create_pin",
        table_name="pin_credentials",
        record_id=staff_id,
        actor_id=actor_id,
        old_values={"has_pin": existing is not None},
        new_values={"has_pin": True},
    )
