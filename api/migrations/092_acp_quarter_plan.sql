-- Migration 092: acp_shared.quarter_plan + quarter_plan_version (AA-320)
--
-- Context: Gate B (Ms. Thu approval of a QuarterPlan) currently exists only in-memory
-- (QuarterPlan.approved flag, set by approve_quarter_plan() in services/acp_planning/quarter.py).
-- N6 (allocate_month -> compute_slot_grid) already refuses to run without an approved plan
-- (allocator.py:78-80, QuarterPlanNotApprovedError) -- that check stays, only its DATA SOURCE
-- changes: from an in-memory flag to a persisted quarter_plan_version.approval_status row.
--
-- Decision (Nghiep, S131): full versioning from day one (phuong an B), not minimal-then-migrate,
-- because AA-307 (N5b Quarter Override) will need quarter_plan_version regardless. Re-approving
-- a quarter NEVER overwrites -- it always creates a new version; old versions stay queryable.
--
-- tenant_id type decision (Nghiep, S131): UUID, not varchar. This diverges from the acp_shared
-- house style seen in acp_runs/acp_run_context/audit_log (all varchar tenant_id) -- deliberate,
-- because services/acp_planning/*.py already types tenant_id as UUID throughout (plan_quarter,
-- allocate_month signatures). Matching the live Python code takes priority over matching older
-- sibling tables. Future acp_shared tables should not assume one convention from this alone --
-- check the actual call site's type before copying either pattern.
--
-- STEP 0 source (S131): services/acp_planning/quarter.py:212-233, allocator.py:78-82,191-207,
-- models.py:25-27 (QuarterPlanNotApprovedError), admin.py (verify_admin_secret pattern),
-- admin_atoms.py:360-411 (preview-slotgrid demo endpoint -- NOT reused by the real endpoints
-- this migration supports; preview keeps its own hardcoded demo constants and auto-approve,
-- untouched by this change).
--
-- Syntax fix vs. reviewed draft (S131 refresh): shared.schema_versions.version is VARCHAR(20)
-- (see 003_schema_v3.sql) and house style (086-091) always inserts it quoted ('089', '091').
-- Draft used a bare integer (92) -- quoted to '092' below to match the actual column type and
-- repo convention. No other content changed from the reviewed design.

BEGIN;

CREATE TABLE acp_shared.quarter_plan (
    plan_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    year                INTEGER NOT NULL,
    quarter             SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    current_version_id  UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, year, quarter)
);

CREATE TABLE acp_shared.quarter_plan_version (
    version_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id           UUID NOT NULL REFERENCES acp_shared.quarter_plan(plan_id),
    version_no        INTEGER NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    source            VARCHAR NOT NULL DEFAULT 'standard' CHECK (source IN ('standard', 'override')),
    approval_status   VARCHAR NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    approved_by       VARCHAR,
    approved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, version_no)
);

ALTER TABLE acp_shared.quarter_plan
    ADD CONSTRAINT fk_quarter_plan_current_version
    FOREIGN KEY (current_version_id) REFERENCES acp_shared.quarter_plan_version(version_id);

CREATE INDEX idx_quarter_plan_version_plan_id ON acp_shared.quarter_plan_version(plan_id);
CREATE INDEX idx_quarter_plan_version_approval_status ON acp_shared.quarter_plan_version(approval_status);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('092', now(), 'AA-320: acp_shared.quarter_plan + quarter_plan_version -- Gate B persist')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- NOT covered by this migration (deliberately out of scope for AA-320):
-- - No backfill: no historical quarter plans exist to migrate (feature was never persisted).
-- - AA-307 (N5b Quarter Override) will consume the `source = 'override'` value already
--   reserved here, but override-specific fields (if any) are AA-307's own migration, not this one.
