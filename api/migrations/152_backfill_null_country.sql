-- Migration 152: AA-571 Việc 3 -- backfill 9 NULL-country raw_tours rows
--
-- Per-row country inferred from provider name + src_itineraries place names (posted to the
-- Linear issue as a table, approved by Nghiep verbatim, no changes):
--   8 rows -> Bhutan  (Blue Poppy Bhutan / Wangchuk Tours & Trek provider names, itineraries
--             naming Paro/Thimphu/Punakha/Bumthang/Jomolhari/Druk Path -- all Bhutan places)
--   1 row  -> Sri Lanka (src_summary explicitly says "Enchanting Sri Lanka", itinerary names
--             Kandy + Bandaranaike International Airport)
-- This is inference from other fields, not an obvious spelling fix like SRI-LANDKA/OKINAWA
-- (migration 149) -- required Nghiep's explicit row-by-row approval before this migration was
-- written, unlike 149.

BEGIN;

UPDATE silver_aa_internal.raw_tours
SET country = 'Bhutan'
WHERE tour_id IN (
    '0c02884c-5d9b-4109-b5db-24944d6a8e78',  -- Paro Festival
    '22174c35-6cab-408d-b0f1-1d5c6e6c2885',  -- DAY HIKE TOUR
    '296abe67-80e6-43c8-81af-2088b111d31f',  -- Yaksa Trek BEST DEAL
    '59708e94-856c-4d84-af6d-b3207697dd47',  -- Bumthang festival tour cheap
    '6d0c09ba-d5e3-4915-b137-6a11c9df7e42',  -- Punakha Festival
    '8555c70f-26bd-4722-91ba-e6dc3b97ac50',  -- Jomolhari Trek
    'c4faf93f-894a-430a-b7a4-3ff645d744fd',  -- MOUNTAIN BIKING
    'fc5cce14-9e53-44be-a206-0cb984ea9afd'   -- Druk Path Trek
)
AND country IS NULL;

UPDATE silver_aa_internal.raw_tours
SET country = 'Sri Lanka'
WHERE tour_id = '96ac5a71-31c6-405e-a23b-a7fda683d50f'  -- Highland & Colombo
AND country IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('152', now(),
    'AA-571 Việc 3: backfill 9 NULL-country raw_tours rows (8 Bhutan, 1 Sri Lanka), Nghiep-approved per-row')
ON CONFLICT (version) DO NOTHING;

COMMIT;
