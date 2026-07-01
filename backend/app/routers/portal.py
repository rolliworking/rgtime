"""Portal API — staff, schedules, PINs, face enrollment, absence reasons."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import DbConn, get_actor_type
from app.portal_auth import require_portal_auth
from app.services.absence_reasons import create_reason, list_reasons, update_reason
from app.services.face_reference import save_face_reference
from app.services.offer_templates import create_template, get_template, list_templates
from app.services.pto_ladder import (
    get_active_ladder,
    list_ladder_versions,
    sync_annual_and_rate,
    upsert_ladder_tier,
)
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
    set_pto_offer,
    set_staff_pin,
    suggest_staff_code,
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
    pto_offer_type: str = "default"
    pto_tenure_credit_years: int | None = None
    pto_custom_annual_hours: str | None = None
    pto_custom_daily_rate: str | None = None
    save_offer_template: bool = False
    offer_template_name: str | None = None


class StaffUpdateBody(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    hire_date: date | None = None
    auto_clock_out_cap: str | None = None
    face_check_enabled: bool | None = None


class PtoOfferBody(BaseModel):
    pto_offer_type: str
    pto_tenure_credit_years: int | None = None
    pto_custom_annual_hours: str | None = None
    pto_custom_daily_rate: str | None = None
    template_id: UUID | None = None
    save_as_template: bool = False
    template_name: str | None = None


class OfferTemplateCreateBody(BaseModel):
    name: str
    offer_type: str
    tenure_credit_years: int | None = None
    pto_custom_annual_hours: str | None = None
    pto_custom_daily_rate: str | None = None


class LadderTierUpdateBody(BaseModel):
    min_years: int
    max_years: int | None = None
    tier_label: str
    annual_pto_hours: int | None = None
    rate_per_qualifying_day: str | None = None
    effective_from: date
    confirmed: bool = False


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


    return time(h, m, s)


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(value)


async def _resolve_offer_from_body(
    conn: asyncpg.Connection,
    body: PtoOfferBody,
) -> tuple[str, int | None, Decimal | None, Decimal | None]:
    if body.template_id is not None:
        tpl = await get_template(conn, body.template_id)
        if tpl is None:
            raise HTTPException(status_code=404, detail="template not found")
        if tpl["offer_type"] == "tenure_credit":
            return "tenure_credit", tpl["tenure_credit_years"], None, None
        return (
            "custom_rate",
            None,
            Decimal(str(tpl["custom_annual_hours"])) if tpl.get("custom_annual_hours") else None,
            Decimal(str(tpl["custom_daily_rate"])) if tpl.get("custom_daily_rate") else None,
        )
    return (
        body.pto_offer_type,
        body.pto_tenure_credit_years,
        _optional_decimal(body.pto_custom_annual_hours),
        _optional_decimal(body.pto_custom_daily_rate),
    )


@router.get("/staff/suggest-code")
async def portal_suggest_staff_code(
    conn: DbConn,
    first_name: str,
    last_name: str = "",
) -> dict:
    code = await suggest_staff_code(conn, first_name=first_name, last_name=last_name)
    return {"staff_code": code}


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
            pto_offer_type=body.pto_offer_type,
            pto_tenure_credit_years=body.pto_tenure_credit_years,
            pto_custom_annual_hours=_optional_decimal(body.pto_custom_annual_hours),
            pto_custom_daily_rate=_optional_decimal(body.pto_custom_daily_rate),
        )
        if body.save_offer_template and body.offer_template_name and body.pto_offer_type != "default":
            await create_template(
                conn,
                name=body.offer_template_name,
                offer_type=body.pto_offer_type,
                tenure_credit_years=body.pto_tenure_credit_years,
                custom_annual_hours=_optional_decimal(body.pto_custom_annual_hours),
                custom_daily_rate=_optional_decimal(body.pto_custom_daily_rate),
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


@router.put("/staff/{staff_id}/pto-offer")
async def portal_set_pto_offer(
    staff_id: UUID,
    body: PtoOfferBody,
    conn: DbConn,
) -> dict:
    try:
        offer_type, credit, annual, daily = await _resolve_offer_from_body(conn, body)
        staff = await set_pto_offer(
            conn,
            staff_id=staff_id,
            pto_offer_type=offer_type,
            pto_tenure_credit_years=credit,
            pto_custom_annual_hours=annual,
            pto_custom_daily_rate=daily,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if staff is None:
        raise HTTPException(status_code=404, detail="staff not found")
    if body.save_as_template and body.template_name and offer_type != "default":
        await create_template(
            conn,
            name=body.template_name,
            offer_type=offer_type,
            tenure_credit_years=credit,
            custom_annual_hours=annual,
            custom_daily_rate=daily,
        )
    return staff


@router.get("/offer-templates")
async def portal_list_offer_templates(conn: DbConn) -> dict:
    return {"templates": await list_templates(conn)}


@router.post("/offer-templates", status_code=201)
async def portal_create_offer_template(
    body: OfferTemplateCreateBody,
    conn: DbConn,
) -> dict:
    try:
        return await create_template(
            conn,
            name=body.name,
            offer_type=body.offer_type,
            tenure_credit_years=body.tenure_credit_years,
            custom_annual_hours=_optional_decimal(body.pto_custom_annual_hours),
            custom_daily_rate=_optional_decimal(body.pto_custom_daily_rate),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="template name already exists") from e


@router.get("/pto-ladder")
async def portal_get_pto_ladder(conn: DbConn) -> dict:
    return {
        "active": await get_active_ladder(conn),
        "history": await list_ladder_versions(conn),
    }


@router.put("/pto-ladder")
async def portal_update_pto_ladder(
    body: LadderTierUpdateBody,
    conn: DbConn,
) -> dict:
    try:
        annual, rate = sync_annual_and_rate(
            annual_pto_hours=body.annual_pto_hours,
            rate_per_qualifying_day=(
                Decimal(body.rate_per_qualifying_day)
                if body.rate_per_qualifying_day
                else None
            ),
        )
        return await upsert_ladder_tier(
            conn,
            min_years=body.min_years,
            max_years=body.max_years,
            tier_label=body.tier_label,
            annual_pto_hours=annual,
            rate_per_qualifying_day=rate,
            effective_from=body.effective_from,
            confirmed=body.confirmed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
