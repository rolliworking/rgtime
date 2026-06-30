"""Verify locked-rules migration alters absence_reasons correctly."""

from pathlib import Path


def test_locked_rules_migration_exists():
    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20250630100000_locked_rules_absence_funding.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "DROP COLUMN is_excused" in sql
    assert "DROP COLUMN is_paid" in sql
    assert "counts_as_worked" in sql
    assert "paid_outright" in sql
    assert "Working remotely" in sql
    assert "pto_accrual_rates" in sql
    assert "reported_hours" in sql
