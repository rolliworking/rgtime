"""Effective-dated PTO tenure ladder — Phase 4.5."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.audit import write_audit_log
from app.config import get_settings
from app.pto_rates import (
    DEFAULT_LADDER_EFFECTIVE_FROM,
    PTO_ACCRUAL_TIERS,
    PtoAccrualTier,
    derive_annual_from_daily,
    derive_daily_rate_from_annual,
    ladder_for_work_date,
)


def _row_to_tier(row: asyncpg.Record) -> PtoAccrualTier:
    return PtoAccrualTier(
        tenure_label=row["tier_label"],
        min_years=row["min_years"],
        max_years=row["max_years"],
        annual_pto_hours=row["annual_pto_hours"],
        rate_per_qualifying_day=Decimal(str(row["rate_per_qualifying_day"])),
        effective_from=row["effective_from"],
    )


def _tier_to_dict(tier: PtoAccrualTier) -> dict[str, Any]:
    return {
        "tier_label": tier.tenure_label,
        "min_years": tier.min_years,
        "max_years": tier.max_years,
        "annual_pto_hours": tier.annual_pto_hours,
        "rate_per_qualifying_day": str(tier.rate_per_qualifying_day),
        "effective_from": tier.effective_from.isoformat(),
    }


async def fetch_all_ladder_rows(conn: asyncpg.Connection) -> list[PtoAccrualTier]:
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT tier_label, min_years, max_years, annual_pto_hours,
               rate_per_qualifying_day, effective_from
        FROM {settings.db_schema}.pto_ladder_rates
        ORDER BY effective_from ASC, min_years ASC
        """
    )
    return [_row_to_tier(r) for r in rows]


async def get_ladder_for_work_date(
    conn: asyncpg.Connection,
    work_date: date,
) -> tuple[PtoAccrualTier, ...]:
    rows = await fetch_all_ladder_rows(conn)
    return ladder_for_work_date(rows, work_date)


async def get_active_ladder(
    conn: asyncpg.Connection,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Currently active ladder tiers for admin display."""
    as_of = as_of or date.today()
    tiers = await get_ladder_for_work_date(conn, as_of)
    return [_tier_to_dict(t) for t in tiers]


async def list_ladder_versions(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """All ladder rows grouped by effective_from (read-only history)."""
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT id, tier_label, min_years, max_years, annual_pto_hours,
               rate_per_qualifying_day, effective_from, created_at
        FROM {settings.db_schema}.pto_ladder_rates
        ORDER BY effective_from DESC, min_years ASC
        """
    )
    result: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["effective_from"] = d["effective_from"].isoformat()
        d["rate_per_qualifying_day"] = str(d["rate_per_qualifying_day"])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result


async def upsert_ladder_tier(
    conn: asyncpg.Connection,
    *,
    min_years: int,
    max_years: int | None,
    tier_label: str,
    annual_pto_hours: int,
    rate_per_qualifying_day: Decimal,
    effective_from: date,
    actor_id: UUID | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Insert a new effective-dated ladder row for one tier band.
    Requires confirmed=True (confirm-on-save guardrail).
    """
    if not confirmed:
        raise ValueError("Ladder edit requires confirmed=true")

    settings = get_settings()
    old_rows = await conn.fetch(
        f"""
        SELECT * FROM {settings.db_schema}.pto_ladder_rates
        WHERE min_years = $1
          AND (max_years IS NOT DISTINCT FROM $2)
          AND effective_from <= $3
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        min_years,
        max_years,
        effective_from,
    )
    old = dict(old_rows[0]) if old_rows else None

    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.pto_ladder_rates (
            tier_label, min_years, max_years, annual_pto_hours,
            rate_per_qualifying_day, effective_from, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (min_years, max_years, effective_from) DO UPDATE SET
            tier_label = EXCLUDED.tier_label,
            annual_pto_hours = EXCLUDED.annual_pto_hours,
            rate_per_qualifying_day = EXCLUDED.rate_per_qualifying_day,
            created_by = EXCLUDED.created_by
        RETURNING *
        """,
        tier_label,
        min_years,
        max_years,
        annual_pto_hours,
        rate_per_qualifying_day,
        effective_from,
        actor_id,
    )
    if row is None:
        raise RuntimeError("ladder insert failed")

    new = dict(row)
    await write_audit_log(
        conn,
        actor_type="admin",
        action="update_ladder",
        table_name="pto_ladder_rates",
        record_id=row["id"],
        actor_id=actor_id,
        old_values=old,
        new_values=new,
    )

    return {
        "id": str(row["id"]),
        "tier_label": row["tier_label"],
        "min_years": row["min_years"],
        "max_years": row["max_years"],
        "annual_pto_hours": row["annual_pto_hours"],
        "rate_per_qualifying_day": str(row["rate_per_qualifying_day"]),
        "effective_from": row["effective_from"].isoformat(),
    }


def sync_annual_and_rate(
    *,
    annual_pto_hours: int | None,
    rate_per_qualifying_day: Decimal | None,
) -> tuple[int, Decimal]:
    """Derive missing annual or rate for ladder edits (display consistency)."""
    if rate_per_qualifying_day is not None:
        rate = rate_per_qualifying_day.quantize(Decimal("0.001"))
        annual = int(derive_annual_from_daily(rate))
        return annual, rate
    if annual_pto_hours is not None:
        rate = derive_daily_rate_from_annual(Decimal(annual_pto_hours))
        return annual_pto_hours, rate
    raise ValueError("annual_pto_hours or rate_per_qualifying_day required")


def default_seed_tiers() -> tuple[PtoAccrualTier, ...]:
    return PTO_ACCRUAL_TIERS
