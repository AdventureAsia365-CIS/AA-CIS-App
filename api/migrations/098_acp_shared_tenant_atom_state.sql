-- Migration 098: acp_shared.tenant_atom_state (AA-309 N1)
--
-- Context: AA-309 [ACP2-N1] onboarding. D3 (confirmed AA-330 STEP 0): atoms stay TOUR-owned,
-- platform-scoped (owner_scope='platform' on acp_contract.tour_atoms) — only USAGE STATE is
-- per-tenant. This table is that per-tenant state. Grain is (tenant_id, tour_id), NOT
-- (tenant_id, atom_id) — a deliberate decision (Nghiep, AA-309 build task, confirmed 08/08/2026),
-- narrower than this migration's own STEP 0 comment proposal (which suggested atom_id grain).
-- assigned_angle/starred/cooldown_until are decided at the TOUR level for a tenant, not per
-- individual atom fact.
--
-- assigned_angle vocabulary (AA-309 build task decision 3 — fixed list, not free text, to avoid
-- 11 tenants inventing 11 incompatible angle names with nothing comparable across them):
--   culinary_people      Ẩm thực & Con người
--   physical_terrain     Thể lực & Địa hình
--   culture_craft        Văn hoá & Thủ công
--   nature_wildlife      Thiên nhiên & Hoang dã
--   luxury_leisure       Sang trọng & Nghỉ dưỡng
--   family_group         Gia đình & Trải nghiệm nhóm
--   wellness_spiritual   Tâm linh & Chữa lành
-- 7 angles, not the 3 illustrative examples in AA-309's original description: AA-332 cites a real
-- business ceiling of ~3-5 tenants per (destination, source market) before a new destination must
-- be opened — 7 gives headroom above that ceiling (not every destination's content fits every
-- angle equally well; a Sang trọng & Nghỉ dưỡng framing may not suit a budget trekking country,
-- so some slack beyond the exact tenant ceiling matters) without growing so large that comparing
-- tenants' angles becomes unmanageable. Each angle is a distinct narrative lens applicable across
-- destinations (not destination-specific), so the same underlying atom facts can genuinely produce
-- different content depending which angle a tenant is assigned. TEXT + CHECK, not a native Postgres
-- enum, matching this table family's own existing convention (acp_contract.tour_atoms.
-- distinctiveness, migration 079) — extending the list later is an ALTER ... DROP/ADD CONSTRAINT,
-- not an ALTER TYPE (which cannot run inside a transaction).
--
-- cooldown_until (TIMESTAMPTZ, nullable, single value — not the {channel: date} JSONB shape
-- tour_atoms.cooldown_until uses) and usage_log (JSONB, default '[]') both seed EMPTY here and have
-- NO WRITER in this issue. AA-330 STEP 0 already found tour_atoms.cooldown_until (the platform-level
-- analogue) has ZERO write sites anywhere in the repo despite being read by allocator.py — a
-- designed-but-never-wired column. This migration deliberately does not repeat that silently: the
-- real writer for these two columns belongs to a future N7/N8-scoped issue (once per-tenant content
-- production actually runs), NOT this one. Flagged here so it isn't rediscovered as a surprise gap.
--
-- No FK to acp_contract.tour_atoms (grain is tour_id, not atom_id) — FK is to
-- silver_aa_internal.raw_tours(tour_id), the same target acp_contract.tour_atoms.tour_id itself
-- references (migration 079).

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.tenant_atom_state (
    tenant_id       UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    tour_id         UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
    assigned_angle  TEXT
                        CHECK (assigned_angle IN (
                            'culinary_people', 'physical_terrain', 'culture_craft',
                            'nature_wildlife', 'luxury_leisure', 'family_group', 'wellness_spiritual'
                        )),
    starred         BOOLEAN NOT NULL DEFAULT false,
    cooldown_until  TIMESTAMPTZ,
    usage_log       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tour_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_atom_state_tenant ON acp_shared.tenant_atom_state(tenant_id);

-- Gate A approval state — mirrors acp_shared.quarter_plan_version's pattern (AA-320) exactly
-- (approval_status/approved_by/approved_at, row-locked approve, reject re-approval) since the
-- AA-309 build task requires the SAME pattern. Deliberately NOT versioned like quarter_plan_version
-- (no plan_id/version_no/current_version_id indirection) — onboarding happens once per tenant, no
-- re-planning need, so a single row per tenant is enough; PRIMARY KEY tenant_id instead of a
-- separate version table. portfolio_id is kept for traceability back to the Marketplace handoff
-- (AA-330) even though tenant_atom_state.tour_id already carries the same tour list.
CREATE TABLE IF NOT EXISTS acp_shared.tenant_onboarding (
    tenant_id        UUID PRIMARY KEY REFERENCES shared.tenants(tenant_id),
    portfolio_id     UUID NOT NULL REFERENCES acp_shared.marketplace_portfolios(portfolio_id),
    approval_status  TEXT NOT NULL DEFAULT 'pending' CHECK (approval_status IN ('pending', 'approved')),
    approved_by      TEXT,
    approved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_shared TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.tenant_atom_state TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.tenant_onboarding TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('098', now(), 'AA-309 N1: acp_shared.tenant_atom_state (per-tenant tour usage state) + acp_shared.tenant_onboarding (Gate A)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
