-- Phase 2: offline sync failure surfacing (manager-visible, loud)

CREATE TABLE rgtime.sync_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_local_id TEXT,
    staff_id UUID REFERENCES rgtime.staff (id) ON DELETE SET NULL,
    error_message TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_sync_failures_unresolved ON rgtime.sync_failures (resolved, created_at DESC);
