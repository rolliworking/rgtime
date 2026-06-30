"""Core time-tracking logic for kiosk punches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.timezone_util import TZ, combine_eastern, work_date_for

LUNCH_DEDUCT_MINUTES = 30
# Lunch disambiguation (§2): clock_out→clock_in pairs with gap ≤ this many whole
# minutes count as a lunch break. Longer gaps are leave-and-return re-entries.
LUNCH_BREAK_MAX_GAP_MINUTES = 120
LATENESS_FLAG_THRESHOLD_MINUTES = 31  # 30 min late is on-time; flag at 31+


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


def minutes_late_floor(clock_in: datetime, scheduled_start: datetime) -> int:
    """Whole minutes late; seconds truncated before compare (locked §1)."""
    delta = clock_in.astimezone(TZ) - scheduled_start.astimezone(TZ)
    return max(0, int(delta.total_seconds() // 60))


def compute_lateness(
    occurred_at: datetime,
    work_date: date,
    schedule: ScheduleInfo | None,
) -> tuple[bool, int | None]:
    """Flag late only when minutes_late >= 31 (30 and under is on-time)."""
    if schedule is None:
        return False, None
    scheduled_start = combine_eastern(work_date, schedule.scheduled_start_time)
    minutes_late = minutes_late_floor(occurred_at, scheduled_start)
    if minutes_late < LATENESS_FLAG_THRESHOLD_MINUTES:
        return False, None
    return True, minutes_late


def gap_minutes_floor(earlier: datetime, later: datetime) -> int:
    """Whole minutes between two timestamps; seconds truncated."""
    delta = later.astimezone(TZ) - earlier.astimezone(TZ)
    return max(0, int(delta.total_seconds() // 60))


def is_lunch_break_pair(clock_out_at: datetime, clock_in_at: datetime) -> bool:
    """
    Duration heuristic (locked §2): a clock_out→clock_in pair is a lunch break
    when the gap is > 0 and <= LUNCH_BREAK_MAX_GAP_MINUTES. Longer gaps are
    treated as leave-and-return (evening re-entry), not lunch.
    """
    gap = gap_minutes_floor(clock_out_at, clock_in_at)
    return 0 < gap <= LUNCH_BREAK_MAX_GAP_MINUTES


def day_has_lunch_punch(events: list[asyncpg.Record]) -> bool:
    """True if any clock_out→clock_in pair qualifies as a lunch break."""
    for i in range(len(events) - 1):
        out_ev = events[i]
        in_ev = events[i + 1]
        if out_ev["event_type"] != "clock_out":
            continue
        if in_ev["event_type"] != "clock_in":
            continue
        if is_lunch_break_pair(out_ev["occurred_at"], in_ev["occurred_at"]):
            return True
    return False


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


async def get_punch_by_client_local_id(
    conn: asyncpg.Connection, client_local_id: str
) -> PunchResult | None:
    settings = get_settings()
    row = await conn.fetchrow(
        f"""
        SELECT id, event_type, occurred_at, work_date, is_late_arrival, late_minutes,
               lunch_deducted_minutes, is_missing_clockout_flag
        FROM {settings.db_schema}.time_events
        WHERE client_local_id = $1
        """,
        client_local_id,
    )
    if row is None:
        return None
    local = row["occurred_at"].astimezone(TZ)
    time_str = local.strftime("%I:%M %p").lstrip("0")
    et = row["event_type"]
    if et == "clock_in":
        confirmation = f"Clocked in at {time_str}"
    elif et == "auto_clock_out":
        confirmation = f"Auto clocked out at {time_str} — flagged for manager review"
    else:
        confirmation = f"Clocked out at {time_str}"
    return PunchResult(
        event_id=row["id"],
        event_type=et,
        occurred_at=row["occurred_at"],
        work_date=row["work_date"],
        is_late_arrival=row["is_late_arrival"],
        late_minutes=row["late_minutes"],
        lunch_deducted_minutes=row["lunch_deducted_minutes"],
        is_missing_clockout_flag=row["is_missing_clockout_flag"],
        confirmation=confirmation,
    )


async def record_punch(
    conn: asyncpg.Connection,
    *,
    staff_id: UUID,
    staff_name: str,
    event_type: str,
    occurred_at: datetime,
    is_missing_clockout_flag: bool = False,
    client_local_id: str | None = None,
    mark_synced: bool = False,
) -> PunchResult:
    settings = get_settings()
    if client_local_id:
        existing = await get_punch_by_client_local_id(conn, client_local_id)
        if existing is not None:
            return existing
    # work_date is always the America/New_York calendar date of occurred_at (§3).
    work_date = work_date_for(occurred_at)
    schedule = await get_schedule(conn, staff_id)

    is_late = False
    late_minutes: int | None = None
    if event_type == "clock_in":
        # Lateness applies only to the first clock_in on this work_date (§3).
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
            lunch_deducted_minutes, client_local_id, synced_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
        client_local_id,
        datetime.now(TZ) if mark_synced or client_local_id else None,
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
