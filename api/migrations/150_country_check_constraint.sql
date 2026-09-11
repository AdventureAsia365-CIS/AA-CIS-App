-- Migration 150: AA-571 Việc 2A -- CHECK constraint on raw_tours.country
--
-- Country list confirmed by Nghiep from AA's own legacy `countries` table (backup.sql,
-- 4 identical copies verified byte-for-byte via md5sum under /mnt/d/Nghiep_works/...,
-- destinations/landing-page content) -- 16 entries:
--   Bhutan, Cambodia, China, India, Indonesia, Japan, Kyrgyzstan, Laos, Malaysia, Mongolia,
--   Myanmar, Nepal, Sri Lanka, Thailand, Uzbekistan, Viet Nam
-- "Viet Nam" -> normalized to "Vietnam" here to match the canonical spelling
-- shared/country_resolver.py::COUNTRY_MASTER already uses -- using the backup.sql spelling
-- verbatim would have created a brand-new 2-way variant in the one place meant to prevent
-- exactly that.
--
-- Cross-checked this 16-list against all 11 country values with REAL active data in raw_tours
-- today (this issue's own Bước 1 audit) and found 2 mismatches, not just the 1 Nghiep already
-- flagged (South Korea) -- Taiwan (36 real rows) is ALSO absent from the legacy list. Per
-- Nghiep's own rule ("giữ lại ... vì đã có data vận hành thật, không loại bỏ"), both South
-- Korea and Taiwan are added to the constraint rather than excluded, since real live data
-- exists for both and this constraint must never reject data that is already correct.
--
-- Final 18-value list = the 16 above (Viet Nam -> Vietnam) + South Korea + Taiwan.
--
-- NULL is explicitly allowed (9 rows today, see AA-571 Việc 3 -- under separate, un-backfilled
-- investigation; NULL is a "missing", not "invalid", state and must not be blocked here).

BEGIN;

ALTER TABLE silver_aa_internal.raw_tours
    ADD CONSTRAINT chk_raw_tours_country CHECK (
        country IS NULL OR country = ANY (ARRAY[
            'Bhutan', 'Cambodia', 'China', 'India', 'Indonesia', 'Japan', 'Kyrgyzstan', 'Laos',
            'Malaysia', 'Mongolia', 'Myanmar', 'Nepal', 'South Korea', 'Sri Lanka', 'Taiwan',
            'Thailand', 'Uzbekistan', 'Vietnam'
        ])
    );

COMMENT ON CONSTRAINT chk_raw_tours_country ON silver_aa_internal.raw_tours IS
    'AA-571 -- restricts country to AA''s confirmed operating-country list (legacy countries '
    'table, backup.sql, + South Korea/Taiwan for real existing active data not in that legacy '
    'list). NULL allowed (missing, not invalid). Extend this list only after Nghiep confirms a '
    'new operating country -- do not guess.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('150', now(),
    'AA-571 Việc 2A: CHECK constraint on raw_tours.country -- 18-value confirmed operating list, NULL allowed')
ON CONFLICT (version) DO NOTHING;

COMMIT;
