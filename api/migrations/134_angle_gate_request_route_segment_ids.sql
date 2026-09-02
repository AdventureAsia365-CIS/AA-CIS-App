-- Migration 134: AA-511 Gap A (post-Done follow-up, 2026-09-02) —
-- angle_gate_request.route_segment_ids
--
-- The original AA-511 pass's `pick_subject()` resolved a Route/Blog pick down to ONE
-- representative atom, same as a Segment pick — disclosed in that function's own docstring as
-- "T9's writer therefore currently sees only that one atom's text, not the full journey
-- acp_contract.route.ordered_segment_ids describes". Reported as a real gap ("phá đúng mục đích
-- Route") and fixed here: `pick_subject()` now ALSO persists the Route's full
-- `ordered_segment_ids` at pick time (nullable — NULL for every Segment pick and every
-- pre-existing atom-picker request, which never had a Route to begin with).
--
-- `atom_id`/`trip_id` are UNCHANGED (still NOT NULL, still one representative atom) — this is an
-- ADDITIONAL column, not a replacement, since angle_gate_request's grain stays per-atom for every
-- other reader (T8's goal/angle steps). T9's start_write() (services/acp_content_writing/
-- service.py) is the one consumer that reads route_segment_ids, when present, to build its write
-- seed from every Segment along the walk instead of the single representative atom.

BEGIN;

ALTER TABLE acp_shared.angle_gate_request
    ADD COLUMN IF NOT EXISTS route_segment_ids JSONB NULL;

COMMENT ON COLUMN acp_shared.angle_gate_request.route_segment_ids IS
    'AA-511 Gap A — the Route''s full ordered_segment_ids at pick time (acp_shared.slate.py::'
    'pick_subject()), for a Route/Blog Subject pick only. NULL for a Segment pick or a '
    'pre-Slate atom-picker request. Read by services/acp_content_writing/service.py::'
    'start_write() to build the T9 write seed from the whole walk, not just atom_id''s one '
    'representative atom.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('134', now(),
    'AA-511 Gap A: angle_gate_request.route_segment_ids — a Route/Blog pick now carries its '
    'whole ordered_segment_ids, not just one representative atom')
ON CONFLICT (version) DO NOTHING;

COMMIT;
