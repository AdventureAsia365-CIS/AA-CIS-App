-- Migration 126: AA-469 Việc 4 (flow-order fix) — angle_gate_request.channel becomes nullable.
--
-- Confirmed with Nghiệp (this session, supersedes an earlier same-day assumption that the
-- existing [atom+channel] -> goal -> angle -> write order was correct — it was NOT): the real
-- order is atom(+DFS/PAA+brand, server-side) -> Goal -> generate 3 angles -> pick 1 (step 7) ->
-- pick Channel (NEW step 8) -> T9 write. Channel is no longer known at request-creation time
-- (services/acp_angle_gate/service.py::create_request() no longer takes it as a param — see
-- that function's own updated header), so the column can no longer be NOT NULL.
--
-- This is the deferred flip migration 124's own header comment explicitly anticipated: "the
-- actual 'tenant picks channel at write time' UX/API flip is explicitly deferred... revisit
-- dropping [angle_gate_request.channel] only once AngleGateTab.tsx's write-time-channel redesign
-- actually ships" — that redesign is THIS session's build. Per that same comment, the column is
-- NOT dropped, only relaxed: it is still the live source `services/acp_content_writing/
-- service.py::start_write()` reads from (via `angle_gate_service.set_channel()`, new this
-- session) — just populated one step later than before, not removed.
--
-- Live-verified (30/08/2026, direct RDS read via the standard S3-mediated ECS-exec pattern, at
-- apply time): 6 total angle_gate_request rows exist, all 6 already have a real (non-NULL)
-- channel value — every real request so far went through the OLD (channel-at-creation) code
-- path. This migration touches only the constraint, not existing data — no backfill needed.

BEGIN;

ALTER TABLE acp_shared.angle_gate_request
    ALTER COLUMN channel DROP NOT NULL;

COMMENT ON COLUMN acp_shared.angle_gate_request.channel IS
    'AA-469 Việc 4 (flow-order fix): NULL until services/acp_angle_gate/service.py::set_channel() '
    '(workflow step 8, tenant-triggered, AFTER an angle is chosen) sets it. Was NOT NULL and set '
    'at request-creation time before this migration (AA-449) — create_request() no longer takes '
    'channel as a param. Required (non-NULL) before T9''s start_write() will proceed.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('126', now(),
    'AA-469 Việc 4: angle_gate_request.channel DROP NOT NULL — channel now set at a new step 8 '
    '(after angle choice), not at request creation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
