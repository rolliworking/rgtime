"""Tests for locked-rules PTO accrual literals."""

from decimal import Decimal

from app.pto_rates import (
    PTO_ACCRUAL_TIERS,
    rate_for_tenure_years,
    tenure_years_on_date,
)
from datetime import date


def test_pto_rates_are_authoritative_literals():
    assert rate_for_tenure_years(0) == Decimal("0.000")
    assert rate_for_tenure_years(1) == Decimal("0.031")
    assert rate_for_tenure_years(2) == Decimal("0.062")
    assert rate_for_tenure_years(3) == Decimal("0.092")
    assert rate_for_tenure_years(4) == Decimal("0.123")
    assert rate_for_tenure_years(5) == Decimal("0.154")
    assert rate_for_tenure_years(99) == Decimal("0.154")


def test_six_tiers_defined():
    assert len(PTO_ACCRUAL_TIERS) == 6


def test_tenure_anniversary_boundary():
    hire = date(2020, 6, 15)
    assert tenure_years_on_date(hire, date(2021, 6, 14)) == 0
    assert tenure_years_on_date(hire, date(2021, 6, 15)) == 1
