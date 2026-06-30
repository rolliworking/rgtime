"""Core time-tracking logic for kiosk punches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.timezone_util import TZ, combine_eastern, work_date_for

LUNCH_DEDUCT_MINUTES = 30
LATENESS_GRACE_MINUTES = 30


@dataclass
class ScheduleInfo:
    scheduled_start_time: time
    scheduled_end_time: time


@dataclass
class PunchResult:
    event_id: UUID
    event_type: str
    occurred_at: datetime
    work_date: date
    is_late_arrival: bool
    late_minutes: int | None
    lunch_deducted_minutes: int
    is_missing_clockout_flag: bool
    confirmation: str


async def get_staff_by_pin(conn: asyncpg.Connection, pin: str) -> asyncpg.Record | None:
    settings = get_settings()
    rows = await conn.fetch(
        f"""
        SELECT s.id, s.first_name, s.last_name, s.staff_code, s.is_active,
               p.pin_hash
        FROM {settings.db_schema}.staff s
        JOIN {settings.db_schema}.pin_credentials p ON p.staff_id = s.id
        WHERE s.is_active = TRUE
        """
    )
    from app.pin import verify_pin

    for row in rows:
        if verify_pin(pin, row["pin_hash"]):
            return row
    return None


async def get_schedule(conn: asyncpg.Connection, staff_id: UUID) -> ScheduleInfo | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT scheduled_start_time, scheduled_end_time
        FROM {settings.db_schema}.schedules
        WHERE staff_id = $1
        """,
        staff_id,
    )
    if row is None:
        return None
    return ScheduleInfo(row["scheduled_start_time"], row["scheduled_end_time"])


async def get_last_event(conn: asyncpg.Connection, staff_id: UUID) -> asyncpg.Record | None:
    settings = get_settings()
    return await conn.fetchrow(
        f"""
        SELECT event_type, occurred_at, work_date
        FROM {settings.db_schema}.time_events
        WHERE staff_id = $1
        ORDER BY occurred_at DESC, created_at DESC
        LIMIT 1
        """,
        staff_id,
    )


def is_clocked_in(last_event: asyncpg.Record | None) -> bool:
    if last_event is None:
        return False
    return last_event["event_type"] == "clock_in"


def next_event_type(last_event: asyncpg.Record | None) -> str:
    return "clock_out" if is_clocked_in(last_event) else "clock_in"


def compute_lateness(
    occurred_at: datetime,
    work_date: date,
    schedule: ScheduleInfo | None,
) -> tuple[bool, int | None]:
    if schedule is None:
        return False, None
    local = occurred_at.astimezone(TZ)
    scheduled_start = combine_eastern(work_date, schedule.scheduled_start_time)
    grace_end = scheduled_start + timedelta(minutes=LATENESS_GRACE_MINUTES)
    if local <= grace_end:
        return False, None
    late_minutes = int((local - scheduled_start).total_seconds() // 60)
    return True, late_minutes


def day_has_lunch_punch(events: list[asyncpg.Record]) -> bool:
    """Lunch = intermediate clock_out immediately followed by clock_in."""
    types = [e["event_type"] for e in events]
    for i in range(len(types) - 1):
        if types[i] == "clock_out" and types[i + 1] == "clock_in" and i > 0:
            return True
    return False


def compute_lunch_deduction(events: list[asyncpg.Record], closing_type: str) -> int:
    """Apply 30-min deduction when day closes without a lunch punch pair."""
    if closing_type not in ("clock_out", "auto_clock_out"):
        return 0
    if not events:
        return 0
    if day_has_lunch_punch(events):
        return 0
    # At least one full in-out segment without lunch break recorded.
    ins = sum(1 for e in events if e["event_type"] == "clock_in")
    outs = sum(1 for e in events if e["event_type"] in ("clock_out", "auto_clock_out"))
    if ins >= 1 and outs >= 1:
        return LUNCH_DEDUCT_MINUTES
    return 0


async def get_day_events(
    conn: asyncpg.Connection, staff_id: UUID, work_date: date
) -> list[asyncpg.Record]:
    settings = get_settings()
    return list(
        await conn.fetch(
            f"""
            SELECT event_type, occurred_at
            FROM {settings.db_schema}.time_events
            WHERE staff_id = $1 AND work_date = $2
            ORDER BY occurred_at ASC, created_at ASC
            """,
            staff_id,
            work_date,
        )
    )


async def record_punch(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    staff_name: str,
    event_type: str,
    occurred_at: datetime,
    is_missing_clockout_flag: bool = False,
) -> PunchResult:
    settings = get_settings()
    work_date = work_date_for(occurred_at)
    schedule = await get_schedule(conn, staff_id)

    is_late = False
    late_minutes: int | None = None
    if event_type == "clock_in":
        prior_ins = await get_day_events(conn, staff_id, work_date)
        is_first_clock_in = not any(e["event_type"] == "clock_in" for e in prior_ins)
        if is_first_clock_in:
            is_late, late_minutes = compute_lateness(occurred_at, work_date, schedule)

    prior_events = await get_day_events(conn, staff_id, work_date)
    lunch_deducted = 0
    if event_type in ("clock_out", "auto_clock_out"):
        ins = sum(1 for e in prior_events if e["event_type"] == "clock_in")
        outs = sum(
            1
            for e in prior_events
            if e["event_type"] in ("clock_out", "auto_clock_out")
        )
        if not day_has_lunch_punch(prior_events) and ins >= 1 and outs + 1 >= 1:
            lunch_deducted = LUNCH_DEDUCT_MINUTES

    row = await conn.fetchrow(
        f"""
        INSERT INTO {settings.db_schema}.time_events (
            staff_id, event_type, occurred_at, work_date,
            is_late_arrival, late_minutes, is_missing_clockout_flag,
            lunch_deducted_minutes
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        staff_id,
        event_type,
        occurred_at,
        work_date,
        is_late,
        late_minutes,
        is_missing_clockout_flag,
        lunch_deducted,
    )
    assert row is not None
    event_id = row["id"]

    local = occurred_at.astimezone(TZ)
    time_str = local.strftime("%I:%M %p").lstrip("0")
    if event_type == "clock_in":
        confirmation = f"Clocked in at {time_str}"
    elif event_type == "auto_clock_out":
        confirmation = f"Auto clocked out at {time_str} — flagged for manager review"
    else:
        confirmation = f"Clocked out at {time_str}"

    return PunchResult(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        work_date=work_date,
        is_late_arrival=is_late,
        late_minutes=late_minutes,
        lunch_deducted_minutes=lunch_deducted,
        is_missing_clockout_flag=is_missing_clockout_flag,
        confirmation=confirmation,
    )


async def run_auto_clock_outs(conn: asyncpg.Connection, as_of: datetime | None = None) -> list[PunchResult]:
    """Close open punches at per-staff cap; flag missing_clockout."""
    settings = get_settings()
    as_of = as_of or datetime.now(TZ)
    work_date = work_date_for(as_of)
    local_time = as_of.astimezone(TZ).time()

    rows = await conn.fetch(
        f"""
        SELECT s.id, s.first_name, s.last_name, s.auto_clock_out_cap
        FROM {settings.db_schema}.staff s
        WHERE s.is_active = TRUE
          AND s.auto_clock_out_cap <= $1::time
        """,
        local_time,
    )

    results: list[PunchResult] = []
    for staff in rows:
        last = await get_last_event(conn, staff["id"])
        if not is_clocked_in(last):
            continue
        cap_dt = combine_eastern(work_date, staff["auto_clock_out_cap"])
        if as_of < cap_dt:
            continue
        name = f"{staff['first_name']} {staff['last_name']}"
        result = await record_punch(
            conn,
            staff_id=staff["id"],
            staff_name=name,
            event_type="auto_clock_out",
            occurred_at=cap_dt,
            is_missing_clockout_flag=True,
        )
        results.append(result)
    return results
