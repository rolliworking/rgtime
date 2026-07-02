"""Biweekly pay period math from pay_period_anchor_date config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import asyncpg

from app.config import get_settings

PAY_PERIOD_DAYS = 14


@dataclass(frozen=True)
class PayPeriod:
    start_date: date
    end_date: date

    @property
    def label(self) -> str:
        return f"{self.start_date.isoformat()} – {self.end_date.isoformat()}"


@dataclass(frozen=True)
class PayWeek:
    week_index: int  # 1 or 2 within the pay period
    start_date: date
    end_date: date


async def get_anchor_date(conn: asyncpg.Connection) -> date:
    settings = get_settings()
    raw = await conn.fetchval(
        f"SELECT value FROM {settings.db_schema}.config WHERE key = 'pay_period_anchor_date'"
    )
    if raw is None:
        return date(2025, 1, 6)
    if isinstance(raw, str):
        return date.fromisoformat(json.loads(raw))
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw).strip('"'))


def period_containing(anchor: date, as_of: date) -> PayPeriod:
    """Return the 14-day pay period that contains as_of (inclusive)."""
    if as_of < anchor:
        delta = (anchor - as_of).days
        periods_back = (delta + PAY_PERIOD_DAYS - 1) // PAY_PERIOD_DAYS
        start = anchor - timedelta(days=periods_back * PAY_PERIOD_DAYS)
    else:
        delta = (as_of - anchor).days
        start = anchor + timedelta(days=(delta // PAY_PERIOD_DAYS) * PAY_PERIOD_DAYS)
    end = start + timedelta(days=PAY_PERIOD_DAYS - 1)
    return PayPeriod(start, end)


def weeks_in_period(period: PayPeriod) -> tuple[PayWeek, PayWeek]:
    return (
        PayWeek(1, period.start_date, period.start_date + timedelta(days=6)),
        PayWeek(2, period.start_date + timedelta(days=7), period.end_date),
    )


def list_periods(anchor: date, *, through: date, count: int = 12) -> list[PayPeriod]:
    """Most recent pay periods up to `through`, newest first."""
    current = period_containing(anchor, through)
    periods = [current]
    start = current.start_date
    while len(periods) < count:
        start -= timedelta(days=PAY_PERIOD_DAYS)
        periods.append(PayPeriod(start, start + timedelta(days=PAY_PERIOD_DAYS - 1)))
    return periods


def iter_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
