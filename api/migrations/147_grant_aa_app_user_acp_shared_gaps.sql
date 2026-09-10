-- Migration 147: AA-544 Stage 0 — GRANT aa_app_user on 7 acp_shared tables missing it
--
-- Context: AA-544 found `aa_app_user` (the non-BYPASSRLS role RLS policies actually depend on,
-- migration 007b) has never been wired into any live connection pool — `api/main.py` only ever
-- opens one pool, as `aa_cis_admin` (BYPASSRLS), so every RLS policy in this DB is currently
-- decorative regardless of GRANT state. Stage 0 of AA-544's approved 7-stage rollout prepares
-- the infra for a future 2-pool split (Admin stays on aa_cis_admin; Tenant Portal moves to
-- aa_app_user + real GUC) WITHOUT changing any behavior yet — this migration only fixes GRANTs
-- so aa_app_user is actually usable once that cutover happens; nothing queries through it today.
--
-- Live-DB audit (05097885195, 10/09/2026) confirmed 37 tables live across acp_* schemas, only 7
-- already GRANTed to aa_app_user (acp_deliver.packets/pieces, acp_shared.acp_v2_runs/
-- acp_v2_slots/marketplace_portfolios/tenant_atom_state/tenant_onboarding/unknown_ledger --
-- migrations 094-098). The other ~30 are acp_contract/acp_silver_s2/acp_silver_s3/
-- acp_gold_output/admin-only acp_shared tables (tour_atoms, atom_segment, route, hub, ...) --
-- read exclusively by Admin routes, which keep the aa_cis_admin pool under AA-544's design, so
-- granting those is explicitly OUT of this migration's scope (would be unused privilege
-- creep -- same class of problem AA-517 already burned this account on once).
--
-- The 7 tables below are exactly the ones a real /portal/* (tenant) request already reads/
-- writes today and that AA-544's Round 2 investigation flagged as GRANT gaps on the
-- `app.tenant_id`-GUC cohort (migrations 112/113/115/116/145) -- 5 directly RLS-enabled tables,
-- plus the 2 tables that ship alongside them in the same migrations and are functionally
-- required for those same features to work end-to-end (angle_gate_option is angle_gate_request's
-- own child row set, T8; year_plan is content_metric_snapshot's migration-112 sibling, T7):
--   - acp_shared.year_plan               (112, T7  -- no RLS of its own, see migration 112)
--   - acp_shared.content_metric_snapshot (112, T7  -- RLS on app.tenant_id)
--   - acp_shared.angle_gate_request      (113, T8  -- RLS on app.tenant_id)
--   - acp_shared.angle_gate_option       (113, T8  -- no RLS, child of angle_gate_request)
--   - acp_shared.content_piece           (115, T9/T10 -- RLS on app.tenant_id)
--   - acp_shared.publish_log             (116, T11 -- RLS on app.tenant_id)
--   - acp_shared.facts                   (145, T9  -- RLS on app.tenant_id OR scope='platform')
--
-- GRANT guarded by role-existence check, same convention as 094-098 (doesn't hard-fail on an
-- environment where 007b/aa_app_user was never applied). USAGE ON SCHEMA acp_shared is already
-- granted (095-098) -- re-stated here anyway for this file's own idempotence/self-containment,
-- matching every prior migration's own pattern.
--
-- 0 behavior change: no application code connects as aa_app_user yet (api/main.py still opens
-- one pool only, as aa_cis_admin) -- this migration only makes the grants correct for when it
-- does. Not the same thing as "RLS is now enforced" -- see AA-544 for the full rollout plan.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_shared TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.year_plan TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.content_metric_snapshot TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.angle_gate_request TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.angle_gate_option TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.content_piece TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.publish_log TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.facts TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('147',
    now(),
    'AA-544 Stage 0: GRANT aa_app_user on 7 acp_shared tables missing it '
    '(year_plan, content_metric_snapshot, angle_gate_request, angle_gate_option, '
    'content_piece, publish_log, facts) -- infra prep only, 0 behavior change')
ON CONFLICT (version) DO NOTHING;

COMMIT;
