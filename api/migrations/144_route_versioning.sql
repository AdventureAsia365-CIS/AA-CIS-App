-- Migration 144: AA-532 — acp_contract.route gains version/superseded_at (versioning, replaces
-- the DELETE+INSERT-whole rebuild route_detection.py used to do).
--
-- Bug (found live during AA-526's live-verify, 05/09/2026): run_route_detection() DELETEs every
-- one of a tenant's route rows then re-INSERTs from scratch on every run. Since AA-511
-- (migration 133), acp_shared.subject.route_id is a REAL FK into acp_contract.route(route_id)
-- with the default NO ACTION delete behavior — deleting a route a Subject still references
-- raises a foreign-key-violation and the whole rebuild fails. Confirmed live (05/09/2026, real
-- RDS): `subject_route_id_fkey`'s confdeltype is 'a' (NO ACTION), and real WanderLux Travel data
-- has both a real `acp_shared.subject` row pointing at a real `acp_contract.route` row for the
-- same tenant that has an active Subject — the collision is real, not hypothetical.
--
-- Fix (Nghiệp's decision, 05/09/2026): versioning instead of delete-then-reinsert. A route
-- identity is (tenant_id, tour_id, first_day, last_day) — re-running detection either leaves an
-- unchanged identity alone (no write), marks a changed/removed identity's current row
-- `superseded_at = now()` and inserts a new current row for a changed one, or inserts a brand
-- new row for a genuinely new identity. A superseded row is NEVER deleted — any subject.route_id
-- pointing at it keeps resolving, FK intact, forever.

BEGIN;

ALTER TABLE acp_contract.route
    ADD COLUMN version        INT NOT NULL DEFAULT 1,
    ADD COLUMN superseded_at  TIMESTAMPTZ NULL;

COMMENT ON COLUMN acp_contract.route.version IS
    'AA-532 — 1 for a route identity''s first detection; incremented each time re-detection '
    'finds this (tenant_id, tour_id, first_day, last_day) identity''s content actually changed. '
    'route_id itself carries the version past v1 (":v{version}" suffix, route_detection.py) so '
    'the PK stays globally unique across every version ever written.';
COMMENT ON COLUMN acp_contract.route.superseded_at IS
    'AA-532 — NULL means this is the CURRENT row for its (tenant_id, tour_id, first_day, '
    'last_day) identity; a non-NULL timestamp means a later re-detection replaced or removed it. '
    'A superseded row is NEVER deleted — acp_shared.subject.route_id (migration 133, a real FK) '
    'can keep pointing at it indefinitely without violating the constraint. Every reader that '
    'means "the route as it stands today" (Slate candidate lists, the tenant-facing Route '
    'picker, Hub-family matching) must filter `WHERE superseded_at IS NULL`; a reader resolving '
    'one SPECIFIC already-known route_id (e.g. a Subject''s own snapshot join) does not, by '
    'design — it wants that exact historical row, current or not.';

-- At most one CURRENT row per route identity — protects the invariant the application code
-- above depends on (exactly one "the current route for this span" per identity), catches a bug
-- in route_detection.py's own supersede-then-insert logic as a real constraint violation rather
-- than silent duplicate current rows.
CREATE UNIQUE INDEX idx_route_current_identity
    ON acp_contract.route (tenant_id, tour_id, first_day, last_day)
    WHERE superseded_at IS NULL;

-- Every "current routes for this tenant" reader (Slate, tenant Route picker, Hub-family
-- matching, the admin dashboard) filters on this pair — a dedicated partial index rather than
-- relying on idx_route_tenant_score/idx_route_tenant_tour (migration 131) picking it up
-- incidentally, since those aren't partial and would still scan superseded rows.
CREATE INDEX idx_route_tenant_current
    ON acp_contract.route (tenant_id)
    WHERE superseded_at IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('144', now(),
    'AA-532: acp_contract.route.version/superseded_at — route_detection.py switches from '
    'DELETE+INSERT-whole to versioning (supersede, never delete), fixing a real FK violation '
    'against acp_shared.subject.route_id (migration 133) on any tenant with an active Subject')
ON CONFLICT (version) DO NOTHING;

COMMIT;
