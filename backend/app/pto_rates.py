"""Authoritative PTO accrual rates — locked rules §1.

Do NOT compute ladder rates as annual ÷ expected_workdays_per_year at runtime.
Apply ladder literals directly per qualifying day.

Custom offers may derive per-day rate from annual hours using expected_workdays_per_year
(NEEDS MICHAEL: confirm 260 is the intended divisor for custom annual → daily).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

THREEPLACES = Decimal("0.001")

# Provenance divisor for custom annual → daily derivation only (not ladder tiers).
EXPECTED_WORKDAYS_PER_YEAR = 260

# Baseline effective date for seeded ladder rows (see migration).
DEFAULT_LADDER_EFFECTIVE_FROM = date(2020, 1, 1)


@dataclass(frozen=True)
class PtoAccrualTier:
    tenure_label: str
    min_years: int
    max_years: int | None  # None = open-ended (5+)
    annual_pto_hours: int
    rate_per_qualifying_day: Decimal
    effective_from: date = DEFAULT_LADDER_EFFECTIVE_FROM


# AUTHORITATIVE — hardcoded literals per locked rules (fallback if DB ladder empty).
PTO_ACCRUAL_TIERS: tuple[PtoAccrualTier, ...] = (
    PtoAccrualTier("Yr 0-1", 0, 1, 0, Decimal("0.000")),
    PtoAccrualTier("Yr 1-2", 1, 2, 8, Decimal("0.031")),
    PtoAccrualTier("Yr 2-3", 2, 3, 16, Decimal("0.062")),
    PtoAccrualTier("Yr 3-4", 3, 4, 24, Decimal("0.092")),
    PtoAccrualTier("Yr 4-5", 4, 5, 32, Decimal("0.123")),
    PtoAccrualTier("Yr 5+", 5, None, 40, Decimal("0.154")),
)

QUALIFYING_HOURS_THRESHOLD = Decimal("8.0")

PtoOfferType = str  # 'default' | 'tenure_credit' | 'custom_rate'


@dataclass(frozen=True)
class PtoOffer:
    offer_type: PtoOfferType = "default"
    tenure_credit_years: int | None = None
    custom_annual_hours: Decimal | None = None
    custom_daily_rate: Decimal | None = None


def tenure_years_on_date(hire_date: date, as_of_date: date) -> int:
    """Whole years since hire_date, advancing on each work anniversary."""
    years = as_of_date.year - hire_date.year
    if (as_of_date.month, as_of_date.day) < (hire_date.month, hire_date.day):
        years -= 1
    return max(years, 0)


def effective_tenure_for_rate(
    hire_date: date,
    work_date: date,
    tenure_credit_years: int,
) -> int:
    """Real tenure + credit offset for ladder lookup; anniversaries still use hire_date."""
    return tenure_years_on_date(hire_date, work_date) + tenure_credit_years


def rate_for_tenure_years(
    tenure_years: int,
    ladder: tuple[PtoAccrualTier, ...] | None = None,
) -> Decimal:
    tiers = ladder or PTO_ACCRUAL_TIERS
    for tier in tiers:
        if tier.max_years is None:
            if tenure_years >= tier.min_years:
                return tier.rate_per_qualifying_day
        elif tier.min_years <= tenure_years < tier.max_years:
            return tier.rate_per_qualifying_day
    return Decimal("0.000")


def tier_for_tenure_years(
    tenure_years: int,
    ladder: tuple[PtoAccrualTier, ...] | None = None,
) -> PtoAccrualTier:
    tiers = ladder or PTO_ACCRUAL_TIERS
    for tier in tiers:
        if tier.max_years is None:
            if tenure_years >= tier.min_years:
                return tier
        elif tier.min_years <= tenure_years < tier.max_years:
            return tier
    return tiers[0]


def derive_daily_rate_from_annual(annual_hours: Decimal) -> Decimal:
    """Custom offer: annual hours → per-qualifying-day rate (3 decimal places)."""
    return (annual_hours / Decimal(EXPECTED_WORKDAYS_PER_YEAR)).quantize(
        THREEPLACES, rounding=ROUND_HALF_UP
    )


def derive_annual_from_daily(daily_rate: Decimal) -> Decimal:
    """Display helper: per-day rate → implied annual hours."""
    return (daily_rate * Decimal(EXPECTED_WORKDAYS_PER_YEAR)).quantize(
        THREEPLACES, rounding=ROUND_HALF_UP
    )


def resolve_custom_daily_rate(offer: PtoOffer) -> Decimal:
    if offer.custom_daily_rate is not None:
        return offer.custom_daily_rate.quantize(THREEPLACES, rounding=ROUND_HALF_UP)
    if offer.custom_annual_hours is not None:
        return derive_daily_rate_from_annual(offer.custom_annual_hours)
    return Decimal("0.000")


def resolve_pto_rate(
    *,
    hire_date: date,
    work_date: date,
    offer: PtoOffer,
    ladder: tuple[PtoAccrualTier, ...] | None = None,
) -> tuple[Decimal, int]:
    """
    Three-layer resolution: custom_rate > tenure_credit > default ladder.
    Returns (rate_per_qualifying_day, tenure_years_for_display).
    """
    tiers = ladder or PTO_ACCRUAL_TIERS
    real_tenure = tenure_years_on_date(hire_date, work_date)

    if offer.offer_type == "custom_rate":
        return resolve_custom_daily_rate(offer), real_tenure

    lookup_tenure = real_tenure
    if offer.offer_type == "tenure_credit" and offer.tenure_credit_years is not None:
        lookup_tenure = effective_tenure_for_rate(
            hire_date, work_date, offer.tenure_credit_years
        )

    return rate_for_tenure_years(lookup_tenure, tiers), real_tenure


def ladder_for_work_date(
    rows: list[PtoAccrualTier],
    work_date: date,
) -> tuple[PtoAccrualTier, ...]:
    """
    Build effective ladder for work_date from versioned DB rows.
    Per tier band, pick row with latest effective_from <= work_date.
    Falls back to PTO_ACCRUAL_TIERS if rows empty.
    """
    if not rows:
        return PTO_ACCRUAL_TIERS

    bands: dict[tuple[int, int | None], PtoAccrualTier] = {}
    for row in rows:
        if row.effective_from > work_date:
            continue
        key = (row.min_years, row.max_years)
        existing = bands.get(key)
        if existing is None or row.effective_from > existing.effective_from:
            bands[key] = row

    if not bands:
        return PTO_ACCRUAL_TIERS

    return tuple(sorted(bands.values(), key=lambda t: t.min_years))


_STAFF_CODE_BASE = re.compile(r"[^A-Z0-9]")


def base_staff_code_from_name(first_name: str) -> str:
    """Uppercase alphanumeric from first name, max 16 chars."""
    base = _STAFF_CODE_BASE.sub("", first_name.strip().upper())
    return (base or "STAFF")[:16]
