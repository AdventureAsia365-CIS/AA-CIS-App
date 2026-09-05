-- Migration 145: AA-529 — acp_shared.facts, the "Facts Entry" citable source T9's content_seed
-- builder was missing (see docs/implementation-notes/AA-529.md for the full STEP0/decisions
-- record). Real, measured gap this closes: a claim that doesn't live in a tour's own itinerary
-- text (reference price, travel season, visa/entry requirement, estimated transfer time between
-- places...) had NOTHING to cite it against, so F1_grounding correctly-but-permanently blocked
-- that whole class of otherwise valid content (piece c771a4d5/7ca09d4b, tenant wanderlux-travel,
-- a "$100 in Laos" claim — the atom's own text has zero digits in it).
--
-- Two scopes, not one flat table (Nghiep's confirmed architecture, 05/09/2026, appended to the
-- AA-529 issue itself): 'platform' = AA-admin writes ONE shared set of objective facts usable by
-- EVERY tenant (weather/season, visa, typical transfer times...); 'tenant' = each tenant writes
-- their OWN facts, visible ONLY to them (their own pricing, their own cancel/rebook terms, deals
-- specific to their business). tenant_id is NULL iff scope='platform', required iff
-- scope='tenant' — enforced by a CHECK, not just convention.
--
-- fact_id is TEXT PRIMARY KEY, application-generated as "fact_" + uuid4().hex[:10] — same format
-- acp_contract.tour_atoms.atom_id already uses (migration 079), for the same reason: this id is
-- what a [F:<fact_id>] citation tag in generated content actually names (services/
-- acp_content_writing/quality_gates.py::TAG_RE already accepts "F:" identically to "R:" — it was
-- unused latent capacity until this migration gives it a real source to point at).
--
-- One `provenance TEXT NOT NULL` column (not separate written_by/source_note fields) — the
-- issue's own ask is "nguồn dẫn (ai viết, dựa trên gì)" as one idea; a free-text field ("Admin
-- Nghiep, based on the published rate card, 09/2026") is what keeps a fact verifiable, without
-- inventing structure the issue never asked for. NOT NULL — a fact with no stated source defeats
-- the whole point of this table.
--
-- No write-side UI/API in this migration or the issue it ships with — deferred to the upcoming
-- Admin/Tenant redesign epic per the issue's own explicit instruction (backend/schema only here).

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.facts (
    fact_id      TEXT PRIMARY KEY,
    scope        TEXT NOT NULL CHECK (scope IN ('platform', 'tenant')),
    tenant_id    UUID REFERENCES shared.tenants(tenant_id),
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    stated_on    DATE,
    provenance   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT facts_scope_tenant_ck CHECK (
        (scope = 'platform' AND tenant_id IS NULL) OR
        (scope = 'tenant' AND tenant_id IS NOT NULL)
    )
);

COMMENT ON TABLE acp_shared.facts IS
    'AA-529 — hand-written, sourced claims not present in any tour itinerary (price, season, '
    'visa, transfer time...) that T9 can cite via [F:<fact_id>], alongside [R:<atom_id>]. '
    'scope=platform is written by AA-admin, visible to every tenant; scope=tenant is one '
    'tenant''s own, visible only to them. tenant_id NULL iff scope=platform (enforced by '
    'facts_scope_tenant_ck).';

CREATE INDEX IF NOT EXISTS idx_facts_tenant
    ON acp_shared.facts(tenant_id) WHERE scope = 'tenant';
CREATE INDEX IF NOT EXISTS idx_facts_scope
    ON acp_shared.facts(scope);

-- Same tenant_isolation convention acp_shared.content_piece/angle_gate_request already carry
-- (migration 115/113) — defense-in-depth, not this table's actual enforcement boundary (the app
-- doesn't set app.tenant_id on this pool; the real boundary is services/acp_content_writing/
-- facts.py::fetch_facts_for_writing()'s own explicit WHERE clause, same as every other
-- tenant-scoped query in this codebase). Extended for the platform/tenant split: a platform row
-- is visible regardless of the session's own tenant setting.
ALTER TABLE acp_shared.facts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON acp_shared.facts;
CREATE POLICY tenant_isolation ON acp_shared.facts
    USING (scope = 'platform' OR tenant_id::text = current_setting('app.tenant_id', true));

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('145', now(),
    'AA-529: acp_shared.facts — platform/tenant-scoped Facts Entry source for T9 content_seed, '
    'cited via [F:<fact_id>] (TAG_RE already accepted this prefix, previously unused)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
