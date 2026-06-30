"""Kiosk API — PIN auth and clock in/out."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.audit import write_audit_log
from app.dependencies import DbConn, get_actor_type
from app.pin import validate_pin_format
from app.services.photos import save_punch_photos
from app.services.time_tracking import (
    get_last_event,
    get_staff_by_pin,
    is_clocked_in,
    next_event_type,
    record_punch,
    run_auto_clock_outs,
)
from app.timezone_util import now_eastern
from fastapi import Depends, Request

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


class PinBody(BaseModel):
    pin: str = Field(min_length=4, max_length=6)


class PhotoPayload(BaseModel):
    sequence_number: int = Field(ge=1, le=3)
    captured_at: str
    data_base64: str


class PunchBody(PinBody):
    photos: list[PhotoPayload] = Field(default_factory=list, max_length=3)


class KioskStateResponse(BaseModel):
    staff_id: UUID
    staff_code: str
    display_name: str
    is_clocked_in: bool
    next_action: str


class PunchResponse(BaseModel):
    event_id: UUID
    event_type: str
    occurred_at: datetime
    work_date: str
    is_late_arrival: bool
    late_minutes: int | None
    lunch_deducted_minutes: int
    is_missing_clockout_flag: bool
    photos_saved: int
    confirmation: str


@router.post("/state", response_model=KioskStateResponse)
async def kiosk_state(body: PinBody, conn: DbConn) -> KioskStateResponse:
    validate_pin_format(body.pin)
    staff = await get_staff_by_pin(conn, body.pin)
    if staff is None:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    last = await get_last_event(conn, staff["id"])
    clocked_in = is_clocked_in(last)
    return KioskStateResponse(
        staff_id=staff["id"],
        staff_code=staff["staff_code"],
        display_name=f"{staff['first_name']} {staff['last_name']}",
        is_clocked_in=clocked_in,
        next_action="clock_out" if clocked_in else "clock_in",
    )


@router.post("/punch", response_model=PunchResponse)
async def kiosk_punch(
    body: PunchBody,
    conn: DbConn,
    request: Request,
    actor_type: str = Depends(get_actor_type),
) -> PunchResponse:
    validate_pin_format(body.pin)
    staff = await get_staff_by_pin(conn, body.pin)
    if staff is None:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    # Enforce auto-clock-out before new punches when past cap.
    await run_auto_clock_outs(conn, now_eastern())

    last = await get_last_event(conn, staff["id"])
    event_type = next_event_type(last)
    occurred_at = now_eastern()
    display_name = f"{staff['first_name']} {staff['last_name']}"

    result = await record_punch(
        conn,
        staff_id=staff["id"],
        staff_name=display_name,
        event_type=event_type,
        occurred_at=occurred_at,
    )

    photos_saved = await save_punch_photos(
        conn,
        time_event_id=result.event_id,
        staff_id=staff["id"],
        photos=[p.model_dump() for p in body.photos],
    )

    await write_audit_log(
        conn,
        actor_type="kiosk",
        action="punch",
        table_name="time_events",
        record_id=result.event_id,
        new_values={
            "staff_id": str(staff["id"]),
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "is_late_arrival": result.is_late_arrival,
            "lunch_deducted_minutes": result.lunch_deducted_minutes,
            "photos_saved": photos_saved,
        },
    )

    return PunchResponse(
        event_id=result.event_id,
        event_type=result.event_type,
        occurred_at=result.occurred_at,
        work_date=str(result.work_date),
        is_late_arrival=result.is_late_arrival,
        late_minutes=result.late_minutes,
        lunch_deducted_minutes=result.lunch_deducted_minutes,
        is_missing_clockout_flag=result.is_missing_clockout_flag,
        photos_saved=photos_saved,
        confirmation=result.confirmation,
    )


@router.post("/auto-clock-out/run")
async def trigger_auto_clock_out(conn: DbConn) -> dict:
    """Manual trigger for tests and scheduled jobs."""
    results = await run_auto_clock_outs(conn, now_eastern())
    return {"closed": len(results), "events": [str(r.event_id) for r in results]}
