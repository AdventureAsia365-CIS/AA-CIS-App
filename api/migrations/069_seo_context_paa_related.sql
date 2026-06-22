-- AA-218: persist people_also_ask + related_keywords on seo_context
-- DFS already returns both (DataForSEOClient.fetch_all); handler/repo dropped them.
-- JSONB arrays of strings.

ALTER TABLE silver_aa_internal.seo_context
    ADD COLUMN IF NOT EXISTS people_also_ask jsonb,
    ADD COLUMN IF NOT EXISTS related_keywords jsonb;

INSERT INTO shared.schema_versions (version, description)
    VALUES ('069', 'AA-218: seo_context people_also_ask + related_keywords columns')
    ON CONFLICT DO NOTHING;
