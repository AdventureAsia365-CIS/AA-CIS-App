-- Migration 103: acp_shared.acp_v2_runs / acp_v2_slots — add `month` (AA-410)
--
-- Context: AA-404's real N7 retrigger (3rd run, 15/08/2026) hit a hard block — every slot for
-- aa_internal, week 1-4/2026, was already 'produced'. Root cause (docs/implementation-notes/
-- AA-410.md): migration 096 gave acp_v2_runs a UNIQUE(tenant_id, year, week) with `week` being
-- SlotGrid's own week-of-month numbering (1-4, NOT ISO week) but never persisted a `month`
-- column at all. `create_weekly_produce_run()` took a `month` param nowhere — it only ever
-- wrote (tenant_id, year, week) — so every calendar month collapses onto the SAME 4 rows per
-- tenant/year: October week 1 and November week 1 are the same UNIQUE key. `persist_slot_grid()`
-- had the identical gap (never read `SlotGrid.month`), and `_deterministic_slot_id()` was
-- ALSO missing `year` from its hash (a second, independent bug — the original AA-377 spec
-- documented `sha256(tenant_id|year|week|tour_id|channel)`, migration 096's own header
-- comment and AA-377.md Decision #3 both say so, but the shipped code hashed only
-- `tenant_id|week|trip_id|channel`). Both gaps are fixed together here since they're the same
-- family of bug (missing calendar-scoping in slot/run identity) and share one migration per
-- migration 096's own precedent (both tables changed together, no broken intermediate state).
--
-- Fix:
--  1. `acp_v2_runs`/`acp_v2_slots` both get a real `month` column (1-12), NOT NULL after
--     backfill.
--  2. `acp_v2_runs`'s UNIQUE(tenant_id, year, week) -> UNIQUE(tenant_id, year, month, week) —
--     the actual real-world identity of one weekly run.
--  3. `create_weekly_produce_run()` / `persist_slot_grid()` (services/acp_planning/
--     allocator.py, same PR) now read/write `month` — see AA-410.md for the full trace.
--  4. `_deterministic_slot_id()` (same file) now hashes
--     `tenant_id|year|month|week|tour_id|channel` — adds BOTH the always-missing `year` and
--     the new `month`, keeps the rest of the original AA-377 field order unchanged.
--
-- `acp_v2_slots` itself carries no separate UNIQUE constraint beyond its `slot_id` PK (that
-- PK IS the dedup key, via the hash above) — no constraint change needed there, only the new
-- `month` column so a slot row is self-describing without a join back to its run (matches the
-- existing convention of `week` already being denormalized onto both tables).
--
-- Backfill: exactly 4 real acp_v2_runs rows exist live (aa_internal, year=2026, week=1-4,
-- checked immediately before writing this migration) and all 15 acp_v2_slots rows reference
-- one of them — every one was created 15/08/2026 (`created_at` all same UTC calendar date), so
-- `EXTRACT(MONTH FROM created_at)` backfills the true value (8), not a guessed default. Slots
-- backfill via a join to their parent run rather than their own `created_at` — a run and its
-- slots are always allocated in the same `allocate_month()` call, so the run's month IS the
-- slot's month, and this avoids relying on the slot's own timestamp being in the same wall-clock
-- minute as its run's.
--
-- ADDITIVE, not destructive — no existing row is deleted, no existing column dropped. All 4
-- runs / 15 slots keep their PKs and FKs untouched, only gain the new `month` value + the old
-- 3-column UNIQUE constraint on acp_v2_runs is replaced by the 4-column one (same semantics,
-- correctly scoped).

BEGIN;

-- ---------------------------------------------------------------- acp_v2_runs
ALTER TABLE acp_shared.acp_v2_runs ADD COLUMN IF NOT EXISTS month SMALLINT;

UPDATE acp_shared.acp_v2_runs
SET month = EXTRACT(MONTH FROM created_at)::smallint
WHERE month IS NULL;

ALTER TABLE acp_shared.acp_v2_runs ALTER COLUMN month SET NOT NULL;

ALTER TABLE acp_shared.acp_v2_runs
    ADD CONSTRAINT acp_v2_runs_month_check CHECK (month BETWEEN 1 AND 12);

ALTER TABLE acp_shared.acp_v2_runs
    DROP CONSTRAINT IF EXISTS acp_v2_runs_tenant_id_year_week_key;

ALTER TABLE acp_shared.acp_v2_runs
    ADD CONSTRAINT acp_v2_runs_tenant_id_year_month_week_key UNIQUE (tenant_id, year, month, week);

-- Superseded by the UNIQUE constraint's own auto-created index (tenant_id, year, month, week) —
-- no live call site queries acp_v2_runs by a (tenant_id, year, week) prefix without month.
DROP INDEX IF EXISTS acp_shared.idx_acp_v2_runs_tenant;

-- ---------------------------------------------------------------- acp_v2_slots
ALTER TABLE acp_shared.acp_v2_slots ADD COLUMN IF NOT EXISTS month SMALLINT;

UPDATE acp_shared.acp_v2_slots s
SET month = r.month
FROM acp_shared.acp_v2_runs r
WHERE s.run_id = r.run_id AND s.month IS NULL;

ALTER TABLE acp_shared.acp_v2_slots ALTER COLUMN month SET NOT NULL;

ALTER TABLE acp_shared.acp_v2_slots
    ADD CONSTRAINT acp_v2_slots_month_check CHECK (month BETWEEN 1 AND 12);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('103', now(),
    'AA-410: acp_shared.acp_v2_runs/acp_v2_slots.month -- fixes week/month collision blocking '
    'new-month N7 runs (UNIQUE now tenant_id,year,month,week) + _deterministic_slot_id() missing '
    'year+month in its hash')
ON CONFLICT (version) DO NOTHING;

COMMIT;
