"""Reusable PTO offer templates — Phase 4.5."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.pto_rates import PtoOffer, derive_annual_from_daily, derive_daily_rate_from_annual


def _template_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat()
    if d.get("custom_annual_hours") is not None:
        d["custom_annual_hours"] = str(d["custom_annual_hours"])
    if d.get("custom_daily_rate") is not None:
        d["custom_daily_rate"] = str(d["custom_daily_rate"])
    return d


def template_to_offer(row: asyncpg.Record | dict[str, Any]) -> PtoOffer:
    offer_type = row["offer_type"]
    if offer_type == "tenure_credit":
        return PtoOffer(
            offer_type="tenure_credit",
            tenure_credit_years=row["tenure_credit_years"],
        )
    return PtoOffer(
        offer_type="custom_rate",
        custom_annual_hours=(
            Decimal(str(row["custom_annual_hours"]))
            if row.get("custom_annual_hours") is not None
            else None
        ),
        custom_daily_rate=(
            Decimal(str(row["custom_daily_rate"]))
            if row.get("custom_daily_rate") is not None
            else None
        ),
    )


async def list_templates(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT id, name, offer_type, tenure_credit_years,
               custom_annual_hours, custom_daily_rate, created_at
        FROM {settings.db_schema}.offer_templates
        ORDER BY name
        """
    )
    return [_template_to_dict(r) for r in rows]


async def get_template(conn: asyncpg.Connection, template_id: UUID) -> dict[str, Any] | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT id, name, offer_type, tenure_credit_years,
               custom_annual_hours, custom_daily_rate, created_at
        FROM {settings.db_schema}.offer_templates
        WHERE id = $1
        """,
        template_id,
    )
    return _template_to_dict(row) if row else None


async def create_template(
    conn: asyncpg.Connection,
    *,
    name: str,
    offer_type: str,
    tenure_credit_years: int | None = None,
    custom_annual_hours: Decimal | None = None,
    custom_daily_rate: Decimal | None = None,
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    if offer_type == "tenure_credit":
        if tenure_credit_years is None:
            raise ValueError("tenure_credit_years required for tenure_credit template")
    elif offer_type == "custom_rate":
        if custom_annual_hours is None and custom_daily_rate is None:
            raise ValueError("custom_annual_hours or custom_daily_rate required")
        if custom_daily_rate is None and custom_annual_hours is not None:
            custom_daily_rate = derive_daily_rate_from_annual(custom_annual_hours)
        elif custom_annual_hours is None and custom_daily_rate is not None:
            custom_annual_hours = derive_annual_from_daily(custom_daily_rate)
    else:
        raise ValueError("offer_type must be tenure_credit or custom_rate")

    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.offer_templates (
            name, offer_type, tenure_credit_years,
            custom_annual_hours, custom_daily_rate, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        name.strip(),
        offer_type,
        tenure_credit_years,
        custom_annual_hours,
        custom_daily_rate,
        actor_id,
    )
    if row is None:
        raise RuntimeError("template insert failed")
    return _template_to_dict(row)
