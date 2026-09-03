-- Migration 140: AA-499 (AA-494 Decision 5) — ivfflat cosine index on
-- acp_shared.content_piece.content_embedding.
--
-- STEP0 (AA-520 audit, confirmed no re-investigation needed — see this issue's own Linear
-- description): pgvector extension already installed (v0.8.1, migration 041/AA-62);
-- content_piece.content_embedding vector(1536) already exists (migration 124, 29/08) but was
-- never written to by any code (0 hits, confirmed by grep) until this build. AA-484's own STEP0
-- comment explicitly flagged the missing index as a real risk ("nếu chưa có index, query
-- cross-tenant sẽ chậm dần khi số bài tăng") — added here, in the same build that starts
-- actually populating the column, rather than deferred to whichever issue first needs fast
-- queries.
--
-- Same pattern as migration 041's own 2 indexes (idx_pt_embedding/idx_bd_embedding) — ivfflat +
-- vector_cosine_ops, lists=10 (that migration's own comment: "suitable for < 1M rows, UAT
-- scale") — content_piece is a much smaller table than either of those, so the same list count
-- is generously sized, not under-provisioned.
--
-- A partial index (WHERE content_embedding IS NOT NULL) is NOT used here — ivfflat naturally
-- skips NULL rows in its own build/scan (same as any B-tree), and a WHERE clause on a
-- vector-similarity index changes nothing about which rows get indexed, only which encoding
-- postgres reports for the choice — kept as a plain index for one less thing to reason about.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_content_piece_embedding
    ON acp_shared.content_piece
    USING ivfflat (content_embedding vector_cosine_ops)
    WITH (lists = 10);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('140', now(),
    'AA-499: ivfflat cosine index on content_piece.content_embedding (Decision 5) — column '
    'itself already existed from migration 124, this just makes similarity queries fast before '
    'any code starts issuing them')
ON CONFLICT (version) DO NOTHING;

COMMIT;
