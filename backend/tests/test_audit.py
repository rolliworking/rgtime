"""Tests for audit_log wiring."""

from __future__ import annotations

import inspect

from app.audit import write_audit_log
from app.routers import config as config_router


def test_write_audit_log_is_async():
    assert inspect.iscoroutinefunction(write_audit_log)


def test_config_update_calls_write_audit_log():
    source = inspect.getsource(config_router.update_config)
    assert "write_audit_log" in source


def test_audit_log_table_in_migration():
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20250630000000_rgtime_schema.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE rgtime.audit_log" in sql
    for col in ("actor_id", "actor_type", "action", "table_name", "record_id", "old_values", "new_values"):
        assert col in sql
