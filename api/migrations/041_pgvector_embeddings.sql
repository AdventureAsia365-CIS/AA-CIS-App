-- =============================================================================
-- Migration 041: pgvector extension + content_embedding columns [AA-62]
-- Project: AA-CIS | Date: 21/05/2026
-- =============================================================================
-- Requires rds_superuser role or pg_extension_owner membership.
-- Dimension 1536 = Bedrock Titan Embed Text v2 output.
-- ivfflat index: lists=10 suitable for < 1M rows (UAT scale).
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE gold_aa_internal.published_tours
    ADD COLUMN IF NOT EXISTS content_embedding vector(1536);

CREATE INDEX IF NOT EXISTS idx_pt_embedding
    ON gold_aa_internal.published_tours
    USING ivfflat (content_embedding vector_cosine_ops)
    WITH (lists = 10);

ALTER TABLE acp_silver_s4.blog_drafts
    ADD COLUMN IF NOT EXISTS content_embedding vector(1536);

CREATE INDEX IF NOT EXISTS idx_bd_embedding
    ON acp_silver_s4.blog_drafts
    USING ivfflat (content_embedding vector_cosine_ops)
    WITH (lists = 10);

INSERT INTO shared.schema_versions (version, description)
VALUES ('041', 'pgvector extension + content_embedding columns [AA-62]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
