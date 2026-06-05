-- AA-162: add s1_tour_ids to acp_shared.acp_run_context
-- JSONB array of tour UUID strings processed during S1 batch

ALTER TABLE acp_shared.acp_run_context
    ADD COLUMN IF NOT EXISTS s1_tour_ids JSONB DEFAULT '[]'::jsonb;

INSERT INTO shared.schema_versions (version, description)
    VALUES ('068', 's1_tour_ids column on acp_run_context [AA-162]')
    ON CONFLICT DO NOTHING;
