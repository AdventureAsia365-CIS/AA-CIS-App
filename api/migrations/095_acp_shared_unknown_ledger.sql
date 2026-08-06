-- Migration 095: acp_shared.unknown_ledger (AA-369)
--
-- Context: AA-369 STEP 0 (Linear comment, 06/08/2026) confirmed this table
-- does not exist anywhere -- grep across services/, api/migrations/, tests/
-- returned zero hits. `unknown_ledger` is a spec-level concept from AA-298's
-- original issue text (Phần B / N8 Deliver-Learn, "supplier gap questions"),
-- but Phần B was never ported/built (AA-298's completion notes only cover
-- Phần A -- gates.py/dataforseo.py/reliability). AA-369 (N7 C3 demand-law
-- reject) is the first real code path that needs to write to it.
--
-- Schema placement: acp_shared, not acp_deliver/acp_contract -- matches the
-- acp_contract (input) / acp_shared (operational) / acp_deliver (output)
-- split established at AA-364.md D1. unknown_ledger is an operational
-- artifact (tracks gaps found during production), same category as
-- acp_shared.quarter_plan (092) and acp_shared.acp_stage_checkpoints (065),
-- not a delivery-layer output like acp_deliver.pieces/packets (094).
--
-- No FK to acp_shared.acp_runs(run_id): unlike acp_stage_checkpoints, a
-- ledger entry can outlive the run that produced it (its value is exactly
-- that it persists across runs -- "đã bỏ qua N lần" requires surviving the
-- run boundary) and slot_id/keyword identify the entry, not run_id.
--
-- kind vocabulary: the aamc/ prototype (models.py::UnknownEntry) reused the
-- generic "other" kind for BOTH demand-law-reject and no-CTA-target cases --
-- confirmed by reading aamc/research.py::compile_brief() during AA-369 STEP
-- 0. Split into explicit no_demand_evidence/no_cta_target here instead of
-- carrying that ambiguity forward, same "fix the bug while porting, don't
-- patch it later" approach N7 P0-1/P0-2/P0-3 already used (AA-298.md).
--
-- Dedup-by-repeat: UNIQUE(tenant_id, kind, detail) + application-side
-- upsert (increment count/last_seen) reproduces the prototype's
-- log_unknown() dedup behaviour ("Đã bỏ qua 4 lần" framing) without needing
-- a separate read-then-write race -- ON CONFLICT DO UPDATE is atomic.

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_shared;

CREATE TABLE IF NOT EXISTS acp_shared.unknown_ledger (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL,
    kind          TEXT NOT NULL
                      CHECK (kind IN ('no_demand_evidence', 'no_atom', 'no_cta_target',
                                      'unanswerable_paa', 'other')),
    detail        TEXT NOT NULL,
    demand_cost   TEXT,
    slot_id       TEXT,
    keyword       TEXT,
    count         INTEGER NOT NULL DEFAULT 1,
    first_seen    DATE NOT NULL DEFAULT CURRENT_DATE,
    last_seen     DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (tenant_id, kind, detail)
);

CREATE INDEX IF NOT EXISTS idx_acp_shared_unknown_ledger_tenant
    ON acp_shared.unknown_ledger(tenant_id, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_acp_shared_unknown_ledger_slot
    ON acp_shared.unknown_ledger(slot_id) WHERE slot_id IS NOT NULL;

ALTER TABLE acp_shared.unknown_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_shared.unknown_ledger
    USING (tenant_id = current_setting('app.tenant_id', true));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_shared TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.unknown_ledger TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('095', now(), 'AA-369: acp_shared.unknown_ledger -- N7 C3 demand-law TOPIC REJECTED tracking')
ON CONFLICT (version) DO NOTHING;

COMMIT;
