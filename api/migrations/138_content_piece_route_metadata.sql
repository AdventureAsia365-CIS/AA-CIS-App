-- Migration 138: AA-519 Việc 4 -- content_piece.route_hub_name / route_segment_count
--
-- A Route/Blog pick (AA-511 Gap A, migration 134) already carries its full walk into T9's write
-- seed via angle_gate_request.route_segment_ids, and start_write() (services/acp_content_writing/
-- service.py) already resolves the pick's Hub name (angle_gate_service.fetch_request()'s own
-- subject_hub_name, joined from acp_shared.subject -> acp_contract.route) -- but neither value
-- was ever written onto content_piece itself, so it was invisible again the moment T9 finished
-- (STEP0/AA-519 issue's own finding, confirmed by grep -- 0 existing route/hub column anywhere on
-- this table). These 2 columns close that gap: set once at INSERT (immutable across T9's own
-- internal write/rewrite retry loop, same as channel/angle_gate_option_id), read by T10
-- (fetch_piece/fetch_review/fetch_review_list) and T11 (v1_publish.py::list_pending) to show
-- "Route: <hub>, N Segments" instead of a route-aware piece looking identical to a plain
-- single-atom one.
--
-- Nullable, NULL for every Segment pick, every pre-Slate atom-picker request, and every
-- pre-AA-519 row -- same "NULL means not applicable" convention every other optional
-- content_piece column already uses (seo_title/meta_description/slug, migration 136).

BEGIN;

ALTER TABLE acp_shared.content_piece
    ADD COLUMN IF NOT EXISTS route_hub_name TEXT NULL,
    ADD COLUMN IF NOT EXISTS route_segment_count SMALLINT NULL;

COMMENT ON COLUMN acp_shared.content_piece.route_hub_name IS
    'AA-519 -- the Route''s Hub name at write time (angle_gate_request/subject/route, snapshotted
    not live-joined), for a Route/Blog pick only. NULL for a Segment pick or a pre-Slate
    atom-picker request.';
COMMENT ON COLUMN acp_shared.content_piece.route_segment_count IS
    'AA-519 -- len(angle_gate_request.route_segment_ids) at write time, for a Route/Blog pick
    only. NULL alongside route_hub_name for every non-Route piece.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('138', now(),
    'AA-519 Việc 4: content_piece.route_hub_name/route_segment_count -- threads the Route/Hub
    metadata T9 already resolves through to T10/T11, previously dropped after write')
ON CONFLICT (version) DO NOTHING;

COMMIT;
