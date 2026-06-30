-- RG Time — Locked rules §4: absence_reasons funding axis + reseed
-- Also seeds authoritative PTO accrual rates (§1) and adds reported_hours for remote days (§6).

-- Clear legacy Phase 0 reasons (no production absences yet).
DELETE FROM rgtime.absence_reasons;

ALTER TABLE rgtime.absence_reasons
    DROP COLUMN is_excused,
    DROP COLUMN is_paid;

ALTER TABLE rgtime.absence_reasons
    ADD COLUMN funding TEXT NOT NULL
        CONSTRAINT absence_reasons_funding_check CHECK (
            funding IN (
                'paid_outright',
                'paid_from_pto',
                'unpaid_pto_coverable',
                'unpaid'
            )
        ),
    ADD COLUMN counts_as_worked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN rgtime.absence_reasons.funding IS
    'paid_outright | paid_from_pto | unpaid_pto_coverable | unpaid';
COMMENT ON COLUMN rgtime.absence_reasons.counts_as_worked IS
    'True only for working remotely; accrual keys off this + hours threshold';

-- Manager-entered hours for counts_as_worked days (e.g. working remotely); no kiosk punch.
ALTER TABLE rgtime.absences
    ADD COLUMN reported_hours NUMERIC(10, 2);

COMMENT ON COLUMN rgtime.absences.reported_hours IS
    'Audit-entered hours for counts_as_worked absence days; required before PTO accrual eval';

-- Authoritative PTO accrual rate table (§1) — literals, not computed at runtime.
INSERT INTO rgtime.config (key, value, description) VALUES
    (
        'pto_accrual_rates',
        '[
            {"tenure_label": "Yr 0-1", "min_years": 0, "max_years": 1, "annual_pto_hours": 0, "rate_per_qualifying_day": 0.000},
            {"tenure_label": "Yr 1-2", "min_years": 1, "max_years": 2, "annual_pto_hours": 8, "rate_per_qualifying_day": 0.031},
            {"tenure_label": "Yr 2-3", "min_years": 2, "max_years": 3, "annual_pto_hours": 16, "rate_per_qualifying_day": 0.062},
            {"tenure_label": "Yr 3-4", "min_years": 3, "max_years": 4, "annual_pto_hours": 24, "rate_per_qualifying_day": 0.092},
            {"tenure_label": "Yr 4-5", "min_years": 4, "max_years": 5, "annual_pto_hours": 32, "rate_per_qualifying_day": 0.123},
            {"tenure_label": "Yr 5+", "min_years": 5, "max_years": null, "annual_pto_hours": 40, "rate_per_qualifying_day": 0.154}
        ]'::jsonb,
        'AUTHORITATIVE PTO rates per qualifying day by tenure tier — apply literals directly'
    )
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    description = EXCLUDED.description,
    updated_at = now();

UPDATE rgtime.config
SET description = 'Provenance note only (260 workdays/year); engine uses pto_accrual_rates literals'
WHERE key = 'expected_workdays_per_year';

-- Locked rules §4 seeded reason library
INSERT INTO rgtime.absence_reasons (name, funding, counts_as_worked) VALUES
    ('Holiday', 'paid_outright', FALSE),
    ('Vacation', 'paid_from_pto', FALSE),
    ('Sick', 'unpaid_pto_coverable', FALSE),
    ('No-show', 'unpaid_pto_coverable', FALSE),
    ('Suspended', 'unpaid', FALSE),
    ('Working remotely', 'paid_outright', TRUE);
