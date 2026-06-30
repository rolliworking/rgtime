"""Authoritative PTO accrual rates — locked rules §1.

Do NOT compute rates as annual ÷ expected_workdays_per_year at runtime.
Apply these literals directly per qualifying day.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PtoAccrualTier:
    tenure_label: str
    min_years: int
    max_years: int | None  # None = open-ended (5+)
    annual_pto_hours: int
    rate_per_qualifying_day: Decimal


# AUTHORITATIVE — hardcoded literals per locked rules.
PTO_ACCRUAL_TIERS: tuple[PtoAccrualTier, ...] = (
    PtoAccrualTier("Yr 0-1", 0, 1, 0, Decimal("0.000")),
    PtoAccrualTier("Yr 1-2", 1, 2, 8, Decimal("0.031")),
    PtoAccrualTier("Yr 2-3", 2, 3, 16, Decimal("0.062")),
    PtoAccrualTier("Yr 3-4", 3, 4, 24, Decimal("0.092")),
    PtoAccrualTier("Yr 4-5", 4, 5, 32, Decimal("0.123")),
    PtoAccrualTier("Yr 5+", 5, None, 40, Decimal("0.154")),
)

QUALIFYING_HOURS_THRESHOLD = Decimal("8.0")


def tenure_years_on_date(hire_date, as_of_date) -> int:
    """Whole years since hire_date, advancing on each work anniversary."""
    years = as_of_date.year - hire_date.year
    if (as_of_date.month, as_of_date.day) < (hire_date.month, hire_date.day):
        years -= 1
    return max(years, 0)


def rate_for_tenure_years(tenure_years: int) -> Decimal:
    for tier in PTO_ACCRUAL_TIERS:
        if tier.max_years is None:
            if tenure_years >= tier.min_years:
                return tier.rate_per_qualifying_day
        elif tier.min_years <= tenure_years < tier.max_years:
            return tier.rate_per_qualifying_day
    return Decimal("0.000")
