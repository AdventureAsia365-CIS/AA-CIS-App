-- Migration 112: AA-448 — T7 Content Planning: year_plan wrapper + manual content metrics
--
-- Two independent, purely additive pieces (round 6 decisions, see
-- docs/implementation-notes/AA-448-t7-content-planning.md for the full round-by-round record):
--
-- 1. acp_shared.year_plan (Shape 1, round 3/4/6) — a grouping wrapper around the 4
--    acp_shared.quarter_plan rows of one tenant/year. Every existing quarter_plan/
--    quarter_plan_version column/row keeps its current meaning unchanged; this only adds a
--    nullable FK column so a tenant's 4 quarters can be addressed as "one year plan, 4 quarters
--    inside it" without touching per-quarter version history (AA-323 round 4's history view is
--    unaffected). No data migration needed for existing rows — year_plan_id stays NULL until a
--    tenant's quarter_plan row is next touched by T7's own code, which links it.
--
-- 2. acp_shared.content_metric_snapshot (round 6, feedback loop) — manual engagement-metric
--    entry per published piece (acp_deliver.pieces.piece_id). Matches aa-marketing-v2's own H1
--    ingest_metrics precedent ("connector surface... metric snapshots can also be entered
--    manually for now" — no live Search Console/Meta connector exists in the reference OR this
--    repo). One tenant can enter more than one snapshot per piece over time (day 7/30/... same
--    idea as aamc's MetricSnapshot.day, though this repo's shape is simpler — reach/engagement/
--    clicks only, see services/acp_shared/content_metrics.py for the full rationale).

BEGIN;

-- ---------------------------------------------------------------- 1. year_plan
CREATE TABLE IF NOT EXISTS acp_shared.year_plan (
    year_plan_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    year          INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, year)
);

COMMENT ON TABLE acp_shared.year_plan IS
    'AA-448 Shape 1 — pure grouping wrapper around 4 quarter_plan rows for one tenant/year. '
    'Carries no approval/status of its own (round 6: locking + Gate B both operate at the '
    'quarter/week level, never at this table) — do not add a gating column here without '
    're-reading AA-448-00 STEP0''s naming-collision note first (this table is unrelated to '
    'aa-marketing-v2''s own YearPlan concept, which is a content-strategy document, not a '
    'grouping wrapper).';

ALTER TABLE acp_shared.quarter_plan
    ADD COLUMN IF NOT EXISTS year_plan_id UUID REFERENCES acp_shared.year_plan(year_plan_id);

CREATE INDEX IF NOT EXISTS idx_quarter_plan_year_plan_id
    ON acp_shared.quarter_plan(year_plan_id) WHERE year_plan_id IS NOT NULL;

-- ---------------------------------------------------------------- 2. content_metric_snapshot
CREATE TABLE IF NOT EXISTS acp_shared.content_metric_snapshot (
    snapshot_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    piece_id     TEXT NOT NULL REFERENCES acp_deliver.pieces(piece_id),
    reach        INTEGER,
    engagement   INTEGER,
    clicks       INTEGER,
    entered_by   TEXT NOT NULL,
    entered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE acp_shared.content_metric_snapshot IS
    'AA-448 round 6 — manual engagement-metric entry per published piece. NEW extension beyond '
    'aa-marketing-v2''s own Module H design (that reference never built a live connector '
    'either — see services/acp_shared/content_metrics.py module docstring for the full '
    'rationale). Feeds rollup_atom_weights() -> tour_atoms.weight -> compute_quarter_plan()''s '
    '5th scoring term (engagement_adjustment) and N6''s existing atom-eligibility weighting.';

CREATE INDEX IF NOT EXISTS idx_content_metric_snapshot_piece
    ON acp_shared.content_metric_snapshot(piece_id, entered_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_metric_snapshot_tenant
    ON acp_shared.content_metric_snapshot(tenant_id, entered_at DESC);

ALTER TABLE acp_shared.content_metric_snapshot ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON acp_shared.content_metric_snapshot
    USING (tenant_id::text = current_setting('app.tenant_id', true));

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('112', now(),
    'AA-448: acp_shared.year_plan (Shape 1 wrapper) + acp_shared.content_metric_snapshot '
    '(manual engagement entry, feedback loop round 6)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
