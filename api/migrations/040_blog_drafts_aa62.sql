-- =============================================================================
-- Migration 040: Gate 3 2-step + image columns for blog_drafts [AA-62]
-- Project: AA-CIS | Date: 21/05/2026
-- =============================================================================
-- G7 BUG fix: flagged_human was used in code but not in constraint
-- G6: 2-step Gate 3 (Trang QA → Ms.Thu final)
-- G4: image + gate3_rejection_note columns
-- =============================================================================

BEGIN;

-- G7 + G6: drop old constraint, add all required values
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
        'flagged_human'
    ));

-- Migrate existing rows (old schema → new schema)
UPDATE acp_silver_s4.blog_drafts SET hitl_gate3_status = 'pending_trang'  WHERE hitl_gate3_status = 'pending';
UPDATE acp_silver_s4.blog_drafts SET hitl_gate3_status = 'msthy_approved' WHERE hitl_gate3_status = 'approved';
UPDATE acp_silver_s4.blog_drafts SET hitl_gate3_status = 'trang_rejected' WHERE hitl_gate3_status = 'rejected';

-- G4: image sourcing + gate3 rejection note columns
ALTER TABLE acp_silver_s4.blog_drafts
    ADD COLUMN IF NOT EXISTS featured_image_url   TEXT,
    ADD COLUMN IF NOT EXISTS image_credit         TEXT,
    ADD COLUMN IF NOT EXISTS image_source         VARCHAR(20)
        CHECK (image_source IN ('tour_photo', 'unsplash', 'pexels', 'none')),
    ADD COLUMN IF NOT EXISTS gate3_rejection_note TEXT;

INSERT INTO shared.schema_versions (version, description)
VALUES ('040', 'Gate3 2-step + image columns + flagged_human fix [AA-62]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
