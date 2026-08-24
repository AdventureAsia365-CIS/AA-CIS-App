-- Migration 116: AA-455 bước 1 — acp_shared.publish_log (T11 delivery-state table, Option B).
--
-- STEP0 (docs/claude_audit/AA-455-00/-01) confirmed: T11 (Publish) doesn't exist yet, and its
-- eventual write path (blog-only, bước 2, deferred to a later task) is NOT part of this
-- migration. This table is created now, ahead of its own producer, so the mutating actions this
-- PR ships (A4 force-unpublish, tenant self-unpublish) have a real table to act on — same
-- ahead-of-writer pattern as AA-450's `angle_gate_request.cta` column existing before AA-451
-- wired a real writer into it. Deploys safely empty; bước 2 starts populating it later.
--
-- Option B (not Option A / not folded into acp_shared.content_piece): keeps T10's approval state
-- (content_piece.status IN ('approved','held')) fully separate from T11's delivery state — a
-- piece can be approved and never published, or published and later force-unpublished, without
-- overloading content_piece.status with a third concern. Mirrors the real precedent already in
-- this schema for "a delivery/publish queue as its own table" — acp_shared.acp_cms_publish_queue
-- (migration 039) — but scoped to content_piece instead of the old pre-T-series blog_drafts.
--
-- unpublished_by: single TEXT column, "admin:<admin_user_id>" / "tenant:<tenant_user_id>" prefix
-- format — Nghiep's own decision text (Linear AA-455 update, 24/08/2026) gave this exact format
-- as the example, and it matches migration 115's own minimalism precedent (no extra columns
-- beyond what's needed) over a separate unpublished_by_role enum column for the same information.

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.publish_log (
    publish_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    piece_id        UUID NOT NULL REFERENCES acp_shared.content_piece(piece_id),
    tenant_id       UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('published', 'unpublished', 'failed')),
    external_id     TEXT,
    external_url    TEXT,
    published_at    TIMESTAMPTZ,
    unpublished_at  TIMESTAMPTZ,
    unpublished_by  TEXT,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE acp_shared.publish_log IS
    'AA-455 bước 1 — T11 delivery-state, separate from content_piece''s T10 approval state '
    '(Option B). status=published/unpublished/failed; unpublished_by is "admin:<id>" (A4 '
    'force-unpublish) or "tenant:<id>" (tenant self-unpublish) — distinguishes who acted. '
    'Created ahead of T11''s own write path (bước 2, not yet built) so this PR''s '
    'force-unpublish/self-unpublish actions have a real table; deploys empty.';

CREATE INDEX IF NOT EXISTS idx_publish_log_tenant
    ON acp_shared.publish_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_log_piece
    ON acp_shared.publish_log(piece_id);
CREATE INDEX IF NOT EXISTS idx_publish_log_published
    ON acp_shared.publish_log(tenant_id, status) WHERE status = 'published';

-- RLS added for schema consistency with content_piece (migration 115) — NOT itself the real
-- isolation boundary. Confirmed this session (grep, no `app.tenant_id` SET anywhere in
-- api/ or services/) that content_piece's own identical policy is never actually enforced by
-- any connection today; real tenant isolation in this codebase is the explicit `WHERE
-- tenant_id = $N` filter every query already carries (see v1_competitors.py's ownership-check
-- precedent, applied the same way to this table's mutating endpoints). Kept for parity/future-
-- proofing, not relied on as the actual guard.
ALTER TABLE acp_shared.publish_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON acp_shared.publish_log;
CREATE POLICY tenant_isolation ON acp_shared.publish_log
    USING (tenant_id::text = current_setting('app.tenant_id', true));

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('116', now(),
    'AA-455 bước 1: acp_shared.publish_log — T11 delivery state (Option B), built ahead of '
    'T11''s own write path so A4 force-unpublish + tenant self-unpublish have a real table')
ON CONFLICT (version) DO NOTHING;

COMMIT;
