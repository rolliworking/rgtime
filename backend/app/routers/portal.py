"""Portal API — staff, schedules, PINs, face enrollment, absence reasons."""

from __future__ import annotations

from datetime import date, time
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import DbConn, get_actor_type
from app.portal_auth import require_portal_auth
from app.services.absence_reasons import create_reason, list_reasons, update_reason
from app.services.face_reference import save_face_reference
from app.services.schedules import (
    create_preset,
    get_staff_schedule,
    list_presets,
    set_staff_schedule,
    update_preset,
)
from app.services.staff import (
    create_staff,
    get_staff,
    list_staff,
    set_staff_pin,
    terminate_staff,
    update_staff,
)

router = APIRouter(
    prefix="/portal",
    tags=["portal"],
    dependencies=[Depends(require_portal_auth)],
)


class StaffCreateBody(BaseModel):
    staff_code: str = Field(max_length=16)
    first_name: str
    last_name: str
    hire_date: date
    auto_clock_out_cap: str = "21:00:00"
    face_check_enabled: bool = False


class StaffUpdateBody(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    hire_date: date | None = None
    auto_clock_out_cap: str | None = None
    face_check_enabled: bool | None = None


class PinBody(BaseModel):
    pin: str = Field(min_length=4, max_length=6)


class FaceReferenceBody(BaseModel):
    data_base64: str
    captured_at: str | None = None


class PresetCreateBody(BaseModel):
    name: str
    scheduled_start_time: str
    scheduled_end_time: str


class PresetUpdateBody(BaseModel):
    name: str | None = None
    scheduled_start_time: str | None = None
    scheduled_end_time: str | None = None


class ScheduleSetBody(BaseModel):
    preset_id: UUID | None = None
    scheduled_start_time: str | None = None
    scheduled_end_time: str | None = None
    effective_from: date | None = None


class ReasonCreateBody(BaseModel):
    name: str
    funding: str
    counts_as_worked: bool = False


class ReasonUpdateBody(BaseModel):
    name: str | None = None
    funding: str | None = None
    counts_as_worked: bool | None = None
    is_active: bool | None = None


def _parse_time(value: str) -> time:
    parts = value.split(":")
    if len(parts) < 2:
        raise ValueError("time must be HH:MM or HH:MM:SS")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(h, m, s)


@router.get("/staff")
async def portal_list_staff(
    conn: DbConn,
    include_terminated: bool = False,
) -> dict:
    staff = await list_staff(conn, include_terminated=include_terminated)
    return {"staff": staff}


@router.post("/staff", status_code=201)
async def portal_create_staff(
    body: StaffCreateBody,
    conn: DbConn,
    actor_type: str = Depends(get_actor_type),
) -> dict:
    try:
        staff = await create_staff(
            conn,
            staff_code=body.staff_code,
            first_name=body.first_name,
            last_name=body.last_name,
            hire_date=body.hire_date,
            auto_clock_out_cap=_parse_time(body.auto_clock_out_cap),
            face_check_enabled=body.face_check_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="staff_code already in use") from e
    return staff


@router.get("/staff/{staff_id}")
async def portal_get_staff(staff_id: UUID, conn: DbConn) -> dict:
    staff = await get_staff(conn, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    schedule = await get_staff_schedule(conn, staff_id)
    return {"staff": staff, "schedule": schedule}


@router.put("/staff/{staff_id}")
async def portal_update_staff(
    staff_id: UUID,
    body: StaffUpdateBody,
    conn: DbConn,
) -> dict:
    try:
        cap = _parse_time(body.auto_clock_out_cap) if body.auto_clock_out_cap else None
        staff = await update_staff(
            conn,
            staff_id=staff_id,
            first_name=body.first_name,
            last_name=body.last_name,
            hire_date=body.hire_date,
            auto_clock_out_cap=cap,
            face_check_enabled=body.face_check_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    return staff


@router.post("/staff/{staff_id}/terminate")
async def portal_terminate_staff(staff_id: UUID, conn: DbConn) -> dict:
    staff = await terminate_staff(conn, staff_id=staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    return staff


@router.put("/staff/{staff_id}/pin")
async def portal_set_pin(staff_id: UUID, body: PinBody, conn: DbConn) -> dict:
    staff = await get_staff(conn, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    try:
        await set_staff_pin(conn, staff_id=staff_id, pin=body.pin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "has_pin": True}


@router.post("/staff/{staff_id}/face-reference")
async def portal_face_reference(
    staff_id: UUID,
    body: FaceReferenceBody,
    conn: DbConn,
) -> dict:
    staff = await get_staff(conn, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    try:
        path = await save_face_reference(
            conn,
            staff_id=staff_id,
            data_base64=body.data_base64,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid image: {e}") from e
    return {"face_reference_photo_path": path}


@router.get("/schedule-presets")
async def portal_list_presets(conn: DbConn) -> dict:
    return {"presets": await list_presets(conn)}


@router.post("/schedule-presets", status_code=201)
async def portal_create_preset(body: PresetCreateBody, conn: DbConn) -> dict:
    try:
        return await create_preset(
            conn,
            name=body.name,
            scheduled_start_time=_parse_time(body.scheduled_start_time),
            scheduled_end_time=_parse_time(body.scheduled_end_time),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/schedule-presets/{preset_id}")
async def portal_update_preset(
    preset_id: UUID,
    body: PresetUpdateBody,
    conn: DbConn,
) -> dict:
    try:
        preset = await update_preset(
            conn,
            preset_id=preset_id,
            name=body.name,
            scheduled_start_time=_parse_time(body.scheduled_start_time)
            if body.scheduled_start_time
            else None,
            scheduled_end_time=_parse_time(body.scheduled_end_time)
            if body.scheduled_end_time
            else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if preset is None:
        raise HTTPException(status_code=404, detail="preset not found")
    return preset


@router.put("/staff/{staff_id}/schedule")
async def portal_set_schedule(
    staff_id: UUID,
    body: ScheduleSetBody,
    conn: DbConn,
) -> dict:
    staff = await get_staff(conn, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    try:
        return await set_staff_schedule(
            conn,
            staff_id=staff_id,
            preset_id=body.preset_id,
            scheduled_start_time=_parse_time(body.scheduled_start_time)
            if body.scheduled_start_time
            else None,
            scheduled_end_time=_parse_time(body.scheduled_end_time)
            if body.scheduled_end_time
            else None,
            effective_from=body.effective_from,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/absence-reasons")
async def portal_list_reasons(conn: DbConn, active_only: bool = True) -> dict:
    return {"reasons": await list_reasons(conn, active_only=active_only)}


@router.post("/absence-reasons", status_code=201)
async def portal_create_reason(body: ReasonCreateBody, conn: DbConn) -> dict:
    try:
        return await create_reason(
            conn,
            name=body.name,
            funding=body.funding,
            counts_as_worked=body.counts_as_worked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/absence-reasons/{reason_id}")
async def portal_update_reason(
    reason_id: UUID,
    body: ReasonUpdateBody,
    conn: DbConn,
) -> dict:
    try:
        reason = await update_reason(
            conn,
            reason_id=reason_id,
            name=body.name,
            funding=body.funding,
            counts_as_worked=body.counts_as_worked,
            is_active=body.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if reason is None:
        raise HTTPException(status_code=404, detail="reason not found")
    return reason
