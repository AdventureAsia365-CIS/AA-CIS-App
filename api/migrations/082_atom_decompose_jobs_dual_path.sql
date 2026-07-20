-- Migration 082: AA-305 — acp_contract.atom_decompose_jobs dual-path bookkeeping
--
-- Two additive columns, no constraint change, no backfill (existing rows get
-- NULL — honest: we don't know their real per-tour breakdown retroactively).
--
-- job_arn TEXT — the real Bedrock ModelInvocationJob ARN, captured from
--   create_model_invocation_job()'s response at submit time (>=100 path).
--   Not previously stored anywhere — the submit call's return value was never
--   captured. Without it, GetModelInvocationJob(jobIdentifier=...) cannot be
--   called later: jobIdentifier must be the full ARN, a bare job name is
--   rejected ("The provided ARN is invalid" — verified live against
--   atomjob_cf3d9066e0). The AA-305 poller needs this to know which real job
--   to check. Stays NULL for the inline (<100) path — no Bedrock Batch job
--   exists in that case.
--
-- succeeded_count / failed_count INTEGER — tour-level pass/fail counts,
--   queryable directly instead of parsing the error_message JSON blob.
--   Populated immediately at insert for the inline (<100) path (numbers
--   already known in-process). For the >=100 Batch path, NULL at submit time
--   (job hasn't run yet) and filled in later by the poller only when it can
--   read a real value from GetModelInvocationJob's successRecordCount/
--   errorRecordCount fields — never a guessed number.

BEGIN;

ALTER TABLE acp_contract.atom_decompose_jobs
    ADD COLUMN job_arn TEXT,
    ADD COLUMN succeeded_count INTEGER,
    ADD COLUMN failed_count INTEGER;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('082', now(),
        'AA-305: atom_decompose_jobs — job_arn (poller lookup) + succeeded_count/failed_count (dual-path bookkeeping)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
