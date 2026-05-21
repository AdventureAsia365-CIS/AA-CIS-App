-- =============================================================================
-- Migration 038: Add cms_publish_status to blog_drafts
-- Project: AA-CIS | Date: 21/05/2026 | Ticket: AA-100
-- =============================================================================
BEGIN;

ALTER TABLE acp_silver_s4.blog_drafts
    ADD COLUMN IF NOT EXISTS cms_publish_status VARCHAR(20) DEFAULT 'pending'
        CHECK (cms_publish_status IN ('pending','enqueued','published','failed','skipped'));

COMMENT ON COLUMN acp_silver_s4.blog_drafts.cms_publish_status IS
    'CMS publish lifecycle: pending→enqueued (Gate 3 approve)→published|failed';

INSERT INTO shared.schema_versions (version, description)
VALUES ('038', 'add cms_publish_status to blog_drafts [AA-100]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
