-- Migration 105: acp_deliver.pieces review_status/reviewed_by/reviewed_at/review_note (AA-412)
--
-- Context: AA-412 (Gate C per-piece review UI) confirmed there is no column anywhere recording
-- a HUMAN review decision on a piece. `acp_deliver.pieces.status` (migration 094) is the GATE
-- outcome only (in_progress/passed/held, written exclusively by gates.py::run_gates()) -- a
-- packet's own `publish_mode` ramp (propose_only/approve_to_publish/veto_window_auto, migration
-- 094) is the only "approval" state that has ever existed, and it lives on the PACKET, not the
-- piece. AA-412 requires per-piece approve/reject before a packet can advance past
-- 'propose_only' -- see docs/implementation-notes/AA-412.md D1/D2 for the full decision record
-- (the ramp mechanism in trust_ramp.py/packets.py itself is NOT changed by this migration or its
-- follow-up code -- only this new independent per-piece review state is added).
--
-- Additive only, same style as migration 102 (repair_log/repair_budget/initial_failing_gate_count
-- added the same way onto this same table). No backfill needed -- every existing row predates
-- per-piece review and 'pending' (the default) is the correct "not yet reviewed" state for all
-- of them, not a data-quality gap.

BEGIN;

ALTER TABLE acp_deliver.pieces
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    ADD COLUMN IF NOT EXISTS reviewed_by   TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS review_note   TEXT;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('105', now(),
        'AA-412: acp_deliver.pieces.review_status/reviewed_by/reviewed_at/review_note -- '
        'per-piece human approve/reject, independent of the gate-outcome status column')
ON CONFLICT (version) DO NOTHING;

COMMIT;
