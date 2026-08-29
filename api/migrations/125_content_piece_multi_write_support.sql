-- Migration 125: AA-497 (AA-494 Decision 3) — allow a second real T9 write on the same
-- angle_gate_request, after a reopen -> re-select-angle -> approved cycle.
--
-- STEP0-refresh (live schema read, 30/08/2026): migration 124 already added 'reusable' to
-- angle_gate_request.status's CHECK constraint (Decision 3's chosen value name — no new status
-- migration needed here, nothing changes about that constraint). What migration 124's own header
-- explicitly flagged and left open ("a genuine, separate schema question... flagged for the next
-- session") is THIS gap: `content_piece` has UNIQUE (angle_gate_request_id, attempt_number), and
-- services/acp_content_writing/service.py::_insert_placeholder_piece() always inserts
-- attempt_number=1 on every call to start_write() — a single content_piece row is written once
-- per request today, its attempt_number ending at 1 or 2 depending on whether T9's own internal
-- write/rewrite-with-feedback retry loop (MAX_ATTEMPTS=2, unrelated counter) needed a second
-- pass. Once AA-497's reopen action lets a tenant return an 'approved' request to 'reusable' and
-- choose_angle() again, then write again, a second start_write() call on the SAME request_id
-- would try to INSERT a second attempt_number=1 row — colliding with this UNIQUE constraint in
-- the (very common) case where the first write passed on its first internal try. This is a real,
-- reachable crash, not a theoretical one: confirmed live (30/08/2026) there are currently 0 rows
-- with status IN ('approved','reusable') and 0 requests with >1 content_piece row, so this drop
-- is data-safe.
--
-- Fix: drop the constraint. `attempt_number` keeps its existing meaning (T9's internal 1-2 retry
-- counter within ONE write session, unchanged) — it just no longer needs to be unique across the
-- whole request, since a request can now have multiple independent write sessions (multiple rows)
-- over time. Confirmed via grep (STEP0-refresh) that no code anywhere queries content_piece by
-- angle_gate_request_id ordering on attempt_number to find "the" piece for a request — every real
-- call site either fetches by piece_id directly (fetch_piece()) or aggregates by tenant_id +
-- created_at range (tenant_pool.py's atom-availability rule, v1_publish.py's pending-list) — so
-- dropping this constraint doesn't silently break any existing "latest piece" lookup.
-- idx_content_piece_request (angle_gate_request_id, attempt_number DESC) is left in place —
-- harmless, still a valid index for future request-scoped piece listing.

BEGIN;

ALTER TABLE acp_shared.content_piece
    DROP CONSTRAINT IF EXISTS content_piece_angle_gate_request_id_attempt_number_key;

COMMENT ON COLUMN acp_shared.content_piece.attempt_number IS
    'T9''s internal write/rewrite-with-feedback retry counter within ONE write session (1 or 2, '
    'MAX_ATTEMPTS in services/acp_content_writing/service.py) — NOT a per-request sequence number. '
    'AA-497 (migration 125): no longer unique per angle_gate_request_id — a request can have '
    'multiple content_piece rows over time via the approved -> reusable -> re-choose -> approved '
    '-> write-again cycle (AA-494 Decision 3).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('125', now(),
    'AA-497: drop content_piece UNIQUE(angle_gate_request_id, attempt_number) — required for a '
    'second real T9 write on a reopened (reusable -> re-chosen -> approved) request')
ON CONFLICT (version) DO NOTHING;

COMMIT;
