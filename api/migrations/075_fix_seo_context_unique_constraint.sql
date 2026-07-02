-- Migration 075: AA-249 — seo_context UNIQUE constraint: cache_key → tour_id
--
-- Context: silver_aa_internal.seo_context has UNIQUE(cache_key), where
-- cache_key = f"seo:{country}_tours[:location_code]" (handler.py effective_seed,
-- country-level, NOT tour-level). SeoContextRepository.insert() upserts with
-- ON CONFLICT (cache_key) DO UPDATE SET tour_id = EXCLUDED.tour_id, ... — so
-- every tour sharing a country collapses onto ONE physical row; whichever
-- tour's pipeline run writes last "wins" the row (including its tour_id),
-- and every other same-country tour silently has ZERO seo_context row for
-- its own tour_id. Confirmed via live batch test (S88 STEP 1): 5 South Korea
-- tours run concurrently → 5 successful DataForSEO fetches, 5 "seo_inserted"
-- log lines, all sharing ONE db row id. Confirmed via historical audit
-- (S88 STEP 2 Part C): 33/49 (67%) of ever-rewritten tours have no
-- seo_context row at all, concentrated in South Korea/Sri Lanka (multi-tour
-- countries); single-tour countries (Japan, Okinawa) show zero loss.
--
-- Fix (2 layers, this migration = layer 1 only):
--   1. DB persist layer (this migration): the real identity of a
--      seo_context row is tour_id, not cache_key. Move the UNIQUE
--      constraint accordingly. cache_key stays as a plain (non-unique)
--      column — kept for debugging/tracing which seed produced a given row.
--   2. Cache layer (STEP 2 BƯỚC 2/3, application code, separate change):
--      seo_context_repository.py ON CONFLICT target moves to tour_id;
--      a real Redis-backed cache (keyed by country/seed, TTL) is wired in
--      to avoid redundant DataForSEO calls across same-country tours — the
--      original intent behind the "{tenant_id}:{country}:{activity}:{market}"
--      cache_key comment in migration 002, which was never actually wired
--      to a live cache client (LocalCache() instantiated fresh per call,
--      per-call scope only — see STEP 2 Part B3 audit).
--
-- Pre-check (S88 STEP 2.x live audit) found 2 EXISTING tour_id duplicates
-- (2 rows each) — leftover from seed_builder format churn across code
-- revisions (e.g. "seo:japan" pre-AA-197 vs "seo:japan_tours" post-AA-197),
-- NOT from the cache_key collision itself. Both rows in each pair have
-- n_ideas=0 (both pre-AA-197 era, no real DataForSEO ideas data lost either
-- way) — approved by Nghiep to delete the older row of each pair rather
-- than backfill (S88 session: no backfill of any historical gap — let
-- affected tours self-heal via natural re-rewrite, avoid unnecessary
-- DataForSEO spend in dev).
--
-- Explicitly NOT in scope here: backfilling the 33 tours that lost their
-- row to the collision bug historically — they heal naturally next time
-- they're rewritten, now that the UNIQUE constraint is on tour_id.
--
-- Applied: Dev only (per Nghiep — do not run against Prod until STEP 2
-- BƯỚC 2-4 land and are verified).

BEGIN;

-- ── 1. Dedup: keep the newest row per tour_id, drop older duplicates ───────
-- Generic self-anti-join (no hard-coded UUIDs) — only affects tour_ids that
-- currently have >1 row; tour_ids with exactly 1 row have no matching
-- newer sibling and are left untouched.
DELETE FROM silver_aa_internal.seo_context a
USING silver_aa_internal.seo_context b
WHERE a.tour_id = b.tour_id
  AND a.fetched_at < b.fetched_at;

-- ── 2. Drop the old country-level UNIQUE (the actual root cause) ───────────
ALTER TABLE silver_aa_internal.seo_context
    DROP CONSTRAINT IF EXISTS seo_context_cache_key_key;

-- ── 3. Add the real UNIQUE — one seo_context row per tour ──────────────────
ALTER TABLE silver_aa_internal.seo_context
    ADD CONSTRAINT seo_context_tour_id_key UNIQUE (tour_id);

-- ── 4. Drop the now-redundant plain index (constraint 3 auto-creates its own
--        unique index on tour_id; idx_aa_internal_seo_tour duplicates it and
--        is not referenced anywhere in application code — verified via
--        repo-wide grep, S88 session) ─────────────────────────────────────
DROP INDEX IF EXISTS silver_aa_internal.idx_aa_internal_seo_tour;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('075', NOW(), 'AA-249: seo_context UNIQUE constraint cache_key -> tour_id (fixes country-level row collision)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
