-- Migration 089: AA-289 Part B — shared.prompt_eval_runs
--
-- Storage for the on-demand eval regression gate. Each run of scripts/eval_regression.py
-- writes one row per pipeline it evaluated, so the NEXT run can compare its avg quality/density
-- against the most recent PRIOR row with a DIFFERENT prompt_version (its "baseline") — this
-- table IS the baseline store, not a separate mechanism.
--
-- Two pipelines share one table (pipeline column) rather than two tables: same shape of
-- question ("did quality regress at this prompt_version"), just a different quality signal per
-- pipeline (avg_quality_score for S1-old, which has a judge; avg_words_per_citation +
-- gate pass/fail counts for S1-from-atom, which does not — AA-289 STEP 0 finding, not invented
-- here). Both columns are nullable so one row never needs to fake a value for the other
-- pipeline's metric.
--
-- No FK to acp_contract.s1_from_atom_runs or generated_content — this table is a rollup written
-- directly by the eval script from its own in-memory results, not derived from those tables via
-- trigger/view. Keeps the eval script's write path independent of either pipeline's production
-- schema evolving.

BEGIN;

CREATE TABLE shared.prompt_eval_runs (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline                    TEXT NOT NULL CHECK (pipeline IN ('s1_old', 's1_from_atom')),
    prompt_version              TEXT NOT NULL,
    tour_count                  INTEGER NOT NULL,
    avg_quality_score           NUMERIC,
    avg_words_per_citation      NUMERIC,
    gate_pass_count             INTEGER,
    gate_fail_count             INTEGER,
    cost_usd                    NUMERIC,
    regression_detected         BOOLEAN NOT NULL DEFAULT false,
    baseline_prompt_version     TEXT,
    baseline_avg_quality_score  NUMERIC,
    details                     JSONB,
    triggered_by                TEXT NOT NULL DEFAULT 'manual',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_prompt_eval_runs_pipeline_created ON shared.prompt_eval_runs(pipeline, created_at DESC);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('089', now(), 'AA-289 Part B: shared.prompt_eval_runs — on-demand eval regression gate storage/baseline')
ON CONFLICT (version) DO NOTHING;

COMMIT;
