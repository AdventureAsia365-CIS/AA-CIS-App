-- Migration 113: AA-449 — T8 Angle Gate (written fresh, per ADR-2026-038 §0.5 — no reuse of
-- acp_silver_s4.social_content, which stays untouched and unused).
--
-- 2 tables, tenant self-service (ADR §0.2/§10.3 — the tenant chooses, never AA):
--
-- angle_gate_request — one row per (atom_id, channel) content-generation request, the unit
-- STEP0 (docs/claude_audit/AA-449-00-step0-t8-angle-gate-investigation.md §5) confirmed the
-- workflow actually operates on: Slot.channel is already produced per-slot by T7, atom_id comes
-- from a curated T6 atom — T8 does not choose either, it receives both as input (workflow step
-- 1). `goal` starts NULL (chosen by the tenant at step 2, one of the 8 Bang-1 goals — kept as
-- free TEXT, not a CHECK-constrained enum, since services/acp_angle_gate/goals.py already owns
-- the canonical 8-value list in code and re-stating it as a DB constraint would be a second,
-- driftable source of truth). `status` models the lifecycle STEP0 §4 found no existing table
-- for: pending_goal (created, no goal chosen yet) -> pending_choice (goal chosen, 3 angles
-- generated, waiting on the tenant) -> approved (tenant has chosen one). No expiry/timeout
-- column by design (Nghiep's round-3 explicit decision — no time limit; `created_at` is kept
-- so a timeout CAN be added later by simply reading its age, without a schema change).
--
-- angle_gate_option — exactly 3 child rows per request (idx 0/1/2), the 3 angles STEP0 confirmed
-- SKILL_v2.md's own "Angle Selection Output" format requires (Name/Why it works/Best final
-- style) plus the 4th field this build explicitly asks for (`formula_fit` — STEP0 flagged this
-- as a genuinely NEW field, not recoverable from any source document; built as asked, not
-- silently omitted). `recommended` marks the LLM's own top pick (exactly one TRUE per request);
-- `chosen` marks the tenant's actual pick (exactly one TRUE per request, only after `approved`).
-- These are deliberately two separate booleans, not one — the tenant is free to choose a
-- non-recommended angle (workflow step 7: "có thể chọn theo đề xuất... hoặc chọn khác").
--
-- tenant_id type: UUID, matching services/acp_planning/*.py's own convention (see migration
-- 092's own note on this same repo-wide inconsistency) — this module's Python layer
-- (services/acp_angle_gate/) types tenant_id as UUID throughout, same as acp_planning.

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.angle_gate_request (
    request_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    atom_id      TEXT NOT NULL,
    trip_id      UUID,
    channel      TEXT NOT NULL,
    goal         TEXT,
    status       TEXT NOT NULL DEFAULT 'pending_goal'
                 CHECK (status IN ('pending_goal', 'pending_choice', 'approved')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE acp_shared.angle_gate_request IS
    'AA-449 T8 — one (atom_id, channel) angle-generation request. Written fresh per '
    'ADR-2026-038 §0.5; NOT related to acp_silver_s4.social_content (old, excluded, 0 rows, '
    'kept only as an unused legacy table). No expiry column by design — see module comment '
    'above and docs/implementation-notes/AA-449-t8-angle-gate.md.';

CREATE TABLE IF NOT EXISTS acp_shared.angle_gate_option (
    option_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id        UUID NOT NULL REFERENCES acp_shared.angle_gate_request(request_id)
                       ON DELETE CASCADE,
    idx               SMALLINT NOT NULL CHECK (idx BETWEEN 0 AND 2),
    name              TEXT NOT NULL,
    why_it_works      TEXT NOT NULL,
    formula_fit       TEXT NOT NULL,
    best_final_style  TEXT NOT NULL,
    recommended       BOOLEAN NOT NULL DEFAULT false,
    chosen            BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (request_id, idx)
);

COMMENT ON TABLE acp_shared.angle_gate_option IS
    'AA-449 T8 — exactly 3 rows per angle_gate_request (idx 0-2). 4 fields per SKILL_v2.md''s '
    'Angle Selection Output (Name/Why it works/Best final style) + formula_fit (new field, '
    'STEP0-flagged, built per explicit build-task instruction).';

CREATE INDEX IF NOT EXISTS idx_angle_gate_request_tenant
    ON acp_shared.angle_gate_request(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_angle_gate_request_status
    ON acp_shared.angle_gate_request(status);
CREATE INDEX IF NOT EXISTS idx_angle_gate_option_request
    ON acp_shared.angle_gate_option(request_id);

ALTER TABLE acp_shared.angle_gate_request ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON acp_shared.angle_gate_request
    USING (tenant_id::text = current_setting('app.tenant_id', true));

-- angle_gate_option carries no tenant_id of its own (matches acp_shared.quarter_plan_version's
-- own precedent, migration 092 — a child table keyed only by its parent's id, tenant isolation
-- enforced at the API layer via the parent request_id, not a second RLS policy here).

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('113', now(), 'AA-449: T8 Angle Gate — angle_gate_request + angle_gate_option, written fresh')
ON CONFLICT (version) DO NOTHING;

COMMIT;
