-- Migration 133: AA-511 -- acp_shared.subject (the Slate proposal) + angle_gate_request.subject_id
--
-- See docs/claude_audit/AA-511-step0-slate-investigation.md for the full evidence trail:
--   - subject.score is copied from acp_contract.atom_ranking.total_rank (Segment subjects) or
--     acp_contract.route.score (Route/Blog subjects) -- no separate scoring table (confirmed
--     duplicate of AA-515's atom_ranking, per STEP0 point 3a; NOT built here).
--   - The name `subject` was freed for this table by migration 132 (renamed AA-510's own
--     `acp_contract.subject` -> `acp_contract.route_pick` -- a different, unrelated concept).
--
-- Literal schema from the AA-511 build prompt, unchanged except the 2 partial unique indexes
-- added below (needed for propose_slate()'s idempotent upsert -- a re-run must refresh a still-
-- `proposed` row's score/cleared_bar_reason rather than mint a duplicate, and must never touch a
-- row already `picked`/`used`/`cut`; see services/acp_shared/slate.py's own module docstring).

BEGIN;

CREATE TABLE acp_shared.subject (
  subject_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES shared.tenants(tenant_id),
  segment_id         text REFERENCES acp_contract.atom_segment(segment_id),
  route_id           text REFERENCES acp_contract.route(route_id),
  channel            text NOT NULL,
  state              text NOT NULL DEFAULT 'proposed' CHECK (state IN ('proposed','picked','used','cut')),
  cleared_bar_reason jsonb NOT NULL,
  score              numeric,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CHECK ((segment_id IS NOT NULL AND route_id IS NULL) OR (segment_id IS NULL AND route_id IS NOT NULL))
);

-- One live proposal per (tenant, channel, segment-or-route) -- propose_slate()'s ON CONFLICT
-- target. Deliberately NOT scoped to `state = 'proposed'` in the index predicate itself (a
-- partial unique index's predicate must match the ON CONFLICT clause verbatim for Postgres to
-- use it for inference) -- the "never touch an already-decided row" rule is enforced instead by
-- the INSERT's own `DO UPDATE ... WHERE state = 'proposed'` clause, which turns a conflict
-- against a picked/used/cut row into a silent no-op rather than an overwrite.
CREATE UNIQUE INDEX idx_subject_unique_segment
    ON acp_shared.subject(tenant_id, channel, segment_id) WHERE segment_id IS NOT NULL;
CREATE UNIQUE INDEX idx_subject_unique_route
    ON acp_shared.subject(tenant_id, channel, route_id) WHERE route_id IS NOT NULL;

CREATE INDEX idx_subject_tenant_channel_score ON acp_shared.subject(tenant_id, channel, score);

COMMENT ON TABLE acp_shared.subject IS
    'AA-511: the Slate proposal -- one row per (tenant, Channel, Segment-or-Route) that has '
    'cleared that Channel''s Bar at least once. score = acp_contract.atom_ranking.total_rank '
    '(Segment) or acp_contract.route.score (Route/Blog), copied at propose time, never '
    'recomputed here. NOT the same table as acp_contract.route_pick (a one-time Route-pick '
    'snapshot, migration 132) -- different grain, different purpose, unrelated except by the '
    'name they both once carried.';

-- angle_gate_request.subject_id: traces a T8 request back to the Slate proposal that produced
-- it (pick_subject(), services/acp_shared/slate.py). Nullable -- the pre-existing admin/tenant
-- atom-picker entry point (AA-449's own create_request(), unchanged) creates a request with no
-- Subject at all, and that path is NOT being retired by this build.
ALTER TABLE acp_shared.angle_gate_request
    ADD COLUMN subject_id uuid REFERENCES acp_shared.subject(subject_id);

CREATE INDEX idx_angle_gate_request_subject ON acp_shared.angle_gate_request(subject_id)
    WHERE subject_id IS NOT NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('133', now(),
    'AA-511: acp_shared.subject (Slate proposal, Bar+Score from AA-515/AA-510, state machine '
    'proposed/picked/used/cut) + angle_gate_request.subject_id (traces a T8 request back to its '
    'Slate pick)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
