-- =============================================================================
-- Migration 039: Create acp_cms_publish_queue
-- Project: AA-CIS | Date: 21/05/2026 | Ticket: AA-100
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.acp_cms_publish_queue (
    queue_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         UUID        NOT NULL,
    tenant_id      VARCHAR(50) NOT NULL,
    draft_id       UUID        NOT NULL,
    cms_type       VARCHAR(20) NOT NULL DEFAULT 'wordpress'
                       CHECK (cms_type IN ('wordpress','webflow','ghost')),
    cms_secret_key TEXT        NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','processing','published','failed')),
    wp_post_id     INTEGER,
    wp_post_url    TEXT,
    retries        SMALLINT    NOT NULL DEFAULT 0,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cms_queue_status
    ON acp_shared.acp_cms_publish_queue(status, created_at)
    WHERE status IN ('pending', 'failed');

CREATE INDEX IF NOT EXISTS idx_cms_queue_tenant
    ON acp_shared.acp_cms_publish_queue(tenant_id, status);

COMMENT ON TABLE acp_shared.acp_cms_publish_queue IS
    'Gate 3 approve → enqueue CMS publish. WordPress draft created async.';

INSERT INTO shared.schema_versions (version, description)
VALUES ('039', 'create acp_cms_publish_queue [AA-100]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
