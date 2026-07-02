"""Manager-confirmed PTO draws during biweekly audit."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.services.pto_accrual import get_current_balance

TWOPLACES = Decimal("0.01")


def _preview(staff_id: UUID, hours: Decimal, balance: Decimal) -> dict[str, Any]:
    hours = hours.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    if hours <= 0:
        raise ValueError("draw hours must be positive")
    if hours > balance:
        raise ValueError(f"insufficient PTO balance ({balance} available)")
    return {
        "staff_id": str(staff_id),
        "hours": str(hours),
        "balance_before": str(balance),
        "balance_after": str((balance - hours).quantize(TWOPLACES)),
    }


async def propose_pto_draw(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    hours: Decimal,
) -> dict[str, Any]:
    balance = await get_current_balance(conn, staff_id)
    return _preview(staff_id, hours, balance)


async def confirm_pto_draw(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    hours: Decimal,
    work_date: date | None = None,
    pay_period_start: date | None = None,
    absence_id: UUID | None = None,
    notes: str | None = None,
    confirmed: bool = False,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("PTO draw requires confirmed=true")

    balance = await get_current_balance(conn, staff_id)
    preview = _preview(staff_id, hours, balance)
    draw_hours = Decimal(preview["hours"])
    new_balance = Decimal(preview["balance_after"])

    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.pto_ledger (
            staff_id, entry_type, hours, balance_after, work_date,
            pay_period_start, notes, created_by
        )
        VALUES ($1, 'draw', $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        staff_id,
        draw_hours,
        new_balance,
        work_date,
        pay_period_start,
        notes or "Manager-confirmed PTO draw",
        actor_id,
    )
    await conn.execute(
        f"UPDATE {settings.db_schema}.staff SET pto_balance = $2 WHERE id = $1",
        staff_id,
        new_balance,
    )

    if absence_id is not None:
        await conn.execute(
            f"""
            UPDATE {settings.db_schema}.absences
            SET audit_resolved = TRUE
            WHERE id = $1
            """,
            absence_id,
        )

    ledger_id = row["id"] if row else None
    result = {
        **preview,
        "ledger_id": str(ledger_id) if ledger_id else None,
        "absence_id": str(absence_id) if absence_id else None,
    }
    await write_audit_log(
        conn,
        actor_type="admin",
        action="pto_draw",
        table_name="pto_ledger",
        record_id=ledger_id,
        actor_id=actor_id,
        old_values={"pto_balance": preview["balance_before"]},
        new_values=result,
    )
    return result
