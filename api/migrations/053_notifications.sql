-- =============================================================================
-- Migration 053: Notification Layer Phase 1
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 02/06/2026
-- Ticket: AA-156 — Master active/inactive + Notification Layer Phase 1
-- =============================================================================

CREATE TABLE IF NOT EXISTS shared.notifications (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     VARCHAR(100) REFERENCES shared.tenants(tenant_id) ON DELETE CASCADE,
    actor_type    VARCHAR(50)  NOT NULL DEFAULT 'system',
    event_type    VARCHAR(100) NOT NULL,
    entity_type   VARCHAR(50),
    entity_id     VARCHAR(100),
    payload       JSONB        NOT NULL DEFAULT '{}',
    target_roles  TEXT[]       NOT NULL DEFAULT '{admin}',
    is_read       BOOLEAN      NOT NULL DEFAULT FALSE,
    dispatched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notif_tenant_unread
    ON shared.notifications(tenant_id, created_at DESC)
    WHERE is_read = FALSE;

CREATE INDEX idx_notif_event_type
    ON shared.notifications(event_type, created_at DESC);

INSERT INTO shared.schema_versions(version, description, applied_at)
VALUES ('053', 'shared.notifications notification layer phase 1', NOW());
