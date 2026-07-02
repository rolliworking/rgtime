"""RS weekly-summary endpoint — read rolled-up data (Phase 8)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import DbConn
from app.rs_auth import require_rs_auth
from app.services.weekly_rollup import list_summaries

router = APIRouter(
    prefix="/weekly-summary",
    tags=["weekly-summary"],
    dependencies=[Depends(require_rs_auth)],
)


@router.get("")
async def weekly_summary(
    conn: DbConn,
    week_start_date: date = Query(...),
    staff_code: str | None = None,
) -> dict:
    summaries = await list_summaries(
        conn, week_start_date=week_start_date, staff_code=staff_code
    )
    if staff_code and not summaries:
        raise HTTPException(status_code=404, detail="no summary for staff/week")
    return {"summaries": summaries}
