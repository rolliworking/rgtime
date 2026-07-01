#!/usr/bin/env python3
"""Print sample PTO accrual math for Michael review (Phase 4 hard stop)."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import asyncpg

from app.services.pto_accrual import accrual_for_day, accrue_for_date_range

# Sample staff: hired 2020-01-15, crosses yr2→yr3 on 2023-01-15 mid-period
SAMPLE_HIRE = date(2020, 1, 15)
PERIOD_START = date(2023, 1, 9)  # Monday
PERIOD_END = date(2023, 1, 22)  # Two weeks


def sample_days() -> list[tuple[date, Decimal, bool, str]]:
    """Synthetic day inputs for eyeball math (no DB punches needed)."""
    days: list[tuple[date, Decimal, bool, str]] = []
    d = PERIOD_START
    while d <= PERIOD_END:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        note = ""
        if d == date(2023, 1, 9):
            hours, worked, note = Decimal("8.0"), True, "Mon — 8.0h qualifying"
        elif d == date(2023, 1, 10):
            hours, worked, note = Decimal("7.5"), True, "Tue — 7.5h NOT qualifying"
        elif d == date(2023, 1, 11):
            hours, worked, note = Decimal("10.0"), True, "Wed — 10h OT, one day accrual only"
        elif d == date(2023, 1, 12):
            hours, worked, note = Decimal("8.0"), True, "Thu — 8.0h (still tier 2)"
        elif d == date(2023, 1, 13):
            hours, worked, note = Decimal("8.0"), True, "Fri — 8.0h (still tier 2)"
        elif d == date(2023, 1, 16):
            hours, worked, note = Decimal("0"), False, "Mon — vacation (no accrual)"
        elif d == date(2023, 1, 17):
            hours, worked, note = Decimal("8.0"), True, "Tue — anniversary → tier 3 (0.092)"
        elif d == date(2023, 1, 18):
            hours, worked, note = Decimal("8.0"), True, "Wed — tier 3"
        elif d == date(2023, 1, 19):
            hours, worked, note = Decimal("8.0"), True, "Thu — remote 8h reported"
        elif d == date(2023, 1, 20):
            hours, worked, note = Decimal("6.0"), True, "Fri — remote 6h, no accrual"
        else:
            d += timedelta(days=1)
            continue
        days.append((d, hours, worked, note))
        d += timedelta(days=1)
    return days


async def main() -> int:
    print("=" * 72)
    print("RG Time — Sample PTO Accrual Math (Phase 4)")
    print(f"Staff hire_date: {SAMPLE_HIRE}")
    print(f"Pay period: {PERIOD_START} to {PERIOD_END}")
    print("=" * 72)
    print(f"{'Date':<12} {'Hrs':>6} {'Worked?':>8} {'Tier':>5} {'Rate':>8} {'Earned':>8}  Notes")
    print("-" * 72)

    total = Decimal("0")
    for work_date, hours, worked, note in sample_days():
        r = accrual_for_day(
            hire_date=SAMPLE_HIRE,
            work_date=work_date,
            hours_worked=hours,
            counts_as_worked=worked,
        )
        total += r.accrual_hours
        print(
            f"{work_date.isoformat():<12} {hours:>6} {str(worked):>8} {r.tenure_years:>5} "
            f"{r.rate:>8} {r.accrual_hours:>8}  {note}"
        )

    print("-" * 72)
    print(f"Period PTO earned: {total} hours")
    print()
    print("Tier rates (literals): Yr0-1=0.000, Yr1-2=0.031, Yr2-3=0.062,")
    print("  Yr3-4=0.092, Yr4-5=0.123, Yr5+=0.154 hrs/qualifying day")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
