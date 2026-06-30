#!/usr/bin/env python3
"""Print rgtime schema DDL and table/column inventory from migration file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20250630000000_rgtime_schema.sql"

TABLES = [
    "staff",
    "pin_credentials",
    "schedule_presets",
    "schedules",
    "time_events",
    "punch_photos",
    "absence_reasons",
    "absences",
    "pto_ledger",
    "audit_log",
    "config",
    "weekly_summary",
]


def main() -> int:
    if not MIGRATION.exists():
        print(f"Migration not found: {MIGRATION}", file=sys.stderr)
        return 1

    sql = MIGRATION.read_text(encoding="utf-8")
    print("=" * 72)
    print("RG Time — rgtime schema (from migration)")
    print("=" * 72)
    print(sql)
    print("=" * 72)
    print("TABLE INVENTORY")
    print("=" * 72)

    for table in TABLES:
        pattern = rf"CREATE TABLE rgtime\.{table}\s*\((.*?)\);"
        match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
        if not match:
            print(f"  MISSING: rgtime.{table}")
            continue
        body = match.group(1)
        cols = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith("CONSTRAINT"):
                continue
            col = line.split()[0]
            cols.append(col)
        print(f"\nrgtime.{table} ({len(cols)} columns)")
        for col in cols:
            print(f"  - {col}")

    print("\n" + "=" * 72)
    found = sum(1 for t in TABLES if f"CREATE TABLE rgtime.{t}" in sql)
    print(f"\nTables found: {found}/{len(TABLES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
