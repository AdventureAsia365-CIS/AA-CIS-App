-- =============================================================================
-- Migration 060: acp_run_context S3 offload keys
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-122 — S3 Lambda context size guardrail
-- =============================================================================
-- Adds TEXT columns to store S3 keys for large stage outputs.
-- When present, the S3 Lambda reads data from S3 instead of inline JSONB,
-- preventing OOM on large keyword/visibility payloads (500KB threshold).
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_run_context
    ADD COLUMN IF NOT EXISTS s2_keywords_s3_key  TEXT,
    ADD COLUMN IF NOT EXISTS s2_report_s3_key     TEXT;

COMMENT ON COLUMN acp_shared.acp_run_context.s2_keywords_s3_key IS
    'S3 key for DataForSEO keyword payload (acp/s2/{run_id}/keywords.json). '
    'When set, S3 Lambda loads keywords from S3 instead of inline s2_keyword_research.';

COMMENT ON COLUMN acp_shared.acp_run_context.s2_report_s3_key IS
    'S3 key for large visibility report (acp/s2/{run_id}/s2_visibility_report.json). '
    'Currently unused — reserved for when s2_visibility_report exceeds 200KB.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('060', NOW(), 'acp_run_context S3 offload keys [AA-122]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
