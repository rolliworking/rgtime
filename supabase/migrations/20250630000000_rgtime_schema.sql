-- RG Time — Phase 0 schema (rgtime)
-- All workday logic uses America/New_York; timestamps stored as TIMESTAMPTZ.

CREATE SCHEMA IF NOT EXISTS rgtime;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- staff
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_code VARCHAR(16) NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    hire_date DATE NOT NULL,
    face_check_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    face_reference_photo_path TEXT,
    auto_clock_out_cap TIME NOT NULL DEFAULT '21:00:00',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    terminated_at TIMESTAMPTZ,
    pto_balance NUMERIC(10, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT staff_staff_code_format CHECK (staff_code ~ '^[A-Z0-9]{1,16}$'),
    CONSTRAINT staff_staff_code_unique UNIQUE (staff_code)
);

CREATE INDEX idx_staff_is_active ON rgtime.staff (is_active);

-- ---------------------------------------------------------------------------
-- pin_credentials (4–6 digit PIN, stored hashed)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.pin_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    pin_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pin_credentials_staff_unique UNIQUE (staff_id)
);

-- ---------------------------------------------------------------------------
-- schedule_presets
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.schedule_presets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    scheduled_start_time TIME NOT NULL,
    scheduled_end_time TIME NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT schedule_presets_name_unique UNIQUE (name)
);

-- ---------------------------------------------------------------------------
-- schedules (per-person; may reference a preset)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    preset_id UUID REFERENCES rgtime.schedule_presets (id) ON DELETE SET NULL,
    scheduled_start_time TIME NOT NULL,
    scheduled_end_time TIME NOT NULL,
    effective_from DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT schedules_staff_unique UNIQUE (staff_id)
);

-- ---------------------------------------------------------------------------
-- time_events
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.time_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    work_date DATE NOT NULL,
    is_late_arrival BOOLEAN NOT NULL DEFAULT FALSE,
    late_minutes INTEGER,
    is_missing_clockout_flag BOOLEAN NOT NULL DEFAULT FALSE,
    face_mismatch_flag BOOLEAN NOT NULL DEFAULT FALSE,
    lunch_deducted_minutes INTEGER NOT NULL DEFAULT 0,
    client_local_id TEXT,
    synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT time_events_event_type_check CHECK (
        event_type IN ('clock_in', 'clock_out', 'auto_clock_out')
    ),
    CONSTRAINT time_events_client_local_id_unique UNIQUE (client_local_id)
);

CREATE INDEX idx_time_events_staff_work_date ON rgtime.time_events (staff_id, work_date);
CREATE INDEX idx_time_events_occurred_at ON rgtime.time_events (occurred_at);

-- ---------------------------------------------------------------------------
-- punch_photos (3 per punch, ~2s apart)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.punch_photos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    time_event_id UUID NOT NULL REFERENCES rgtime.time_events (id) ON DELETE CASCADE,
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    sequence_number SMALLINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    storage_path TEXT NOT NULL,
    face_match_score NUMERIC(5, 4),
    face_match_passed BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT punch_photos_sequence_check CHECK (sequence_number BETWEEN 1 AND 3),
    CONSTRAINT punch_photos_event_sequence_unique UNIQUE (time_event_id, sequence_number)
);

-- ---------------------------------------------------------------------------
-- absence_reasons (editable library: excused/unexcused × paid/unpaid)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.absence_reasons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    is_excused BOOLEAN NOT NULL,
    is_paid BOOLEAN NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT absence_reasons_name_unique UNIQUE (name)
);

-- ---------------------------------------------------------------------------
-- absences (portal-entered; kiosk does not record absences)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.absences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    absence_date DATE NOT NULL,
    reason_id UUID NOT NULL REFERENCES rgtime.absence_reasons (id),
    notes TEXT,
    entered_by UUID,
    audit_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    pay_period_start DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT absences_staff_date_unique UNIQUE (staff_id, absence_date)
);

CREATE INDEX idx_absences_absence_date ON rgtime.absences (absence_date);

-- ---------------------------------------------------------------------------
-- pto_ledger
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.pto_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL,
    hours NUMERIC(10, 2) NOT NULL,
    balance_after NUMERIC(10, 2) NOT NULL,
    work_date DATE,
    pay_period_start DATE,
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pto_ledger_entry_type_check CHECK (
        entry_type IN ('accrual', 'draw', 'forfeiture', 'adjustment', 'cash_out')
    )
);

CREATE INDEX idx_pto_ledger_staff_created ON rgtime.pto_ledger (staff_id, created_at);

-- ---------------------------------------------------------------------------
-- audit_log (every mutating endpoint writes here)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID,
    actor_type TEXT NOT NULL,
    action TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id UUID,
    old_values JSONB,
    new_values JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT audit_log_actor_type_check CHECK (
        actor_type IN ('admin', 'system', 'kiosk')
    )
);

CREATE INDEX idx_audit_log_occurred_at ON rgtime.audit_log (occurred_at DESC);
CREATE INDEX idx_audit_log_table_record ON rgtime.audit_log (table_name, record_id);

-- ---------------------------------------------------------------------------
-- config (pay_period_anchor_date, expected_workdays_per_year, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID
);

-- ---------------------------------------------------------------------------
-- weekly_summary (nightly rollup for RS integration)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.weekly_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID NOT NULL REFERENCES rgtime.staff (id) ON DELETE CASCADE,
    staff_code VARCHAR(16) NOT NULL,
    week_start_date DATE NOT NULL,
    week_end_date DATE NOT NULL,
    hours_worked NUMERIC(10, 2) NOT NULL DEFAULT 0,
    days_attended INTEGER NOT NULL DEFAULT 0,
    days_missed INTEGER NOT NULL DEFAULT 0,
    days_excused INTEGER NOT NULL DEFAULT 0,
    late_arrivals INTEGER,
    weekly_target_hours NUMERIC(10, 2),
    summary_computed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT weekly_summary_staff_week_unique UNIQUE (staff_code, week_start_date)
);

CREATE INDEX idx_weekly_summary_week_start ON rgtime.weekly_summary (week_start_date);

-- ---------------------------------------------------------------------------
-- updated_at trigger helper
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION rgtime.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER staff_set_updated_at
    BEFORE UPDATE ON rgtime.staff
    FOR EACH ROW EXECUTE FUNCTION rgtime.set_updated_at();

CREATE TRIGGER pin_credentials_set_updated_at
    BEFORE UPDATE ON rgtime.pin_credentials
    FOR EACH ROW EXECUTE FUNCTION rgtime.set_updated_at();

CREATE TRIGGER schedules_set_updated_at
    BEFORE UPDATE ON rgtime.schedules
    FOR EACH ROW EXECUTE FUNCTION rgtime.set_updated_at();

CREATE TRIGGER absence_reasons_set_updated_at
    BEFORE UPDATE ON rgtime.absence_reasons
    FOR EACH ROW EXECUTE FUNCTION rgtime.set_updated_at();

CREATE TRIGGER absences_set_updated_at
    BEFORE UPDATE ON rgtime.absences
    FOR EACH ROW EXECUTE FUNCTION rgtime.set_updated_at();

-- ---------------------------------------------------------------------------
-- seed defaults
-- ---------------------------------------------------------------------------
INSERT INTO rgtime.config (key, value, description) VALUES
    ('pay_period_anchor_date', '"2025-01-06"'::jsonb, 'First biweekly pay period start (Monday)'),
    ('expected_workdays_per_year', '260'::jsonb, 'Denominator for per-day PTO accrual from annual allotment'),
    ('timezone', '"America/New_York"'::jsonb, 'Workday and week-boundary timezone')
ON CONFLICT (key) DO NOTHING;

INSERT INTO rgtime.schedule_presets (name, scheduled_start_time, scheduled_end_time) VALUES
    ('9-5', '09:00:00', '17:00:00'),
    ('8:30-4:30', '08:30:00', '16:30:00'),
    ('8-4', '08:00:00', '16:00:00')
ON CONFLICT (name) DO NOTHING;

INSERT INTO rgtime.absence_reasons (name, is_excused, is_paid) VALUES
    ('Requested time off', TRUE, TRUE),
    ('Vacation', TRUE, TRUE),
    ('Holiday', TRUE, TRUE),
    ('Natural disaster', TRUE, TRUE),
    ('No-show', FALSE, FALSE),
    ('Sick (unexcused)', FALSE, FALSE)
ON CONFLICT (name) DO NOTHING;
