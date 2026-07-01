#!/usr/bin/env python3
"""Verify cloud rgtime schema after migrations (reads DATABASE_URL from env or backend/.env)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

try:
    import asyncpg
except ImportError:
    print("Install deps: pip install asyncpg python-dotenv")
    sys.exit(1)

# Load backend/.env if present
env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

DSN = os.environ.get("DATABASE_URL")
if not DSN:
    print("ERROR: DATABASE_URL not set. Copy backend/.env.example → backend/.env")
    sys.exit(1)

EXPECTED_TABLES = {
    "absence_reasons",
    "absences",
    "audit_log",
    "config",
    "offer_templates",
    "pin_credentials",
    "pto_ladder_rates",
    "pto_ledger",
    "punch_photos",
    "schedule_presets",
    "schedules",
    "staff",
    "sync_failures",
    "time_events",
    "weekly_summary",
}

EXPECTED_REASONS = {
    "Holiday",
    "Vacation",
    "Sick",
    "No-show",
    "Suspended",
    "Working remotely",
}


async def main() -> int:
    conn = await asyncpg.connect(DSN, server_settings={"search_path": "rgtime,public"})
    tables = {
        r["table_name"]
        for r in await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'rgtime'
            """
        )
    }
    print(f"Tables in rgtime: {len(tables)}")
    missing = EXPECTED_TABLES - tables
    extra = tables - EXPECTED_TABLES
    if missing:
        print(f"  MISSING: {sorted(missing)}")
    if extra:
        print(f"  EXTRA: {sorted(extra)}")

    cols = {
        r["column_name"]
        for r in await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'rgtime' AND table_name = 'absence_reasons'
            """
        )
    }
    bad_cols = {"is_excused", "is_paid"} & cols
    need_cols = {"funding", "counts_as_worked"} <= cols
    print(f"absence_reasons columns OK (§4): {need_cols and not bad_cols}")
    if bad_cols:
        print(f"  OLD columns still present: {bad_cols}")

    reasons = await conn.fetch(
        "SELECT name, funding, counts_as_worked FROM rgtime.absence_reasons ORDER BY name"
    )
    print(f"absence_reasons rows: {len(reasons)}")
    for r in reasons:
        print(f"  {r['name']}: {r['funding']}, counts_as_worked={r['counts_as_worked']}")

    names = {r["name"] for r in reasons}
    if names != EXPECTED_REASONS:
        print(f"  Expected names: {EXPECTED_REASONS}")
        print(f"  Got: {names}")

    config_keys = [
        r["key"] for r in await conn.fetch("SELECT key FROM rgtime.config ORDER BY key")
    ]
    print(f"config keys ({len(config_keys)}): {config_keys}")
    has_pto_rates = "pto_accrual_rates" in config_keys

    presets = await conn.fetchval("SELECT COUNT(*) FROM rgtime.schedule_presets")
    print(f"schedule_presets: {presets}")

    await conn.close()

    ok = (
        EXPECTED_TABLES <= tables
        and need_cols
        and not bad_cols
        and names == EXPECTED_REASONS
        and has_pto_rates
        and presets == 3
    )
    print("\n" + ("PASS" if ok else "FAIL — run migrations or check DATABASE_URL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
