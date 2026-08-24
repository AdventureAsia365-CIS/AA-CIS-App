-- Migration 115: AA-450 — acp_shared.content_piece (T9 write output + T10 inline quality-gate
-- result, single-endpoint architecture — see docs/claude_audit/AA-450-01-t9-t10-retry-loop-
-- investigation.md for why this is NOT keyed like acp_deliver.pieces, which references
-- acp_shared.acp_runs — N7's admin run concept, wrong for a tenant-self-service request).
--
-- One row per WRITE ATTEMPT (not one row per request) — `attempt_number` scoped by
-- `angle_gate_request_id`, mirroring `angle_gate_option`'s own `(request_id, idx)` precedent
-- (migration 113) for "ordered child rows under one parent". No `previous_piece_id` chain: an
-- attempt is never a branch, only ever "replaces what's shown for this request" — the row with
-- the highest `attempt_number` for a given request is the one to display, per the architecture
-- Nghiep confirmed after Phase 1 (single endpoint, up to 2 attempts total, no async retry).
--
-- No denormalized `cta`/`channel`/`goal`/`angle_name` columns — follows `angle_gate_option`'s
-- own precedent (migration 113: a child table carries no copy of its parent's fields, callers
-- join back to `angle_gate_request` when they need them). Consistent with the one other
-- parent/child pair this schema already has, not a new convention.
--
-- `gate_ledger`/`repair_log` (JSONB) mirror `services.acp_produce.models.Piece.gate_ledger`/
-- `RepairRoundLog` shape/spirit (N7's own precedent for "a human reviewing a held piece needs
-- the full per-round history in the same row they already look at, not a separate log store")
-- — adapted to T10's own smaller gate set (docs/claude_audit/AA-450-02-t10-gate-map.md), not a
-- literal copy of N7's 9-gate ledger shape.
--
-- `status` has only 2 values (`approved`/`held`) — no `in_progress`, because a row is only ever
-- INSERTed once the single write-and-check request has already finished (the whole point of
-- the confirmed single-endpoint architecture is that the tenant never sees an in-between
-- state). T10 (a real, separate future gate) is out of scope here per the build task; this
-- schema has no extra room reserved for a THIRD "pending_quality_check"-style status because
-- the confirmed architecture folds T10 fully into the same request T9 already answers with —
-- there is no longer a state where a piece exists but hasn't been checked yet.

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.content_piece (
    piece_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    angle_gate_request_id  UUID NOT NULL REFERENCES acp_shared.angle_gate_request(request_id)
                            ON DELETE CASCADE,
    attempt_number         SMALLINT NOT NULL DEFAULT 1,
    content_text           TEXT NOT NULL,
    status                 TEXT NOT NULL CHECK (status IN ('approved', 'held')),
    held_reason            TEXT,
    gate_ledger            JSONB NOT NULL DEFAULT '[]',
    repair_log             JSONB NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (angle_gate_request_id, attempt_number)
);

COMMENT ON TABLE acp_shared.content_piece IS
    'AA-450 T9/T10 — one row per write attempt (max 2/request, single-endpoint architecture). '
    'status=approved passed every T10 gate; status=held exhausted attempts still failing, kept '
    'visible with gate_ledger/repair_log/held_reason for review, never silently discarded.';

CREATE INDEX IF NOT EXISTS idx_content_piece_request
    ON acp_shared.content_piece(angle_gate_request_id, attempt_number DESC);
CREATE INDEX IF NOT EXISTS idx_content_piece_tenant
    ON acp_shared.content_piece(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_piece_held
    ON acp_shared.content_piece(tenant_id, status) WHERE status = 'held';

ALTER TABLE acp_shared.content_piece ENABLE ROW LEVEL SECURITY;
-- DROP+CREATE (not CREATE POLICY IF NOT EXISTS, which Postgres has no syntax for) — makes this
-- file safely re-runnable, same idempotence guarantee CREATE TABLE IF NOT EXISTS already gives
-- the rest of this migration (confirmed necessary live, 24/08/2026: a live-verify session's SSM
-- connection dropped mid-migration on a re-run and hit DuplicateObjectError on this exact line).
DROP POLICY IF EXISTS tenant_isolation ON acp_shared.content_piece;
CREATE POLICY tenant_isolation ON acp_shared.content_piece
    USING (tenant_id::text = current_setting('app.tenant_id', true));

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('115', now(),
    'AA-450: acp_shared.content_piece — T9 write + T10 inline quality-gate result, keyed by '
    'angle_gate_request_id (not N7''s acp_runs), attempt_number not previous_piece_id chain')
ON CONFLICT (version) DO NOTHING;

COMMIT;
