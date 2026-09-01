-- Migration 130: AA-515 — acp_contract.search_demand (bought-keyword cache) +
-- acp_contract.segment_research_log (place-level research freshness) +
-- acp_contract.atom_ranking (Segment rank-sum, per (tenant, tour)).
--
-- Ported from Ms. Thư's aa-social-media (src/aa_social/stages/research.py's `search_demand`
-- table + src/aa_social/stages/score.py's `atom_scores`/rank-sum) — see
-- docs/claude_audit/AA-515-step0-ranking-investigation.md,
-- AA-515-step0b-demand-research-loop.md, AA-515-step0c-multimarket-schema.md for the full
-- evidence this schema is built on.

BEGIN;

-- search_demand: NOT scoped by tenant_id, unlike every other AA-508/509 table. Deliberate —
-- a keyword's search volume in a market is a fact about the outside world, not tenant content
-- (unlike an atom's text or a Segment's grouping, which describe one tenant's own tour). Two
-- tenants both researching "Kyoto" share one row and one purchase, saving a real repeat
-- DataForSEO cost rather than risking any cross-tenant data leak — matches Ms. Thư's own
-- reference schema (PK on (keyword, market) alone, one SQLite file per BRAND but no tenant
-- concept to begin with either way).
CREATE TABLE acp_contract.search_demand (
    keyword         TEXT NOT NULL,
    market          TEXT NOT NULL,
    search_volume   INT NULL,
    people_also_ask JSONB NOT NULL DEFAULT '[]',
    retrieved_on    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (keyword, market)
);

COMMENT ON COLUMN acp_contract.search_demand.search_volume IS
    'NULL is a real, distinct measured value (DataForSEO returned the keyword with no volume '
    'data) from "never measured" (row absence) — same convention services/acp_shared/'
    'dfs_relevance.py already uses for keyword_ideas.search_volume.';

-- segment_research_log: place-level freshness marker, separate from the per-keyword cache
-- above. Checked BEFORE starting the LLM ReAct loop for a place — if every market a tenant
-- sells to already has a row here within FRESH_FOR (182 days, segment_research.py), the whole
-- loop is skipped (no LLM call, no DataForSEO call), not just the individual keyword buys.
-- Not tenant-scoped for the same reason search_demand isn't — "was this place researched
-- recently" is a fact about the place+market, not about which tenant asked.
CREATE TABLE acp_contract.segment_research_log (
    canonical_place TEXT NOT NULL,
    market          TEXT NOT NULL,
    researched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canonical_place, market)
);

-- atom_ranking: one row per (tenant, tour, Segment) — NOT per atom (unlike Ms. Thư's
-- atom_scores, which is written per-Atom "because that is the grain the slate reads"; AA-CIS's
-- own Route (AA-510) reads per-tour, so this table is unnested by tour_id instead — a Segment
-- spanning 3 tours of one tenant gets 3 rows, same rank values, one per tour it actually
-- touches). Rebuilt WHOLE per tenant on every run (DELETE+INSERT, matching the AA-510 STEP0
-- finding that Ms. Thư's own `routes`/`atom_scores` tables are "derived, never accumulated" —
-- no downstream table has an FK into this one yet expecting stability across re-runs).
--
-- excluded_reason carries a Segment past the transit/unnamed-place gate rather than dropping
-- it silently — "an exclusion is arguable rather than a silent absence" (score.py's own
-- docstring). A ranked row has excluded_reason NULL and every rank column populated; an
-- excluded row has excluded_reason set and every rank column NULL — WHERE excluded_reason IS
-- NULL is the real ranking list, the rest is the "excluded, why" list.
CREATE TABLE acp_contract.atom_ranking (
    tenant_id        UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    tour_id          UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
    segment_id       TEXT NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
    demand_rank      INT NULL,
    recurrence_rank  INT NULL,
    questions_rank   INT NULL,
    said_rank        INT NULL,
    total_rank       INT NULL,
    demand_market    TEXT NULL,
    demand_volume    INT NULL,
    recurrence       INT NOT NULL DEFAULT 0,
    questions        INT NOT NULL DEFAULT 0,
    said             INT NOT NULL DEFAULT 0,
    excluded_reason  TEXT NULL CHECK (excluded_reason IN ('transit', 'unnamed_place')),
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, tour_id, segment_id)
);

CREATE INDEX idx_atom_ranking_tenant_tour ON acp_contract.atom_ranking(tenant_id, tour_id);
CREATE INDEX idx_atom_ranking_tenant_total_rank
    ON acp_contract.atom_ranking(tenant_id, total_rank)
    WHERE excluded_reason IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('130', now(),
    'AA-515: acp_contract.search_demand (bought-keyword cache, not tenant-scoped by design) + '
    'segment_research_log (place-level freshness) + atom_ranking (Segment rank-sum per '
    'tenant/tour, transit/unnamed-place excluded but not hidden) — ranking stage for Route '
    '(AA-510)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
