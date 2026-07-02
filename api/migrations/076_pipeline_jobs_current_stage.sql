-- Migration 076: AA-250 B2 — shared.pipeline_jobs.current_stage
--
-- Context: S1 run-tour jobs (migration 071, AA-223) only write status at 2 points —
-- mark_running() at dispatch and mark_succeeded/mark_failed() at the end (confirmed via
-- STEP 0 code read of _run_tour_job / _execute_run_tour). The LangGraph run in between
-- (generate -> validate -> llm_judge -> [retry loop] -> brand_audit -> flag_fix ->
-- revalidate, ~2.5-3.5min/tour per live sample) has no persisted sub-stage, so the FE
-- stage-progress bar (AA-250 B2) has nothing to poll for. This migration adds a single
-- nullable text column the graph-streaming loop (BUOC 3, admin_pipeline.py) writes to via
-- jobs_repo.update_stage() after each node completes. NULL for any job created before this
-- migration or for jobs whose stage was never reported (queued/failed-before-first-node) —
-- FE treats NULL as "no stage info yet", not an error.
--
-- Plain ADD COLUMN (not ALTER TYPE) — no transactional-safety caveat applies (that lesson
-- was for enum ALTER TYPE ADD VALUE, migration 073/S89); this runs inside a normal BEGIN/COMMIT.
-- Applied: Dev only, per project convention (single-env architecture, same as 071-075).

BEGIN;

ALTER TABLE shared.pipeline_jobs ADD COLUMN IF NOT EXISTS current_stage TEXT;

COMMENT ON COLUMN shared.pipeline_jobs.current_stage IS
    'AA-250 B2: last LangGraph node name to complete for this job (generate/validate/'
    'llm_judge/increment_retry/brand_audit/flag_fix/revalidate). Written by jobs_repo.'
    'update_stage() during admin_pipeline._run_tour_job graph streaming. NULL = no stage '
    'reported yet (job created pre-migration, or failed before first node).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('076', NOW(), 'AA-250 B2: shared.pipeline_jobs.current_stage for S1 stage-progress bar')
ON CONFLICT (version) DO NOTHING;

COMMIT;
