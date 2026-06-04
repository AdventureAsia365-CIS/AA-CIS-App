-- =============================================================================
-- Migration 063: Add escalated_msthy to blog_drafts hitl_gate3_status [AA-124]
-- Project: AA-CIS | Date: 2026-06-04
-- Ticket: AA-124 — Per-Blog Reject Semantics
-- =============================================================================
-- When Trang rejects a blog after max retries, status is set to escalated_msthy
-- so Ms. Thu must make the final call. Distinct from msthy_rejected (Ms. Thu decided).
-- =============================================================================

BEGIN;

ALTER TABLE acp_silver_s4.blog_drafts
    DROP CONSTRAINT IF EXISTS blog_drafts_hitl_gate3_status_check;

ALTER TABLE acp_silver_s4.blog_drafts
    ADD CONSTRAINT blog_drafts_hitl_gate3_status_check
    CHECK (hitl_gate3_status IN (
        'pending_trang',
        'trang_approved',
        'trang_rejected',
        'msthy_approved',
        'msthy_rejected',
        'flagged_human',
        'escalated_msthy'
    ));

INSERT INTO shared.schema_versions (version, description)
VALUES ('063', 'Add escalated_msthy to blog_drafts hitl_gate3_status [AA-124]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
