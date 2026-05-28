-- AA-130: add metadata JSONB snapshot to generated_content
-- Stores brand_rule_id, seo_mode, model, cost at generation time
-- so compare modal never needs to join brand_rules (brand may change after generation)
ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_generated_content_metadata_brand_rule
    ON silver_aa_internal.generated_content USING GIN (metadata);

COMMENT ON COLUMN silver_aa_internal.generated_content.metadata
    IS 'Snapshot at generation time: brand_rule_id, brand_name, seo_mode, model_used, llm_cost_usd, dataforseo_used, generated_at, pipeline_version';
