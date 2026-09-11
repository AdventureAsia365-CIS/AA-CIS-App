-- Migration 151: AA-571 Việc 2B (Cách A, Nghiep confirmed) -- unresolved-country marker column
--
-- Decision: when country_resolver.resolve_country() can't map a raw value, DO NOT block
-- ingestion (the tour still comes in normally, country stays NULL as before) -- just make the
-- affected rows trivially queryable afterward, instead of only visible via a log line
-- (excel_parser.py's country_unresolved_null warning from Việc 2B round 1).
--
-- Reused nothing from raw_tours.review_status/review_notes (migration 024, AA-44 "S0 Data
-- Quality Review") on purpose after checking: those columns are set to their DEFAULT at
-- ingestion and a live grep across api/ + services/ found NO code anywhere that reads or
-- writes silver_aa_internal.raw_tours.review_status/review_notes today (024's own S0 review
-- workflow appears to have never been wired up) -- reusing an already-dead, differently-named
-- lifecycle column for a new, unrelated meaning would be more confusing than a new column with
-- an exact, self-describing name, not less.
--
-- A single nullable TEXT column is enough: `WHERE country_raw_unresolved IS NOT NULL` answers
-- "which tours have an unresolved country" directly. No new enum/flag needed alongside it.

BEGIN;

ALTER TABLE silver_aa_internal.raw_tours
    ADD COLUMN IF NOT EXISTS country_raw_unresolved TEXT;

COMMENT ON COLUMN silver_aa_internal.raw_tours.country_raw_unresolved IS
    'AA-571 Việc 2B -- the raw country cell value when country_resolver.resolve_country() '
    'could not map it (country ends up NULL, same as before). Set by services/ingestion/'
    'excel_parser.py at ingest time. NULL means either country resolved fine or the cell was '
    'empty to begin with -- query `WHERE country_raw_unresolved IS NOT NULL` to find affected '
    'tours instead of searching logs.';

CREATE INDEX IF NOT EXISTS idx_raw_tours_country_raw_unresolved
    ON silver_aa_internal.raw_tours (country_raw_unresolved)
    WHERE country_raw_unresolved IS NOT NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('151', now(),
    'AA-571 Việc 2B: raw_tours.country_raw_unresolved marker column (Cách A -- no ingestion block)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
