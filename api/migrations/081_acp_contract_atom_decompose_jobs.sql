-- Migration 081: AA-302 — acp_contract.atom_decompose_jobs
--
-- Tracks Bedrock Batch (CreateModelInvocationJob) submissions for
-- POST /v1/atoms/decompose. One row per batch job, not per tour.

BEGIN;

CREATE TABLE acp_contract.atom_decompose_jobs (
  job_id            TEXT PRIMARY KEY,
  tour_ids          JSONB NOT NULL,
  status            TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','in_progress','completed','failed')),
  input_s3_uri      TEXT NOT NULL,
  output_s3_uri     TEXT,
  submitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at      TIMESTAMPTZ,
  error_message     TEXT,
  atoms_created      INTEGER DEFAULT 0
);

CREATE INDEX idx_atom_decompose_jobs_status ON acp_contract.atom_decompose_jobs(status) WHERE status IN ('submitted','in_progress');

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('081', now(), 'AA-302: acp_contract.atom_decompose_jobs — tracking Bedrock Batch job')
ON CONFLICT (version) DO NOTHING;

COMMIT;
