-- Migration 131: AA-510 — acp_contract.hub + acp_contract.route + acp_contract.subject
--
-- Ported from Ms. Thư's aa-social-media (src/aa_social/routes.py's derive_routes()/families()/
-- stops(), score.py's _routes()/_store_routes()) — see docs/claude_audit/
-- AA-510-step0-route-hub-investigation.md and docs/implementation-notes/AA-510.md for the full
-- evidence trail and every deviation from the build prompt's literal SQL (2 corrections, 1
-- addition — all documented, not silent).

BEGIN;

-- hub: the marketer's "unit of choice" (CONTEXT.md) — the journey a family of Routes tells,
-- named as a traveller would say it ("Nakasendo Way: The Kiso Valley from Kyoto"). Reuses
-- hub_id across a Route rebuild when the same tour-id family regroups (route_detection.py),
-- never deleted — an orphaned hub (no Route currently maps to it) is expected, not cleaned up,
-- because a Subject that snapshotted it (ADR 0024) still needs the name to mean something.
CREATE TABLE acp_contract.hub (
    hub_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    hub_name     TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_hub_tenant ON acp_contract.hub(tenant_id);

-- route: one journey — a consecutive-day span of one tour's ranked, non-excluded Segments
-- (Blog-only concept; enforced by which consumer reads this table, not a column here — see
-- implementation notes Decision 11). Rebuilt WHOLE per tenant on every run (DELETE+INSERT,
-- STEP0-confirmed: the origin's own routes/route_members are "derived, never accumulated") —
-- unlike acp_contract.hub above, which persists.
--
-- route_id is a deterministic composite key (tenant_id:tour_id:first_day-last_day), NOT a
-- hash/uuid4() — mirrors the origin's own f"{trip_code}:{first}-{last}" (routes.py:107),
-- extended with tenant_id since AA-CIS is multi-tenant and the origin never was (implementation
-- notes: "route_id generation — reported before deciding").
--
-- 2 corrections vs. the build prompt's literal SQL, both documented in implementation notes:
--  - tour_id is UUID, not TEXT (silver_aa_internal.raw_tours.tour_id is UUID; a TEXT FK into a
--    UUID PK does not typecheck in Postgres).
--  - first_day/last_day/score are ADDED (present in the origin's own reference schema,
--    workspace.py:318, omitted from the build prompt's literal SQL) — without them there is
--    nothing to ORDER BY the live-verify requirement ("Route đúng thứ tự total_rank") against
--    without re-deriving the whole thing from atom_ranking on every read.
CREATE TABLE acp_contract.route (
    route_id             TEXT PRIMARY KEY,
    tenant_id             UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    tour_id               UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
    hub_id                UUID REFERENCES acp_contract.hub(hub_id),
    hub_name              TEXT NOT NULL,
    ordered_segment_ids   JSONB NOT NULL,
    first_day             SMALLINT NOT NULL,
    last_day              SMALLINT NOT NULL,
    score                 INT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_route_tenant_score ON acp_contract.route(tenant_id, score);
CREATE INDEX idx_route_tenant_tour ON acp_contract.route(tenant_id, tour_id);
CREATE INDEX idx_route_hub ON acp_contract.route(hub_id) WHERE hub_id IS NOT NULL;

COMMENT ON COLUMN acp_contract.route.score IS
    'Mean of the member Segments'' atom_ranking.total_rank, rounded — lower is better (rank-sum '
    'convention, AA-515). Ascending ORDER BY score is "best route first", matching total_rank.';

-- subject: the marketer's PICK, snapshotted — never a live FK into route.route_id (ADR 0024,
-- "A Subject outlives the Segment it was generated from"; the same lesson applies one layer up
-- here). route_snapshot carries everything a Subject needs to still describe the journey it was
-- picked for even after the next rebuild deletes/regroups the Route it came from — route_id,
-- tour_id, hub_id/hub_name AT SELECTION TIME, ordered_segment_ids, places, first_day/last_day/
-- score, and a resolved `stops` array (day/place/actions) so the snapshot is human-readable
-- without any live join.
CREATE TABLE acp_contract.subject (
    subject_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    hub_name         TEXT NOT NULL,
    route_snapshot   JSONB NOT NULL,
    selected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    selected_by      TEXT
);

CREATE INDEX idx_subject_tenant ON acp_contract.subject(tenant_id, selected_at DESC);

COMMENT ON COLUMN acp_contract.subject.route_snapshot IS
    'Immutable snapshot of the Route at pick time (ADR 0024) — no live FK to route.route_id. '
    'The Route it came from can be deleted or regrouped by the next rebuild without touching '
    'this row.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('131', now(),
    'AA-510: acp_contract.hub (persists, reused across rebuilds) + route (rebuilt whole per '
    'tenant, DELETE+INSERT) + subject (ADR-0024 snapshot, no live FK) — journey detection from '
    'ranked Segments, ported from aa-social-media routes.py')
ON CONFLICT (version) DO NOTHING;

COMMIT;
