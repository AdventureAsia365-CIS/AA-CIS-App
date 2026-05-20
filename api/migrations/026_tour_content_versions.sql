-- =============================================================================
-- Migration 026: Tour Content Versions table
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 20/05/2026
-- Ticket: AA-90 — S1 Configured Rewrite Engine
-- =============================================================================
-- Versioned S1 output per (raw_tour, acp_run) pair.
-- is_active=TRUE marks the current live version for a given raw_tour.
-- FK raw_tour_id → silver_aa_internal.raw_tours(tour_id)  [PK is tour_id]
-- FK acp_run_id  → acp_shared.acp_runs(run_id)            [PK is run_id]
-- Published_tours is NOT touched this sprint (separate issue post-AA-43).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS silver_aa_internal.tour_content_versions (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_tour_id   UUID         NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id) ON DELETE CASCADE,
    acp_run_id    UUID         NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    run_config    JSONB        NOT NULL DEFAULT '{}',
    content       JSONB        NOT NULL DEFAULT '{}',
    quality_score NUMERIC(4,2),
    status        VARCHAR(20)  NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft', 'approved', 'published', 'rejected', 'failed')),
    is_active     BOOLEAN      NOT NULL DEFAULT FALSE,
    failure_codes JSONB        NOT NULL DEFAULT '[]',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (raw_tour_id, acp_run_id)
);

CREATE INDEX IF NOT EXISTS idx_tcv_raw_tour
    ON silver_aa_internal.tour_content_versions(raw_tour_id);

CREATE INDEX IF NOT EXISTS idx_tcv_active
    ON silver_aa_internal.tour_content_versions(raw_tour_id, is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_tcv_run
    ON silver_aa_internal.tour_content_versions(acp_run_id);

CREATE INDEX IF NOT EXISTS idx_tcv_status
    ON silver_aa_internal.tour_content_versions(status);

COMMENT ON TABLE silver_aa_internal.tour_content_versions IS
    'Versioned S1 rewrite output. is_active=TRUE = current live version for that raw_tour.';

COMMIT;
