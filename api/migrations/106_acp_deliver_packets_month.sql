-- Migration 106: acp_deliver.packets.month (AA-412 follow-up, Phần 2a)
--
-- Context (docs/implementation-notes/AA-412-produce-page-usability.md D1): migration 094 created
-- acp_deliver.packets with UNIQUE(tenant_id, year, week) and no `month` column at all -- the exact
-- collision pattern migration 103 (AA-410) already fixed for acp_shared.acp_v2_runs/acp_v2_slots
-- ("every calendar month collapses onto the SAME 4 rows"), never applied here. admin_produce.py's
-- _get_or_create_packet() looks up an existing packet by (tenant_id, year, week) only, so two
-- different months' Week-N runs for the same tenant silently share one packet row and
-- assemble_packet() merges both months' pieces into it.
--
-- Confirmed live via ECS exec, 16/08/2026: the one real acp_deliver.packets row
-- (6cadcbaa-ddaf-4ff4-88ef-740a06054733, tenant 00000000-0000-0000-0000-000000000001, year=2026,
-- week=1) held 4 pieces from TWO distinct runs -- month=7 and month=9 -- all still
-- review_status='pending' (no human review decision recorded on any of them, confirmed safe to
-- repair by splitting rather than merely relabeling).
--
-- This migration:
--   1. Adds `month` (nullable at first, so the repair step below can run).
--   2. Repairs existing rows: for each packet, finds the distinct months actually present among
--      its assigned pieces (via pieces.run_id -> acp_v2_runs.month, the same source of truth
--      GET /admin/produce/runs already uses). Exactly one distinct month -> backfill directly.
--      More than one -> SPLIT: the original packet_id keeps its lowest month's pieces; each
--      additional month gets a NEW packet row (same tenant_id/year/week/status/publish_mode/
--      created_at) and its pieces are moved onto that new row via UPDATE packet_id. No piece
--      review_status/reviewed_by/reviewed_at/review_note/gate data is touched -- only packet_id
--      reassignment.
--   3. A packet with zero assigned pieces has no data to infer month from (none exist live today
--      -- verified, only 1 packet total in the table before this migration runs) -- falls back to
--      EXTRACT(MONTH FROM created_at), same convention migration 103's own backfill used for
--      acp_v2_runs.
--   4. Makes `month` NOT NULL + CHECK(1-12), and replaces the old UNIQUE(tenant_id, year, week)
--      with UNIQUE(tenant_id, year, month, week) -- matching acp_v2_runs's own constraint shape
--      from migration 103 exactly.

BEGIN;

ALTER TABLE acp_deliver.packets ADD COLUMN IF NOT EXISTS month SMALLINT;

-- Must drop the OLD (tenant_id, year, week)-only constraint BEFORE the repair/split step below —
-- splitting a corrupted packet inserts a new row with the SAME (tenant_id, year, week) as the
-- original (only `month` differs), which the old constraint (not yet aware `month` exists)
-- would reject as a duplicate.
ALTER TABLE acp_deliver.packets DROP CONSTRAINT IF EXISTS packets_tenant_id_year_week_key;

DO $$
DECLARE
    pkt RECORD;
    mrow RECORD;
    first_month SMALLINT;
    new_packet_id UUID;
BEGIN
    FOR pkt IN
        SELECT packet_id, tenant_id, year, week, status, publish_mode, created_at
        FROM acp_deliver.packets
        WHERE month IS NULL
    LOOP
        first_month := NULL;
        FOR mrow IN
            SELECT DISTINCT r.month
            FROM acp_deliver.pieces pc
            JOIN acp_shared.acp_v2_runs r ON r.run_id = pc.run_id
            WHERE pc.packet_id = pkt.packet_id
            ORDER BY r.month
        LOOP
            IF first_month IS NULL THEN
                first_month := mrow.month;
                UPDATE acp_deliver.packets SET month = first_month WHERE packet_id = pkt.packet_id;
            ELSE
                INSERT INTO acp_deliver.packets (tenant_id, year, month, week, status, publish_mode, created_at)
                VALUES (pkt.tenant_id, pkt.year, mrow.month, pkt.week, pkt.status, pkt.publish_mode, pkt.created_at)
                RETURNING packet_id INTO new_packet_id;

                UPDATE acp_deliver.pieces pc
                SET packet_id = new_packet_id
                FROM acp_shared.acp_v2_runs r
                WHERE pc.run_id = r.run_id AND pc.packet_id = pkt.packet_id AND r.month = mrow.month;
            END IF;
        END LOOP;
    END LOOP;

    -- Orphan fallback: a packet with 0 assigned pieces has no run to infer month from. None exist
    -- live as of this migration, but future re-runs of this file (ON CONFLICT DO NOTHING at the
    -- bottom makes it a safe no-op after the first run, this UPDATE is here purely so the
    -- subsequent NOT NULL step below can never fail).
    UPDATE acp_deliver.packets
    SET month = EXTRACT(MONTH FROM created_at)::smallint
    WHERE month IS NULL;
END $$;

ALTER TABLE acp_deliver.packets ALTER COLUMN month SET NOT NULL;

ALTER TABLE acp_deliver.packets
    ADD CONSTRAINT packets_month_check CHECK (month BETWEEN 1 AND 12);

ALTER TABLE acp_deliver.packets
    ADD CONSTRAINT packets_tenant_id_year_month_week_key UNIQUE (tenant_id, year, month, week);

DROP INDEX IF EXISTS acp_deliver.idx_acp_deliver_packets_tenant;
CREATE INDEX idx_acp_deliver_packets_tenant ON acp_deliver.packets(tenant_id, year, month, week);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('106', now(),
    'AA-412 follow-up: acp_deliver.packets.month -- fixes week/month collision merging different '
    'months'' pieces into one packet (UNIQUE now tenant_id,year,month,week), splits the one live '
    'corrupted packet found (month=7 + month=9 merged under week=1)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
