-- Phase 4.5: PTO offer flexibility, editable ladder, offer templates

-- ---------------------------------------------------------------------------
-- staff: per-person PTO offer override
-- ---------------------------------------------------------------------------
ALTER TABLE rgtime.staff
    ADD COLUMN pto_offer_type TEXT NOT NULL DEFAULT 'default'
        CONSTRAINT staff_pto_offer_type_check CHECK (
            pto_offer_type IN ('default', 'tenure_credit', 'custom_rate')
        ),
    ADD COLUMN pto_tenure_credit_years INTEGER
        CONSTRAINT staff_pto_tenure_credit_nonneg CHECK (
            pto_tenure_credit_years IS NULL OR pto_tenure_credit_years >= 0
        ),
    ADD COLUMN pto_custom_annual_hours NUMERIC(10, 3),
    ADD COLUMN pto_custom_daily_rate NUMERIC(10, 3);

COMMENT ON COLUMN rgtime.staff.pto_offer_type IS
    'default | tenure_credit | custom_rate — three-layer PTO resolution';
COMMENT ON COLUMN rgtime.staff.pto_tenure_credit_years IS
    'Tenure credit years when pto_offer_type = tenure_credit';
COMMENT ON COLUMN rgtime.staff.pto_custom_annual_hours IS
    'Flat annual PTO hours when pto_offer_type = custom_rate';
COMMENT ON COLUMN rgtime.staff.pto_custom_daily_rate IS
    'Explicit per-qualifying-day rate when pto_offer_type = custom_rate';

-- ---------------------------------------------------------------------------
-- offer_templates: reusable custom PTO offers
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.offer_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    offer_type TEXT NOT NULL
        CONSTRAINT offer_templates_offer_type_check CHECK (
            offer_type IN ('tenure_credit', 'custom_rate')
        ),
    tenure_credit_years INTEGER
        CONSTRAINT offer_templates_tenure_credit_nonneg CHECK (
            tenure_credit_years IS NULL OR tenure_credit_years >= 0
        ),
    custom_annual_hours NUMERIC(10, 3),
    custom_daily_rate NUMERIC(10, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,
    CONSTRAINT offer_templates_name_unique UNIQUE (name)
);

-- ---------------------------------------------------------------------------
-- pto_ladder_rates: effective-dated tenure ladder (replaces runtime-only literals)
-- ---------------------------------------------------------------------------
CREATE TABLE rgtime.pto_ladder_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier_label TEXT NOT NULL,
    min_years INTEGER NOT NULL,
    max_years INTEGER,
    annual_pto_hours INTEGER NOT NULL,
    rate_per_qualifying_day NUMERIC(10, 3) NOT NULL,
    effective_from DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,
    CONSTRAINT pto_ladder_rates_tier_range CHECK (min_years >= 0),
    CONSTRAINT pto_ladder_rates_unique_tier_effective UNIQUE (
        min_years, max_years, effective_from
    )
);

CREATE INDEX idx_pto_ladder_rates_effective
    ON rgtime.pto_ladder_rates (effective_from DESC);

-- Seed authoritative literals — effective_from 2020-01-01 covers historical accrual.
-- NEEDS MICHAEL: confirm baseline date vs earliest hire date in production.
INSERT INTO rgtime.pto_ladder_rates (
    tier_label, min_years, max_years, annual_pto_hours,
    rate_per_qualifying_day, effective_from
) VALUES
    ('Yr 0-1', 0, 1, 0, 0.000, '2020-01-01'),
    ('Yr 1-2', 1, 2, 8, 0.031, '2020-01-01'),
    ('Yr 2-3', 2, 3, 16, 0.062, '2020-01-01'),
    ('Yr 3-4', 3, 4, 24, 0.092, '2020-01-01'),
    ('Yr 4-5', 4, 5, 32, 0.123, '2020-01-01'),
    ('Yr 5+', 5, NULL, 40, 0.154, '2020-01-01');
