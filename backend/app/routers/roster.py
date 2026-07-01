"""Staff roster REST — consumer apps pull authoritative staff from RG Time."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import DbConn
from app.rs_auth import require_rs_auth
from app.services.staff_roster import get_roster_member, list_active_roster

router = APIRouter(
    prefix="/staff",
    tags=["staff-roster"],
    dependencies=[Depends(require_rs_auth)],
)


@router.get("/roster")
async def staff_roster(conn: DbConn) -> dict:
    return {"staff": await list_active_roster(conn)}


@router.get("/{staff_code}")
async def staff_by_code(staff_code: str, conn: DbConn) -> dict:
    member = await get_roster_member(conn, staff_code)
    if member is None:
        raise HTTPException(status_code=404, detail="staff not found")
    return member
