-- Migration 118: AA-466 — acp_shared.content_piece gains 'processing' + 'failed' status values.
--
-- Reverses part of migration 115's own documented premise ("status has only 2 values because a
-- row is only ever INSERTed once the single write-and-check request has already finished... no
-- extra room reserved for a THIRD in-between status"). That premise is what AA-466 changes: T9's
-- /write endpoint moves to 202 Accepted + poll (real API Gateway 504s on long LLM+T10 runs,
-- AA-453/465) — a placeholder row must now exist from the START of the write attempt, not only
-- at the end, so callers have something to poll by `piece_id` immediately.
--
-- 'processing' = in-flight placeholder, the ONLY non-terminal value. Never written back to once
-- one of the 3 terminal values below is set.
--
-- 'failed' is deliberately NOT the same as 'held':
--   - 'held' = a real, complete business outcome. T10 gates blocked the content after exhausting
--     attempts (or hit a non-repairable violation) — content_text is real writer output,
--     held_reason explains which gate/why, gate_ledger/repair_log are populated. The tenant is
--     meant to review it (services/acp_content_writing/service.py's own "hold VISIBLE, never
--     silent" precedent, migration 115's comment above).
--   - 'failed' = the background task itself threw (Bedrock throttle, network error, any
--     uncaught exception) before ever producing a real content_text. Nothing to review — the
--     tenant should be offered Retry, not shown "content held for quality reasons." Conflating
--     the two would surface a system outage as a content-quality verdict, which is not what
--     happened.
-- `held_reason` (existing TEXT, nullable) is reused to carry the failure message for 'failed'
-- rows too — same "why this row didn't reach approved" meaning in both cases, not a new column.
--
-- angle_gate_request.status (migration 113) is deliberately NOT touched by this migration — T8
-- and T9 stay 2 separate API surfaces/data models (AngleGateTab.tsx's own comment), so T9's
-- in-flight state lives only in T9's own table.

BEGIN;

ALTER TABLE acp_shared.content_piece
    ALTER COLUMN content_text SET DEFAULT '';

-- Default (unnamed) constraint name Postgres assigns an inline column CHECK: <table>_<column>_check
-- — matches migration 115's own unnamed `CHECK (status IN ('approved', 'held'))`.
ALTER TABLE acp_shared.content_piece
    DROP CONSTRAINT IF EXISTS content_piece_status_check;
ALTER TABLE acp_shared.content_piece
    ADD CONSTRAINT content_piece_status_check
    CHECK (status IN ('processing', 'approved', 'held', 'failed'));

COMMENT ON TABLE acp_shared.content_piece IS
    'AA-450 T9/T10 — one row per write attempt (max 2/request, single-endpoint architecture). '
    'AA-466: row now exists from request start (status=processing placeholder), updated in place '
    'when the background task finishes. status=approved passed every T10 gate; status=held '
    'exhausted attempts still failing, kept visible with gate_ledger/repair_log/held_reason for '
    'review, never silently discarded; status=failed is a real system error in the background '
    'task (no content produced) — distinct from held, see this migration''s own header.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('118', now(),
    'AA-466: content_piece.status gains processing (in-flight placeholder) + failed (system '
    'error, distinct from held) — enables /write 202 Accepted + poll')
ON CONFLICT (version) DO NOTHING;

COMMIT;
