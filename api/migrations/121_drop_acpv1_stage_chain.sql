-- Migration 121: AA-477 — physical DB cleanup of the dead ACPv1 S1→S4.2 stage-chain.
--
-- Architecture death date: 13/07/2026 (ADR-2026-013 "Stage Orchestration S1→S4.2" superseded,
-- ADR-2026-024, ADR-2026-026 — all Accepted same day). Confirmed dead via STEP0 (2 rounds,
-- docs/claude_audit/AA-258-259-acpv1-tables-audit.md): all 15 tables below at 0 rows (re-verified
-- fresh immediately before drafting this migration, not just relying on the STEP0 snapshot), the
-- PRD's own words ("S2→S4 cũ đã build nhưng CHƯA từng chạy production"), 0 EventBridge rule ever
-- wired to either of the 2 Lambdas that fed this chain, 0 resource policy on either Lambda, and
-- CloudWatch Logs Insights over the full 14-day retention window showing 0 real external traffic
-- to any of the 6 backend routers that wrote to these tables (already removed from the codebase
-- in this same PR).
--
-- FK-graph-first (pg_constraint), extended to full closure (not just 1 hop from acp_runs, per
-- AA-473's own methodology note) — found ONE real complication STEP0's 1-hop check missed:
-- acp_shared.acp_output_rules (a LIVE, KEPT table — PRD §10 "Giữ acp_output_rules, deterministic
-- flywheel") has acp_output_rules_source_hitl_id_fkey referencing acp_hitl_requests(hitl_id).
-- acp_output_rules itself is 0 rows right now (separately verified, unrelated to this migration —
-- not touched beyond dropping the one stale FK constraint tying it to the table being removed
-- below). Order matters: blog_drafts (has its own separate FK to acp_hitl_requests) must drop
-- before acp_hitl_requests; the acp_output_rules constraint must be dropped explicitly (not via
-- blanket CASCADE) before acp_hitl_requests, since acp_output_rules itself is NOT being dropped.
--
-- Application-logic confirmation (not just "migration runs clean" — Nghiep asked specifically for
-- this, see docs/implementation-notes/AA-477.md "FK dependency re-check" section for the full
-- trail): apply_output_rules() (api/services/acp_post_processor.py, the real N7/N8 production
-- path) never reads source_hitl_id or joins acp_hitl_requests — grep-confirmed. The only writer
-- of source_hitl_id, h3_rule_extractor.py::extract_and_save_rule(), has 0 live callers (its sole
-- caller, v1_acp_gate.py::gate_reject(), was deleted earlier in this same PR) — and the live N7
-- gates.py code itself documents (services/acp_produce/gates.py:916-921) that N7 was deliberately
-- never wired into that path. Empirically verified too: inserted an orphan acp_output_rules row
-- (source_hitl_id pointing at a nonexistent hitl_id, FK already dropped in the same test
-- transaction) and called the REAL apply_output_rules() against it — rule matched, run_count
-- incremented, OutputRuleViolation raised correctly. Rolled back, zero actual change.
--
-- 0 view depends on any of these 15 tables (checked via pg_depend).
--
-- Scope: this migration ONLY drops tables. Terraform removal of the 2 feeder Lambdas
-- (acp-s3-campaign-planner, acp-s4-evaluate) is a separate, human-applied change in AA-CIS-Infra
-- PR (draft, not yet applied — ADR-2026-023, human-only). Their AA-CIS-App backend code (6
-- routers, services/acp_s4/, services/acp_s3/, services/acp_s4_evaluate/, and the dead files
-- inside services/acp_s4_blog/) was already removed earlier in this same PR.
--
-- NOT dropped, explicitly out of scope: shared.acp_runs (different schema, different table —
-- the A0-A3 admin pipeline's own batch-keyed run tracker, unrelated — see AA-438 audit finding
-- #15 "naming trap"), services/acp_shared/* (idempotency.py, tracer.py, h3_rule_extractor.py,
-- cost_utils.py — still reference the dropped tables in their SQL strings but were never named in
-- this task's scope; flagged for a possible future round, not silently expanded here),
-- acp_shared.acp_output_rules itself (kept, per PRD).

BEGIN;

-- Step 1: detach the one external dependent that isn't itself being dropped.
ALTER TABLE acp_shared.acp_output_rules
    DROP CONSTRAINT IF EXISTS acp_output_rules_source_hitl_id_fkey;

-- Step 2: children with their own secondary FK into acp_hitl_requests go first.
DROP TABLE IF EXISTS acp_silver_s4.blog_drafts;

-- Step 3: acp_hitl_requests itself (now safe — no more external references).
DROP TABLE IF EXISTS acp_shared.acp_hitl_requests;

-- Step 4: remaining 10 "other" children of acp_runs (leaf-level, nothing else FKs into them —
-- confirmed via the full-closure pg_constraint check above).
DROP TABLE IF EXISTS acp_shared.acp_lessons_agency;
DROP TABLE IF EXISTS acp_shared.acp_lessons_shared;
DROP TABLE IF EXISTS acp_shared.acp_run_context;
DROP TABLE IF EXISTS acp_shared.acp_stage_checkpoints;
DROP TABLE IF EXISTS acp_shared.pipeline_checkpoints;
DROP TABLE IF EXISTS acp_silver_s3.ads_plan;
DROP TABLE IF EXISTS acp_silver_s3.content_calendars;
DROP TABLE IF EXISTS acp_silver_s4.social_content;
DROP TABLE IF EXISTS acp_gold_output.published_content;
DROP TABLE IF EXISTS acp_silver_s2.visibility_reports;

-- Step 5: tour_content_versions — FK-locked to acp_runs (NOT NULL), confirmed empty since
-- ≥AA-343 (a prior, unrelated session), already flagged as an "empty ACP slot" by ADR-2026-037.
DROP TABLE IF EXISTS silver_aa_internal.tour_content_versions;

-- Step 6: acp_stage_runs — the second table named in AA-258/259's original ask.
DROP TABLE IF EXISTS acp_shared.acp_stage_runs;

-- Step 7: acp_runs — the root of the whole cluster, dropped last.
DROP TABLE IF EXISTS acp_shared.acp_runs;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('121', now(),
    'AA-477: DROP 15-table dead ACPv1 S1-S4.2 stage-chain cluster (acp_runs + 14 FK-dependents), '
    'architecture superseded 13/07/2026 (ADR-2026-013/024/026), physical cleanup first pass')
ON CONFLICT (version) DO NOTHING;

COMMIT;
