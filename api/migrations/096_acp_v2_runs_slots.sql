-- Migration 096: acp_shared.acp_v2_runs + acp_shared.acp_v2_slots (AA-377 + AA-378)
--
-- Context: STEP 0 recon (docs/implementation-notes/AA-377.md) found `acp_shared.acp_runs` is
-- the acpcore v0.4.0 S1-S4 pipeline's run table (created outside api/migrations/, via
-- DBeaver/acp_m0_migration.sql, AA-41) -- live, read/written by api/routers/v1_s1.py, v1_s3.py,
-- v1_s4_blog.py, v1_s4_social.py, services/acp/s2/router.py, services/acp_s3/handler.py,
-- services/acp_canary/lambda_handler.py, and admin_pipeline.py's stuck-run sweep. Its `status`
-- vocabulary ('s1_pending', ...) and admin/canary sweep logic are all S1-S4-specific. Nghiep
-- decision (STEP 0, confirmed before this migration was written): a NEW table for N7 weekly
-- runs, not a reuse -- zero blast radius on that live S1-S4 path.
--
-- acp_v2_slots persists services/acp_planning/models.py::Slot (previously pure in-memory
-- output of compute_slot_grid()/allocate_month(), never written to DB) so slot_id becomes
-- stable across repeated allocation calls for the same run -- fixes AA-377's actual bug
-- (slot_id was uuid.uuid4().hex[:10], different every call). slot_id is now deterministic --
-- sha256(tenant_id|year|week|tour_id|channel), see
-- services/acp_planning/allocator.py::_deterministic_slot_id() -- so re-allocating the same
-- (tenant, week, tour, channel) always produces the same row; `ON CONFLICT (slot_id) DO
-- NOTHING` on insert (persist_slot_grid(), allocator.py) makes re-allocation a no-op for slots
-- that already exist, matching "resume/retry the same slot, not duplicate content" from the
-- AA-377 issue text. `week` here is the SlotGrid's own week-of-month numbering (1-4, see
-- allocator.py's `weeks = [1, 2, 3, 4]`), NOT the ISO year+week acp_deliver.packets (migration
-- 094) uses -- reconciling the two is an explicit non-goal of this migration (AA-377.md
-- Tradeoffs).
--
-- FK re-point: acp_deliver.pieces.run_id (migration 094) currently references
-- acp_shared.acp_runs(run_id) only because AA-378 hadn't been decided yet when 094 was written
-- (094's own header comment says so explicitly). Re-pointed here at acp_v2_runs(run_id) instead.
-- acp_deliver.pieces confirmed 0 rows live immediately before writing this file (re-checked at
-- the start of this implementation session, not reused from STEP 0's earlier count) -- no
-- backfill, straight DROP+ADD CONSTRAINT. Real constraint name confirmed live via
-- pg_constraint before writing this migration: `pieces_run_id_fkey` (Postgres default naming,
-- migration 094 never named it explicitly).
--
-- Schema/RLS/GRANT convention: copies migration 094/095 exactly -- RLS on `app.tenant_id` (the
-- GUC actually SET LOCAL by real code -- migration 094's own finding, NOT
-- `app.current_tenant`, which no real code path ever sets), GRANT guarded by aa_app_user
-- existence check so this migration doesn't hard-fail on an environment where 007b/aa_app_user
-- was never applied.

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_shared;  -- idempotent no-op; schema already exists (acp_runs/unknown_ledger live there)

CREATE TABLE acp_shared.acp_v2_runs (
    run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL,
    year         INTEGER NOT NULL,
    week         SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 4),
    status       TEXT NOT NULL DEFAULT 'allocated'
                     CHECK (status IN ('allocated', 'producing', 'completed', 'failed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (tenant_id, year, week)
);

CREATE INDEX idx_acp_v2_runs_tenant ON acp_shared.acp_v2_runs(tenant_id, year, week);

ALTER TABLE acp_shared.acp_v2_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_shared.acp_v2_runs
    USING (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE acp_shared.acp_v2_slots (
    slot_id        TEXT PRIMARY KEY,
    run_id         UUID NOT NULL REFERENCES acp_shared.acp_v2_runs(run_id) ON DELETE CASCADE,
    tenant_id      TEXT NOT NULL,
    week           SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 4),
    channel        TEXT NOT NULL,
    kind           TEXT NOT NULL,
    tour_id        UUID,
    status         TEXT NOT NULL DEFAULT 'due'
                       CHECK (status IN ('due', 'produced', 'skipped')),
    due_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    produced_at    TIMESTAMPTZ,
    skipped_reason TEXT,
    payload        JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_acp_v2_slots_run_id ON acp_shared.acp_v2_slots(run_id);
CREATE INDEX idx_acp_v2_slots_due ON acp_shared.acp_v2_slots(tenant_id, status) WHERE status = 'due';

ALTER TABLE acp_shared.acp_v2_slots ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_shared.acp_v2_slots
    USING (tenant_id = current_setting('app.tenant_id', true));

-- Re-point acp_deliver.pieces.run_id at the new run table (was acp_shared.acp_runs, migration 094)
ALTER TABLE acp_deliver.pieces DROP CONSTRAINT IF EXISTS pieces_run_id_fkey;
ALTER TABLE acp_deliver.pieces
    ADD CONSTRAINT pieces_run_id_fkey
    FOREIGN KEY (run_id) REFERENCES acp_shared.acp_v2_runs(run_id) ON DELETE CASCADE;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_shared TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.acp_v2_runs TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.acp_v2_slots TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('096', now(),
    'AA-377+AA-378: acp_shared.acp_v2_runs + acp_v2_slots -- N7 weekly run/Slot persistence, '
    'deterministic slot_id, re-points acp_deliver.pieces.run_id FK from acp_shared.acp_runs')
ON CONFLICT (version) DO NOTHING;

COMMIT;
