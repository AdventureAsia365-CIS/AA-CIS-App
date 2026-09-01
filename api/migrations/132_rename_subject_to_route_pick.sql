-- Migration 132: AA-511 STEP0 — rename acp_contract.subject -> acp_contract.route_pick
--
-- AA-510 (migration 131) named its Route-pick-snapshot table `subject`. AA-511 needs a
-- genuinely different concept under that same word — a Slate proposal, channel-scoped, with a
-- Score/Bar/state machine (proposed/picked/used/cut), covering BOTH Segment and Route picks —
-- built as `acp_shared.subject`. Two tables named `subject` (different schemas, unrelated shape)
-- would be a permanent source of confusion. Nghiệp's explicit decision (AA-511 STEP0 report):
-- rename AA-510's table out of the way rather than have both keep the name.
--
-- AA-510's table keeps its exact shape and data (a straight rename, no column changes) — it is
-- a one-time Route pick snapshot (ADR 0024), unrelated in grain and purpose to the new
-- acp_shared.subject this issue builds. `/v1/subjects` (AA-510) had no real frontend consumer
-- yet, so the API-contract break here is accepted deliberately (see docs/implementation-notes/
-- AA-510.md, note added the same day) rather than kept as a compatibility shim.

BEGIN;

ALTER TABLE acp_contract.subject RENAME TO route_pick;
ALTER TABLE acp_contract.route_pick RENAME COLUMN subject_id TO route_pick_id;
ALTER INDEX acp_contract.idx_subject_tenant RENAME TO idx_route_pick_tenant;

COMMENT ON TABLE acp_contract.route_pick IS
    'AA-510: a marketer''s one-time Route pick, snapshotted (ADR 0024) — never a live FK into '
    'route.route_id. Named `subject` at AA-510, renamed here (AA-511) to free that name for the '
    'unrelated Slate-proposal concept in acp_shared.subject.';

COMMENT ON COLUMN acp_contract.route_pick.route_snapshot IS
    'Immutable snapshot of the Route at pick time (ADR 0024) — no live FK to route.route_id. '
    'The Route it came from can be deleted or regrouped by the next rebuild without touching '
    'this row.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('132', now(),
    'AA-511 STEP0: rename acp_contract.subject -> acp_contract.route_pick (data-preserving '
    'RENAME, subject_id -> route_pick_id) — frees the name `subject` for acp_shared.subject '
    '(AA-511 Slate), a different concept AA-510 did not anticipate. No column/data changes '
    'beyond the rename.')
ON CONFLICT (version) DO NOTHING;

COMMIT;
