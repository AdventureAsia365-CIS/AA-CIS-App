-- =============================================================================
-- Migration 036: Add Gate 1 columns to acp_hitl_requests
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 21/05/2026
-- Ticket: AA-98 — Gate 1 auto-approve (PRD v1.3 §2.2)
-- =============================================================================
-- Gate 1: AA internal + confidence >= 0.85 → auto-approve.
-- B2B tenants always get a pending HITL request (self-approve via portal).
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_hitl_requests
    ADD COLUMN IF NOT EXISTS auto_approved    BOOLEAN      NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS reviewer_type    VARCHAR(20)  NOT NULL DEFAULT 'aa_internal'
        CHECK (reviewer_type IN ('aa_internal', 'tenant_admin'));

COMMENT ON COLUMN acp_shared.acp_hitl_requests.auto_approved IS
    'TRUE if system auto-approved (aa_internal + confidence >= 0.85)';
COMMENT ON COLUMN acp_shared.acp_hitl_requests.reviewer_type IS
    'aa_internal: Nghiep reviews; tenant_admin: B2B self-approve via portal';

INSERT INTO shared.schema_versions (version, description)
VALUES ('036', 'add gate1 auto_approved/confidence_score/reviewer_type to acp_hitl_requests [AA-98]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
