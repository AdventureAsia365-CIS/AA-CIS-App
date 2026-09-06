-- Migration 146: AA-545 — Segment/Score/Route/Hub → platform-wide.
--
-- Full spec + STEP0 + 3 rounds of /grill-with-docs (confirmed decisions, real EXPLAIN ANALYZE
-- evidence for Q3) live on the AA-545 Linear issue and docs/implementation-notes/AA-545.md.
-- ADR-0001/0003 record WHY this was tech debt, not design, and the decision to fix it.
--
-- 1 PR, 1 migration for all 4 layers (Nghiệp's explicit instruction — no half-migrated state
-- like AA-526's own Segment revert).

BEGIN;

-- ── 1. Segment (atom_segment) — drop tenant_id, PK (segment_id) unchanged ──────────────────
--
-- No rehash of the 23 existing rows' segment_id values (build decision #1,
-- docs/implementation-notes/AA-545.md) — segment_id is an opaque TEXT PK nothing downstream
-- parses; only NEW segments minted from here on use the new sha256(place|verb) formula
-- (services/acp_contract/segment_matching.py::_mint()). This also means
-- acp_shared.angle_gate_request.route_segment_ids' 1 real approved row (16 old-format
-- segment_id strings, found in /grill-with-docs round 2) needs NO fix — those exact strings
-- still exist, unchanged, in atom_segment after this migration.
DROP INDEX IF EXISTS acp_contract.idx_atom_segment_tenant;
ALTER TABLE acp_contract.atom_segment DROP COLUMN tenant_id;

COMMENT ON TABLE acp_contract.atom_segment IS
    'AA-545: platform-wide (dropped tenant_id, AA-509''s original per-tenant scoping). '
    'segment_id identity is sha256(place|verb) for anything minted after this migration '
    '(pre-migration rows keep their old-formula string values — opaque PK, never rehashed, see '
    'docs/implementation-notes/AA-545.md). A Segment can now span multiple tours AND multiple '
    'tenants'' rewrites of the same real-world moment (the origin, Ms. Thư''s aa-social-media, '
    'design ADR-0001/0003 restore).';

-- ── 2. Score (atom_ranking) — drop tenant_id, PK (tenant_id, tour_id, segment_id) →
--    (market, tour_id, segment_id) ───────────────────────────────────────────────────────────
--
-- No downstream FK references atom_ranking by row identity ("derived, never accumulated" per
-- its own migration 130 comment, reconfirmed AA-545 STEP0/build) — wiped rather than backfilled.
-- A full re-run (all 6 DFS_LOCATION_MAP markets: US/UK/AU/DE/FR/NL) repopulates it correctly
-- under the new schema as this build's own required live-verify step, immediately after this
-- migration — not left for the next real A3 trigger to eventually backfill.
DELETE FROM acp_contract.atom_ranking;
DROP INDEX IF EXISTS acp_contract.idx_atom_ranking_tenant_tour;
DROP INDEX IF EXISTS acp_contract.idx_atom_ranking_tenant_total_rank;
ALTER TABLE acp_contract.atom_ranking DROP CONSTRAINT IF EXISTS atom_ranking_pkey;
ALTER TABLE acp_contract.atom_ranking DROP COLUMN tenant_id;
ALTER TABLE acp_contract.atom_ranking ADD COLUMN market TEXT NOT NULL;
ALTER TABLE acp_contract.atom_ranking ADD PRIMARY KEY (market, tour_id, segment_id);

CREATE INDEX idx_atom_ranking_market_tour ON acp_contract.atom_ranking(market, tour_id);
CREATE INDEX idx_atom_ranking_market_total_rank
    ON acp_contract.atom_ranking(market, total_rank)
    WHERE excluded_reason IS NULL;

COMMENT ON COLUMN acp_contract.atom_ranking.market IS
    'AA-545 — one of the 6 finite platform buyer markets (services/seo_intelligence/'
    'seed_builder.py::DFS_LOCATION_MAP), NOT a tenant. run_atom_ranking(market, pool) computes '
    'one full rank-sum pass per market over the WHOLE platform Segment pool — a tenant with '
    'several target markets reads/merges across the matching rows at read time (Slate), the '
    'merge that used to happen at write time inside rank_segments()''s own best-market pick is '
    'now gone from this table entirely (see services/acp_shared/slate.py''s updated read '
    'queries).';
COMMENT ON TABLE acp_contract.atom_ranking IS
    'AA-545: platform-wide (dropped tenant_id). One row per (market, tour, Segment) — a Segment '
    'now gets up to 6 rows (one per finite market), not one per tenant.';

-- ── 3. Route — drop tenant_id + score, identity (tour_id, first_day, last_day) ──────────────
--
-- Both existing rows are per-tenant artifacts of a pre-redesign (per-tenant) Segment set —
-- neither is trustworthy as THE platform-wide row now that Segment itself is genuinely shared
-- (build decision #2, docs/implementation-notes/AA-545.md). Superseded, never deleted (AA-532,
-- migration 144) — acp_shared.subject.route_id's 1 real FK reference keeps resolving regardless
-- of which of the 2 it points to. The live-verify run_route_detection() pass mints a fresh,
-- correct version-1 row from the real, already-redesigned Segment/Score data right after this
-- migration.
UPDATE acp_contract.route SET superseded_at = now() WHERE superseded_at IS NULL;

DROP INDEX IF EXISTS acp_contract.idx_route_tenant_score;
DROP INDEX IF EXISTS acp_contract.idx_route_tenant_tour;
DROP INDEX IF EXISTS acp_contract.idx_route_hub;
DROP INDEX IF EXISTS acp_contract.idx_route_current_identity;
DROP INDEX IF EXISTS acp_contract.idx_route_tenant_current;

ALTER TABLE acp_contract.route DROP COLUMN tenant_id;
ALTER TABLE acp_contract.route DROP COLUMN score;

CREATE INDEX idx_route_tour ON acp_contract.route(tour_id);
CREATE INDEX idx_route_hub ON acp_contract.route(hub_id) WHERE hub_id IS NOT NULL;

-- At most one CURRENT row per (tour_id, first_day, last_day) — AA-532's own invariant,
-- re-created without tenant_id in the key (was (tenant_id, tour_id, first_day, last_day)).
CREATE UNIQUE INDEX idx_route_current_identity
    ON acp_contract.route (tour_id, first_day, last_day)
    WHERE superseded_at IS NULL;
CREATE INDEX idx_route_current ON acp_contract.route (tour_id) WHERE superseded_at IS NULL;

COMMENT ON TABLE acp_contract.route IS
    'AA-545: platform-wide (dropped tenant_id AND score — AA-545 Q3, "families()"/composition '
    'never needed score, only route.score-the-column and hub_name tie-break did). route_id = '
    'f"{tour_id}:{first_day}-{last_day}" (":vN" suffix from v2, AA-532 versioning unchanged). '
    'Ordering/ranking for display is computed at READ TIME from acp_contract.atom_ranking, '
    'joined by the reading tenant''s own market(s) (services/acp_shared/slate.py) — never '
    'stored here, since a platform-wide Route has no single tenant/market of its own.';

-- ── 4. Hub — drop tenant_id ──────────────────────────────────────────────────────────────────
DROP INDEX IF EXISTS acp_contract.idx_hub_tenant;
ALTER TABLE acp_contract.hub DROP COLUMN tenant_id;

COMMENT ON TABLE acp_contract.hub IS
    'AA-545: platform-wide (dropped tenant_id). Persists across Route rebuilds, reused by '
    'tour-set overlap (route_detection.py) same as before — just no longer isolated per tenant.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('146', now(),
    'AA-545: Segment/Score/Route/Hub → platform-wide. atom_segment/hub/route drop tenant_id '
    '(route also drops score); atom_ranking PK (tenant_id,tour_id,segment_id) -> '
    '(market,tour_id,segment_id), wiped+recomputed post-migration (no downstream FK depended on '
    'row stability); route''s 2 existing rows superseded (never deleted, AA-532) pending a fresh '
    'platform-wide run_route_detection() pass. See docs/implementation-notes/AA-545.md.')
ON CONFLICT (version) DO NOTHING;

COMMIT;
