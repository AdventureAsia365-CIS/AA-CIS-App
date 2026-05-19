-- =============================================================================
-- Migration 024: S0 review status columns on raw_tours
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 19/05/2026
-- Ticket: AA-44 — S0 Data Quality Review
-- =============================================================================
-- Adds review lifecycle columns to silver_aa_internal.raw_tours.
-- All ADD COLUMN calls are idempotent (IF NOT EXISTS).
-- Existing rows default to 'pending_review' via the DEFAULT clause.
-- =============================================================================

BEGIN;

ALTER TABLE silver_aa_internal.raw_tours
    ADD COLUMN IF NOT EXISTS review_status  VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (review_status IN ('pending_review','reviewed','approved','rejected')),
    ADD COLUMN IF NOT EXISTS reviewed_by    UUID,
    ADD COLUMN IF NOT EXISTS reviewed_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS review_notes   TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_tours_review_status
    ON silver_aa_internal.raw_tours(review_status);

COMMIT;
