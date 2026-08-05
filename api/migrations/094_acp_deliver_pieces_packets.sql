-- Migration 094: acp_deliver.packets + acp_deliver.pieces (AA-364)
--
-- Context: AA-364 STEP 0 (docs/implementation-notes/AA-364.md, branch
-- feat/AA-364-n8-persistence-design) designed this schema against the real
-- N7 Produce Piece (services/acp_produce/models.py) -- previously pure
-- in-memory Pydantic, confirmed zero existing table via grep across every
-- migration in this repo. Nghiep confirmed 3 decisions before this file was
-- written (Linear AA-364, 05/08/2026): (1) RLS ON for both tables, (2) start
-- the F1/F8/F9 orchestrator now, gate trust-ramp escalation past
-- 'propose_only' on F6 (route-to-sellable) existing, (3) use migration slot
-- 094.
--
-- Schema: acp_deliver (existing, migration 078, AA-302) -- already the
-- repo's real delivery-layer namespace (currently only tenant_tour_pages).
-- Matches the acp_contract (input) / acp_shared (operational) / acp_deliver
-- (output) split established by the 3 real ACP schemas -- see AA-364.md D1.
--
-- packets created before pieces (pieces.packet_id references packets) -- no
-- circular FK, unlike quarter_plan/quarter_plan_version (migration 092)
-- which needed the ALTER-TABLE-after trick for a genuine two-way reference.
--
-- RLS GUC name -- DEVIATION from the AA-364 task's instruction to copy
-- acp_silver_s3.ads_plan's policy verbatim (migration 031,
-- `current_setting('app.current_tenant', TRUE)`): grepping this entire repo
-- (api/, services/, tests/) found ZERO callers anywhere that ever
-- `SET app.current_tenant` -- ads_plan's policy variable is never populated
-- by any real code path. The GUC name that IS actually set and tested --
-- migration 004 (raw_tours/seo_context/generated_content/quality_scores),
-- tests/integration/test_007_rls_isolation.py, tests/integration/conftest.py,
-- tests/integration/test_export_service.py -- is `app.tenant_id`, always via
-- `SET LOCAL app.tenant_id = '<value>'`. Using `app.current_tenant` here
-- would silently propagate a policy that can never actually be satisfied by
-- any session in this codebase. `app.tenant_id` is used below instead; no
-- ::uuid cast, matching migration 004's TEXT-column raw_tours policy (our
-- tenant_id is TEXT per AA-364.md D3, not UUID like quarter_plan/
-- quarter_plan_version).
--
-- GRANTs to aa_app_user -- a second gap found while preparing the live RLS
-- verification this migration needs (tasked by Nghiep): migration 007b
-- (aa_app_user, the only non-BYPASSRLS role in this DB, used by
-- tests/integration/test_007_rls_isolation.py) grants USAGE only on
-- `shared`/`silver_aa_internal`/`gold_aa_internal` -- confirmed by reading
-- 007b_create_app_user.sql and 008_rls_gold_silver.sql (the only 2 files
-- that ever mention aa_app_user in this entire migrations/ directory). No
-- ACP schema (acp_shared, acp_contract, acp_deliver, acp_silver_s3, ...) has
-- ever granted this role anything -- meaning ads_plan's RLS policy
-- (migration 031) could never have been exercised by the one role this repo
-- actually uses to test RLS: aa_app_user can't even connect to that schema,
-- let alone hit its policy. Both gaps (wrong GUC name + missing GRANT) point
-- the same way: no ACP-schema RLS policy has ever actually been verified
-- live in this repo before now. Grants below are scoped to exactly the 2 new
-- tables, guarded by a role-existence check (same defensive style as 007b)
-- so this migration doesn't hard-fail on an environment where 007b/aa_app_user
-- was never applied.

-- NOT covered by this migration (unchanged from the STEP 0 draft):
-- - `channel` has no CHECK constraint -- Piece.channel doesn't exist in the
--   real Pydantic model yet (confirmed by reading models.py again before
--   writing this file). Adding a CHECK on values the code doesn't validate
--   yet would be ahead of the code that needs it (same principle as
--   migration 093's itinerary_day decision).
-- - needed_from_you / veto_deadline (aamc/models.py::Packet fields) -- no
--   consuming Linear issue yet, see AA-364.md D2.
-- - Backfill: N/A, no historical Piece/Packet data exists anywhere to
--   migrate (feature was never persisted before this migration).

BEGIN;

CREATE TABLE acp_deliver.packets (
    packet_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL,
    year          INTEGER NOT NULL,
    week          SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 53),
    publish_mode  TEXT NOT NULL DEFAULT 'propose_only'
                      CHECK (publish_mode IN ('propose_only', 'approve_to_publish', 'veto_window_auto')),
    status        TEXT NOT NULL DEFAULT 'assembling'
                      CHECK (status IN ('assembling', 'ready', 'delivered')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at  TIMESTAMPTZ,
    UNIQUE (tenant_id, year, week)
);

CREATE INDEX idx_acp_deliver_packets_tenant ON acp_deliver.packets(tenant_id, year, week);

ALTER TABLE acp_deliver.packets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_deliver.packets
    USING (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE acp_deliver.pieces (
    piece_id         TEXT PRIMARY KEY,
    run_id           UUID NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    tenant_id        TEXT NOT NULL,
    slot_id          TEXT,
    channel          TEXT NOT NULL,
    body_tagged      TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'in_progress'
                          CHECK (status IN ('in_progress', 'passed', 'held')),
    gate_ledger      JSONB NOT NULL DEFAULT '[]',
    brand_seo_audit  JSONB,
    repair_count     SMALLINT NOT NULL DEFAULT 0,
    held_reason      TEXT,
    packet_id        UUID REFERENCES acp_deliver.packets(packet_id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_acp_deliver_pieces_run_id ON acp_deliver.pieces(run_id);
CREATE INDEX idx_acp_deliver_pieces_tenant_created ON acp_deliver.pieces(tenant_id, created_at DESC);
CREATE INDEX idx_acp_deliver_pieces_held ON acp_deliver.pieces(status) WHERE status = 'held';
CREATE INDEX idx_acp_deliver_pieces_packet_id ON acp_deliver.pieces(packet_id) WHERE packet_id IS NOT NULL;

ALTER TABLE acp_deliver.pieces ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_deliver.pieces
    USING (tenant_id = current_setting('app.tenant_id', true));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_deliver TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_deliver.packets TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_deliver.pieces TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('094', now(), 'AA-364: acp_deliver.packets + acp_deliver.pieces -- N7 Piece/gate_ledger persistence, RLS on app.tenant_id')
ON CONFLICT (version) DO NOTHING;

COMMIT;
