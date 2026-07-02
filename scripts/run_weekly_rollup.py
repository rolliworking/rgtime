#!/usr/bin/env python3
"""Nightly weekly-summary rollup (run via cron / Task Scheduler)."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# Load backend/.env
env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        import os

        os.environ.setdefault(k.strip(), v.strip())

import asyncpg  # noqa: E402

from app.services.weekly_rollup import monday_on_or_before, rollup_week  # noqa: E402


async def main() -> int:
    from app.config import get_settings

    settings = get_settings()
    week_start = monday_on_or_before(date.today())
    conn = await asyncpg.connect(
        settings.database_url,
        server_settings={"search_path": f"{settings.db_schema},public"},
    )
    try:
        result = await rollup_week(conn, week_start=week_start)
        print(result)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
