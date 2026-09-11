-- Migration 149: AA-571 -- normalize non-standard silver_aa_internal.raw_tours.country values
--
-- STEP0 (full 793-row raw_tours + 74-row published_tours audit, this issue's own comment)
-- confirmed exactly 2 non-standard country values exist in the whole dataset, no more:
--   SRI-LANDKA (6 rows) -- misspelling of Sri Lanka
--   OKINAWA    (1 row)  -- a Japanese region entered where country should read Japan
-- Nghiep approved this exact 2-row mapping, nothing else, before this migration was written.
--
-- gold_aa_internal.published_tours has NO country column of its own (confirmed via
-- information_schema.columns) -- it always inherits country by JOIN on raw_tours.tour_id, so
-- fixing raw_tours alone fixes both tables; no separate UPDATE against published_tours is
-- possible or needed.

BEGIN;

UPDATE silver_aa_internal.raw_tours
SET country = 'Sri Lanka'
WHERE country = 'SRI-LANDKA';

UPDATE silver_aa_internal.raw_tours
SET country = 'Japan'
WHERE country = 'OKINAWA';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('149', now(),
    'AA-571: normalize raw_tours.country -- SRI-LANDKA->Sri Lanka (6 rows), OKINAWA->Japan (1 row)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
