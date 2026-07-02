"""Biweekly audit — clean vs flagged staff-period classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.services.pay_period import PayPeriod, iter_dates, weeks_in_period
from app.services.pto_accrual import compute_punched_hours

WEEKLY_TARGET_HOURS = Decimal("40.00")
TWOPLACES = Decimal("0.01")


@dataclass
class DayFlag:
    work_date: date
    flag_type: str
    detail: str


@dataclass
class StaffPeriodAudit:
    staff_id: UUID
    staff_code: str
    first_name: str
    last_name: str
    pay_period_start: date
    pay_period_end: date
    week1_hours: Decimal
    week2_hours: Decimal
    flags: list[DayFlag] = field(default_factory=list)
    pto_balance: Decimal = Decimal("0")

    @property
    def is_clean(self) -> bool:
        return len(self.flags) == 0

    @property
    def is_flagged(self) -> bool:
        return len(self.flags) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "staff_id": str(self.staff_id),
            "staff_code": self.staff_code,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "pay_period_start": self.pay_period_start.isoformat(),
            "pay_period_end": self.pay_period_end.isoformat(),
            "week1_hours": str(self.week1_hours),
            "week2_hours": str(self.week2_hours),
            "pto_balance": str(self.pto_balance),
            "flags": [
                {
                    "work_date": f.work_date.isoformat(),
                    "flag_type": f.flag_type,
                    "detail": f.detail,
                }
                for f in self.flags
            ],
            "bucket": "clean" if self.is_clean else "flagged",
        }


async def _day_credit_hours(
    conn: asyncpg.Connection,
    staff_id: UUID,
    work_date: date,
) -> Decimal:
    """Hours credited toward weekly totals (punches + remote reported hours)."""
    punched = await compute_punched_hours(conn, staff_id, work_date)
    settings = get_settings()
    absence = await conn.fetchrow(
        f"""
        SELECT a.reported_hours, r.counts_as_worked
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.staff_id = $1 AND a.absence_date = $2
        """,
        staff_id,
        work_date,
    )
    if absence and absence["counts_as_worked"] and punched == 0:
        return Decimal(str(absence["reported_hours"] or 0)).quantize(TWOPLACES)
    return punched


async def _week_hours(
    conn: asyncpg.Connection,
    staff_id: UUID,
    week_start: date,
    week_end: date,
) -> Decimal:
    total = Decimal("0")
    for d in iter_dates(week_start, week_end):
        total += await _day_credit_hours(conn, staff_id, d)
    return total.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


async def audit_staff_period(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    period: PayPeriod,
) -> StaffPeriodAudit:
    settings = get_settings()
    staff = await conn.fetchrow(
        f"""
        SELECT id, staff_code, first_name, last_name, pto_balance
        FROM {settings.db_schema}.staff WHERE id = $1
        """,
        staff_id,
    )
    if staff is None:
        raise ValueError("staff not found")

    week1, week2 = weeks_in_period(period)
    w1 = await _week_hours(conn, staff_id, week1.start_date, week1.end_date)
    w2 = await _week_hours(conn, staff_id, week2.start_date, week2.end_date)

    audit = StaffPeriodAudit(
        staff_id=staff["id"],
        staff_code=staff["staff_code"],
        first_name=staff["first_name"],
        last_name=staff["last_name"],
        pay_period_start=period.start_date,
        pay_period_end=period.end_date,
        week1_hours=w1,
        week2_hours=w2,
        pto_balance=Decimal(str(staff["pto_balance"])).quantize(TWOPLACES),
    )

    if w1 < WEEKLY_TARGET_HOURS:
        audit.flags.append(
            DayFlag(
                week1.start_date,
                "under_hours",
                f"Week 1 hours {w1} < {WEEKLY_TARGET_HOURS}",
            )
        )
    if w2 < WEEKLY_TARGET_HOURS:
        audit.flags.append(
            DayFlag(
                week2.start_date,
                "under_hours",
                f"Week 2 hours {w2} < {WEEKLY_TARGET_HOURS}",
            )
        )

    events = await conn.fetch(
        f"""
        SELECT work_date, is_late_arrival, late_minutes,
               is_missing_clockout_flag, face_mismatch_flag, event_type
        FROM {settings.db_schema}.time_events
        WHERE staff_id = $1
          AND work_date BETWEEN $2 AND $3
        ORDER BY work_date, occurred_at
        """,
        staff_id,
        period.start_date,
        period.end_date,
    )
    for ev in events:
        d = ev["work_date"]
        if ev["is_late_arrival"] and ev["late_minutes"] is not None:
            audit.flags.append(
                DayFlag(d, "late", f"Late {ev['late_minutes']} min")
            )
        if ev["is_missing_clockout_flag"]:
            audit.flags.append(
                DayFlag(d, "missing_clockout", f"Missing clock-out ({ev['event_type']})")
            )
        if ev["face_mismatch_flag"]:
            audit.flags.append(DayFlag(d, "face_mismatch", "Face mismatch on punch"))

    absences = await conn.fetch(
        f"""
        SELECT a.absence_date, r.name, r.funding
        FROM {settings.db_schema}.absences a
        JOIN {settings.db_schema}.absence_reasons r ON r.id = a.reason_id
        WHERE a.staff_id = $1
          AND a.absence_date BETWEEN $2 AND $3
        """,
        staff_id,
        period.start_date,
        period.end_date,
    )
    for ab in absences:
        # Flagging independent of funding — PTO-covered no-show still flagged.
        audit.flags.append(
            DayFlag(
                ab["absence_date"],
                "absence",
                f"{ab['name']} ({ab['funding']})",
            )
        )

    return audit


async def build_period_audit(
    conn: asyncpg.Connection,
    period: PayPeriod,
    *,
    include_terminated: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    where = "" if include_terminated else "WHERE is_active = TRUE"
    staff_rows = await conn.fetch(
        f"""
        SELECT id FROM {settings.db_schema}.staff {where} ORDER BY staff_code
        """
    )

    clean: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []

    for row in staff_rows:
        audit = await audit_staff_period(conn, staff_id=row["id"], period=period)
        entry = audit.to_dict()
        if audit.is_clean:
            clean.append(entry)
        else:
            flagged.append(entry)

    return {
        "pay_period_start": period.start_date.isoformat(),
        "pay_period_end": period.end_date.isoformat(),
        "weekly_target_hours": str(WEEKLY_TARGET_HOURS),
        "clean": clean,
        "flagged": flagged,
        "clean_count": len(clean),
        "flagged_count": len(flagged),
    }
