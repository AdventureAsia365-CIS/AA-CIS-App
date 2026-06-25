-- =============================================================================
-- Migration 071 — shared.pipeline_jobs (async run-tour job lifecycle)
-- AA-223 / ADR-2026-016: decouple POST /admin/run-tour from the full pipeline.
--         The async endpoint inserts a queued job, dispatches the existing
--         _run_tour_safe executor in the background, and returns 202 + a poll
--         URL. Each row tracks one run_tour job through queued → running →
--         succeeded/failed/interrupted.
-- NOTE: result_version_id + pipeline_run_id are UUID (not BIGINT) to match the
--       existing PKs: silver_aa_internal.generated_content.id (UUID, RETURNING id
--       in _execute_run_tour) and shared.pipeline_runs.id (UUID). pipeline_run_id
--       stores the run's batch_id (the canonical pipeline-run business key used
--       everywhere, e.g. pipeline_runs.batch_id UNIQUE).
-- Applied: pending
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS shared.pipeline_jobs (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type           TEXT NOT NULL DEFAULT 'run_tour',
    status             TEXT NOT NULL DEFAULT 'queued',
    request            JSONB NOT NULL,
    tenant             TEXT,
    result_version_id  UUID,
    pipeline_run_id    UUID,
    error              TEXT,
    heartbeat_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_status  ON shared.pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_created ON shared.pipeline_jobs(created_at DESC);

INSERT INTO shared.schema_versions (version, description)
    VALUES ('071', 'shared.pipeline_jobs — async run-tour job lifecycle [AA-223]')
    ON CONFLICT DO NOTHING;

COMMIT;
