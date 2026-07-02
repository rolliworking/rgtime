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
from app.pto_rates import (
    PTO_ACCRUAL_TIERS,
    PtoOffer,
    derive_annual_from_daily,
    derive_daily_rate_from_annual,
    resolve_pto_rate,
    tier_for_tenure_years,
    tenure_years_on_date,
    effective_tenure_for_rate,
)
from app.staff_names import format_display_name, initials_staff_code, staff_code_with_suffix

STAFF_CODE_PATTERN = re.compile(r"^[A-Z0-9]{1,16}$")


def validate_staff_code(code: str) -> str:
    upper = code.strip().upper()
    if not STAFF_CODE_PATTERN.match(upper):
        raise ValueError("staff_code must be 1–16 uppercase alphanumeric characters")
    return upper


def _offer_from_staff(d: dict[str, Any]) -> PtoOffer:
    return PtoOffer(
        offer_type=d.get("pto_offer_type") or "default",
        tenure_credit_years=d.get("pto_tenure_credit_years"),
        custom_annual_hours=(
            Decimal(str(d["pto_custom_annual_hours"]))
            if d.get("pto_custom_annual_hours") is not None
            else None
        ),
        custom_daily_rate=(
            Decimal(str(d["pto_custom_daily_rate"]))
            if d.get("pto_custom_daily_rate") is not None
            else None
        ),
    )


def tenure_info(hire_date: date, as_of: date | None = None, offer: PtoOffer | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    offer = offer or PtoOffer()
    years = tenure_years_on_date(hire_date, as_of)
    rate, _ = resolve_pto_rate(hire_date=hire_date, work_date=as_of, offer=offer)
    lookup_years = years
    if offer.offer_type == "tenure_credit" and offer.tenure_credit_years is not None:
        lookup_years = effective_tenure_for_rate(hire_date, as_of, offer.tenure_credit_years)
    tier = tier_for_tenure_years(lookup_years)
    info: dict[str, Any] = {
        "tenure_years": years,
        "tenure_label": tier.tenure_label,
        "pto_rate_per_qualifying_day": str(rate),
        "pto_offer_type": offer.offer_type,
    }
    if offer.offer_type == "custom_rate":
        if offer.custom_annual_hours is not None:
            info["pto_custom_annual_hours"] = str(offer.custom_annual_hours)
        if offer.custom_daily_rate is not None:
            info["pto_custom_daily_rate"] = str(offer.custom_daily_rate)
    elif offer.offer_type == "tenure_credit" and offer.tenure_credit_years is not None:
        info["pto_tenure_credit_years"] = offer.tenure_credit_years
    return info


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
    for key in (
        "pto_offer_type",
        "pto_tenure_credit_years",
        "pto_custom_annual_hours",
        "pto_custom_daily_rate",
    ):
        if key in d and d[key] is not None and key != "pto_offer_type":
            if key == "pto_tenure_credit_years":
                d[key] = int(d[key])
            else:
                d[key] = str(d[key])
    if d.get("hire_date"):
        hire = date.fromisoformat(d["hire_date"]) if isinstance(d["hire_date"], str) else d["hire_date"]
        d.update(tenure_info(hire, offer=_offer_from_staff(d)))
    middle = d.get("middle_name")
    d["display_name"] = format_display_name(
        d.get("first_name", ""),
        d.get("last_name", ""),
        middle_name=middle,
    )
    d["display_name_short"] = format_display_name(
        d.get("first_name", ""),
        d.get("last_name", ""),
        middle_name=middle,
        short_middle=True,
    )
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


async def _staff_code_taken(conn: asyncpg.Connection, code: str) -> bool:
    """True if code was ever used (active or terminated staff)."""
    settings = get_settings()
    return bool(
        await conn.fetchval(
            f"SELECT 1 FROM {settings.db_schema}.staff WHERE staff_code = $1",
            code,
        )
    )


async def suggest_staff_code(
    conn: asyncpg.Connection,
    *,
    first_name: str,
    last_name: str = "",
    middle_name: str | None = None,
) -> str:
    """Suggest initials-based staff_code; never reuse a code that exists or existed."""
    base, mid_code = initials_staff_code(first_name, last_name, middle_name=middle_name)

    if not await _staff_code_taken(conn, base):
        return base

    if mid_code and not await _staff_code_taken(conn, mid_code):
        return mid_code

    root = mid_code if mid_code else base
    suffix = 2
    while True:
        candidate = staff_code_with_suffix(root, suffix)
        if not await _staff_code_taken(conn, candidate):
            return candidate
        suffix += 1


async def create_staff(
    conn: asyncpg.Connection,
    *,
    staff_code: str,
    first_name: str,
    last_name: str,
    hire_date: date,
    middle_name: str | None = None,
    auto_clock_out_cap: time = time(21, 0),
    face_check_enabled: bool = False,
    pto_offer_type: str = "default",
    pto_tenure_credit_years: int | None = None,
    pto_custom_annual_hours: Decimal | None = None,
    pto_custom_daily_rate: Decimal | None = None,
    actor_id: UUID | None = None,
) -> dict:
    settings = get_settings()
    code = validate_staff_code(staff_code)
    _validate_pto_offer(
        pto_offer_type,
        pto_tenure_credit_years,
        pto_custom_annual_hours,
        pto_custom_daily_rate,
    )
    middle = middle_name.strip() if middle_name and middle_name.strip() else None
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.staff (
            staff_code, first_name, middle_name, last_name, hire_date,
            auto_clock_out_cap, face_check_enabled,
            pto_offer_type, pto_tenure_credit_years,
            pto_custom_annual_hours, pto_custom_daily_rate
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING *
        """,
        code,
        first_name.strip(),
        middle,
        last_name.strip(),
        hire_date,
        auto_clock_out_cap,
        face_check_enabled,
        pto_offer_type,
        pto_tenure_credit_years,
        pto_custom_annual_hours,
        pto_custom_daily_rate,
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
    middle_name: str | None = None,
    last_name: str | None = None,
    hire_date: date | None = None,
    auto_clock_out_cap: time | None = None,
    face_check_enabled: bool | None = None,
    actor_id: UUID | None = None,
    update_middle_name: bool = False,
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
    if update_middle_name:
        updates.append(f"middle_name = ${idx}")
        params.append(middle_name.strip() if middle_name and middle_name.strip() else None)
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


def _validate_pto_offer(
    offer_type: str,
    tenure_credit_years: int | None,
    custom_annual_hours: Decimal | None,
    custom_daily_rate: Decimal | None,
) -> None:
    if offer_type == "default":
        return
    if offer_type == "tenure_credit":
        if tenure_credit_years is None or tenure_credit_years < 0:
            raise ValueError("tenure_credit requires pto_tenure_credit_years >= 0")
        return
    if offer_type == "custom_rate":
        if custom_annual_hours is None and custom_daily_rate is None:
            raise ValueError("custom_rate requires annual hours or daily rate")
        return
    raise ValueError("pto_offer_type must be default, tenure_credit, or custom_rate")


async def set_pto_offer(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    pto_offer_type: str,
    pto_tenure_credit_years: int | None = None,
    pto_custom_annual_hours: Decimal | None = None,
    pto_custom_daily_rate: Decimal | None = None,
    actor_id: UUID | None = None,
) -> dict | None:
    """Update per-person PTO offer with audit log."""
    if pto_offer_type == "custom_rate":
        if pto_custom_daily_rate is None and pto_custom_annual_hours is not None:
            pto_custom_daily_rate = derive_daily_rate_from_annual(pto_custom_annual_hours)
        elif pto_custom_annual_hours is None and pto_custom_daily_rate is not None:
            pto_custom_annual_hours = derive_annual_from_daily(pto_custom_daily_rate)
    _validate_pto_offer(
        pto_offer_type,
        pto_tenure_credit_years,
        pto_custom_annual_hours,
        pto_custom_daily_rate,
    )

    settings = get_settings()
    old = await get_staff(conn, staff_id)
    if old is None:
        return None

    await conn.execute(
        f"""
        UPDATE {settings.db_schema}.staff SET
            pto_offer_type = $2,
            pto_tenure_credit_years = $3,
            pto_custom_annual_hours = $4,
            pto_custom_daily_rate = $5
        WHERE id = $1
        """,
        staff_id,
        pto_offer_type,
        pto_tenure_credit_years if pto_offer_type == "tenure_credit" else None,
        pto_custom_annual_hours if pto_offer_type == "custom_rate" else None,
        pto_custom_daily_rate if pto_offer_type == "custom_rate" else None,
    )
    new = await get_staff(conn, staff_id)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="set_pto_offer",
        table_name="staff",
        record_id=staff_id,
        actor_id=actor_id,
        old_values={
            "pto_offer_type": old.get("pto_offer_type"),
            "pto_tenure_credit_years": old.get("pto_tenure_credit_years"),
            "pto_custom_annual_hours": old.get("pto_custom_annual_hours"),
            "pto_custom_daily_rate": old.get("pto_custom_daily_rate"),
        },
        new_values={
            "pto_offer_type": new.get("pto_offer_type") if new else None,
            "pto_tenure_credit_years": new.get("pto_tenure_credit_years") if new else None,
            "pto_custom_annual_hours": new.get("pto_custom_annual_hours") if new else None,
            "pto_custom_daily_rate": new.get("pto_custom_daily_rate") if new else None,
        },
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
