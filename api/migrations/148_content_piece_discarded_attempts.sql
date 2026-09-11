-- Migration 148: AA-570 -- content_piece.discarded_attempts
--
-- AA-570's own investigation (real DB numbers, 30-day window): 66.7% of finalized pieces had
-- exactly 1 discarded attempt (MAX_ATTEMPTS=2), avg discarded content_text ~2463 bytes.
-- Projected storage cost of keeping every discarded attempt: <$0.01/month even at 50-tenant
-- scale -- storage was never the blocker, only whether it was worth building. Nghiep confirmed
-- do-now.
--
-- Single JSONB column on content_piece itself (NOT a separate table) -- the volume this issue's
-- own numbers found is far too small to justify a child table + its own indexes/migrations.
-- Written exactly once, at the same UPDATE _finalize_piece() already does (services/
-- acp_content_writing/service.py) -- never touched again after that. Each element:
-- {attempt_number, content_text, gate_ledger} -- the exact shape AA-570's own build task asked
-- for. Empty array (the default) for every single-attempt piece (the common case) and every
-- pre-AA-570 row -- there is nothing to backfill, since the earlier attempt's content was never
-- persisted anywhere before this column existed.
--
-- No TTL/archival -- AA-570's own cost analysis found the volume too small to warrant one.

BEGIN;

ALTER TABLE acp_shared.content_piece
    ADD COLUMN IF NOT EXISTS discarded_attempts JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN acp_shared.content_piece.discarded_attempts IS
    'AA-570 -- every attempt that did NOT become this row''s final content_text (MAX_ATTEMPTS=2,
    so at most 1 element today). Each element: {attempt_number, content_text, gate_ledger}.
    Written once by _finalize_piece(), never updated again. Empty for single-attempt pieces and
    every pre-AA-570 row (nothing to backfill -- the discarded content was never persisted
    before this column existed).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('148', now(),
    'AA-570: content_piece.discarded_attempts -- keeps the earlier, overwritten attempt(s) for '
    'the Data Flywheel/lesson-log use case')
ON CONFLICT (version) DO NOTHING;

COMMIT;
