"""Phase 5 acceptance — biweekly audit clean/flagged sort and resolution."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import asyncpg
import pytest

from app.services.absences import upsert_absence
from app.services.biweekly_audit import build_period_audit
from app.services.pay_period import PayPeriod
from app.services.pto_draw import confirm_pto_draw, propose_pto_draw
from app.services.time_tracking import record_punch
from app.services.timesheet import resolve_missing_clockout
from app.timezone_util import combine_eastern

PERIOD_START = date(2025, 1, 6)
PERIOD_END = date(2025, 1, 19)
PERIOD = PayPeriod(PERIOD_START, PERIOD_END)


async def _reason_id(conn, name: str) -> uuid.UUID:
    rid = await conn.fetchval(
        "SELECT id FROM rgtime.absence_reasons WHERE name = $1",
        name,
    )
    assert rid is not None
    return rid


async def _seed_flagged_staff(conn) -> uuid.UUID:
    staff_id = uuid.uuid4()
    code = f"FLG{uuid.uuid4().hex[:5].upper()}"
    await conn.execute(
        """
        INSERT INTO rgtime.staff (
            id, staff_code, first_name, last_name, hire_date, pto_balance
        )
        VALUES ($1, $2, 'Flagged', 'Worker', '2020-01-01', 16.00)
        """,
        staff_id,
        code,
    )
    await conn.execute(
        """
        INSERT INTO rgtime.schedules (staff_id, scheduled_start_time, scheduled_end_time)
        VALUES ($1, '09:00:00', '17:00:00')
        """,
        staff_id,
    )

    # Week 1: Mon–Thu 8h each (32h total → under_hours)
    for day in (6, 7, 9, 10):
        d = date(2025, 1, day)
        if day == 7:
            # Late >30 min on Tue Jan 7
            cin = combine_eastern(d, datetime.strptime("09:45", "%H:%M").time())
        else:
            cin = combine_eastern(d, datetime.strptime("09:00", "%H:%M").time())
        cout = combine_eastern(d, datetime.strptime("17:30", "%H:%M").time())
        await record_punch(conn, staff_id=staff_id, staff_name="Flagged Worker", event_type="clock_in", occurred_at=cin)
        if day == 10:
            # Leave Fri Jan 10 clocked in for auto clock-out
            continue
        await record_punch(conn, staff_id=staff_id, staff_name="Flagged Worker", event_type="clock_out", occurred_at=cout)

    # Auto clock-out Fri Jan 10 → missing_clockout flag
    auto_out = combine_eastern(date(2025, 1, 10), datetime.strptime("21:00", "%H:%M").time())
    await record_punch(
        conn,
        staff_id=staff_id,
        staff_name="Flagged Worker",
        event_type="auto_clock_out",
        occurred_at=auto_out,
        is_missing_clockout_flag=True,
    )

    # No-show Wed Jan 8
    noshow_id = await _reason_id(conn, "No-show")
    await upsert_absence(
        conn,
        staff_id=staff_id,
        absence_date=date(2025, 1, 8),
        reason_id=noshow_id,
        pay_period_start=PERIOD_START,
    )

    # Week 2: full 40h Mon–Fri
    for day in range(13, 18):
        d = date(2025, 1, day)
        cin = combine_eastern(d, datetime.strptime("09:00", "%H:%M").time())
        cout = combine_eastern(d, datetime.strptime("17:30", "%H:%M").time())
        punch = await record_punch(
            conn, staff_id=staff_id, staff_name="Flagged Worker", event_type="clock_in", occurred_at=cin
        )
        if day == 13:
            await conn.execute(
                "UPDATE rgtime.time_events SET face_mismatch_flag = TRUE WHERE id = $1",
                punch.event_id,
            )
        await record_punch(
            conn, staff_id=staff_id, staff_name="Flagged Worker", event_type="clock_out", occurred_at=cout
        )

    return staff_id


async def _seed_clean_staff(conn) -> uuid.UUID:
    staff_id = uuid.uuid4()
    code = f"CLN{uuid.uuid4().hex[:5].upper()}"
    await conn.execute(
        """
        INSERT INTO rgtime.staff (
            id, staff_code, first_name, last_name, hire_date, pto_balance
        )
        VALUES ($1, $2, 'Clean', 'Worker', '2020-01-01', 8.00)
        """,
        staff_id,
        code,
    )
    await conn.execute(
        """
        INSERT INTO rgtime.schedules (staff_id, scheduled_start_time, scheduled_end_time)
        VALUES ($1, '09:00:00', '17:00:00')
        """,
        staff_id,
    )
    for day in list(range(6, 11)) + list(range(13, 18)):
        d = date(2025, 1, day)
        cin = combine_eastern(d, datetime.strptime("09:00", "%H:%M").time())
        cout = combine_eastern(d, datetime.strptime("17:30", "%H:%M").time())
        await record_punch(conn, staff_id=staff_id, staff_name="Clean Worker", event_type="clock_in", occurred_at=cin)
        await record_punch(conn, staff_id=staff_id, staff_name="Clean Worker", event_type="clock_out", occurred_at=cout)
    return staff_id


@pytest.mark.asyncio
async def test_phase5_audit_sort_and_resolution():
    from app.config import get_settings

    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            dsn=settings.database_url,
            timeout=5,
            server_settings={"search_path": "rgtime,public"},
        )
    except Exception:
        pytest.skip("DATABASE_URL not reachable")

    flagged_id = await _seed_flagged_staff(conn)
    clean_id = await _seed_clean_staff(conn)

    try:
        before = await build_period_audit(conn, PERIOD)
        flagged_entry = next(
            (s for s in before["flagged"] if s["staff_id"] == str(flagged_id)),
            None,
        )
        clean_entry = next(
            (s for s in before["clean"] if s["staff_id"] == str(clean_id)),
            None,
        )
        assert flagged_entry is not None, "flagged staff should be in flagged table"
        assert clean_entry is not None, "clean staff should be in clean table"

        flag_types = {f["flag_type"] for f in flagged_entry["flags"]}
        assert "under_hours" in flag_types
        assert "late" in flag_types
        assert "absence" in flag_types
        assert "missing_clockout" in flag_types
        assert "face_mismatch" in flag_types

        # --- resolutions ---
        absence_row = await conn.fetchrow(
            """
            SELECT a.id, r.funding FROM rgtime.absences a
            JOIN rgtime.absence_reasons r ON r.id = a.reason_id
            WHERE a.staff_id = $1 AND a.absence_date = '2025-01-08'
            """,
            flagged_id,
        )
        assert absence_row["funding"] == "unpaid_pto_coverable"

        preview = await propose_pto_draw(conn, staff_id=flagged_id, hours=Decimal("8.0"))
        assert preview["balance_before"] == "16.00"
        draw = await confirm_pto_draw(
            conn,
            staff_id=flagged_id,
            hours=Decimal("8.0"),
            work_date=date(2025, 1, 8),
            pay_period_start=PERIOD_START,
            absence_id=absence_row["id"],
            confirmed=True,
            notes="No-show covered by PTO",
        )
        assert draw["balance_after"] == "8.00"
        ledger = await conn.fetchrow(
            """
            SELECT entry_type, hours FROM rgtime.pto_ledger
            WHERE staff_id = $1 AND entry_type = 'draw'
            ORDER BY created_at DESC LIMIT 1
            """,
            flagged_id,
        )
        assert ledger["entry_type"] == "draw"
        assert Decimal(str(ledger["hours"])) == Decimal("8.0")

        auto_ev = await conn.fetchrow(
            """
            SELECT id FROM rgtime.time_events
            WHERE staff_id = $1 AND work_date = '2025-01-10'
              AND is_missing_clockout_flag = TRUE
            LIMIT 1
            """,
            flagged_id,
        )
        await resolve_missing_clockout(
            conn,
            event_id=auto_ev["id"],
            departure_time="17:30:00",
            work_date=date(2025, 1, 10),
        )

        after = await build_period_audit(conn, PERIOD)
        still_flagged = next(
            (s for s in after["flagged"] if s["staff_id"] == str(flagged_id)),
            None,
        )
        assert still_flagged is not None, "no-show covered by PTO stays flagged"
        assert any(f["flag_type"] == "absence" for f in still_flagged["flags"])

        audit_draw = await conn.fetchval(
            """
            SELECT COUNT(*) FROM rgtime.audit_log
            WHERE action = 'pto_draw' AND table_name = 'pto_ledger'
            """,
        )
        assert audit_draw >= 1

        print("\n=== BEFORE ===")
        print(f"clean: {[s['staff_code'] for s in before['clean']]}")
        print(f"flagged: {[s['staff_code'] for s in before['flagged']]}")
        for s in before["flagged"]:
            print(f"  {s['staff_code']} flags:", [f["flag_type"] for f in s["flags"]])
        print("\n=== AFTER PTO draw + missing clockout fix ===")
        print(f"PTO balance: {draw['balance_after']}")
        print(f"flagged still contains {still_flagged['staff_code']}: YES")
    finally:
        await conn.execute("DELETE FROM rgtime.staff WHERE id = ANY($1::uuid[])", [flagged_id, clean_id])
        await conn.close()


def test_pay_period_blocks():
    from app.services.pay_period import period_containing

    anchor = date(2025, 1, 6)
    p = period_containing(anchor, date(2025, 1, 15))
    assert p.start_date == date(2025, 1, 6)
    assert p.end_date == date(2025, 1, 19)
