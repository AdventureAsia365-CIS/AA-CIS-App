-- Migration 088: AA-289/AA-288 — acp_contract.s1_from_atom_runs
--
-- S1-from-atom (AA-306, services/content_generation/s1_from_atom.py) has been fully stateless
-- since it shipped — generate_s1_from_atom() returns a result dict, nothing is ever persisted.
-- AA-289 Part A needs a real place to answer "quality by prompt_version" for this pipeline too,
-- the same way generated_content.metadata.prompt_version now does for S1-old. Deliberately a
-- NEW, minimal table rather than reusing generated_content (which is old-S1's write path with
-- its own status/version_num/is_active semantics that don't apply here) or pipeline_runs (a
-- batch aggregate, wrong granularity — see the same reasoning in migration's sibling PR notes,
-- docs/implementation-notes/AA-289-AA-288.md).
--
-- No quality_score column: S1-from-atom has no judge/quality-scoring node of its own yet (a real
-- gap, not silently invented here) — density_pass/closed_world_pass from the deterministic
-- grounding gate are the only quality signal that exists today. quality_score can be added in a
-- later migration once/if a judge node exists for this pipeline.
--
-- One row per generate_s1_from_atom() call (including gate-rejected/exhausted-retry attempts,
-- not just successes) — a run that FAILED the gate is exactly the kind of regression this table
-- needs to make visible by prompt_version, not just the ones that happened to pass.

BEGIN;

CREATE TABLE acp_contract.s1_from_atom_runs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tour_id               UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
    prompt_version        TEXT NOT NULL,
    model_tier            TEXT NOT NULL,
    model_used            TEXT,
    status                TEXT NOT NULL CHECK (status IN ('passed', 'gate_failed', 'error')),
    retries               SMALLINT,
    atoms_available       INTEGER,
    atoms_used_count      INTEGER,
    citation_count        INTEGER,
    word_count            INTEGER,
    words_per_citation    NUMERIC,
    density_pass          BOOLEAN,
    closed_world_pass     BOOLEAN,
    input_tokens          INTEGER,
    output_tokens         INTEGER,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_s1_from_atom_runs_tour_id ON acp_contract.s1_from_atom_runs(tour_id);
CREATE INDEX idx_s1_from_atom_runs_prompt_version ON acp_contract.s1_from_atom_runs(prompt_version);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('088', now(), 'AA-289/AA-288: acp_contract.s1_from_atom_runs — prompt_version + gate/cache observability for S1-from-atom')
ON CONFLICT (version) DO NOTHING;

COMMIT;
